import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from magi2.client import MagiError
from magi2.media import prepare_native_references
from magi2.nodes import (
    Magi2AudioReferenceRH, Magi2FirstLastFrameRH, Magi2ImageToVideoRH,
    Magi2MultiImageReferenceRH, Magi2TaskResultRH, Magi2VideoReferenceRH, NODE_CLASS_MAPPINGS,
)
from test_magi2 import DummyVideo, MP4, Response, SUCCESS, client
from tools.build_examples import EXAMPLE_KINDS, example

COMMON = dict(prompt="camera moves", duration=4, aspect_ratio="16:9", resolution="1080p",
              generate_audio=True, seed=7)


def image(width=8, height=8, count=1):
    return np.zeros((count, height, width, 3), dtype=np.float32)


def audio(seconds=2):
    return {"waveform": np.zeros((1, 1, int(seconds * 8000))), "sample_rate": 8000}


class InputVideo:
    def __init__(self, seconds=2, marker=b"first"):
        self.seconds, self.marker, self.exports = seconds, marker, []

    def get_duration(self):
        return self.seconds

    def save_to(self, path, **kwargs):
        self.exports.append(path)
        Path(path).write_bytes(MP4 + self.marker)


def execute(node, references, uploads):
    responses = [Response({"code": 0, "data": {"download_url": f"https://example.com/upload-{i}"}})
                 for i in range(uploads)]
    api, session = client(responses + [Response({"taskId": "12345"}), Response(SUCCESS)])
    with tempfile.TemporaryDirectory() as directory, patch.object(
        node, "context", return_value=(api, Path(directory), DummyVideo, "")
    ):
        result = node().generate(**COMMON, **references)
        assert Path(result["result"][0].path).is_file()
    generation = [(url, arguments["json"]) for url, arguments in session.posts
                  if not url.endswith(("/query", "/media/upload/binary"))]
    return generation, session


class FocusedNodeTests(unittest.TestCase):
    def test_single_image_uses_dedicated_image_endpoint(self):
        calls, session = execute(Magi2ImageToVideoRH, {"image": image()}, 1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith("/image-to-video"))
        self.assertIn("imageUrl", calls[0][1])
        self.assertNotIn("imageUrls", calls[0][1])
        self.assertNotIn("mode", calls[0][1])
        self.assertEqual(len(session.posts), 3)

    def test_first_and_last_frames_keep_distinct_payload_fields(self):
        calls, _ = execute(Magi2FirstLastFrameRH, {"first_frame": image(), "last_frame": image(12, 10)}, 2)
        payload = calls[0][1]
        self.assertEqual(payload["imageUrl"], "https://example.com/upload-0")
        self.assertEqual(payload["endImageUrl"], "https://example.com/upload-1")

    def test_multi_image_accepts_different_shapes_and_preserves_batch_order(self):
        calls, session = execute(Magi2MultiImageReferenceRH,
                                 {"image_1": image(8, 10, 2), "image_2": image(20, 12)}, 3)
        self.assertTrue(calls[0][0].endswith("/reference-to-video"))
        self.assertEqual(calls[0][1]["imageUrls"], [f"https://example.com/upload-{i}" for i in range(3)])
        dimensions = []
        for _, arguments in session.posts[:3]:
            with Image.open(io.BytesIO(arguments["files"]["file"][1])) as uploaded:
                dimensions.append(uploaded.size)
        self.assertEqual(dimensions, [(8, 10), (8, 10), (20, 12)])

    def test_video_node_supports_five_native_videos_and_cross_references(self):
        references = {f"video_{i}": InputVideo(2) for i in range(1, 6)}
        references.update(reference_images=image(), reference_audio=audio())
        calls, session = execute(Magi2VideoReferenceRH, references, 7)
        payload = calls[0][1]
        self.assertEqual([len(payload[name]) for name in ("imageUrls", "videoUrls", "audioUrls")], [1, 5, 1])
        filenames = [arguments["files"]["file"][0] for _, arguments in session.posts if arguments.get("files")]
        self.assertEqual(len(set(name for name in filenames if name.endswith(".mp4"))), 5)

    def test_audio_node_supports_five_native_audios_and_cross_references(self):
        references = {f"audio_{i}": audio(2) for i in range(1, 6)}
        references.update(reference_images=image(), reference_video=InputVideo(2))
        calls, _ = execute(Magi2AudioReferenceRH, references, 7)
        self.assertEqual([len(calls[0][1][name]) for name in ("imageUrls", "videoUrls", "audioUrls")], [1, 1, 5])

    def test_single_image_batches_are_not_silently_truncated(self):
        api, session = client([])
        with tempfile.TemporaryDirectory() as directory, patch.object(
            Magi2ImageToVideoRH, "context", return_value=(api, Path(directory), DummyVideo, "")
        ), self.assertRaises(MagiError):
            Magi2ImageToVideoRH().generate(image=image(count=2), **COMMON)
        self.assertEqual(session.posts, [])

    def test_missing_primary_and_invalid_prompt_fail_before_context(self):
        for node in (Magi2MultiImageReferenceRH, Magi2VideoReferenceRH, Magi2AudioReferenceRH):
            with self.subTest(node=node.__name__), patch.object(node, "context") as context:
                with self.assertRaises(MagiError):
                    node().generate(**COMMON)
                context.assert_not_called()
                with self.assertRaises(MagiError):
                    node().generate(**dict(COMMON, prompt=""))
                context.assert_not_called()

    def test_task_recovery_only_queries_and_preserves_known_endpoint(self):
        api, session = client([Response(SUCCESS)])
        with tempfile.TemporaryDirectory() as directory, patch.object(
            Magi2TaskResultRH, "context", return_value=(api, Path(directory), DummyVideo, "12345")
        ):
            receipt = Path(directory) / "task_12345.json"
            receipt.write_text(json.dumps({"endpoint": "sand-ai/magi-2/image-to-video"}), encoding="utf-8")
            result = Magi2TaskResultRH().generate("12345")
            self.assertEqual(result["result"][2], "12345")
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["endpoint"], "sand-ai/magi-2/image-to-video")
        self.assertEqual(len(session.posts), 1)
        self.assertTrue(session.posts[0][0].endswith("/query"))

    def test_empty_recovery_id_never_creates_task(self):
        with patch.object(Magi2TaskResultRH, "context") as context:
            for task_id in ("", " ", None):
                with self.assertRaises(MagiError):
                    Magi2TaskResultRH().generate(task_id)
            context.assert_not_called()

    def test_resume_on_all_native_reference_nodes_skips_media(self):
        for node in (Magi2MultiImageReferenceRH, Magi2VideoReferenceRH, Magi2AudioReferenceRH):
            api, session = client([Response(SUCCESS)])
            with tempfile.TemporaryDirectory() as directory, patch.object(
                node, "context", return_value=(api, Path(directory), DummyVideo, "12345")
            ):
                node().generate(**dict(COMMON, prompt="", resume_task_id="12345"))
            self.assertEqual(len(session.posts), 1)
            self.assertTrue(session.posts[0][0].endswith("/query"))


