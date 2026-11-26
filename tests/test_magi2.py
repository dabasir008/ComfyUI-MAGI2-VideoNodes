import importlib.util
import io
import json
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import requests

from magi2.client import MagiError, RunningHubClient, Settings, check_url
from magi2.media import audio_upload, image_uploads, prepare_reference, upload_reference
from magi2.nodes import Magi2ReferenceVideoRH, Magi2TextToVideoRH, NODE_CLASS_MAPPINGS, _run
from magi2.schema import ASPECT_RATIOS, common_payload, parse_urls

KEY = "unit-test-key-never-real"
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2" + b"\x00" * 100
SUCCESS = {"taskId": "12345", "status": "SUCCESS", "results": [
    {"outputType": "png", "url": "https://cdn.example.com/preview.png"},
    {"outputType": "mp4", "url": "https://cdn.example.com/result.mp4"},
]}


class Response:
    def __init__(self, data=None, status=200, content=MP4, content_type="video/mp4"):
        self.data, self.status_code, self.content = data, status, content
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("dummy download failure")

    def iter_content(self, chunk_size):
        yield self.content[:16]
        yield self.content[16:]


class Session:
    def __init__(self, responses=(), download=None):
        self.responses = iter(responses)
        self.posts, self.gets = [], []
        self.download = download if download is not None else Response()

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self.download

    def close(self):
        pass


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def client(responses, **kwargs):
    session = Session(responses, kwargs.pop("download", None))
    clock = Clock()
    instance = RunningHubClient(Settings(KEY, poll_interval=1, max_wait=3), session=session,
                                clock=clock, sleep=clock.sleep, **kwargs)
    return instance, session


def urls(**updates):
    result = {"first": "", "last": "", "imageUrls": [], "videoUrls": [], "audioUrls": []}
    result.update(updates)
    return result


class DummyVideo:
    def __init__(self, path):
        self.path = path

    def get_dimensions(self):
        if Path(self.path).read_bytes()[4:8] != b"ftyp":
            raise ValueError("not a video")
        return 1920, 1080


class SchemaTests(unittest.TestCase):
    def test_exactly_two_nodes_and_no_credentials_widgets(self):
        self.assertEqual(len(NODE_CLASS_MAPPINGS), 2)
        for node in NODE_CLASS_MAPPINGS.values():
            inputs = node.INPUT_TYPES()
            names = set(inputs["required"]) | set(inputs["optional"])
            self.assertFalse(names & {"api_key", "apiKey", "token", "base_url"})
            self.assertEqual(node.RETURN_TYPES[0], "VIDEO")
            self.assertTrue(node.OUTPUT_NODE)
            self.assertTrue(callable(getattr(node(), node.FUNCTION)))

    def test_plugin_root_import(self):
        path = Path(__file__).resolve().parents[1] / "__init__.py"
        spec = importlib.util.spec_from_file_location("test_magi2_plugin", path,
                                                    submodule_search_locations=[str(path.parent)])
        module = importlib.util.module_from_spec(spec)
        import sys
        with patch.dict(sys.modules, {spec.name: module}):
            spec.loader.exec_module(module)
        self.assertEqual(set(module.NODE_CLASS_MAPPINGS), set(NODE_CLASS_MAPPINGS))

    def test_all_official_aspects_and_duration_boundaries(self):
        for aspect in ASPECT_RATIOS:
            for duration in (4, 30):
                result = common_payload("镜头", duration, aspect, "1080p", False, 2147483647)
                self.assertEqual(result["aspectRatio"], aspect)
                self.assertEqual(result["duration"], duration)
                self.assertIs(result["generateAudio"], False)

    def test_invalid_payloads_are_rejected(self):
        valid = ["prompt", 5, "16:9", "1080p", True, 0]
        cases = [(0, ""), (0, "a" * 15001), (1, 3), (1, 31), (1, 5.0), (1, True),
                 (2, "auto"), (2, ""), (3, "4k"), (4, "true"), (5, -1), (5, 2147483648)]
        for index, value in cases:
            with self.subTest(index=index, value=str(value)[:30]):
                values = valid.copy()
                values[index] = value
                with self.assertRaises(MagiError):
                    common_payload(*values)

    def test_image_prompt_is_optional(self):
        payload = common_payload("  ", 5, "16:9", "1080p", True, 0, required_prompt=False)
        self.assertNotIn("prompt", payload)

    def test_url_formats_and_order(self):
        expected = ["https://example.com/1.png", "https://example.com/2.png"]
        self.assertEqual(parse_urls("\n".join(expected), 10, "图"), expected)
        self.assertEqual(parse_urls(json.dumps(expected), 10, "图"), expected)
        self.assertEqual(parse_urls("", 10, "图"), [])

    def test_invalid_and_excess_urls(self):
        for value in ('["https://example.com", 2]', '["unfinished"', 'file:///C:/image.png',
                      'https://name:password@example.com/a.png', 'data:image/png;base64,AAA', 'https://['):
            with self.subTest(value=value), self.assertRaises(MagiError):
                parse_urls(value, 10, "图")
        with self.assertRaises(MagiError):
            parse_urls("\n".join(["https://example.com"] * 11), 10, "图")


