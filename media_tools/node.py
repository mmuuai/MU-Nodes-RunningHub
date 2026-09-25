import json
import io
from contextlib import contextmanager
from pathlib import Path

import requests

from .audio_utils import audio_to_wav_bytes
from .http_client import sanitize
from .meowload import MEOWLOAD_BASE_URL, extract_media
from .transcription import (
    DASHSCOPE_BASE_URL,
    transcribe_paraformer,
    upload_transcription_file,
)
from ..proxy import PROXY_ADDRESS, PROXY_PASSWORD, PROXY_USERNAME, proxy_input_fields, configure_proxy


MODELS = (
    "单个视频解析",
    "主页视频批量解析",
    "音视频转写文字（文件/URL）",
)
KEY_INFO = (
    "视频解析需分享链接｜主页最多5页｜转写支持附件或公网URL",
)


class MmuuAIMediaParserNode:
    OUTPUT_NODE = True
    CATEGORY = "MU/接口"
    FUNCTION = "execute"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("文本", "视频链接", "音频链接", "封面链接", "原始响应")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "模型": (MODELS, {"default": MODELS[0]}),
                "密钥": ("STRING", {"default": "", "multiline": False, "password": True}),
                "媒体链接": ("STRING", {"default": "", "multiline": True, "placeholder": "视频分享链接，或 Paraformer 可公网访问的音视频 URL"}),
                "主页解析页数": ("INT", {"default": 1, "min": 1, "max": 5, "step": 1}),
                "轮询间隔（秒）": ("INT", {"default": 2, "min": 1, "max": 60, "step": 1}),
                "超时时间（秒）": ("INT", {"default": 3600, "min": 60, "max": 2147483647, "step": 1}),
                "关键说明": (KEY_INFO, {"default": KEY_INFO[0]}),
                **proxy_input_fields(),
            },
            "optional": {
                "视频文件": ("VIDEO",),
                "音频文件": ("AUDIO",),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def execute(self, **values):
        model = values["模型"]
        source_url = values["媒体链接"].strip()
        video = values.get("视频文件")
        audio = values.get("音频文件")
        # 备用节点未接入媒体时不应阻塞工作流中的其他分支。
        # 一旦提供 URL、视频或音频，后续仍会严格校验密钥。
        if not source_url and video is None and audio is None:
            return ("", "", "", "", "")
        api_key = values["密钥"].strip()
        if not api_key:
            raise ValueError("密钥不能为空")
        try:
            api_key.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("密钥只能填写真实的 API key，不能包含中文或其他非 ASCII 字符") from exc
        interval = int(values["轮询间隔（秒）"])
        timeout = int(values["超时时间（秒）"])
        base_url = self._preset(model)
        session = requests.Session()
        try:
            configure_proxy(
                session, values.get(PROXY_ADDRESS, ""), values.get(PROXY_USERNAME, ""),
                values.get(PROXY_PASSWORD, ""),
            )
            if model == MODELS[0]:
                self._require_url(source_url)
                summary, raw = extract_media(session, base_url, api_key, source_url, None, (30, timeout))
                return self._media_result(summary, raw)
            if model == MODELS[1]:
                self._require_url(source_url)
                summary, raw = extract_media(
                    session, base_url, api_key, source_url, values["主页解析页数"], (30, timeout)
                )
                return self._media_result(summary, raw)
            if model == MODELS[2]:
                source = self._transcription_input(
                    session,
                    base_url,
                    api_key,
                    source_url,
                    video,
                    audio,
                    timeout,
                )
                text, raw = transcribe_paraformer(session, base_url, api_key, source, interval, timeout)
                return (text, "", "", "", self._raw(raw))
            raise ValueError(f"不支持的模型：{model}")
        except Exception as exc:
            raise RuntimeError(f"mmuuai媒体解析节点执行失败：{sanitize(str(exc))}") from exc
        finally:
            session.close()

    @staticmethod
    def _preset(model):
        if model in MODELS[:2]:
            return MEOWLOAD_BASE_URL
        if model == MODELS[2]:
            return DASHSCOPE_BASE_URL
        raise ValueError(f"没有为该模型配置基础地址：{model}")

    @staticmethod
    def _transcription_input(session, base_url, api_key, source_url, video, audio, timeout):
        provided = int(bool(source_url)) + int(video is not None) + int(audio is not None)
        if provided == 0:
            raise ValueError("转写必须填写媒体链接，或连接一个视频文件/音频文件")
        if provided > 1:
            raise ValueError("媒体链接、视频文件、音频文件只能选择一个")
        if source_url:
            return source_url
        with _attachment(video, audio) as (file_source, file_name):
            return upload_transcription_file(
                session,
                base_url,
                api_key,
                file_source,
                file_name,
                timeout,
            )

    @staticmethod
    def _require_url(value):
        if not value:
            raise ValueError("当前模型必须填写媒体分享链接")

    def _media_result(self, summary, raw):
        return (
            summary["text"],
            "\n".join(summary["videos"]),
            "\n".join(summary["audios"]),
            "\n".join(summary["images"]),
            self._raw(raw),
        )

    @staticmethod
    def _raw(value):
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        return sanitize(serialized)


@contextmanager
def _attachment(video, audio):
    if audio is not None:
        yield io.BytesIO(audio_to_wav_bytes(audio)), "input.wav"
        return
    if video is None or not hasattr(video, "get_stream_source"):
        raise ValueError("视频文件输入不是有效的 ComfyUI VIDEO")
    source = video.get_stream_source()
    if isinstance(source, (str, Path)):
        with open(source, "rb") as handle:
            yield handle, Path(source).name
        return
    if not hasattr(source, "read"):
        raise ValueError("视频文件输入不支持流式读取")
    source.seek(0)
    try:
        yield source, "input.mp4"
    finally:
        source.seek(0)
