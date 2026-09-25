import io
from urllib.parse import urljoin

import av
import numpy as np
import requests
import torch
from PIL import Image, ImageOps

from .http_client import public_https_url, sanitize


MAX_REDIRECTS = 3
USER_AGENT = "ComfyUI-mmuuai-media-parser/1.0"


def split_links(value):
    links = []
    seen = set()
    for line in (value or "").splitlines():
        link = line.strip()
        if not link:
            continue
        normalized = public_https_url(link, resolve=False)
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    if not links:
        raise ValueError("链接文本中没有可用的公网 HTTPS 地址")
    return links


def download_media(session, url, connect_timeout, wait_timeout, media_name, accept):
    current_url = public_https_url(url)
    timeout = (connect_timeout, None if wait_timeout == 0 else wait_timeout)

    for redirect_count in range(MAX_REDIRECTS + 1):
        try:
            response = session.get(
                current_url,
                headers={"Accept": accept, "User-Agent": USER_AGENT},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"{media_name}下载失败：{sanitize(str(exc))}") from exc

        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise RuntimeError(f"{media_name}下载返回了没有目标地址的重定向")
            if redirect_count >= MAX_REDIRECTS:
                raise RuntimeError(f"{media_name}下载重定向超过 3 次")
            current_url = public_https_url(urljoin(current_url, location))
            continue

        if response.status_code >= 400:
            snippet = sanitize(response.content[:2000].decode("utf-8", errors="replace"))
            response.close()
            raise RuntimeError(f"{media_name}下载返回 HTTP {response.status_code}: {snippet}")

        buffer = io.BytesIO()
        try:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    buffer.write(chunk)
        except requests.RequestException as exc:
            raise RuntimeError(f"{media_name}下载中断：{sanitize(str(exc))}") from exc
        finally:
            response.close()

        if buffer.tell() == 0:
            raise RuntimeError(f"{media_name}下载结果为空")
        buffer.seek(0)
        return buffer, response.headers.get("content-type", "")

    raise RuntimeError(f"{media_name}下载失败")


def download_video(session, url, connect_timeout, wait_timeout):
    buffer, _content_type = download_media(
        session,
        url,
        connect_timeout,
        wait_timeout,
        "视频",
        "video/*,application/octet-stream;q=0.9,*/*;q=0.5",
    )
    return buffer


def decode_audio(buffer):
    with av.open(buffer) as container:
        if not container.streams.audio:
            raise ValueError("下载文件中没有音频轨道")
        stream = container.streams.audio[0]
        frames = []
        for frame in container.decode(streams=stream.index):
            data = torch.from_numpy(frame.to_ndarray())
            if data.shape[0] != stream.channels:
                data = data.view(-1, stream.channels).t()
            frames.append(data)
        if not frames:
            raise ValueError("下载文件中没有可解码的音频帧")
        waveform = torch.cat(frames, dim=1)
        if not waveform.dtype.is_floating_point:
            divisor = 2 ** (15 if waveform.dtype == torch.int16 else 31)
            waveform = waveform.float() / divisor
        return {"waveform": waveform.unsqueeze(0), "sample_rate": stream.codec_context.sample_rate}


def decode_image(buffer):
    with Image.open(buffer) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        pixels = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(pixels).unsqueeze(0)


def detect_media_type(buffer, content_type):
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    for prefix, media_type in (("video/", "视频"), ("audio/", "音频"), ("image/", "图片")):
        if mime.startswith(prefix):
            return media_type

    buffer.seek(0)
    try:
        with Image.open(buffer) as source:
            source.verify()
        buffer.seek(0)
        return "图片"
    except (OSError, ValueError):
        buffer.seek(0)

    try:
        with av.open(buffer) as container:
            audio_streams = list(container.streams.audio)
            video_streams = [
                stream
                for stream in container.streams.video
                if not getattr(stream.disposition, "attached_pic", False)
            ]
            if video_streams:
                media_type = "视频"
            elif audio_streams:
                media_type = "音频"
            else:
                raise ValueError("下载文件中没有可识别的图片、音频或视频")
    except av.AVError as exc:
        raise ValueError("无法识别下载文件的媒体类型") from exc
    finally:
        buffer.seek(0)
    return media_type


def media_input_schema(name):
    return {
        "required": {
            name: ("STRING", {"forceInput": True}),
            "连接超时（秒）": ("INT", {"default": 30, "min": 1, "max": 300, "step": 1}),
            "等待超时（秒，0不限）": ("INT", {"default": 600, "min": 0, "max": 86400, "step": 1}),
        },
    }


class MmuuAILinkListSplitterNode:
    CATEGORY = "MU/工具"
    FUNCTION = "split"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("链接",)
    OUTPUT_IS_LIST = (True,)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "链接文本": ("STRING", {"forceInput": True}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def split(self, **kwargs):
        return (split_links(kwargs["链接文本"]),)


class MmuuAIMediaUrlLoaderNode:
    CATEGORY = "MU/加载"
    FUNCTION = "load"
    RETURN_TYPES = ("VIDEO", "AUDIO", "IMAGE")
    RETURN_NAMES = ("视频", "音频", "图片")

    @classmethod
    def INPUT_TYPES(cls):
        schema = media_input_schema("媒体链接")
        schema["required"] = {
            "媒体链接": schema["required"]["媒体链接"],
            "媒体类型": (["自动识别", "视频", "音频", "图片"], {"default": "自动识别"}),
            "连接超时（秒）": schema["required"]["连接超时（秒）"],
            "等待超时（秒，0不限）": schema["required"]["等待超时（秒，0不限）"],
        }
        return schema

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def load(self, **kwargs):
        from comfy_api.latest import InputImpl

        buffer, content_type = download_media(
            requests.Session(),
            kwargs["媒体链接"],
            kwargs["连接超时（秒）"],
            kwargs["等待超时（秒，0不限）"],
            "媒体",
            "video/*,audio/*,image/*,application/octet-stream;q=0.8,*/*;q=0.5",
        )
        media_type = kwargs["媒体类型"]
        if media_type == "自动识别":
            media_type = detect_media_type(buffer, content_type)
        if media_type == "视频":
            return (InputImpl.VideoFromFile(buffer), None, None)
        if media_type == "音频":
            return (None, decode_audio(buffer), None)
        return (None, None, decode_image(buffer))