class CredentialTests(unittest.TestCase):
    def test_environment_key_and_alias(self):
        for name in ("RUNNINGHUB_API_KEY", "RH_API_KEY"):
            with patch.dict("os.environ", {name: KEY}, clear=True), patch.dict("sys.modules", {"server": None}):
                settings = Settings.resolve()
                self.assertEqual(settings.api_key, KEY)
                self.assertNotIn(KEY, repr(settings))

    def test_hosted_shared_key_has_priority(self):
        server = types.SimpleNamespace(PromptServer=types.SimpleNamespace(
            instance=types.SimpleNamespace(shared_api_key=KEY)))
        with patch.dict("os.environ", {"RH_API_KEY": "unused"}, clear=True), patch.dict("sys.modules", {"server": server}):
            self.assertEqual(Settings.resolve().api_key, KEY)

    def test_unknown_or_blank_shared_key_falls_back(self):
        for shared in ("unknown", " ", None):
            server = types.SimpleNamespace(PromptServer=types.SimpleNamespace(
                instance=types.SimpleNamespace(shared_api_key=shared)))
            with patch.dict("os.environ", {"RH_API_KEY": KEY}, clear=True), patch.dict("sys.modules", {"server": server}):
                self.assertEqual(Settings.resolve().api_key, KEY)

    def test_missing_key_and_invalid_wait_fail(self):
        with patch.dict("os.environ", {}, clear=True), patch.dict("sys.modules", {"server": None}):
            with self.assertRaises(MagiError):
                Settings.resolve()
        with patch.dict("os.environ", {"RH_API_KEY": KEY}, clear=True), patch.dict("sys.modules", {"server": None}):
            with self.assertRaises(MagiError):
                Settings.resolve(max_wait=0)


