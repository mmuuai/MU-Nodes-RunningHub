import json
import re
import time
from urllib.parse import urljoin, urlsplit

import requests

from ..proxy import configure_proxy, redact_proxy_credentials


BASE_URL = "https://api.mmuu.uk"
SUPPORTED_BASE_URLS = ("https://api.mmuu.uk", "https://api.mmuu.ai")
UPLOAD_TIMEOUT_SECONDS = 180
MAX_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_IMAGE_BYTES = 100 * 1024 * 1024
_SECRET = re.compile(r"\b(?:sk|AQ)\.[A-Za-z0-9_-]{8,}\b|\bsk-[A-Za-z0-9_-]{8,}\b")
_DATA_URI = re.compile(r"data:(?:image|video)/[^;]+;base64,[A-Za-z0-9+/=]+")


class UnknownSubmissionError(RuntimeError):
    pass


class UpstreamHTTPError(RuntimeError):
    def __init__(self, status_code, message, code=""):
        self.status_code = status_code
        self.upstream_message = sanitize(message)
        self.code = sanitize(code)
        super().__init__(self._display_message())

    def rejects_parameter(self, parameter):
        if self.status_code != 400:
            return False
        text = f"{self.upstream_message} {self.code}".lower()
        name = parameter.lower()
        return name in text and any(
            marker in text
            for marker in ("unsupported", "not supported", "deprecated", "unknown parameter")
        )

    def _display_message(self):
        text = self.upstream_message
        lowered = text.lower()
        if self.status_code == 429:
            return f"上游限流（HTTP 429）：{text}"
        if self.status_code == 502:
            return "UK 连接上游失败（HTTP 502）"
        if self.status_code == 524:
            return "UK 等待上游返回超过 Cloudflare 时限（HTTP 524）"
        if "no eligible grok media accounts" in lowered:
            return "当前 Key 所属账号组没有可用的 Grok 图片账号（HTTP 503）"
        if "no available gemini accounts" in lowered:
            return "当前 Key 所属账号组没有可用的 Gemini 账号（HTTP 503）"
        if "not supported by any configured account" in lowered or "unknown model" in lowered:
            return f"当前 Key 所属账号组不支持该模型（HTTP {self.status_code}）：{text}"
        return f"UK 返回 HTTP {self.status_code}：{text}"


