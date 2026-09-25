import json

from .client import redact_response, sanitize
from .media import MAX_IMAGES, tensor_batch_to_png


PLATFORMS = ("GPT", "Gemini", "Claude", "Grok")
IMAGE_PLATFORMS = ("GPT", "Gemini", "Grok")
KEY_ADVERTISEMENT = "获取key：https://mmuu.ai"
PLATFORM_PREFIXES = {
    "GPT": "OpenAI｜",
    "Gemini": "Google｜",
    "Claude": "Anthropic｜",
    "Grok": "xAI｜",
}
REQUEST_PROTOCOLS = (
    "自动（按模型）",
    "OpenAI Responses",
    "Google Gemini",
    "Anthropic Claude",
    "xAI Grok",
)
REQUEST_PROTOCOL_TO_PLATFORM = {
    "OpenAI Responses": "GPT",
    "Google Gemini": "Gemini",
    "Anthropic Claude": "Claude",
    "xAI Grok": "Grok",
}
IMAGE_REQUEST_PROTOCOLS = (
    "自动（按模型）",
    "OpenAI Responses",
    "Google Gemini",
    "xAI Grok",
)
URL_CUSTOM_OPTION = "自定义"


def choice(values, default=None):
    return (tuple(values), {"default": default or values[0]})


def platform_for_model(model_label):
    for platform, prefix in PLATFORM_PREFIXES.items():
        if model_label.startswith(prefix):
            return platform
    raise ValueError(f"无法从模型名称识别平台：{model_label}")


def platform_for_request(protocol, model_label):
    if protocol in REQUEST_PROTOCOL_TO_PLATFORM:
        return REQUEST_PROTOCOL_TO_PLATFORM[protocol]
    return platform_for_model(model_label)


def api_key_from_value(value):
    api_key = str(value or "").strip()
    if not api_key or api_key == KEY_ADVERTISEMENT:
        raise ValueError("请填写所选模型对应的 key")
    return api_key


def collect_images(values):
    images = []
    for index in range(1, MAX_IMAGES + 1):
        images.extend(tensor_batch_to_png(values.get(f"图片{index}")))
        if len(images) > MAX_IMAGES:
            raise ValueError("所有图片接口合计最多支持 16 张图片")
    return images


def raw_response(value):
    return json.dumps(redact_response(value), ensure_ascii=False, separators=(",", ":"))


def raise_upstream_error(result):
    error = result.get("error") if isinstance(result, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or "未知上游错误"
        raise RuntimeError(f"上游返回错误：{sanitize(str(message))}")
    if isinstance(error, str):
        raise RuntimeError(f"上游返回错误：{sanitize(error)}")
