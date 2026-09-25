from .http_client import endpoint, request_json


MEOWLOAD_BASE_URL = "https://api.meowload.net"
MAX_PLAYLIST_PAGES = 5


def extract_media(session, base_url, api_key, source_url, page_count, timeout):
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "accept-language": "zh",
    }
    if page_count is None:
        result = request_json(
            session,
            "POST",
            endpoint(base_url, "/openapi/extract/post"),
            headers=headers,
            body={"url": source_url},
            timeout=timeout,
        )
        return summarize_media(result), result

    pages = []
    cursor = None
    for _ in range(max(1, min(int(page_count), MAX_PLAYLIST_PAGES))):
        body = {"url": source_url}
        if cursor:
            body["cursor"] = cursor
        page = request_json(
            session,
            "POST",
            endpoint(base_url, "/openapi/extract/playlist"),
            headers=headers,
            body=body,
            timeout=timeout,
        )
        pages.append(page)
        if not isinstance(page, dict) or page.get("has_more") is not True:
            break
        cursor = page.get("next_cursor")
        if not isinstance(cursor, str) or not cursor.strip():
            raise RuntimeError("主页解析响应声明还有下一页，但没有 next_cursor")
    combined = {
        "fetched_pages": len(pages),
        "posts": [post for page in pages if isinstance(page, dict) for post in page.get("posts", [])],
        "user": next((page.get("user") for page in pages if isinstance(page, dict) and page.get("user")), None),
    }
    return summarize_media(combined), combined


def summarize_media(payload):
    titles = []
    buckets = {"video": [], "audio": [], "image": []}
    _walk(payload, titles, buckets, 0)
    return {
        "text": "\n".join(_unique(titles)),
        "videos": _unique(buckets["video"]),
        "audios": _unique(buckets["audio"]),
        "images": _unique(buckets["image"]),
    }


def _walk(value, titles, buckets, depth, declared_type=None):
    if depth > 8:
        return
    if isinstance(value, list):
        for item in value:
            _walk(item, titles, buckets, depth + 1, declared_type)
        return
    if not isinstance(value, dict):
        return
    media_type = value.get("media_type") if value.get("media_type") in buckets else declared_type
    for key in ("text", "title", "description"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            titles.append(item.strip())
    direct = value.get("resource_url", value.get("url"))
    if media_type and _is_url(direct):
        buckets[media_type].append(direct)
    key_types = {
        "video_url": "video", "audio_url": "audio", "image_url": "image",
        "cover_url": "image", "preview_url": "image", "thumbnail_url": "image",
    }
    for key, kind in key_types.items():
        if _is_url(value.get(key)):
            buckets[kind].append(value[key])
    for key, child in value.items():
        next_type = {"videos": "video", "audios": "audio", "images": "image"}.get(key, media_type)
        if isinstance(child, (dict, list)):
            _walk(child, titles, buckets, depth + 1, next_type)


def _is_url(value):
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _unique(values):
    return list(dict.fromkeys(values))
