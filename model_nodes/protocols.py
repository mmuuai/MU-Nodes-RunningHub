import base64

from .media import image_data_uri


def _encoded(data):
    return base64.b64encode(data).decode("ascii")


THINKING_LEVELS = {
    "最少": "minimal", "低": "low", "中": "medium", "高": "high",
    "极高": "xhigh", "最高": "max",
}
VERBOSITY_LEVELS = {"简洁": "low", "标准": "medium", "详细": "high"}
CLAUDE_EFFORT_MODELS = {"claude-fable-5", "claude-opus-5", "claude-sonnet-5"}


def build_openai_response(
    model, system_prompt, prompt, images, temperature, max_tokens,
    thinking="自动（模型默认）", verbosity="自动（模型默认）", reasoning_mode="标准",
):
    inputs = []
    if system_prompt.strip():
        inputs.append({"role": "system", "content": system_prompt})
    content = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_image", "image_url": image_data_uri(data)} for data in images)
    inputs.append({"role": "user", "content": content})
    payload = {
        "model": model, "input": inputs, "temperature": temperature,
        "max_output_tokens": max_tokens, "stream": True,
    }
    reasoning = {}
    if thinking != "自动（模型默认）":
        effort = THINKING_LEVELS[thinking]
        reasoning["effort"] = "none" if effort == "minimal" else effort
    if reasoning_mode == "专业":
        reasoning["mode"] = "pro"
    if reasoning:
        payload["reasoning"] = reasoning
    if verbosity != "自动（模型默认）":
        payload["text"] = {"verbosity": VERBOSITY_LEVELS[verbosity]}
    return payload


def build_gemini(
    model, system_prompt, prompt, images, videos, temperature, max_tokens, image_options,
    thinking="自动（模型默认）",
):
    parts = [{"text": prompt}]
    parts.extend({
        "inlineData": {"mimeType": "image/png", "data": _encoded(data)},
    } for data in images)
    for value in videos:
        header, data = value.split(",", 1)
        parts.append({
            "inlineData": {"mimeType": header[5:].split(";", 1)[0], "data": data},
        })
    payload = {"contents": [{"role": "user", "parts": parts}]}
    if system_prompt.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    if image_options is None:
        payload["generationConfig"] = {
            "temperature": temperature, "maxOutputTokens": min(max_tokens, 65536),
        }
        action = "generateContent"
    else:
        resolution, size = image_options
        image = {}
        if resolution != "自动":
            image["imageSize"] = resolution.upper()
        if size != "自动":
            image["aspectRatio"] = {
                "1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3",
            }.get(size, size)
        payload["generationConfig"] = {"responseModalities": ["IMAGE"]}
        if image:
            payload["generationConfig"]["imageConfig"] = image
        action = "generateContent"
    if image_options is None and thinking != "自动（模型默认）":
        level = THINKING_LEVELS[thinking]
        generation_level = "HIGH" if level in ("xhigh", "max") else level.upper()
        payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": generation_level}
    return f"v1beta/models/{model}:{action}", payload


def extract_gemini_text(payload):
    if isinstance(payload, list):
        return "".join(extract_gemini_text(event) for event in payload)
    if not isinstance(payload, dict):
        return ""
    return "".join(
        part.get("text", "")
        for candidate in payload.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )


def build_claude(
    model, system_prompt, prompt, images, temperature, max_tokens,
    thinking="自动（模型默认）",
):
    content = []
    content.extend({
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": _encoded(data)},
    } for data in images)
    content.append({"type": "text", "text": prompt})
    payload = {
        "model": model, "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens, "stream": True,
    }
    if model not in ("claude-fable-5", "claude-opus-5"):
        payload["temperature"] = temperature
    if system_prompt.strip():
        payload["system"] = system_prompt
    if thinking != "自动（模型默认）" and model in CLAUDE_EFFORT_MODELS:
        effort = THINKING_LEVELS[thinking]
        payload["output_config"] = {"effort": "low" if effort == "minimal" else effort}
    return payload


def build_grok_response(model, system_prompt, prompt, images, max_tokens):
    content = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_image", "image_url": image_data_uri(data)} for data in images)
    inputs = []
    if system_prompt.strip():
        inputs.append({"role": "system", "content": system_prompt})
    inputs.append({"role": "user", "content": content})
    return {"model": model, "input": inputs, "max_output_tokens": max_tokens, "stream": True}


def extract_grok_text(payload):
    if isinstance(payload, list):
        deltas = [
            str(event.get("delta", "")) for event in payload
            if event.get("type") == "response.output_text.delta"
        ]
        if deltas:
            return "".join(deltas)
        for event in reversed(payload):
            text = extract_grok_text(event)
            if text:
                return text
        return ""
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    return "".join(
        item.get("text", "")
        for output in payload.get("output", [])
        for item in output.get("content", [])
        if isinstance(item, dict) and item.get("type") == "output_text"
    )


def build_grok_image(model, prompt, images, resolution, size, editing=False):
    payload = {"model": model, "prompt": prompt, "n": 1}
    if resolution != "自动":
        payload["resolution"] = resolution.lower()
    if size != "自动":
        payload["aspect_ratio"] = {
            "1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3",
        }.get(size, size)
    if editing and images:
        payload["image_urls"] = [image_data_uri(data) for data in images]
    return payload
