import ipaddress
import json
import re
import socket
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests

from ..proxy import redact_proxy_credentials

try:
    import psutil
except ImportError:  # ComfyUI normally provides psutil; keep standalone tests importable.
    psutil = None


MAX_JSON_BYTES = 64 * 1024 * 1024
CLASH_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_SECRET = re.compile(r"(?i)(bearer\s+|x-api-key[\"']?\s*[:=]\s*[\"']?)([^\s\"']+)")


def sanitize(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = redact_proxy_credentials(text)
    return _SECRET.sub(lambda match: match.group(1) + "[REDACTED]", text)


def _is_clash_fake_ip(addresses):
    if not addresses or any(ipaddress.ip_address(address) not in CLASH_FAKE_IP_NETWORK for address in addresses):
        return False
    if psutil is None:
        return False
    interface_names = {name.lower() for name in psutil.net_if_addrs()}
    return any("mihomo" in name or "clash" in name for name in interface_names)


def public_https_url(value, *, resolve=True):
    parts = urlsplit((value or "").strip())
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError("地址必须是公网 HTTPS URL")
    if parts.username or parts.password or parts.fragment:
        raise ValueError("地址不能包含账号、密码或片段")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("地址不能指向本机或局域网")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("地址不能指向内网或保留 IP")
    except ValueError as exc:
        if "does not appear" not in str(exc):
            raise
    if resolve:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise ValueError("地址域名解析失败") from exc
        has_restricted_address = not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses)
        if has_restricted_address and not _is_clash_fake_ip(addresses):
            raise ValueError("地址解析到了内网或保留 IP")
    # requests/urllib3 ultimately writes the request target through an
    # latin-1 HTTP header path.  Keep the public URL semantics, but percent
    # encode non-ASCII path/query characters before it reaches that layer.
    encoded_path = quote(parts.path or "/", safe="/%:@-._~!$&'()*+,;=")
    encoded_query = quote(parts.query, safe="/%?:@-._~!$&'()*+,;=")
    return urlunsplit(("https", parts.netloc, encoded_path, encoded_query, ""))


def endpoint(base_url, path):
    base = public_https_url(base_url).rstrip("/") + "/"
    return public_https_url(urljoin(base, path.lstrip("/")), resolve=False)


def read_json(response):
    if 300 <= response.status_code < 400:
        response.close()
        raise RuntimeError("服务端返回重定向，已拒绝携带密钥继续请求")
    if response.status_code >= 400:
        snippet = sanitize(response.content[:2000].decode("utf-8", errors="replace"))
        response.close()
        raise RuntimeError(f"API 返回 HTTP {response.status_code}: {snippet}")
    length = int(response.headers.get("content-length", "0") or 0)
    if length > MAX_JSON_BYTES:
        response.close()
        raise RuntimeError("API 响应超过 64 MB")
    data = response.content
    response.close()
    if len(data) > MAX_JSON_BYTES:
        raise RuntimeError("API 响应超过 64 MB")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("API 返回的不是有效 JSON") from exc


def request_json(session, method, url, *, headers=None, body=None, timeout=None):
    try:
        response = session.request(
            method,
            public_https_url(url, resolve=False),
            headers=headers or {},
            json=body,
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        if method.upper() == "POST":
            raise RuntimeError("提交连接中断，结果未知；节点不会自动重发 POST") from exc
        raise RuntimeError(f"查询请求失败：{sanitize(str(exc))}") from exc
    return read_json(response)
