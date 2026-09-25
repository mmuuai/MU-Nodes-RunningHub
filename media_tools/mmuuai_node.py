from .audio_utils import audio_to_wav_bytes
from .node import KEY_INFO, MODELS
from ..model_nodes.client import sanitize
from ..model_nodes.common import KEY_ADVERTISEMENT, api_key_from_value, raw_response
from ..model_nodes.mmuuai_client import MmuuAIClient
from ..model_nodes.mmuuai_media import uploaded_file, video_upload
from ..proxy import PROXY_ADDRESS, PROXY_PASSWORD, PROXY_USERNAME, proxy_input_fields


MODEL_NAMES = {
    MODELS[0]: "视频/图集提取",
    MODELS[1]: "主页视频批量提取",
    MODELS[2]: "音视频转文字",
}


class MmuuAIDirectMediaParserNode:
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
                "key": ("STRING", {"default": KEY_ADVERTISEMENT, "password": True}),
                "媒体链接": ("STRING", {"default": "", "multiline": True, "placeholder": "视频分享链接、主页链接或公网音视频 URL"}),
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
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    def execute(self, **values):
        mode = values["模型"]
        # 备用节点未接入任何媒体时不应阻塞工作流中的其他分支。
        # 一旦提供 URL、视频或音频，后续仍会严格校验 key。
        source_url = str(values.get("媒体链接") or "").strip()
        has_video = values.get("视频文件") is not None
        has_audio = values.get("音频文件") is not None
        if not source_url and not has_video and not has_audio:
            return ("", "", "", "", "")
        client = MmuuAIClient(
            api_key_from_value(values["key"]), int(values["超时时间（秒）"]),
            proxy=values.get(PROXY_ADDRESS, ""), proxy_username=values.get(PROXY_USERNAME, ""),
            proxy_password=values.get(PROXY_PASSWORD, ""),
        )
        try:
            resource = client.resolve_model(mode, "", MODEL_NAMES)
            task_input = self._task_input(client, resource, mode, values)
            response = client.run_model(
                resource, task_input, poll_interval=int(values["轮询间隔（秒）"])
            )
            result = response.get("result") if isinstance(response, dict) else None
            text, videos, audios, images = _result_outputs(result)
            return (
                text,
                "\n".join(videos),
                "\n".join(audios),
                "\n".join(images),
                raw_response(response),
            )
        except Exception as exc:
            raise RuntimeError(f"MU 媒体解析执行失败：{sanitize(str(exc))}") from exc

    @staticmethod
    def _task_input(client, resource, mode, values):
        source_url = str(values["媒体链接"] or "").strip()
        if mode in MODELS[:2]:
            if not source_url:
                raise ValueError("当前解析模式必须填写媒体链接")
            parameters = {"url": source_url}
            if mode == MODELS[1]:
                parameters["page_count"] = int(values["主页解析页数"])
            return {"parameters": parameters}
        if mode != MODELS[2]:
            raise ValueError(f"不支持的解析模式：{mode}")
        video, audio = values.get("视频文件"), values.get("音频文件")
        provided = int(bool(source_url)) + int(video is not None) + int(audio is not None)
        if provided == 0:
            raise ValueError("转写必须填写媒体链接，或连接一个视频文件/音频文件")
        if provided > 1:
            raise ValueError("媒体链接、视频文件、音频文件只能选择一个")
        if source_url:
            return {"parameters": {"video_url": source_url}}
        if audio is not None:
            data = audio_to_wav_bytes(audio)
            file = uploaded_file(
                client, data, "audio", "input.wav", "audio/wav", "video_url"
            )
        else:
            data, file_name, mime_type = video_upload(video, 1)
            file = uploaded_file(
                client, data, "video", file_name, mime_type, "video_url"
            )
        return {"files": [file]}


def _result_outputs(result):
    if not isinstance(result, dict):
        raise RuntimeError("mmuuai 媒体解析结果格式无效")
    texts = []
    if isinstance(result.get("text"), str) and result["text"].strip():
        texts.append(result["text"].strip())
    buckets = {"video": [], "audio": [], "image": []}
    parts = result.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            kind = str(part.get("type", "")).lower()
            if kind == "text" and isinstance(part.get("text"), str):
                value = part["text"].strip()
                if value and value not in texts:
                    texts.append(value)
                continue
            url = part.get("url")
            if kind in buckets and isinstance(url, str) and url:
                buckets[kind].append(url)
    return (
        "\n".join(texts),
        _unique(buckets["video"]),
        _unique(buckets["audio"]),
        _unique(buckets["image"]),
    )


def _unique(values):
    return list(dict.fromkeys(values))
