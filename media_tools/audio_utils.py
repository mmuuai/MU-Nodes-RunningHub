import base64
import io
import wave

import numpy as np


def audio_to_wav_base64(audio):
    return base64.b64encode(audio_to_wav_bytes(audio)).decode("ascii")


def audio_to_wav_bytes(audio):
    if not isinstance(audio, dict) or "waveform" not in audio or "sample_rate" not in audio:
        raise ValueError("音频文件输入不是有效的 ComfyUI AUDIO")
    waveform = audio["waveform"].detach().cpu().float().numpy()
    if waveform.ndim != 3 or waveform.shape[0] != 1 or waveform.shape[1] < 1:
        raise ValueError("音频必须是单个 ComfyUI AUDIO，不能是批次")
    sample_rate = int(audio["sample_rate"])
    if sample_rate <= 0:
        raise ValueError("音频采样率无效")
    pcm = np.clip(waveform[0], -1.0, 1.0)
    pcm = (pcm.T * 32767.0).astype("<i2", copy=False)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(pcm.shape[1])
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()