def sanitize(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = redact_proxy_credentials(text)
    return _DATA_URI.sub("[IMAGE_DATA_REMOVED]", _SECRET.sub("[REDACTED]", text))


def redact_response(value):
    if isinstance(value, dict):
        return {
            key: "[IMAGE_DATA_REMOVED]" if key in ("b64_json", "b64") else redact_response(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_response(child) for child in value]
    return sanitize(value) if isinstance(value, str) else value


def extract_text(payload):
    if isinstance(payload, list):
        deltas = []
        for event in payload:
            if event.get("type") == "response.output_text.delta":
                deltas.append(str(event.get("delta", "")))
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    deltas.append(str(delta.get("text", "")))
            for choice in event.get("choices", []):
                content = choice.get("delta", {}).get("content", "")
                if isinstance(content, str):
                    deltas.append(content)
                elif isinstance(content, list):
                    deltas.extend(
                        item.get("text", "") for item in content
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    )
        if deltas:
            return "".join(deltas)
        for event in reversed(payload):
            text = extract_text(event)
            if text:
                return text
        return ""
    if not isinstance(payload, dict):
        return ""
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    for choice in payload.get("choices", []):
        content = choice.get("message", {}).get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(item.get("text", "") for item in content if isinstance(item, dict))
    content = payload.get("content", [])
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if isinstance(item, dict))
    return ""


class UKClient:
    def __init__(self, api_key, timeout, base_url=BASE_URL, proxy="", proxy_username="", proxy_password=""):
        self.wait_timeout = None if timeout == 0 else timeout
        self.timeout = (UPLOAD_TIMEOUT_SECONDS, None if timeout == 0 else timeout)
        self.session = requests.Session()
        configure_proxy(self.session, proxy, proxy_username, proxy_password)
        self.headers = {"Authorization": f"Bearer {api_key}"}
        parsed = urlsplit(str(base_url or "").strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("自定义 URL 必须是 HTTPS 地址，且不能包含查询参数或片段")
        self.base_url = parsed.geturl().rstrip("/")

    def post_json(self, endpoint, payload, headers=None):
        return self._json(self._request("POST", endpoint, json=payload, extra_headers=headers))

    def post_sse(self, endpoint, payload, headers=None, retry_on_disconnect=False):
        attempts = 2 if retry_on_disconnect else 1
        for attempt in range(attempts):
            try:
                response = self._request("POST", endpoint, json=payload, extra_headers=headers)
                return self._sse(response)
            except UnknownSubmissionError:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(1)

    def post_multipart(self, endpoint, data, files):
        return self._json(self._request("POST", endpoint, data=data, files=files))

    def get_json(self, endpoint):
        return self._json(self._request("GET", endpoint))

    def poll_image_task(self, submission, interval=3):
        task_id = _task_id(submission)
        if not task_id:
            return submission
        endpoints = _poll_endpoints(submission, task_id)
        deadline = None if self.wait_timeout is None else time.monotonic() + self.wait_timeout
        endpoint = None
        while True:
            _check_comfyui_interrupt()
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError(f"等待图片任务 {sanitize(task_id)} 超时")
            if endpoint is None:
                result, endpoint = self._find_poll_endpoint(endpoints)
            else:
                result = self.get_json(endpoint)
            result = _unwrap_task_response(result)
            status = str(result.get("status", "")).lower() if isinstance(result, dict) else ""
            if status in ("completed", "succeeded", "success"):
                return result.get("result", result)
            if status in ("failed", "error", "cancelled", "canceled"):
                message, code = _error_details(result)
                raise RuntimeError(f"图片任务失败：{message or code or '未知上游错误'}")
            if _has_image_result(result):
                return result.get("result", result) if isinstance(result, dict) else result
            _interruptible_sleep(max(1, interval))

    def _find_poll_endpoint(self, endpoints):
        for endpoint in endpoints:
            try:
                return self.get_json(endpoint), endpoint
            except UpstreamHTTPError as exc:
                if exc.status_code != 404:
                    raise
        raise RuntimeError(
            "UK 已返回异步图片任务，但任务查询路由不可用；"
            "需要在 UK 后端开放对应上游任务轮询，或启用并正确配置异步图片对象存储"
        )

    def _request(self, method, endpoint, **kwargs):
        endpoint_path = endpoint.lstrip("/")
        base_path = urlsplit(self.base_url).path.rstrip("/")
        if base_path.endswith("/v1") and endpoint_path.startswith("v1/"):
            endpoint_path = endpoint_path[3:]
        url = f"{self.base_url}/{endpoint_path}"
        extra_headers = kwargs.pop("extra_headers", None) or {}
        headers = {**self.headers, **extra_headers}
        try:
            response = self.session.request(
                method, url, headers=headers, timeout=self.timeout,
                allow_redirects=False, stream=True, **kwargs,
            )
        except requests.RequestException as exc:
            raise UnknownSubmissionError("提交连接中断，结果未知") from exc
        if 300 <= response.status_code < 400:
            response.close()
            raise RuntimeError("UK 返回重定向，已拒绝携带密钥继续请求")
        if response.status_code >= 400:
            snippet = response.raw.read(2000, decode_content=True).decode("utf-8", errors="replace")
            response.close()
            message, code = _error_details(snippet)
            raise UpstreamHTTPError(response.status_code, message or f"HTTP {response.status_code}", code)
        return response

    @staticmethod
    def _json(response):
        chunks, total = [], 0
        try:
            for chunk in response.iter_content(64 * 1024):
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise RuntimeError("UK 响应超过 128 MB")
                chunks.append(chunk)
            return json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("UK 返回的不是有效 JSON") from exc
        finally:
            response.close()

    @staticmethod
    def _sse(response):
        events, total = [], 0
        try:
            for raw in response.iter_lines():
                total += len(raw)
                if total > MAX_RESPONSE_BYTES:
                    raise RuntimeError("UK SSE 响应超过 128 MB")
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    events.append({"data": sanitize(data)})
            return events
        except requests.RequestException as exc:
            raise UnknownSubmissionError("接收流式响应时连接中断，结果未知") from exc
        finally:
            response.close()

    def download_image(self, url):
        current = url
        for _ in range(4):
            parts = urlsplit(current)
            if parts.scheme != "https" or not parts.hostname:
                raise RuntimeError("图片地址不是公网 HTTPS")
            response = self.session.get(current, timeout=self.timeout, allow_redirects=False, stream=True)
            if 300 <= response.status_code < 400:
                location = response.headers.get("location")
                response.close()
                if not location:
                    raise RuntimeError("图片重定向缺少地址")
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                response.close()
                raise RuntimeError(f"图片下载返回 HTTP {response.status_code}")
            chunks, total = [], 0
            try:
                for chunk in response.iter_content(64 * 1024):
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise RuntimeError("单张图片超过 100 MB")
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                response.close()
        raise RuntimeError("图片下载重定向次数超过 3 次")


def _error_details(value):
    payload = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            title = re.search(r"<title>\s*(.*?)\s*</title>", value, flags=re.IGNORECASE | re.DOTALL)
            return (re.sub(r"\s+", " ", title.group(1)).strip() if title else sanitize(value[:300]), "")
    if not isinstance(payload, dict):
        return sanitize(payload), ""
    error = payload.get("error", payload)
    if isinstance(error, dict):
        message = error.get("message") or error.get("detail") or error.get("type") or ""
        code = error.get("code") or error.get("type") or ""
        return sanitize(str(message)), sanitize(str(code))
    return sanitize(str(error)), ""


def _task_id(value):
    if isinstance(value, dict):
        for key in ("task_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                status = str(value.get("status", "")).lower()
                if key == "task_id" or status in ("queued", "pending", "processing", "running"):
                    return candidate.strip()
        for child in value.values():
            found = _task_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _task_id(child)
            if found:
                return found
    return ""


def _poll_endpoints(submission, task_id):
    endpoints = []
    if isinstance(submission, dict):
        poll_url = submission.get("poll_url")
        if isinstance(poll_url, str) and poll_url.startswith("/") and not poll_url.startswith("//"):
            endpoints.append(poll_url.lstrip("/"))
    for endpoint in (f"v1/images/tasks/{task_id}", f"v1/tasks/{task_id}"):
        if endpoint not in endpoints:
            endpoints.append(endpoint)
    return endpoints


def _has_image_result(value):
    value = _unwrap_task_response(value)
    if not isinstance(value, dict):
        return False
    target = value.get("result", value)
    if not isinstance(target, dict):
        return False
    return bool(target.get("data") or target.get("images") or target.get("image_url"))


def _check_comfyui_interrupt():
    """Honor ComfyUI's interrupt flag while waiting on an async provider."""
    try:
        from comfy import model_management
    except ImportError:
        return
    model_management.throw_exception_if_processing_interrupted()


def _interruptible_sleep(seconds):
    deadline = time.monotonic() + seconds
    while True:
        _check_comfyui_interrupt()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))


def _unwrap_task_response(value):
    """Unwrap provider envelopes such as APIMart's {code, data: {...}}."""
    if not isinstance(value, dict):
        return value
    data = value.get("data")
    if isinstance(data, dict) and any(
        key in data for key in ("status", "result", "task_id", "id", "progress")
    ):
        return data
    return value