class MediaTests(unittest.TestCase):
    def test_image_batch_png_encoding(self):
        images = np.zeros((2, 16, 24, 3), dtype=np.float32)
        images[1] = 1
        result = image_uploads(images, "images", 10)
        self.assertEqual(len(result), 2)
        from PIL import Image
        with Image.open(io.BytesIO(result[1].content)) as image:
            self.assertEqual(image.size, (24, 16))
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_no_silent_batch_truncation(self):
        for images in (np.zeros((2, 16, 16, 3)), np.zeros((0, 16, 16, 3)), np.zeros((16, 16, 3))):
            with self.assertRaises(MagiError):
                image_uploads(images, "first_frame", 1)

    def test_bad_pixels_fail(self):
        for value in (np.nan, np.inf, -0.1, 1.1):
            with self.assertRaises(MagiError):
                image_uploads(np.full((1, 2, 2, 3), value), "image", 1)

    def test_audio_wave_encoding_and_duration(self):
        result = audio_upload({"waveform": np.zeros((1, 2, 16000 * 3)), "sample_rate": 16000})
        with wave.open(io.BytesIO(result.content)) as audio:
            self.assertEqual(audio.getnchannels(), 2)
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.getnframes(), 48000)

    def test_invalid_audio_length_batch_and_nan(self):
        for shape in ((1, 1, 16000), (1, 1, 16000 * 31), (2, 1, 48000), (1, 3, 48000)):
            with self.assertRaises(MagiError):
                audio_upload({"waveform": np.zeros(shape), "sample_rate": 16000})
        with self.assertRaises(MagiError):
            audio_upload({"waveform": np.full((1, 1, 48000), np.nan), "sample_rate": 16000})

    def test_first_and_last_frame_require_correct_inputs(self):
        cases = [("first_frame", urls(), {}),
                 ("first_last_frame", urls(first="https://example.com/1.png"), {}),
                 ("first_frame", urls(first="https://example.com/1.png", last="https://example.com/2.png"), {}),
                 ("first_frame", urls(first="https://example.com/1.png"), {"first_frame": np.zeros((1, 4, 4, 3))})]
        for mode, references, inputs in cases:
            with self.assertRaises(MagiError), prepare_reference(mode, references, **inputs):
                pass

    def test_mixed_reference_count_before_upload(self):
        refs = urls(imageUrls=["https://example.com/1.png"] * 10)
        with self.assertRaises(MagiError), prepare_reference(
            "multimodal_reference", refs, reference_images=np.zeros((1, 4, 4, 3))
        ):
            pass

    def test_empty_multimodal_and_irrelevant_inputs_rejected(self):
        with self.assertRaises(MagiError), prepare_reference("multimodal_reference", urls()):
            pass
        with self.assertRaises(MagiError), prepare_reference(
            "multimodal_reference", urls(first="https://example.com/first.png")
        ):
            pass

    def test_reference_order_is_native_then_urls(self):
        refs = urls(imageUrls=["https://example.com/remote.png"])
        uploader = types.SimpleNamespace(upload=lambda *args: "https://example.com/local.png")
        with prepare_reference("multimodal_reference", refs,
                               reference_images=np.zeros((1, 8, 8, 3))) as uploads:
            result = upload_reference(uploader, "multimodal_reference", refs, uploads)
        self.assertEqual(result["imageUrls"], ["https://example.com/local.png", "https://example.com/remote.png"])

    def test_video_export_and_temporary_cleanup(self):
        class TrimmedVideo:
            def get_duration(self):
                return 4

            def save_to(self, path, **kwargs):
                self.path = Path(path)
                self.options = kwargs
                self.path.write_bytes(MP4)

        video = TrimmedVideo()
        with prepare_reference("multimodal_reference", urls(), reference_video=video) as uploads:
            self.assertTrue(video.path.is_file())
            self.assertEqual(video.options, {"format": "mp4", "codec": "h264"})
            self.assertEqual(len(uploads["videoUrls"]), 1)
        self.assertFalse(video.path.exists())


