import json
from urllib.parse import urlsplit

from .client import BASE_URL, SUPPORTED_BASE_URLS, UKClient, UpstreamHTTPError, sanitize
from .common import (
    KEY_ADVERTISEMENT,
    IMAGE_REQUEST_PROTOCOLS,
    URL_CUSTOM_OPTION,
    api_key_from_value,
    choice,
    collect_images,
    platform_for_request,
    raise_upstream_error,
    raw_response,
)
from .media import MAX_IMAGES, decode_image_batch, image_data_uri, multipart_images
from .models import IMAGE_MODEL_IDS, resolve_model
from .protocols import build_gemini, build_grok_image
from ..proxy import PROXY_ADDRESS, PROXY_PASSWORD, PROXY_USERNAME, proxy_input_fields

IMAGE_REQUEST_MODES = (
    "账号模式（OAuth）",
    "API模式（尺寸参数）",
)
IMAGE_SIZE_OPTIONS = (
    "自动",
    "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
    "16:9", "9:16", "2:1", "1:2", "3:1", "1:3", "21:9", "9:21",
)


def _aspect_ratio(value):
    return {
        "1024x1024": "1:1",
        "1536x1024": "3:2",
        "1024x1536": "2:3",
    }.get(value, value)


def _with_size_instruction(prompt, size):
    ratio = _aspect_ratio(size)
    if ratio == "自动":
        return prompt
    return f"{prompt}\n\n尺寸 {ratio}"


def build_image_payload(model, prompt, resolution, size, quality, moderation, request_mode):
    payload = {"model": model, "prompt": prompt, "n": 1}
    if request_mode == "账号模式（OAuth）":
        payload["prompt"] = _with_size_instruction(prompt, size)
        return payload
    if resolution != "自动":
        payload["resolution"] = resolution.lower()
    if size != "自动":
        payload["size"] = _aspect_ratio(size)
    if quality != "自动":
        payload["quality"] = quality
    if moderation != "自动（上游默认）" and model == "gpt-image-2-official":
        payload["moderation"] = "low"
    return payload


def build_gemini_image_payload(model, prompt, images, resolution, size):
    payload = {"model": model, "prompt": prompt, "n": 1}
    if resolution != "自动":
        payload["resolution"] = resolution.upper()
    if size != "自动":
        payload["size"] = {
            "1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3",
        }.get(size, size)
    if images:
        payload["image_urls"] = [image_data_uri(data) for data in images]
    return payload


