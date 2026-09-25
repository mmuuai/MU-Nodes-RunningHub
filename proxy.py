import re
import ssl
from urllib.parse import quote, urlsplit, urlunsplit

from requests.adapters import HTTPAdapter


PROXY_ADDRESS = "代理地址（可选）"
PROXY_USERNAME = "代理用户名（可选）"
PROXY_PASSWORD = "代理密码（可选）"
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^\s/@]+(?::[^\s/@]*)?@")


def redact_proxy_credentials(value):
    return _URL_CREDENTIALS.sub(r"\1[REDACTED]@", str(value))


class SystemTrustProxyAdapter(HTTPAdapter):
    def proxy_manager_for(self, proxy, **proxy_kwargs):
        if urlsplit(proxy).scheme.lower() == "https":
            proxy_kwargs.setdefault("proxy_ssl_context", ssl.create_default_context())
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def proxy_input_fields():
    return {
        PROXY_ADDRESS: ("STRING", {"default": ""}),
        PROXY_USERNAME: ("STRING", {"default": ""}),
        PROXY_PASSWORD: ("STRING", {"default": "", "password": True}),
    }


def configure_proxy(session, proxy="", username="", password=""):
    proxy_url = build_proxy_url(proxy, username, password)
    if session is None or not proxy_url:
        return proxy_url
    session.proxies.update({"http": proxy_url, "https": proxy_url})
    if urlsplit(proxy_url).scheme.lower() == "https":
        session.mount("https://", SystemTrustProxyAdapter())
    return proxy_url


def build_proxy_url(proxy="", username="", password=""):
    proxy = str(proxy or "").strip()
    username = str(username or "").strip()
    password = str(password or "")
    if bool(username) != bool(password):
        raise ValueError("代理用户名和代理密码需要同时填写")
    if not proxy:
        if username or password:
            raise ValueError("填写代理账号密码时，也需要填写代理地址")
        return ""

    parts = urlsplit(proxy)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("代理地址请填写 http:// 或 https:// 开头的代理 URL")
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("代理地址中的端口无效") from exc
    if parts.username is not None or parts.password is not None:
        raise ValueError("请将代理用户名和密码分别填写在对应输入框，不要写入代理地址")
    if not username:
        return proxy

    authority = f"{quote(username, safe='')}:{quote(password, safe='')}@{parts.netloc}"
    return urlunsplit((parts.scheme.lower(), authority, parts.path, parts.query, parts.fragment))
