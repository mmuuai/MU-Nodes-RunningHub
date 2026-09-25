import io
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


def _materialize_source(video):
    source = video.get_stream_source()
    if isinstance(source, (str, Path)):
        return str(source), None

    if not hasattr(source, "read"):
        raise TypeError("视频输入不支持流式读取")

    source.seek(0)
    handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    try:
        shutil.copyfileobj(source, handle, length=1024 * 1024)
    finally:
        handle.close()
    return handle.name, handle.name


def compress_video(video, short_edge, frame_rate, video_bitrate, audio_bitrate, ffmpeg="ffmpeg"):
    source_path, temporary_source = _materialize_source(video)
    output_dir = Path(tempfile.gettempdir()) / "mmuuai-comfyui"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"compressed-{uuid.uuid4().hex}.mp4"
    scale = f"scale='if(gt(iw,ih),-2,{short_edge})':'if(gt(iw,ih),{short_edge},-2)'"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        source_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        scale,
        "-r",
        str(frame_rate),
        "-c:v",
        "libopenh264",
        "-b:v",
        f"{video_bitrate}k",
        "-maxrate",
        f"{video_bitrate}k",
        "-bufsize",
        f"{video_bitrate * 2}k",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        f"{audio_bitrate}k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    finally:
        if temporary_source:
            Path(temporary_source).unlink(missing_ok=True)

    if completed.returncode != 0:
        output_path.unlink(missing_ok=True)
        detail = (completed.stderr or completed.stdout or "未知错误")[-2000:].strip()
        raise RuntimeError(f"视频压缩失败：{detail}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("视频压缩失败：FFmpeg 没有生成输出文件")
    return output_path


class MmuuAIVideoCompressNode:
    CATEGORY = "MU/媒体处理"
    FUNCTION = "compress"
    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("视频", "压缩信息")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "视频": ("VIDEO",),
                "短边像素": ("INT", {"default": 480, "min": 144, "max": 2160, "step": 2}),
                "输出帧率": ("INT", {"default": 24, "min": 1, "max": 120, "step": 1}),
                "视频码率（kbps）": ("INT", {"default": 350, "min": 64, "max": 50000, "step": 1}),
                "音频码率（kbps）": ("INT", {"default": 64, "min": 16, "max": 512, "step": 1}),
            },
        }

    def compress(self, **kwargs):
        from comfy_api.latest import InputImpl

        output_path = compress_video(
            kwargs["视频"],
            kwargs["短边像素"],
            kwargs["输出帧率"],
            kwargs["视频码率（kbps）"],
            kwargs["音频码率（kbps）"],
        )
        size_mb = output_path.stat().st_size / (1024 * 1024)
        details = (
            f"短边 {kwargs['短边像素']}px | {kwargs['输出帧率']} fps | "
            f"视频 {kwargs['视频码率（kbps）']} kbps | "
            f"音频 {kwargs['音频码率（kbps）']} kbps | 输出 {size_mb:.1f} MB"
        )
        return (InputImpl.VideoFromFile(str(output_path)), details)
