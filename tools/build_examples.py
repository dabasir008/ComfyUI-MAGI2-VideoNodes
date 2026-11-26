"""Generate both importable ComfyUI graphs and matching API-format examples."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for kind in ["text_to_video", "first_frame", "first_last_frame", "multimodal_reference"]:
        for suffix, content in zip(["workflow", "api"], example(kind)):
            target = ROOT / "examples" / f"magi2_{kind}.{suffix}.json"
            expected = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
            if args.check:
                if not target.is_file() or target.read_text(encoding="utf-8") != expected:
                    raise SystemExit(f"Outdated or missing: {target.name}")
            else:
                target.parent.mkdir(exist_ok=True)
                target.write_text(expected, encoding="utf-8")
    print("Eight example files verified." if args.check else "Eight example files generated.")


if __name__ == "__main__":
    main()
