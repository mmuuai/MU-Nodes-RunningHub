import json
import os
import ssl
import time
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from ..proxy import (
    PROXY_ADDRESS,
    PROXY_PASSWORD,
    PROXY_USERNAME,
    SystemTrustProxyAdapter as _SystemTrustProxyAdapter,
    build_proxy_url as _proxy_url,
    configure_proxy,
    proxy_input_fields,
)


FILES_API_BASE = "https://generativelanguage.googleapis.com"
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
VIDEO_MIME_TYPES = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "quicktime": "video/quicktime",
    "mpeg": "video/mpeg",
    "mpegvideo": "video/mpeg",
    "avi": "video/avi",
    "webm": "video/webm",
    "flv": "video/x-flv",
    "wmv": "video/wmv",
    "3gp": "video/3gpp",
    "3gpp": "video/3gpp",
}


@dataclass(frozen=True)
class GeminiFile:
    uri: str
    mime_type: str
    name: str


def _mime_type(video):
    container = str(video.get_container_format()).split(",", 1)[0].lower()
    mime_type = VIDEO_MIME_TYPES.get(container)
    if not mime_type:
        raise ValueError(f"Google Files API 不支持当前视频容器格式：{container}")
    return mime_type


@contextmanager
def _video_stream(video):
    source = video.get_stream_source()
    if isinstance(source, (str, os.PathLike)):
        handle = open(source, "rb")
        try:
            size = os.fstat(handle.fileno()).st_size
            yield handle, size
        finally:
            handle.close()
        return

    if not hasattr(source, "read") or not hasattr(source, "seek"):
        raise ValueError("无法读取 VIDEO 的原始文件流")
    original_position = source.tell()
    try:
        source.seek(0, os.SEEK_END)
        size = source.tell()
        source.seek(0)
        yield source, size
    finally:
        source.seek(original_position)


def _error_text(response):
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return response.text[:500]
    error = payload.get("error", payload) if isinstance(payload, dict) else payload
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or error)[:500]
    return str(error)[:500]


def _check_interrupt():
    try:
        from comfy import model_management
    except ImportError:
        return
    model_management.throw_exception_if_processing_interrupted()


def _wait_for_file(session, file_info, api_key, deadline, request_timeout):
    state = str(file_info.get("state", "")).upper()
    name = file_info.get("name")
    while state != "ACTIVE":
        _check_interrupt()
        if state == "FAILED":
            raise RuntimeError("Google 视频文件处理失败")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("等待 Google 视频处理完成超时")
        time.sleep(1)
        _check_interrupt()
        response = session.get(
            f"{FILES_API_BASE}/v1beta/{name}",
            headers={"x-goog-api-key": api_key},
            timeout=request_timeout,
        )
        if not response.ok:
            raise RuntimeError(f"查询 Google 文件状态失败（HTTP {response.status_code}）：{_error_text(response)}")
        file_info = response.json()
        state = str(file_info.get("state", "")).upper()
    return file_info


def upload_gemini_video(video, api_key, proxy="", timeout_seconds=600, session=None,
                        proxy_username="", proxy_password=""):
    api_key = str(api_key or "").strip()
    if not api_key:
        raise ValueError("请填写 Google Gemini API Key")
    _proxy_url(proxy, proxy_username, proxy_password)
    timeout_seconds = int(timeout_seconds)
    if timeout_seconds < 0:
        raise ValueError("超时时间不能小于 0")
    request_timeout = (30, None if timeout_seconds == 0 else timeout_seconds)
    deadline = None if timeout_seconds == 0 else time.monotonic() + timeout_seconds
    owns_session = session is None
    session = session or requests.Session()
    configure_proxy(session, proxy, proxy_username, proxy_password)
    try:
        mime_type = _mime_type(video)
        with _video_stream(video) as (stream, size):
            if size <= 0:
                raise ValueError("视频文件为空")
            if size > MAX_FILE_BYTES:
                raise ValueError("Google Gemini Files API 单文件上限为 2GB")
            start = session.post(
                f"{FILES_API_BASE}/upload/v1beta/files",
                headers={
                    "x-goog-api-key": api_key,
                    "X-Goog-Upload-Protocol": "resumable",
                    "X-Goog-Upload-Command": "start",
                    "X-Goog-Upload-Header-Content-Length": str(size),
                    "X-Goog-Upload-Header-Content-Type": mime_type,
                    "Content-Type": "application/json",
                },
                json={"file": {"display_name": "ComfyUI video input"}},
                timeout=request_timeout,
            )
            if not start.ok:
                raise RuntimeError(f"初始化 Google 视频上传失败（HTTP {start.status_code}）：{_error_text(start)}")
            upload_url = start.headers.get("x-goog-upload-url")
            if not upload_url:
                raise RuntimeError("Google 未返回可续传上传地址")
            if urlsplit(upload_url).scheme != "https":
                raise RuntimeError("Google 返回的上传地址不是 HTTPS，已停止传输")
            _check_interrupt()
            uploaded = session.post(
                upload_url,
                headers={
                    "Content-Length": str(size),
                    "X-Goog-Upload-Offset": "0",
                    "X-Goog-Upload-Command": "upload, finalize",
                },
                data=stream,
                timeout=request_timeout,
            )
            if not uploaded.ok:
                raise RuntimeError(f"上传视频到 Google 失败（HTTP {uploaded.status_code}）：{_error_text(uploaded)}")
            payload = uploaded.json()
            file_info = payload.get("file", payload) if isinstance(payload, dict) else {}
        if not isinstance(file_info, dict) or not file_info.get("name") or not file_info.get("uri"):
            raise RuntimeError("Google 上传响应缺少文件名或 URI")
        file_info = _wait_for_file(session, file_info, api_key, deadline, request_timeout)
        return GeminiFile(
            uri=str(file_info["uri"]),
            mime_type=str(file_info.get("mimeType") or mime_type),
            name=str(file_info["name"]),
        )
    except requests.RequestException:
        raise RuntimeError(
            "Google Files API 网络请求失败，请检查代理地址、账号密码和网络连接"
        ) from None
    finally:
        if owns_session:
            session.close()


class MmuuAIGeminiVideoUploadNode:
    CATEGORY = "MU/接口"
    FUNCTION = "upload"
    RETURN_TYPES = ("GEMINI_FILE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("Google文件", "文件URI", "MIME类型", "文件名")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "视频": ("VIDEO",),
                "Google API Key": ("STRING", {"default": "", "password": True}),
                **proxy_input_fields(),
                "超时时间（秒，0不限）": ("INT", {"default": 600, "min": 0, "max": 2147483647}),
            },
        }

    def upload(self, **values):
        result = upload_gemini_video(
            values["视频"], values["Google API Key"], values.get(PROXY_ADDRESS, ""),
            values["超时时间（秒，0不限）"],
            proxy_username=values.get(PROXY_USERNAME, ""),
            proxy_password=values.get(PROXY_PASSWORD, ""),
        )
        return result, result.uri, result.mime_type, result.name
