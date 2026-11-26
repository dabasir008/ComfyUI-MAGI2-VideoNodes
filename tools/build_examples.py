"""Generate both importable ComfyUI graphs and matching API-format examples."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOCUSED = {
    "image_to_video": ("Magi2ImageToVideoRH", [("image", "IMAGE")]),
    "first_last_frame_dedicated": ("Magi2FirstLastFrameRH", [("first_frame", "IMAGE"), ("last_frame", "IMAGE")]),
    "multi_image_reference": ("Magi2MultiImageReferenceRH", [(f"image_{i}", "IMAGE") for i in range(1, 11)]),
    "video_reference": ("Magi2VideoReferenceRH", [(f"video_{i}", "VIDEO") for i in range(1, 6)]
                        + [("reference_images", "IMAGE"), ("reference_audio", "AUDIO")]),
    "audio_reference": ("Magi2AudioReferenceRH", [(f"audio_{i}", "AUDIO") for i in range(1, 6)]
                        + [("reference_images", "IMAGE"), ("reference_video", "VIDEO")]),
    "task_result": ("Magi2TaskResultRH", []),
}
EXAMPLE_KINDS = ["text_to_video", "first_frame", "first_last_frame", "multimodal_reference", *FOCUSED]


def image_node(node_id, x, y, name, link_id):
    return {
        "id": node_id, "type": "LoadImage", "pos": [x, y], "size": [300, 320],
        "flags": {}, "order": node_id - 1, "mode": 0, "inputs": [],
        "outputs": [
            {"name": "IMAGE", "type": "IMAGE", "links": [link_id], "slot_index": 0},
            {"name": "MASK", "type": "MASK", "links": None, "slot_index": 1},
        ],
        "properties": {"Node name for S&R": "LoadImage"},
        "widgets_values": [name, "image"],
    }


def example(kind):
    if kind in FOCUSED:
        return focused_example(kind)
    text_only = kind == "text_to_video"
    multimodal = kind == "multimodal_reference"
    dual = kind == "first_last_frame"
    node_type = "Magi2TextToVideoRH" if text_only else "Magi2ReferenceVideoRH"
    prompt = ("A cinematic close-up of a glass perfume bottle on wet black marble, "
              "the camera slowly orbits, warm backlight, subtle ambient sound.")
    mode = "multimodal_reference" if multimodal else ("first_last_frame" if dual else "first_frame")
    # seed has ComfyUI's standard control_after_generate widget immediately after it.
    widgets = [prompt, 5, "16:9", "1080p", True, 0, "fixed"]
    if not text_only:
        widgets = [mode] + widgets + ["", "", "", "", ""]
    widgets += ["", 1800, 5]
    inputs = []
    links = []
    nodes = []
    if not text_only:
        pin_types = [("first_frame", "IMAGE"), ("last_frame", "IMAGE"), ("reference_images", "IMAGE"),
                     ("reference_video", "VIDEO"), ("reference_audio", "AUDIO")]
        inputs = [{"name": name, "type": type_name, "link": None} for name, type_name in pin_types]
        slot = 2 if multimodal else 0
        nodes.append(image_node(1, 20, 40, "upload_your_reference.png", 1))
        inputs[slot]["link"] = 1
        links.append([1, 1, 0, 10, slot, "IMAGE"])
        if dual:
            nodes.append(image_node(2, 20, 420, "upload_your_last_frame.png", 2))
            inputs[1]["link"] = 2
            links.append([2, 2, 0, 10, 1, "IMAGE"])
    nodes.append({
        "id": 10, "type": node_type, "pos": [420, 40], "size": [570, 760 if not text_only else 500],
        "flags": {}, "order": len(nodes), "mode": 0, "inputs": inputs,
        "outputs": [{"name": name, "type": type_name, "links": None, "slot_index": index}
                    for index, (name, type_name) in enumerate([
                        ("video", "VIDEO"), ("video_url", "STRING"), ("task_id", "STRING"), ("response_json", "STRING")
                    ])],
        "properties": {"Node name for S&R": node_type}, "widgets_values": widgets,
    })
    note = (
        "MAGI-2 / RunningHub\n1080p | 4–30 seconds | six aspect ratios\n"
        "API usage is billed by RunningHub.\n"
        "Upload your images into LoadImage before queuing.\n"
        "The MAGI-2 node saves and previews MP4 automatically.\n"
        "Connect VIDEO to SaveVideo/GetVideoComponents for more processing.\n"
        "On timeout, use resume_task_id to retrieve the existing task.\n"
        "Multimodal: optional LoadVideo.VIDEO / LoadAudio.AUDIO;\n"
        "additional references: one URL per line, or a JSON array."
    )
    nodes.append({"id": 20, "type": "Note", "pos": [1050, 40], "size": [430, 300],
                  "flags": {}, "order": len(nodes), "mode": 0, "inputs": [], "outputs": [],
                  "properties": {}, "widgets_values": [note], "color": "#243", "bgcolor": "#354"})
    workflow = {
        "last_node_id": 20, "last_link_id": len(links), "nodes": nodes, "links": links,
        "groups": [], "config": {}, "extra": {"ds": {"scale": 0.8, "offset": [30, 30]}}, "version": 0.4,
    }
    api_inputs = {"prompt": prompt, "duration": 5, "aspect_ratio": "16:9", "resolution": "1080p",
                  "generate_audio": True, "seed": 0, "resume_task_id": "", "max_wait_seconds": 1800, "poll_interval": 5}
    api = {}
    if not text_only:
        api_inputs.update(mode=mode, first_frame_url="", last_frame_url="", image_urls="", video_urls="", audio_urls="")
        api["1"] = {"class_type": "LoadImage", "inputs": {"image": "upload_your_reference.png"}}
        api_inputs["reference_images" if multimodal else "first_frame"] = ["1", 0]
        if dual:
            api["2"] = {"class_type": "LoadImage", "inputs": {"image": "upload_your_last_frame.png"}}
            api_inputs["last_frame"] = ["2", 0]
    api["10"] = {"class_type": node_type, "inputs": api_inputs}
    return workflow, api


def focused_example(kind):
    node_type, pins = FOCUSED[kind]
    prompt = "Follow the reference subjects and scene; a slow cinematic camera move, natural ambient sound."
    inputs = [{"name": name, "type": type_name, "link": None} for name, type_name in pins]
    api_inputs = {"prompt": prompt, "duration": 5, "aspect_ratio": "16:9", "resolution": "1080p",
                  "generate_audio": True, "seed": 0, "resume_task_id": "", "max_wait_seconds": 1800, "poll_interval": 5}
    widgets = [prompt, 5, "16:9", "1080p", True, 0, "fixed", "", 1800, 5]
    if kind == "task_result":
        api_inputs = {"task_id": "replace_with_existing_task_id", "max_wait_seconds": 1800, "poll_interval": 5}
        widgets = ["replace_with_existing_task_id", 1800, 5]
    nodes, links, api = [], [], {}
    count = 0 if kind == "task_result" else (1 if kind == "image_to_video" else 2)
    for index, (name, type_name) in enumerate(pins[:count]):
        node_id = index + 1
        if type_name == "IMAGE":
            filename = f"upload_reference_{node_id}.png"
            source = image_node(node_id, 20, 40 + 350 * index, filename, node_id)
            source_class, field = "LoadImage", "image"
        else:
            source_class, field, extension = ("LoadVideo", "file", "mp4") if type_name == "VIDEO" else ("LoadAudio", "audio", "wav")
            filename = f"upload_reference_{node_id}.{extension}"
            source = {"id": node_id, "type": source_class, "pos": [20, 40 + 350 * index], "size": [300, 300],
                      "flags": {}, "order": index, "mode": 0, "inputs": [],
                      "outputs": [{"name": type_name, "type": type_name, "links": [node_id], "slot_index": 0}],
                      "properties": {"Node name for S&R": source_class}, "widgets_values": [filename]}
        nodes.append(source)
        inputs[index]["link"] = node_id
        links.append([node_id, node_id, 0, 10, index, type_name])
        api[str(node_id)] = {"class_type": source_class, "inputs": {field: filename}}
        api_inputs[name] = [str(node_id), 0]
    nodes.append({"id": 10, "type": node_type, "pos": [420, 40], "size": [600, 720],
                  "flags": {}, "order": count, "mode": 0, "inputs": inputs,
                  "outputs": [{"name": name, "type": type_name, "links": None, "slot_index": index}
                              for index, (name, type_name) in enumerate([
                                  ("video", "VIDEO"), ("video_url", "STRING"), ("task_id", "STRING"), ("response_json", "STRING")])],
                  "properties": {"Node name for S&R": node_type}, "widgets_values": widgets})
    note = ("MAGI-2 focused node / 1080p / 4–30 seconds\n"
            "Replace the placeholder media before running.\n"
            "Images: at most 10 in total, including batches.\n"
            "Videos: up to 5; each 2–30s, total at most 30s.\n"
            "Audio: up to 5; each 2–30s, total at most 30s.\n"
            "Reference generation does not guarantee exact motion copying or lip sync.\n"
            "Task recovery only queries/downloads an existing task; no new generation.")
    nodes.append({"id": 20, "type": "Note", "pos": [1080, 40], "size": [450, 280], "flags": {},
                  "order": count + 1, "mode": 0, "inputs": [], "outputs": [], "properties": {},
                  "widgets_values": [note], "color": "#243", "bgcolor": "#354"})
    api["10"] = {"class_type": node_type, "inputs": api_inputs}
    return {"last_node_id": 20, "last_link_id": len(links), "nodes": nodes, "links": links,
            "groups": [], "config": {}, "extra": {"ds": {"scale": 0.8, "offset": [30, 30]}}, "version": 0.4}, api


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for kind in EXAMPLE_KINDS:
        for suffix, content in zip(["workflow", "api"], example(kind)):
            target = ROOT / "examples" / f"magi2_{kind}.{suffix}.json"
            expected = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
            if args.check:
                if not target.is_file() or target.read_text(encoding="utf-8") != expected:
                    raise SystemExit(f"Outdated or missing: {target.name}")
            else:
                target.parent.mkdir(exist_ok=True)
                target.write_text(expected, encoding="utf-8")
    print(f"{len(EXAMPLE_KINDS) * 2} example files " + ("verified." if args.check else "generated."))


if __name__ == "__main__":
    main()
