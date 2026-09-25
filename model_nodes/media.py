import base64
import io
import re

import numpy as np
import torch
from PIL import Image


MAX_IMAGES = 16
MAX_VIDEOS = 6
_EMBEDDED_IMAGE_DATA_URI = re.compile(
    r"data:image/[^;,\s)]+;base64,([A-Za-z0-9+/=]+)"
)


def tensor_batch_to_png(images):
    if images is None:
        return []
    if len(images) > MAX_IMAGES:
        raise ValueError("输入图片最多 16 张")
    output = []
    for tensor in images:
        array = np.clip(tensor.detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
        image = Image.fromarray(array).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        output.append(buffer.getvalue())
    return output


def image_data_uri(data):
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def video_to_data_uri(video):
    source = video.get_stream_source()
    if isinstance(source, str):
        with open(source, "rb") as handle:
            data = handle.read()
    else:
        source.seek(0)
        data = source.read()
        source.seek(0)
    container = video.get_container_format().split(",", 1)[0].lower()
    mime_types = {
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "quicktime": "video/quicktime",
        "mpeg": "video/mpeg",
        "mpegvideo": "video/mpeg",
        "avi": "video/x-msvideo",
        "webm": "video/webm",
        "flv": "video/x-flv",
        "wmv": "video/x-ms-wmv",
        "3gp": "video/3gpp",
        "3gpp": "video/3gpp",
    }
    mime_type = mime_types.get(container)
    if not mime_type:
        raise ValueError(f"不支持当前视频容器格式：{container}")
    return f"data:{mime_type};base64," + base64.b64encode(data).decode("ascii")


def multipart_images(images):
    files = []
    for index, data in enumerate(images):
        field = "image" if len(images) == 1 else f"image[{index}]"
        files.append((field, (f"image-{index}.png", io.BytesIO(data), "image/png")))
    return files


def collect_image_refs(value, output):
    if isinstance(value, dict):
        inline = value.get("inlineData", value.get("inline_data"))
        if isinstance(inline, dict):
            mime_type = str(inline.get("mimeType", inline.get("mime_type", "")))
            data = inline.get("data")
            if mime_type.startswith("image/") and isinstance(data, str):
                output.append(("base64", data))
                return
        for key, child in value.items():
            if key in ("b64_json", "b64") and isinstance(child, str):
                output.append(("base64", child))
            elif key in ("url", "image_url"):
                refs = child if isinstance(child, list) else [child]
                for ref in refs:
                    if not isinstance(ref, str):
                        continue
                    if ref.startswith("data:image/"):
                        output.append(("base64", ref.split(",", 1)[1]))
                    elif ref.startswith("https://") or ref.startswith("/"):
                        output.append(("url", ref))
            else:
                collect_image_refs(child, output)
    elif isinstance(value, list):
        for child in value:
            collect_image_refs(child, output)
    elif isinstance(value, str):
        for match in _EMBEDDED_IMAGE_DATA_URI.finditer(value):
            output.append(("base64", match.group(1)))


def decode_image_batch(payload, download):
    refs = []
    collect_image_refs(payload, refs)
    if not refs:
        return None
    if len(refs) > MAX_IMAGES:
        raise RuntimeError("API 返回图片数量超过 16 张")
    tensors = []
    for kind, value in refs:
        data = download(value) if kind == "url" else base64.b64decode(value, validate=True)
        try:
            image = Image.open(io.BytesIO(data)).convert("RGB")
            image.load()
        except Exception as exc:
            raise RuntimeError("API 返回了无法解析的图片") from exc
        array = np.asarray(image, dtype=np.float32) / 255.0
        tensors.append(torch.from_numpy(array).unsqueeze(0))
    if len({tuple(item.shape[1:]) for item in tensors}) != 1:
        raise RuntimeError("API 返回的图片尺寸不一致，无法组成批次")
    return torch.cat(tensors, dim=0)
