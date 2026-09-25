MODEL_IDS = {
    "OpenAI｜LLM｜GPT-5.6 Sol": "gpt-5.6-sol",
    "OpenAI｜LLM｜GPT-5.6 Terra": "gpt-5.6-terra",
    "OpenAI｜LLM｜GPT-5.6 Luna": "gpt-5.6-luna",
    "OpenAI｜图片｜GPT Image 2": "gpt-image-2",
    "OpenAI｜图片｜GPT Image 2（官方渠道）": "gpt-image-2-official",
    "Google｜LLM｜Gemini 3.7 Flash": "gemini-3.7-flash",
    "Google｜LLM｜Gemini 3.6 Flash": "gemini-3.6-flash",
    "Google｜LLM｜Gemini 3.5 Flash": "gemini-3.5-flash",
    "Google｜LLM｜Gemini 3.5 Flash-Lite": "gemini-3.5-flash-lite",
    "Google｜图片｜Nano Banana 2": "gemini-3.1-flash-image-preview",
    "Google｜图片｜Nano Banana 2（官方渠道）": "gemini-3.1-flash-image-preview-official",
    "Google｜图片｜Nano Banana 2（Google 官方）": "gemini-3.1-flash-image",
    "Google｜图片｜Nano Banana 2 Lite": "gemini-3.1-flash-lite-image",
    "Google｜图片｜Nano Banana Pro": "gemini-3-pro-image-preview",
    "Google｜图片｜Nano Banana Pro（官方渠道）": "gemini-3-pro-image-preview-official",
    "xAI｜LLM｜Grok 4.6": "grok-4.6",
    "xAI｜LLM｜Grok 4.5": "grok-4.5",
    "xAI｜LLM｜Grok 4.3": "grok-4.3",
    "xAI｜图片｜Grok Imagine Image": "grok-imagine-image",
    "xAI｜图片｜Grok Imagine Image Quality": "grok-imagine-image-quality",
    "xAI｜图片｜Grok Imagine Image 2.0": "grok-imagine-image-2.0",
    "xAI｜图片｜Grok Imagine Image 2.0 Ext": "grok-imagine-2.0-ext",
    "Anthropic｜LLM｜Claude Fable 5": "claude-fable-5",
    "Anthropic｜LLM｜Claude Opus 5": "claude-opus-5",
    "Anthropic｜LLM｜Claude Sonnet 5": "claude-sonnet-5",
    "Anthropic｜LLM｜Claude Haiku 4.5": "claude-haiku-4-5-20251001",
}

LLM_MODEL_IDS = {label: model for label, model in MODEL_IDS.items() if "｜LLM｜" in label}
IMAGE_MODEL_IDS = {label: model for label, model in MODEL_IDS.items() if "｜图片｜" in label}


def resolve_model(label, available):
    try:
        return available[label]
    except KeyError as exc:
        raise ValueError(f"当前节点不支持该模型：{label}") from exc
