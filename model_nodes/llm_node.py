from .client import BASE_URL, SUPPORTED_BASE_URLS, UKClient, UpstreamHTTPError, extract_text, sanitize
from .common import (
    KEY_ADVERTISEMENT,
    REQUEST_PROTOCOLS,
    URL_CUSTOM_OPTION,
    api_key_from_value,
    choice,
    collect_images,
    platform_for_request,
    raw_response,
)
from .media import MAX_IMAGES, MAX_VIDEOS, video_to_data_uri
from .models import LLM_MODEL_IDS, resolve_model
from .protocols import (
    build_claude,
    build_gemini,
    build_grok_response,
    build_openai_response,
    extract_gemini_text,
    extract_grok_text,
)
from ..proxy import PROXY_ADDRESS, PROXY_PASSWORD, PROXY_USERNAME, proxy_input_fields


class MmuuAILLMModelNode:
    CATEGORY = "MU/接口"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("文本", "原始响应")

    @classmethod
    def INPUT_TYPES(cls):
        optional = {f"图片{i}": ("IMAGE",) for i in range(1, MAX_IMAGES + 1)}
        optional.update({f"视频{i}": ("VIDEO",) for i in range(1, MAX_VIDEOS + 1)})
        return {
            "required": {
                # Keep the persisted widget order aligned with the UI order.
                # ComfyUI serializes widget values positionally, so these must not
                # be moved client-side after a workflow has been loaded.
                "请求协议": choice(REQUEST_PROTOCOLS, "自动（按模型）"),
                "URL": ([*SUPPORTED_BASE_URLS, URL_CUSTOM_OPTION], {"default": BASE_URL}),
                "自定义URL": ("STRING", {"default": ""}),
                "模型名称": ("STRING", {"default": "gpt-5.6-luna"}),
                "key": ("STRING", {"default": KEY_ADVERTISEMENT, "password": True}),
                "系统提示词": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "提示词": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "温度": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.01}),
                "思考强度": choice(("自动（模型默认）", "最少", "低", "中", "高", "极高", "最高")),
                "最大令牌数": ("INT", {"default": 128000, "min": 1, "max": 128000, "step": 1}),
                "回答详细度（GPT）": choice(("自动（模型默认）", "简洁", "标准", "详细")),
                "推理模式（统一响应）": choice(("标准", "专业")),
                "超时时间（秒，0不限）": ("INT", {"default": 600, "min": 0, "max": 2147483647, "step": 1}),
                **proxy_input_fields(),
            },
            "optional": {
                **optional,
                # Legacy controls remain loadable but are hidden by the browser
                # extension. Keep them after the stable public widget schema.
                "模型": choice(tuple(LLM_MODEL_IDS), "OpenAI｜LLM｜GPT-5.6 Luna"),
                "base地址": (list(SUPPORTED_BASE_URLS), {"default": BASE_URL}),
                "自定义模型名称或ID": ("STRING", {"default": ""}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def execute(self, **values):
        legacy_label = str(values.get("模型") or "").strip()
        requested_model = str(values.get("模型名称") or values.get("自定义模型名称或ID") or legacy_label).strip()
        if not requested_model:
            raise ValueError("请填写模型名称或模型ID")
        model = resolve_model(requested_model, LLM_MODEL_IDS) if requested_model in LLM_MODEL_IDS else requested_model
        protocol = values.get("请求协议") or "自动（按模型）"
        if protocol == "自动（按模型）" and not legacy_label:
            raise ValueError("手动填写模型名称后，请选择对应的请求协议")
        platform = platform_for_request(protocol, legacy_label or model)
        api_key = api_key_from_value(values["key"])
        images = collect_images(values)
        videos = [
            video_to_data_uri(values[f"视频{index}"])
            for index in range(1, MAX_VIDEOS + 1)
            if values.get(f"视频{index}") is not None
        ]
        if videos and platform != "Gemini":
            raise ValueError("当前只有 Gemini 原生协议支持视频输入")
        base_url = values.get("URL") or values.get("base地址") or BASE_URL
        if base_url == URL_CUSTOM_OPTION:
            base_url = values.get("自定义URL") or ""
        client = UKClient(
            api_key, values.get("超时时间（秒，0不限）", 600), base_url,
            values.get(PROXY_ADDRESS, ""), values.get(PROXY_USERNAME, ""), values.get(PROXY_PASSWORD, ""),
        )
        try:
            return self._request(client, platform, model, images, videos, values)
        except Exception as exc:
            raise RuntimeError(f"MU LLM模型执行失败：{sanitize(str(exc))}") from exc

    @staticmethod
    def _request(client, platform, model, images, videos, values):
        system, prompt = values["系统提示词"], values["提示词"]
        temperature, max_tokens = values["温度"], values["最大令牌数"]
        thinking = values["思考强度"]
        if platform == "Gemini":
            endpoint, payload = build_gemini(
                model, system, prompt, images, videos, temperature, max_tokens, None, thinking,
            )
            endpoint = endpoint.replace(":generateContent", ":streamGenerateContent?alt=sse")
            result = client.post_sse(endpoint, payload)
            return extract_gemini_text(result), raw_response(result)
        if platform == "Claude":
            payload = build_claude(model, system, prompt, images, temperature, max_tokens, thinking)
            result = _post_sse_with_temperature_fallback(
                client, "v1/messages", payload, {"anthropic-version": "2023-06-01"},
            )
            return extract_text(result), raw_response(result)
        if platform == "Grok":
            payload = build_grok_response(model, system, prompt, images, max_tokens)
            result = client.post_sse("v1/responses", payload)
            return extract_grok_text(result), raw_response(result)
        payload = build_openai_response(
            model, system, prompt, images, temperature, max_tokens, thinking,
            values["回答详细度（GPT）"], values["推理模式（统一响应）"],
        )
        result = _post_sse_with_temperature_fallback(client, "v1/responses", payload)
        return extract_text(result), raw_response(result)


def _post_sse_with_temperature_fallback(client, endpoint, payload, headers=None):
    try:
        return client.post_sse(endpoint, payload, headers)
    except UpstreamHTTPError as exc:
        if "temperature" not in payload or not exc.rejects_parameter("temperature"):
            raise
        compatible = dict(payload)
        compatible.pop("temperature", None)
        return client.post_sse(endpoint, compatible, headers)
