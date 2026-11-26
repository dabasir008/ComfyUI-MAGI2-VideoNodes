"""Parameter validation shared by both nodes, before uploads or generation."""

import json

from .client import MagiError, check_url

ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]
MODES = ["first_frame", "first_last_frame", "multimodal_reference"]


def common_payload(prompt, duration, aspect_ratio, resolution, generate_audio, seed, *, required_prompt=True):
    if not isinstance(prompt, str):
        raise MagiError("提示词必须是文字。")
    prompt = prompt.strip()
    if len(prompt) > 15000 or (required_prompt and not prompt):
        raise MagiError("提示词长度必须为 1–15000 字；图生视频允许留空。")
    if type(duration) is not int or not 4 <= duration <= 30:
        raise MagiError("时长必须是 4–30 秒的整数。")
    if aspect_ratio not in ASPECT_RATIOS or resolution != "1080p":
        raise MagiError("MAGI-2 仅支持 1080p 和节点中列出的六种画面比例。")
    if type(generate_audio) is not bool:
        raise MagiError("generate_audio 必须是布尔值。")
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise MagiError("随机种子必须为 0–2147483647 的整数。")
    payload = {"duration": duration, "aspectRatio": aspect_ratio, "resolution": resolution,
               "generateAudio": generate_audio, "seed": seed}
    if prompt:
        payload["prompt"] = prompt
    return payload


def parse_urls(text, limit, label):
    if not isinstance(text, str):
        raise MagiError(f"{label}需要每行一个 URL 或 JSON 数组。")
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            values = json.loads(text)
        except ValueError:
            raise MagiError(f"{label}不是有效 JSON 数组。") from None
    else:
        values = [line.strip() for line in text.splitlines() if line.strip()]
    if not isinstance(values, list) or len(values) > limit:
        raise MagiError(f"{label}最多支持 {limit} 项。")
    return [check_url(value) for value in values]
