import time
from pathlib import Path
from urllib.parse import quote

from .http_client import endpoint, public_https_url, request_json


DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com"
PARAFORMER_MODEL = "paraformer-v2"


def upload_transcription_file(session, base_url, api_key, file_source, file_name, timeout):
    policy_url = endpoint(
        base_url,
        f"/api/v1/uploads?action=getPolicy&model={quote(PARAFORMER_MODEL)}",
    )
    policy_response = request_json(
        session,
        "GET",
        policy_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=(30, min(timeout, 60)),
    )
    policy = policy_response.get("data") if isinstance(policy_response, dict) else None
    required = (
        "upload_host",
        "upload_dir",
        "oss_access_key_id",
        "signature",
        "policy",
        "x_oss_object_acl",
        "x_oss_forbid_overwrite",
    )
    if not isinstance(policy, dict) or any(not policy.get(key) for key in required):
        raise RuntimeError("DashScope 临时文件上传凭证不完整")

    safe_name = Path(file_name).name or "input.bin"
    object_key = f"{policy['upload_dir'].rstrip('/')}/{safe_name}"
    fields = [
        ("OSSAccessKeyId", (None, policy["oss_access_key_id"])),
        ("Signature", (None, policy["signature"])),
        ("policy", (None, policy["policy"])),
        ("x-oss-object-acl", (None, policy["x_oss_object_acl"])),
        ("x-oss-forbid-overwrite", (None, policy["x_oss_forbid_overwrite"])),
        ("key", (None, object_key)),
        ("success_action_status", (None, "200")),
        ("file", (safe_name, file_source)),
    ]
    response = session.post(
        public_https_url(policy["upload_host"], resolve=False),
        files=fields,
        timeout=(30, timeout),
        allow_redirects=False,
    )
    try:
        if response.status_code != 200:
            detail = response.content[:2000].decode("utf-8", errors="replace")
            raise RuntimeError(f"DashScope 临时文件上传失败，HTTP {response.status_code}: {detail}")
    finally:
        response.close()
    return f"oss://{object_key}"


def transcribe_paraformer(session, base_url, api_key, media_url, interval, timeout):
    source = _transcription_source(media_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    if source.startswith("oss://"):
        headers["X-DashScope-OssResourceResolve"] = "enable"
    submitted = request_json(
        session,
        "POST",
        endpoint(base_url, "/api/v1/services/audio/asr/transcription"),
        headers=headers,
        body={
            "model": PARAFORMER_MODEL,
            "input": {"file_urls": [source]},
            "parameters": {
                "channel_id": [0],
                "language_hints": ["zh", "en"],
                "timestamp_alignment_enabled": True,
                "diarization_enabled": True,
            },
        },
        timeout=(30, timeout),
    )
    task_id = _nested(submitted, "output", "task_id")
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError("Paraformer 提交响应中没有 task_id")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(interval)
        result = request_json(
            session,
            "POST",
            endpoint(base_url, f"/api/v1/tasks/{task_id}"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=(30, min(timeout, 60)),
        )
        output = result.get("output", {}) if isinstance(result, dict) else {}
        status = str(output.get("task_status", "")).upper()
        if status in ("PENDING", "RUNNING"):
            continue
        completed = output.get("results", [{}])
        completed = completed[0] if isinstance(completed, list) and completed else {}
        if status == "FAILED" or (isinstance(completed, dict) and completed.get("subtask_status") == "FAILED"):
            code = completed.get("code", output.get("code", "FAILED")) if isinstance(completed, dict) else "FAILED"
            if code == "SUCCESS_WITH_NO_VALID_FRAGMENT":
                return "未检测到有效语音。", {"submitted": submitted, "result": result}
            raise RuntimeError(f"Paraformer 转写任务失败：{code}")
        if status != "SUCCEEDED" or not isinstance(completed, dict):
            raise RuntimeError(f"Paraformer 返回未知任务状态：{status or 'EMPTY'}")
        transcript_url = completed.get("transcription_url")
        if not isinstance(transcript_url, str):
            raise RuntimeError("Paraformer 完成响应中没有 transcription_url")
        transcript = request_json(session, "GET", public_https_url(transcript_url), timeout=(30, min(timeout, 60)))
        text = _transcript_text(transcript)
        if not text:
            raise RuntimeError("Paraformer 转写结果中没有文本")
        return text, {"submitted": submitted, "result": result, "transcription": transcript}
    raise RuntimeError(f"Paraformer 转写等待超过 {timeout} 秒")


def _transcription_source(value):
    source = (value or "").strip()
    if source.startswith("oss://") and len(source) > len("oss://"):
        return source
    return public_https_url(source)


def _transcript_text(value):
    transcripts = value.get("transcripts", []) if isinstance(value, dict) else []
    lines = []
    for transcript in transcripts:
        if not isinstance(transcript, dict):
            continue
        sentences = transcript.get("sentences")
        if isinstance(sentences, list) and sentences:
            lines.extend(_sentence_lines(sentences))
            continue
        text = transcript.get("text")
        if isinstance(text, str) and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def _sentence_lines(sentences):
    lines = []
    for sentence in sentences:
        if not isinstance(sentence, dict):
            continue
        text = sentence.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        prefix = _timestamp_prefix(sentence.get("begin_time"), sentence.get("end_time"))
        speaker_id = sentence.get("speaker_id")
        if isinstance(speaker_id, int) and not isinstance(speaker_id, bool):
            prefix += f" 说话人{speaker_id + 1}："
        elif prefix:
            prefix += " "
        lines.append(f"{prefix}{text.strip()}")
    return lines


def _timestamp_prefix(begin_time, end_time):
    if not _is_milliseconds(begin_time) or not _is_milliseconds(end_time):
        return ""
    return f"[{_format_milliseconds(begin_time)} - {_format_milliseconds(end_time)}]"


def _is_milliseconds(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _format_milliseconds(value):
    total = int(round(value))
    hours, remainder = divmod(total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _nested(value, *keys):
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value