class ClientTests(unittest.TestCase):
    def test_submit_and_poll_selects_video_not_thumbnail(self):
        api, session = client([Response({"taskId": "12345", "status": "RUNNING"}),
                               Response({"status": "RUNNING"}), Response(SUCCESS)])
        task_id = api.submit("sand-ai/magi-2/text-to-video", {"prompt": "cat"})
        url, _ = api.poll(task_id)
        self.assertTrue(url.endswith("result.mp4"))
        self.assertTrue(session.posts[0][0].endswith("/sand-ai/magi-2/text-to-video"))
        self.assertEqual(session.posts[1][1]["json"], {"taskId": "12345"})
        self.assertEqual(session.posts[0][1]["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertFalse(session.posts[0][1]["allow_redirects"])

    def test_ambiguous_submission_never_retries_and_hides_key(self):
        api, session = client([requests.Timeout(f"bad request with {KEY}")])
        with self.assertRaises(MagiError) as caught:
            api.submit("sand-ai/magi-2/text-to-video", {})
        self.assertEqual(len(session.posts), 1)
        self.assertNotIn(KEY, str(caught.exception))
        self.assertIn("没有自动重试", str(caught.exception))

    def test_query_transient_error_recovery(self):
        api, session = client([Response({}, 429), Response(SUCCESS)])
        self.assertTrue(api.poll("12345")[0].endswith(".mp4"))
        self.assertEqual(len(session.posts), 2)
        self.assertTrue(all(url.endswith("/query") for url, _ in session.posts))

    def test_query_three_failures_or_deadline_is_bounded(self):
        api, session = client([requests.Timeout()] * 5)
        with self.assertRaises(MagiError) as caught:
            api.poll("12345")
        self.assertLessEqual(len(session.posts), 3)
        self.assertIn("12345", str(caught.exception))

    def test_running_timeout_preserves_task_id(self):
        api, session = client([Response({"status": "RUNNING"})] * 10)
        with self.assertRaisesRegex(MagiError, "12345.*超时"):
            api.poll("12345")
        self.assertLessEqual(len(session.posts), 3)

    def test_terminal_failures_do_not_retry(self):
        for status in ("FAILED", "CANCEL", "CANCELED", "CANCELLED", "unexpected"):
            api, session = client([Response({"status": status, "errorMessage": f"rejected {KEY}"})])
            with self.assertRaises(MagiError) as caught:
                api.poll("12345")
            self.assertEqual(len(session.posts), 1)
            self.assertNotIn(KEY, str(caught.exception))
            self.assertIn("12345", str(caught.exception))

    def test_unauthorized_not_retried(self):
        api, session = client([Response({"message": "unauthorized"}, 401)])
        with self.assertRaisesRegex(MagiError, "401"):
            api.poll("12345")
        self.assertEqual(len(session.posts), 1)

    def test_upload_contract(self):
        api, session = client([Response({"code": 0, "data": {"download_url": "https://example.com/image.png"}})])
        self.assertEqual(api.upload("a.png", b"data", "image/png"), "https://example.com/image.png")
        self.assertTrue(session.posts[0][0].endswith("/media/upload/binary"))
        self.assertEqual(session.posts[0][1]["files"]["file"], ("a.png", b"data", "image/png"))

    def test_nested_response_and_recursive_redaction(self):
        result = dict(SUCCESS, authorization=KEY, nested={"apiKey": "other", "message": KEY})
        api, _ = client([Response({"code": 0, "data": result})])
        _, response = api.poll("12345")
        self.assertNotIn(KEY, json.dumps(response))
        self.assertEqual(response["nested"]["apiKey"], "[REDACTED]")

    def test_missing_video_not_faked(self):
        api, _ = client([Response({"status": "SUCCESS", "results": [{"outputType": "png", "url": "https://example.com/a.png"}]})])
        with self.assertRaisesRegex(MagiError, "没有视频"):
            api.poll("12345")

    def test_interrupt_stops_without_requests(self):
        def stop():
            raise InterruptedError()
        api, session = client([], interrupt=stop)
        with self.assertRaises(InterruptedError):
            api.poll("12345")
        self.assertEqual(session.posts, [])

    def test_download_never_forwards_api_key(self):
        api, session = client([])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.part"
            api.download("https://cdn.example.com/result.mp4?signature=test", target)
            self.assertEqual(target.read_bytes(), MP4)
        self.assertNotIn("headers", session.gets[0][1])

    def test_download_invalid_or_empty_file_rejected(self):
        for content, mime in ((b"", "video/mp4"), (b"<html>not a video</html>", "text/html"),
                              (b"wrong header " * 10, "application/octet-stream")):
            api, _ = client([], download=Response(content=content, content_type=mime))
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(MagiError):
                api.download("https://example.com/a.mp4", Path(directory) / "a.part")


class NodeExecutionTests(unittest.TestCase):
    def test_full_generation_saves_video_receipt_and_native_output(self):
        api, session = client([Response({"taskId": "12345"}), Response(SUCCESS)])
        with tempfile.TemporaryDirectory() as directory:
            result = _run(api, Path(directory), DummyVideo, "sand-ai/magi-2/text-to-video", {"prompt": "test"}, "")
            video, url, task_id, raw = result["result"]
            self.assertIsInstance(video, DummyVideo)
            self.assertTrue(Path(video.path).is_file())
            self.assertEqual(task_id, "12345")
            self.assertEqual(result["ui"]["images"][0]["type"], "output")
            receipt = json.loads((Path(directory) / "task_12345.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "DOWNLOADED")
            self.assertEqual(receipt["width"], 1920)
            self.assertNotIn(KEY, json.dumps(receipt))
            self.assertNotIn("prompt", receipt)
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_resume_skips_generation_and_media_even_with_empty_prompt(self):
        for node in (Magi2TextToVideoRH, Magi2ReferenceVideoRH):
            api, session = client([Response(SUCCESS)])
            with tempfile.TemporaryDirectory() as directory, patch.object(
                node, "context", return_value=(api, Path(directory), DummyVideo, "12345")
            ):
                inputs = {"prompt": "", "duration": 5, "aspect_ratio": "16:9", "resolution": "1080p",
                          "generate_audio": True, "seed": 0, "resume_task_id": "12345"}
                if node is Magi2ReferenceVideoRH:
                    inputs["mode"] = "first_frame"
                node().generate(**inputs)
            self.assertEqual(len(session.posts), 1)
            self.assertTrue(session.posts[0][0].endswith("/query"))

    def test_frame_and_multimodal_use_distinct_official_endpoints(self):
        for mode in ("first_frame", "first_last_frame", "multimodal_reference"):
            api, session = client([Response({"taskId": "12345"}), Response(SUCCESS)])
            with tempfile.TemporaryDirectory() as directory, patch.object(
                Magi2ReferenceVideoRH, "context", return_value=(api, Path(directory), DummyVideo, "")
            ):
                inputs = {"mode": mode, "prompt": "camera pans", "duration": 4, "aspect_ratio": "9:16",
                          "resolution": "1080p", "generate_audio": False, "seed": 123}
                if mode == "multimodal_reference":
                    inputs["image_urls"] = "https://example.com/a.png"
                    inputs["video_urls"] = "https://example.com/a.mp4"
                    inputs["audio_urls"] = "https://example.com/a.wav"
                else:
                    inputs["first_frame_url"] = "https://example.com/first.png"
                    if mode == "first_last_frame":
                        inputs["last_frame_url"] = "https://example.com/last.png"
                Magi2ReferenceVideoRH().generate(**inputs)
            endpoint, call = session.posts[0]
            expected = "reference-to-video" if mode == "multimodal_reference" else "image-to-video"
            self.assertTrue(endpoint.endswith(expected))
            payload = call["json"]
            self.assertEqual(payload["duration"], 4)
            self.assertEqual(payload["aspectRatio"], "9:16")
            self.assertIs(payload["generateAudio"], False)
            self.assertNotIn("api_key", payload)
            self.assertEqual("imageUrls" in payload, mode == "multimodal_reference")
            self.assertEqual("endImageUrl" in payload, mode == "first_last_frame")

    def test_failed_download_preserves_receipt_and_existing_results(self):
        api, _ = client([Response(SUCCESS)], download=Response(content=b""))
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory) / "previous.mp4"
            previous.write_bytes(MP4)
            with self.assertRaisesRegex(MagiError, "12345"):
                _run(api, Path(directory), DummyVideo, "sand-ai/magi-2/text-to-video", None, "12345")
            self.assertTrue((Path(directory) / "task_12345.json").is_file())
            self.assertEqual(previous.read_bytes(), MP4)
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_task_receipt_exists_after_poll_timeout(self):
        api, _ = client([Response({"taskId": "12345"})] + [Response({"status": "RUNNING"})] * 10)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MagiError):
                _run(api, Path(directory), DummyVideo, "sand-ai/magi-2/text-to-video", {}, "")
            receipt = json.loads((Path(directory) / "task_12345.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "QUERYING")


class WorkflowTests(unittest.TestCase):
    def test_examples_match_registered_node_inputs_and_link_types(self):
        from tools.build_examples import example
        for kind in ("text_to_video", "first_frame", "first_last_frame", "multimodal_reference"):
            workflow, api = example(kind)
            for item in api.values():
                if item["class_type"] in NODE_CLASS_MAPPINGS:
                    schema = NODE_CLASS_MAPPINGS[item["class_type"]].INPUT_TYPES()
                    self.assertTrue(set(schema["required"]).issubset(item["inputs"]))
                    self.assertTrue(set(item["inputs"]).issubset(set(schema["required"]) | set(schema["optional"])))
            indexed = {node["id"]: node for node in workflow["nodes"]}
            for link_id, source, out_slot, destination, in_slot, type_name in workflow["links"]:
                self.assertEqual(indexed[source]["outputs"][out_slot]["type"], type_name)
                self.assertEqual(indexed[destination]["inputs"][in_slot]["type"], type_name)
                self.assertEqual(indexed[destination]["inputs"][in_slot]["link"], link_id)


if __name__ == "__main__":
    unittest.main()
