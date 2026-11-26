"""ComfyUI IMAGE/VIDEO/AUDIO inputs to bounded, temporary upload files."""

from __future__ import annotations

import io
import math
import wave
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from .client import MagiError

MIB = 1024 ** 2


@dataclass
class Upload:
    name: str
    mime: str
    content: bytes | Path

    def send(self, client):
        if isinstance(self.content, Path):
            with self.content.open("rb") as stream:
                return client.upload(self.name, stream, self.mime)
        return client.upload(self.name, self.content, self.mime)


def _numpy(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def image_uploads(images, label, max_count):
    if images is None:
        return []
    array = _numpy(images)
    if array.ndim != 4 or array.shape[-1] not in (3, 4) or not 1 <= array.shape[0] <= max_count:
        raise MagiError(f"{label}需要 [N,H,W,3/4] IMAGE，图片数必须为 1–{max_count}。")
    if not array.shape[1] or not array.shape[2] or not np.isfinite(array).all():
        raise MagiError(f"{label}包含空图或无效像素。")
    if array.min() < 0 or array.max() > 1:
        raise MagiError(f"{label}像素范围必须为 0–1。")
    uploads = []
    for index, frame in enumerate(array):
        buffer = io.BytesIO()
        Image.fromarray(np.rint(frame * 255).astype(np.uint8)).save(buffer, format="PNG")
        content = buffer.getvalue()
        if len(content) > 30 * MIB:
            raise MagiError(f"{label}第 {index + 1} 张图片超过 30 MiB。")
        uploads.append(Upload(f"{label}_{index + 1}.png", "image/png", content))
    return uploads


def video_duration(video):
    if not hasattr(video, "get_duration") or not hasattr(video, "save_to"):
        raise MagiError("reference_video 需要原生 VIDEO 输入，请连接 LoadVideo 的 VIDEO 输出。")
    duration = float(video.get_duration())
    if not math.isfinite(duration) or not 2 <= duration <= 30:
        raise MagiError("参考视频必须为 2–30 秒；请先用视频裁剪节点处理。")
    return duration


def video_upload(video, directory, name="reference_video.mp4"):
    video_duration(video)
    target = Path(directory) / name
    # save_to respects VIDEO trim/crop operations; reading its original source
    # directly would accidentally upload the untrimmed/unmodified input.
    video.save_to(str(target), format="mp4", codec="h264")
    if not target.is_file() or not 0 < target.stat().st_size <= 200 * MIB:
        raise MagiError("参考视频为空或超过 200 MiB。")
    return Upload(target.name, "video/mp4", target)


def audio_upload(audio):
    if not isinstance(audio, dict) or "waveform" not in audio or "sample_rate" not in audio:
        raise MagiError("reference_audio 需要 LoadAudio 的 AUDIO 输出。")
    rate = audio["sample_rate"]
    waveform = _numpy(audio["waveform"])
    if type(rate) is not int or rate <= 0:
        raise MagiError("音频采样率必须为正整数。")
    if waveform.ndim != 3 or waveform.shape[0] != 1 or waveform.shape[1] not in (1, 2):
        raise MagiError("参考音频需要单个音频批次及 1 或 2 声道。")
    if not np.isfinite(waveform).all() or not 2 <= waveform.shape[2] / rate <= 30:
        raise MagiError("参考音频必须为 2–30 秒，并且不能包含无效采样。")
    pcm = np.rint(np.clip(waveform[0].T, -1, 1) * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(waveform.shape[1])
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm)
    content = buffer.getvalue()
    if len(content) > 15 * MIB:
        raise MagiError("参考音频超过 15 MiB。请降低采样率后重试。")
    return Upload("reference_audio.wav", "audio/wav", content)


@contextmanager
def prepare_reference(mode, urls, *, first_frame=None, last_frame=None,
                      reference_images=None, reference_video=None, reference_audio=None):
    """Validate and encode ALL media before uploading any of it."""
    with TemporaryDirectory(prefix="magi2_reference_") as directory:
        uploads = {}
        if mode == "multimodal_reference":
            if first_frame is not None or last_frame is not None or urls["first"] or urls["last"]:
                raise MagiError("多模态参考模式请使用 reference_images/image_urls，移除首尾帧输入。")
            images = image_uploads(reference_images, "reference_images", 10)
            videos = [video_upload(reference_video, directory)] if reference_video is not None else []
            audios = [audio_upload(reference_audio)] if reference_audio is not None else []
            for key, local, limit in (("imageUrls", images, 10), ("videoUrls", videos, 5), ("audioUrls", audios, 5)):
                if len(local) + len(urls[key]) > limit:
                    raise MagiError(f"{key}的本地素材加 URL 素材合计不能超过 {limit} 项。")
                uploads[key] = local
            if not any(uploads.values()) and not any(urls[key] for key in uploads):
                raise MagiError("多模态参考模式至少需要一种图片、视频或音频素材。")
        else:
            if reference_images is not None or reference_video is not None or reference_audio is not None or any(
                urls[key] for key in ("imageUrls", "videoUrls", "audioUrls")
            ):
                raise MagiError("首帧/首尾帧模式请使用 first_frame/last_frame，移除多模态参考输入。")
            if first_frame is not None and urls["first"]:
                raise MagiError("首帧图片和首帧 URL 二选一。")
            if first_frame is None and not urls["first"]:
                raise MagiError("请连接 first_frame 或填写 first_frame_url。")
            uploads["imageUrl"] = image_uploads(first_frame, "first_frame", 1)
            if mode == "first_last_frame":
                if last_frame is not None and urls["last"]:
                    raise MagiError("尾帧图片和尾帧 URL 二选一。")
                if last_frame is None and not urls["last"]:
                    raise MagiError("首尾帧模式需要 last_frame 或 last_frame_url。")
                uploads["endImageUrl"] = image_uploads(last_frame, "last_frame", 1)
            elif last_frame is not None or urls["last"]:
                raise MagiError("已提供尾帧，请将 mode 切换为 first_last_frame。")
        yield uploads


def upload_reference(client, mode, urls, uploads):
    if mode == "multimodal_reference":
        # Stable ordering: native connected inputs first, URL entries afterwards.
        return {key: [item.send(client) for item in local] + urls[key]
                for key, local in uploads.items()}
    result = {"imageUrl": uploads["imageUrl"][0].send(client)
              if uploads["imageUrl"] else urls["first"]}
    if mode == "first_last_frame":
        result["endImageUrl"] = uploads["endImageUrl"][0].send(client) if uploads["endImageUrl"] else urls["last"]
    return result


@contextmanager
def prepare_native_references(images=(), videos=(), audios=()):
    """Multiple independent native sockets, including differently sized images.

    Validate aggregate durations before video export or any network upload.
    Each video gets its own file; files live until all uploads have finished.
    """
    if len(videos) > 5 or len(audios) > 5:
        raise MagiError("参考视频和音频分别最多支持5段。")
    if sum(video_duration(video) for video in videos) > 30 + 1e-6:
        raise MagiError("所有本地参考视频合计不能超过30秒。")
    image_files = []
    for image in images:
        image_files.extend(image_uploads(image, "reference_images", 10))
        if len(image_files) > 10:
            raise MagiError("所有图片输入中的图片合计不能超过10张。")
    audio_files = [audio_upload(audio) for audio in audios]
    audio_seconds = 0
    for audio in audio_files:
        with wave.open(io.BytesIO(audio.content), "rb") as source:
            audio_seconds += source.getnframes() / source.getframerate()
    if audio_seconds > 30 + 1e-6:
        raise MagiError("所有本地参考音频合计不能超过30秒。")
    if not image_files and not videos and not audio_files:
        raise MagiError("至少需要一种参考素材。")
    with TemporaryDirectory(prefix="magi2_multi_reference_") as directory:
        video_files = [video_upload(video, directory, f"reference_video_{index + 1}.mp4")
                       for index, video in enumerate(videos)]
        yield {"imageUrls": image_files, "videoUrls": video_files, "audioUrls": audio_files}