class AggregateMediaTests(unittest.TestCase):
    def test_separate_video_files_have_correct_content_and_are_cleaned(self):
        with prepare_native_references(videos=[InputVideo(marker=b"one"), InputVideo(marker=b"two")]) as prepared:
            paths = [upload.content for upload in prepared["videoUrls"]]
            self.assertNotEqual(paths[0], paths[1])
            self.assertTrue(paths[0].read_bytes().endswith(b"one"))
            self.assertTrue(paths[1].read_bytes().endswith(b"two"))
        self.assertTrue(all(not path.exists() for path in paths))

    def test_video_total_over_30_rejected_before_export(self):
        videos = [InputVideo(16), InputVideo(15)]
        with self.assertRaisesRegex(MagiError, "合计"), prepare_native_references(videos=videos):
            pass
        self.assertTrue(all(not video.exports for video in videos))

    def test_audio_total_over_30_rejected_before_video_export(self):
        video = InputVideo(2)
        with self.assertRaisesRegex(MagiError, "合计"), prepare_native_references(
            videos=[video], audios=[audio(16), audio(15)]
        ):
            pass
        self.assertEqual(video.exports, [])

    def test_exact_30_seconds_per_category_is_allowed(self):
        with prepare_native_references(videos=[InputVideo(15), InputVideo(15)], audios=[audio(15), audio(15)]) as prepared:
            self.assertEqual(len(prepared["videoUrls"]), 2)
            self.assertEqual(len(prepared["audioUrls"]), 2)

    def test_all_image_batches_together_are_limited_to_ten(self):
        with self.assertRaisesRegex(MagiError, "10张"), prepare_native_references(images=[image(count=6), image(count=5)]):
            pass

    def test_excess_video_audio_counts_and_short_clips_rejected(self):
        for references in ({"videos": [InputVideo()] * 6}, {"audios": [audio()] * 6},
                           {"videos": [InputVideo(1)]}, {"audios": [audio(1)]}):
            with self.subTest(references=list(references)), self.assertRaises(MagiError), prepare_native_references(**references):
                pass

    def test_over_total_duration_node_does_not_upload_or_submit(self):
        for node, references in (
            (Magi2VideoReferenceRH, {"video_1": InputVideo(20), "video_2": InputVideo(11)}),
            (Magi2AudioReferenceRH, {"audio_1": audio(20), "audio_2": audio(11)}),
        ):
            api, session = client([])
            with tempfile.TemporaryDirectory() as directory, patch.object(
                node, "context", return_value=(api, Path(directory), DummyVideo, "")
            ), self.assertRaises(MagiError):
                node().generate(**COMMON, **references)
            self.assertEqual(session.posts, [])


class AllExampleTests(unittest.TestCase):
    def test_examples_cover_every_node_with_valid_widget_order_and_connections(self):
        covered = set()
        self.assertEqual(len(EXAMPLE_KINDS), 10)
        for kind in EXAMPLE_KINDS:
            workflow, api = example(kind)
            nodes = {node["id"]: node for node in workflow["nodes"]}
            node = nodes[10]
            covered.add(node["type"])
            schema = NODE_CLASS_MAPPINGS[node["type"]].INPUT_TYPES()
            values = api["10"]["inputs"]
            self.assertTrue(set(schema["required"]) <= set(values), kind)
            self.assertTrue(set(values) <= set(schema["required"]) | set(schema["optional"]), kind)
            widgets = []
            for name, spec in {**schema["required"], **schema["optional"]}.items():
                if isinstance(spec[0], list) or spec[0] in ("STRING", "INT", "BOOLEAN", "FLOAT"):
                    widgets.append(values[name])
                    if len(spec) > 1 and spec[1].get("control_after_generate"):
                        widgets.append("fixed")
            self.assertEqual(node["widgets_values"], widgets, kind)
            for link_id, source, out_slot, target, in_slot, type_name in workflow["links"]:
                self.assertEqual(nodes[source]["outputs"][out_slot]["type"], type_name)
                self.assertEqual(nodes[target]["inputs"][in_slot]["type"], type_name)
                pin = nodes[target]["inputs"][in_slot]["name"]
                self.assertEqual(values[pin], [str(source), out_slot])
        self.assertEqual(covered, set(NODE_CLASS_MAPPINGS))


if __name__ == "__main__":
    unittest.main()
