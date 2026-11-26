"""Exactly two workflow nodes; no key widgets or model-weight downloads."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .client import MagiError, RunningHubClient, Settings
from .media import prepare_reference, upload_reference
from .schema import ASPECT_RATIOS, MODES, common_payload, parse_urls


def _interrupt():
    from comfy.model_management import throw_exception_if_processing_interrupted

    throw_exception_if_processing_interrupted()


def _runtime():
    try:
        import folder_paths
        from comfy_api.input_impl import VideoFromFile
    except ImportError:
        raise MagiError("请使用支持原生 VIDEO/VideoFromFile 的较新 ComfyUI 或 RunningHub 运行环境。") from None
    return Path(folder_paths.get_output_directory()) / "magi2", VideoFromFile


def _receipt(directory, task_id, **updates):
    target = directory / f"task_{task_id}.json"
    current = {}
    if target.is_file():
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    current.update(updates, task_id=task_id, updated_at=datetime.now(timezone.utc).isoformat())
    temporary = directory / f".receipt_{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _run(client, directory, video_class, endpoint, payload, resume_task_id):
    task_id = resume_task_id or client.submit(endpoint, payload)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise MagiError("taskId 格式无效，请检查 API 调用记录。")
    # Save the ID before the first query so a restart/interruption can resume it.
    print(f"[MAGI-2] taskId={task_id}")
    try:
        _receipt(directory, task_id, endpoint=endpoint, status="QUERYING")
    except OSError:
        raise MagiError(f"任务 {task_id} 已存在，但本地回执保存失败。请记录此ID并检查输出目录权限或磁盘空间。") from None
    url, response = client.poll(task_id)
    _receipt(directory, task_id, status="SUCCESS", response=response)
    filename = f"magi2_{task_id}_{uuid.uuid4().hex[:12]}.mp4"
    target = directory / filename
    temporary = directory / (filename + ".part")
    try:
        client.download(url, temporary)
        video = video_class(str(temporary))
        width, height = video.get_dimensions()
        if width <= 0 or height <= 0:
            raise MagiError("视频尺寸无效。")
        os.replace(temporary, target)
    except Exception as error:
        temporary.unlink(missing_ok=True)
        if isinstance(error, MagiError):
            raise MagiError(f"任务 {task_id}：{error}") from None
        # Preserve ComfyUI's interrupt exception and the receipt on cancellation.
        raise
    _receipt(directory, task_id, status="DOWNLOADED", filename=filename, width=width, height=height)
    response_text = json.dumps(response, ensure_ascii=False, indent=2)
    return {
        "ui": {
            "images": [{"filename": filename, "subfolder": "magi2", "type": "output", "format": "video/mp4"}],
            "animated": (True,),
            "text": [f"taskId: {task_id}", f"{width} × {height}", url],
        },
        "result": (video_class(str(target)), url, task_id, response_text),
    }


def _inputs():
    return {
        "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "画面、动作与运镜描述，最多15000字。"}),
        "duration": ("INT", {"default": 5, "min": 4, "max": 30, "step": 1, "tooltip": "成片时长（秒），按此秒数计费。"}),
        "aspect_ratio": (ASPECT_RATIOS, {"default": "16:9"}),
        "resolution": (["1080p"], {"default": "1080p", "tooltip": "官方当前仅支持1080p。"}),
        "generate_audio": ("BOOLEAN", {"default": True}),
        "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "control_after_generate": True}),
    }


def _advanced():
    return {
        "resume_task_id": ("STRING", {"default": "", "tooltip": "填写已有任务ID：仅查询和下载，不上传素材、不创建新任务。"}),
        "max_wait_seconds": ("INT", {"default": 1800, "min": 30, "max": 7200, "step": 30}),
        "poll_interval": ("INT", {"default": 5, "min": 1, "max": 30}),
    }


class _Base:
    CATEGORY = "RunningHub/MAGI-2"
    FUNCTION = "generate"
    RETURN_TYPES = ("VIDEO", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video", "video_url", "task_id", "response_json")
    OUTPUT_NODE = True

    @staticmethod
    def context(max_wait_seconds, poll_interval, resume_task_id):
        resume_task_id = resume_task_id.strip()
        if resume_task_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", resume_task_id):
            raise MagiError("resume_task_id 格式无效。")
        settings = Settings.resolve(max_wait_seconds, poll_interval)
        directory, video_class = _runtime()
        directory.mkdir(parents=True, exist_ok=True)
        return RunningHubClient(settings, interrupt=_interrupt), directory, video_class, resume_task_id


class Magi2TextToVideoRH(_Base):
    DESCRIPTION = "通过RunningHub官方API调用MAGI-2文生视频，支持1080p、4–30秒、原生声音。"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": _inputs(), "optional": _advanced()}

    def generate(self, prompt, duration, aspect_ratio, resolution, generate_audio, seed,
                 resume_task_id="", max_wait_seconds=1800, poll_interval=5):
        endpoint = "sand-ai/magi-2/text-to-video"
        payload = None if resume_task_id.strip() else common_payload(
            prompt, duration, aspect_ratio, resolution, generate_audio, seed)
        client, directory, video_class, resume = self.context(max_wait_seconds, poll_interval, resume_task_id)
        with client:
            return _run(client, directory, video_class, endpoint, payload, resume)


class Magi2ReferenceVideoRH(_Base):
    DESCRIPTION = (
        "MAGI-2图片/多模态参考生视频。first_frame=首帧；first_last_frame=首尾帧；"
        "multimodal_reference=图片/视频/音频参考。原生IMAGE/VIDEO/AUDIO会自动上传。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "first_frame": ("IMAGE",),
            "last_frame": ("IMAGE",),
            "reference_images": ("IMAGE", {"tooltip": "图片批次，最多10张；排列在image_urls之前。"}),
            "reference_video": ("VIDEO", {"tooltip": "原生VIDEO，2–30秒，至多200MiB。"}),
            "reference_audio": ("AUDIO", {"tooltip": "原生AUDIO，2–30秒，至多15MiB。"}),
            "first_frame_url": ("STRING", {"default": ""}),
            "last_frame_url": ("STRING", {"default": ""}),
            "image_urls": ("STRING", {"default": "", "multiline": True, "tooltip": "每行一个URL或JSON数组；与本地参考图合计最多10张。"}),
            "video_urls": ("STRING", {"default": "", "multiline": True, "tooltip": "每行一个URL或JSON数组；与本地视频合计最多5段，总时长≤30秒。"}),
            "audio_urls": ("STRING", {"default": "", "multiline": True, "tooltip": "每行一个URL或JSON数组；与本地音频合计最多5段，总时长≤30秒。"}),
            **_advanced(),
        }
        return {"required": {"mode": (MODES, {"default": "first_frame"}), **_inputs()}, "optional": optional}

    def generate(self, mode, prompt, duration, aspect_ratio, resolution, generate_audio, seed,
                 first_frame=None, last_frame=None, reference_images=None, reference_video=None,
                 reference_audio=None, first_frame_url="", last_frame_url="", image_urls="",
                 video_urls="", audio_urls="", resume_task_id="", max_wait_seconds=1800, poll_interval=5):
        if mode not in MODES:
            raise MagiError("请选择有效的图片/多模态参考模式。")
        endpoint = "sand-ai/magi-2/" + ("reference-to-video" if mode == "multimodal_reference" else "image-to-video")
        if resume_task_id.strip():
            client, directory, video_class, resume = self.context(max_wait_seconds, poll_interval, resume_task_id)
            with client:
                return _run(client, directory, video_class, endpoint, None, resume)
        payload = common_payload(prompt, duration, aspect_ratio, resolution, generate_audio, seed,
                                 required_prompt=mode == "multimodal_reference")
        urls = {
            "first": parse_urls(first_frame_url, 1, "首帧 URL"),
            "last": parse_urls(last_frame_url, 1, "尾帧 URL"),
            "imageUrls": parse_urls(image_urls, 10, "图片 URL"),
            "videoUrls": parse_urls(video_urls, 5, "视频 URL"),
            "audioUrls": parse_urls(audio_urls, 5, "音频 URL"),
        }
        urls["first"] = urls["first"][0] if urls["first"] else ""
        urls["last"] = urls["last"][0] if urls["last"] else ""
        client, directory, video_class, _ = self.context(max_wait_seconds, poll_interval, "")
        with client, prepare_reference(
            mode, urls, first_frame=first_frame, last_frame=last_frame,
            reference_images=reference_images, reference_video=reference_video, reference_audio=reference_audio,
        ) as uploads:
            payload.update(upload_reference(client, mode, urls, uploads))
            return _run(client, directory, video_class, endpoint, payload, "")


NODE_CLASS_MAPPINGS = {
    "Magi2TextToVideoRH": Magi2TextToVideoRH,
    "Magi2ReferenceVideoRH": Magi2ReferenceVideoRH,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "Magi2TextToVideoRH": "MAGI-2 文生视频 / Text to Video (RH)",
    "Magi2ReferenceVideoRH": "MAGI-2 图片·多模态参考 / Reference Video (RH)",
}