class MmuuAIImageModelNode:
    CATEGORY = "MU/接口"
    FUNCTION = "execute"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图片", "原始响应")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # This is deliberately the visual and serialization order.  Do
                # not move these widgets in browser JavaScript after load.
                "请求协议": choice(IMAGE_REQUEST_PROTOCOLS, "自动（按模型）"),
                "URL": ([*SUPPORTED_BASE_URLS, URL_CUSTOM_OPTION], {"default": BASE_URL}),
                "自定义URL": ("STRING", {"default": ""}),
                "模型名称": ("STRING", {"default": "gpt-image-2"}),
                "key": ("STRING", {"default": KEY_ADVERTISEMENT, "password": True}),
                "图片请求模式": choice(IMAGE_REQUEST_MODES, "账号模式（OAuth）"),
                "提示词": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "分辨率": choice(("自动", "1K", "2K", "4K")),
                "尺寸": choice(IMAGE_SIZE_OPTIONS),
                "质量": choice(("自动", "low", "medium", "high")),
                "审核强度": choice(("自动（上游默认）", "低")),
                "超时时间（秒，0不限）": ("INT", {"default": 600, "min": 0, "max": 2147483647, "step": 1}),
                **proxy_input_fields(),
            },
            "optional": {
                **{f"图片{i}": ("IMAGE",) for i in range(1, MAX_IMAGES + 1)},
                # Legacy controls remain loadable but are hidden by the browser
                # extension. Keep them after the stable public widget schema.
                "模型": choice(tuple(IMAGE_MODEL_IDS), "OpenAI｜图片｜GPT Image 2"),
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
        model = resolve_model(requested_model, IMAGE_MODEL_IDS) if requested_model in IMAGE_MODEL_IDS else requested_model
        protocol = values.get("请求协议") or "自动（按模型）"
        if protocol == "自动（按模型）" and not legacy_label:
            raise ValueError("手动填写模型名称后，请选择对应的请求协议")
        platform = platform_for_request(protocol, legacy_label or model)
        api_key = api_key_from_value(values["key"])
        images = collect_images(values)
        base_url = values.get("URL") or values.get("base地址") or BASE_URL
        if base_url == URL_CUSTOM_OPTION:
            base_url = values.get("自定义URL") or ""
        client = UKClient(
            api_key, values.get("超时时间（秒，0不限）", 600), base_url,
            values.get(PROXY_ADDRESS, ""), values.get(PROXY_USERNAME, ""), values.get(PROXY_PASSWORD, ""),
        )
        try:
            result = self._request(client, platform, model, images, values)
            result = client.poll_image_task(result)
            image = self._decode_image(result, client)
            validation = _resolution_validation(
                image,
                values.get("图片请求模式", "API模式（尺寸参数）"),
                values["分辨率"],
                values["尺寸"],
            )
            return image, raw_response({"上游响应": result, "MU返图核验": validation})
        except Exception as exc:
            raise RuntimeError(f"MU 图片模型执行失败：{sanitize(str(exc))}") from exc

    @staticmethod
    def _request(client, platform, model, images, values):
        prompt, resolution, size = values["提示词"], values["分辨率"], values["尺寸"]
        if platform == "Gemini":
            payload = build_gemini_image_payload(model, prompt, images, resolution, size)
            try:
                return _post_json_prefer_async(client, "v1/images/generations", payload)
            except UpstreamHTTPError as exc:
                if exc.status_code != 404:
                    raise
                endpoint, legacy_payload = build_gemini(
                    model, "", prompt, images, [], 1.0, 1,
                    (resolution, size), "自动（模型默认）",
                )
                return client.post_json(endpoint, legacy_payload)
        if platform == "Grok":
            payload = build_grok_image(model, prompt, images, resolution, size, bool(images))
            try:
                return _post_json_prefer_async(client, "v1/images/generations", payload)
            except UpstreamHTTPError as exc:
                if not images or not _requires_public_image_url(exc):
                    raise
                data = {
                    key: str(value) for key, value in payload.items()
                    if key != "image_urls"
                }
                try:
                    return _post_multipart_prefer_async(
                        client, "v1/images/edits", data, multipart_images(images),
                    )
                except UpstreamHTTPError as fallback:
                    raise RuntimeError(
                        "当前 Grok 账号路由不接受内联图片，且 multipart 编辑接口也不可用；"
                        "MART 路由需要 UK 后端先上传图片并代理异步任务查询。"
                        f"最终上游错误：{fallback}"
                    ) from fallback
        payload = build_image_payload(
            model,
            prompt,
            resolution,
            size,
            values["质量"],
            values["审核强度"],
            values.get("图片请求模式", "API模式（尺寸参数）"),
        )
        if images:
            request_mode = values.get("图片请求模式", "API模式（尺寸参数）")
            if request_mode == "API模式（尺寸参数）":
                # UK's API-mode GPT image route accepts reference images on
                # the generations contract.  Its multipart edits route is
                # reserved for Grok models and rejects GPT models.
                payload["image_urls"] = [image_data_uri(data) for data in images]
                return _post_json_prefer_async(
                    client, "v1/images/generations", payload,
                )
            # GPT image editing is a multipart `/images/edits` request.  The
            # OAuth route requires the provider-side edit contract so the
            # reference files are not silently ignored as text-to-image.
            data = {key: str(value) for key, value in payload.items()}
            return _post_multipart_prefer_async(
                client,
                "v1/images/edits",
                data,
                multipart_images(images),
            )
        return _post_json_prefer_async(client, "v1/images/generations", payload)

    @staticmethod
    def _decode_image(result, client):
        image = decode_image_batch(result, client.download_image)
        if image is not None:
            return image
        raise_upstream_error(result)
        if "task_id" in json.dumps(result, ensure_ascii=False):
            raise RuntimeError("UK 返回了异步图片任务，但未开放对应任务查询路由")
        raise RuntimeError("上游响应中没有可解析的图片")


def _resolution_validation(image, request_mode, requested_resolution, requested_size):
    height, width = int(image.shape[1]), int(image.shape[2])
    minimum_long_edge = (
        {"1K": 1000, "2K": 2000, "4K": 3800}.get(requested_resolution)
        if request_mode == "API模式（尺寸参数）"
        else None
    )
    resolution_matches = (
        None if minimum_long_edge is None else max(width, height) >= minimum_long_edge
    )
    expected_ratio = _requested_ratio(requested_size)
    ratio_matches = None
    if expected_ratio is not None:
        ratio_matches = abs((width / height) - expected_ratio) / expected_ratio <= 0.03
    validation = {
        "图片请求模式": request_mode,
        "请求分辨率": requested_resolution,
        "请求尺寸": requested_size,
        "实际像素": f"{width}x{height}",
        "图片数量": int(image.shape[0]),
        "符合请求分辨率": resolution_matches,
        "符合请求尺寸": ratio_matches,
    }
    warnings = []
    if request_mode == "账号模式（OAuth）" and requested_resolution != "自动":
        warnings.append("OAuth 账号通道不接收精确 resolution 参数，分辨率由上游账号决定")
    if resolution_matches is False:
        warnings.append(f"请求 {requested_resolution}，实际长边只有 {max(width, height)} 像素")
    if ratio_matches is False:
        warnings.append(f"请求 {requested_size}，实际比例为 {width}:{height}")
    if warnings:
        validation["警告"] = "；".join(warnings)
    return validation


def _requested_ratio(value):
    normalized = {
        "1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3",
    }.get(value, value)
    if ":" not in normalized:
        return None
    left, right = normalized.split(":", 1)
    try:
        numerator, denominator = float(left), float(right)
    except ValueError:
        return None
    return numerator / denominator if denominator > 0 else None


def _post_json_prefer_async(client, endpoint, payload):
    if _is_gateway_client(client):
        # The UK gateway's async image route can acknowledge a task without
        # forwarding it to the configured upstream account. Submit image jobs
        # through the documented synchronous route; it may still return a
        # task envelope, which poll_image_task handles below.
        return client.post_json(endpoint, payload)
    try:
        return client.post_json(f"{endpoint}/async", payload)
    except UpstreamHTTPError as exc:
        if exc.status_code != 404:
            raise
        return client.post_json(endpoint, payload)


def _post_multipart_prefer_async(client, endpoint, data, files):
    if _is_gateway_client(client):
        return client.post_multipart(endpoint, data, files)
    try:
        return client.post_multipart(f"{endpoint}/async", data, files)
    except UpstreamHTTPError as exc:
        if exc.status_code != 404:
            raise
        for _field, (_name, stream, _content_type) in files:
            stream.seek(0)
        return client.post_multipart(endpoint, data, files)


def _is_gateway_client(client):
    return (urlsplit(str(client.base_url or "")).hostname or "").lower() in {
        "api.mmuu.uk", "api.mmuu.ai",
    }


def _requires_public_image_url(error):
    text = f"{error.upstream_message} {error.code}".lower()
    return error.status_code == 400 and (
        "absolute http(s) url" in text or "base64" in text and "not supported" in text
    )
