from urllib.parse import urlsplit

from .client import BASE_URL, UKClient, UpstreamHTTPError, sanitize
from .common import (
    KEY_ADVERTISEMENT,
    api_key_from_value,
    collect_images,
    raise_upstream_error,
    raw_response,
)
from .media import image_data_uri
from ..proxy import PROXY_ADDRESS, PROXY_PASSWORD, PROXY_USERNAME, proxy_input_fields


GOOGLE_IMAGE_RESOLUTIONS = ("自动", "1K", "2K", "4K")
GOOGLE_IMAGE_SIZES = (
    "自动", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4",
    "9:16", "16:9", "21:9",
)
GOOGLE_THINKING_LEVELS = ("自动（模型默认）", "低", "中", "高")
THINKING_VALUES = {"低": "LOW", "中": "MEDIUM", "高": "HIGH"}
MAX_GOOGLE_REFERENCE_IMAGES = 14
GATEWAY_HOSTS = {"api.mmuu.uk", "api.mmuu.ai"}


class MmuuAIGoogleImageModelNode:
    CATEGORY = "MU/接口"
    FUNCTION = "execute"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图片", "原始响应")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "URL": ("STRING", {"default": BASE_URL}),
                "模型名称": ("STRING", {"default": "gemini-3.1-flash-image-preview"}),
                "key": ("STRING", {"default": KEY_ADVERTISEMENT, "password": True}),
                "提示词": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "分辨率": (GOOGLE_IMAGE_RESOLUTIONS, {"default": "自动"}),
                "尺寸": (GOOGLE_IMAGE_SIZES, {"default": "自动"}),
                "超时时间（秒，0不限）": ("INT", {"default": 600, "min": 0, "max": 2147483647, "step": 1}),
                **proxy_input_fields(),
            },
            "optional": {
                "思考级别": (GOOGLE_THINKING_LEVELS, {"default": "自动（模型默认）"}),
                "内容审核": ("BOOLEAN", {"default": False}),
                "Google搜索": ("BOOLEAN", {"default": False}),
                "Google图片搜索": ("BOOLEAN", {"default": False}),
                **{f"图片{i}": ("IMAGE",) for i in range(1, MAX_GOOGLE_REFERENCE_IMAGES + 1)},
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def execute(self, **values):
        model = str(values.get("模型名称") or "").strip()
        if not model:
            raise ValueError("请填写 Google 图片模型名称")
        api_key = api_key_from_value(values.get("key"))
        base_url = str(values.get("URL") or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("请填写 Google 图片模型 URL")
        client = UKClient(
            api_key, values.get("超时时间（秒，0不限）", 600), base_url,
            values.get(PROXY_ADDRESS, ""), values.get(PROXY_USERNAME, ""), values.get(PROXY_PASSWORD, ""),
        )
        payload = self._payload(model, values, collect_images(values))
        try:
            images = collect_images(values)
            if len(images) > MAX_GOOGLE_REFERENCE_IMAGES:
                raise ValueError(f"Google 图片模型最多支持 {MAX_GOOGLE_REFERENCE_IMAGES} 张参考图")
            if _is_gateway_url(base_url):
                try:
                    result = _post_gateway_image(client, self._gateway_payload(model, values, images))
                except UpstreamHTTPError as exc:
                    if exc.status_code != 404:
                        raise
                    # Some UK account routes only expose the Gemini-native
                    # surface. Keep APIMart's canonical model ID and retry
                    # once through that supported gateway surface.
                    model = _gateway_model(model)
                    result = client.post_json(
                        f"v1beta/models/{model}:generateContent",
                        self._payload(model, values, images),
                        headers={"x-goog-api-key": api_key},
                    )
            else:
                result = client.post_json(
                    f"v1beta/models/{model}:generateContent",
                    payload,
                    headers={"x-goog-api-key": api_key},
                )
            result = client.poll_image_task(result)
            image = self._decode_image(result, client)
            return image, raw_response(result)
        except Exception as exc:
            raise RuntimeError(f"MU Google图片模型执行失败：{sanitize(str(exc))}") from exc

    @staticmethod
    def _payload(model, values, images):
        parts = [{"text": str(values.get("提示词") or "")}]
        parts.extend({"inlineData": {"mimeType": "image/png", "data": image_data_uri(data).split(",", 1)[1]}} for data in images)
        generation_config = {"responseModalities": ["IMAGE"]}
        resolution = values.get("分辨率", "自动")
        size = values.get("尺寸", "自动")
        if resolution != "自动" or size != "自动":
            image_config = {}
            if resolution != "自动":
                image_config["imageSize"] = resolution
            if size != "自动":
                image_config["aspectRatio"] = size
            generation_config["imageConfig"] = image_config
        thinking = values.get("思考级别", "自动（模型默认）")
        if thinking in THINKING_VALUES:
            generation_config["thinkingConfig"] = {"thinkingLevel": THINKING_VALUES[thinking]}
        return {"contents": [{"role": "user", "parts": parts}], "generationConfig": generation_config}

    @staticmethod
    def _gateway_payload(model, values, images):
        # APIMart/UK exposes Nano Banana through the OpenAI-compatible image
        # generation contract, not Google's native generateContent endpoint.
        gateway_model = _gateway_model(model)
        payload = {"model": gateway_model, "prompt": str(values.get("提示词") or ""), "n": 1}
        resolution = values.get("分辨率", "自动")
        size = values.get("尺寸", "自动")
        if resolution != "自动":
            payload["resolution"] = resolution
        if size != "自动":
            payload["size"] = size
        if images:
            payload["image_urls"] = [image_data_uri(data) for data in images]
        if values.get("内容审核"):
            payload["nsfw_check"] = True
        if values.get("Google搜索"):
            payload["google_search"] = True
        if values.get("Google图片搜索"):
            payload["google_image_search"] = True
        return payload

    @staticmethod
    def _decode_image(result, client):
        from .media import decode_image_batch

        image = decode_image_batch(result, client.download_image)
        if image is not None:
            return image
        raise_upstream_error(result)
        raise RuntimeError("Google 图片响应中没有可解析的图片")


def _is_gateway_url(base_url):
    return (urlsplit(str(base_url or "").strip()).hostname or "").lower() in GATEWAY_HOSTS


def _gateway_model(model):
    return {
        "gemini-3.1-flash-image": "gemini-3.1-flash-image-preview",
    }.get(model, model)


def _post_gateway_image(client, payload):
    # APIMart's documented Nano Banana endpoint is synchronous from the
    # gateway's perspective.  UK accepts an `/async` variant but can leave it
    # queued before it reaches the MART account, so submit to the documented
    # route and let `poll_image_task` handle a task response if one is returned.
    return client.post_json("v1/images/generations", payload)
