from .client import BASE_URL, SUPPORTED_BASE_URLS, UKClient, extract_text, sanitize
from .common import KEY_ADVERTISEMENT, URL_CUSTOM_OPTION, api_key_from_value, choice, raw_response
from .gemini_video_file import GeminiFile
from .protocols import extract_gemini_text
from ..proxy import PROXY_ADDRESS, PROXY_PASSWORD, PROXY_USERNAME, proxy_input_fields


THINKING_OPTIONS = ("自动（模型默认）", "最少", "低", "中", "高", "极高", "最高")
THINKING_LEVELS = {
    "最少": "MINIMAL", "低": "LOW", "中": "MEDIUM", "高": "HIGH",
    "极高": "HIGH", "最高": "HIGH",
}


class MmuuAIGeminiVideoLLMNode:
    CATEGORY = "MU/接口"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("文本", "原始响应")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "Google文件": ("GEMINI_FILE",),
                "URL": ([*SUPPORTED_BASE_URLS, URL_CUSTOM_OPTION], {"default": BASE_URL}),
                "自定义URL": ("STRING", {"default": ""}),
                "模型名称": ("STRING", {"default": "gemini-3.6-flash"}),
                "key": ("STRING", {"default": KEY_ADVERTISEMENT, "password": True}),
                "系统提示词": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "提示词": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "温度": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.01}),
                "思考强度": choice(THINKING_OPTIONS, "自动（模型默认）"),
                "最大令牌数": ("INT", {"default": 8192, "min": 1, "max": 65536, "step": 1}),
                "超时时间（秒，0不限）": ("INT", {"default": 600, "min": 0, "max": 2147483647}),
                **proxy_input_fields(),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def execute(self, **values):
        file_info = values["Google文件"]
        if isinstance(file_info, dict):
            uri = str(file_info.get("uri", "")).strip()
            mime_type = str(file_info.get("mime_type") or file_info.get("mimeType") or "").strip()
        else:
            uri = str(getattr(file_info, "uri", "")).strip()
            mime_type = str(getattr(file_info, "mime_type", "")).strip()
        if not uri or not mime_type:
            raise ValueError("Google文件输入无效，请连接 Google 视频上传节点")
        if not isinstance(file_info, (GeminiFile, dict)):
            raise ValueError("Google文件输入类型无效，请连接 Google 视频上传节点")
        model = str(values["模型名称"] or "").strip()
        if not model:
            raise ValueError("请填写 Gemini 模型名称或模型ID")
        base_url = values["URL"]
        if base_url == URL_CUSTOM_OPTION:
            base_url = values["自定义URL"]
        client = UKClient(
            api_key_from_value(values["key"]), values["超时时间（秒，0不限）"], base_url,
            values.get(PROXY_ADDRESS, ""), values.get(PROXY_USERNAME, ""), values.get(PROXY_PASSWORD, ""),
        )
        payload = {
            "contents": [{"role": "user", "parts": [
                {"fileData": {"mimeType": mime_type, "fileUri": uri}},
                {"text": values["提示词"]},
            ]}],
            "generationConfig": {
                "temperature": values["温度"],
                "maxOutputTokens": min(values["最大令牌数"], 65536),
            },
        }
        if values["系统提示词"].strip():
            payload["systemInstruction"] = {"parts": [{"text": values["系统提示词"]}]}
        thinking = values["思考强度"]
        if thinking != "自动（模型默认）":
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingLevel": THINKING_LEVELS[thinking],
            }
        endpoint = f"v1beta/models/{model}:streamGenerateContent?alt=sse"
        try:
            result = client.post_sse(endpoint, payload)
            text = extract_gemini_text(result) or extract_text(result)
            return text, raw_response(result)
        except Exception as exc:
            raise RuntimeError(f"MU Gemini视频LLM执行失败：{sanitize(str(exc))}") from exc
