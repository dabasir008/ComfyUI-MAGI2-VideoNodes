"""Optional integration check: real HTTP multipart uploads and a real MP4.

The local server is a protocol fixture, not a MAGI model. No paid API is called.
Install PyAV (`pip install av`) to enable this check outside ComfyUI.
"""

import importlib.util
import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import numpy as np

from magi2.client import RunningHubClient, Settings
from magi2.nodes import Magi2ReferenceVideoRH


@unittest.skipUnless(importlib.util.find_spec("av"), "optional PyAV is not installed")
class HttpMediaTests(unittest.TestCase):
    def test_real_http_uploads_mp4_download_and_resume(self):
        import av

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original.mp4"
            with av.open(str(original), "w") as output:
                stream = output.add_stream("libx264", rate=12)
                stream.width, stream.height, stream.pix_fmt = 320, 180, "yuv420p"
                for index in range(24):
                    frame = np.zeros((180, 320, 3), dtype=np.uint8)
                    frame[:, :, 0] = index * 10
                    for packet in stream.encode(av.VideoFrame.from_ndarray(frame, format="rgb24")):
                        output.mux(packet)
                for packet in stream.encode():
                    output.mux(packet)
            video_bytes = original.read_bytes()
            events = []
            query_count = [0]

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def respond(self, payload, mime="application/json"):
                    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def do_POST(self):
                    body = self.rfile.read(int(self.headers["Content-Length"]))
                    events.append((self.path, dict(self.headers), body))
                    if self.path.endswith("/media/upload/binary"):
                        self.respond({"code": 0, "data": {"download_url": base + "/reference"}})
                    elif self.path.endswith("/reference-to-video"):
                        self.respond({"taskId": "88001", "status": "RUNNING"})
                    elif self.path.endswith("/query"):
                        query_count[0] += 1
                        if query_count[0] == 1:
                            self.respond({"taskId": "88001", "status": "RUNNING"})
                        else:
                            self.respond({"taskId": "88001", "status": "SUCCESS", "results": [
                                {"outputType": "mp4", "url": base + "/result.mp4"}
                            ]})
                    else:
                        self.send_error(404)

                def do_GET(self):
                    events.append((self.path, dict(self.headers), b""))
                    self.respond(video_bytes, "video/mp4")

            class AvVideo:
                def __init__(self, path):
                    self.path = path

                def get_duration(self):
                    with av.open(self.path) as container:
                        return container.duration / av.time_base

                def get_dimensions(self):
                    with av.open(self.path) as container:
                        stream = container.streams.video[0]
                        return stream.width, stream.height

                def save_to(self, path, **_):
                    shutil.copyfile(self.path, path)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            base = f"http://127.0.0.1:{server.server_port}"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            output_dir = root / "magi2"
            output_dir.mkdir()

            def context(max_wait, interval, resume):
                api = RunningHubClient(Settings("dummy-test-key", timeout=3, poll_interval=0.01, max_wait=5))
                return api, output_dir, AvVideo, resume

            try:
                with patch("magi2.client.BASE_URL", base + "/openapi/v2"), patch.object(
                    Magi2ReferenceVideoRH, "context", side_effect=context
                ):
                    inputs = dict(mode="multimodal_reference", prompt="camera moves", duration=4,
                                  aspect_ratio="16:9", resolution="1080p", generate_audio=True, seed=1,
                                  reference_images=np.zeros((1, 16, 16, 3), dtype=np.float32),
                                  reference_video=AvVideo(str(original)),
                                  reference_audio={"waveform": np.zeros((1, 1, 32000)), "sample_rate": 16000})
                    result = Magi2ReferenceVideoRH().generate(**inputs)
                    self.assertEqual(result["result"][0].get_dimensions(), (320, 180))
                    self.assertAlmostEqual(result["result"][0].get_duration(), 2, places=2)
                    event_count = len(events)
                    Magi2ReferenceVideoRH().generate(**dict(inputs, resume_task_id="88001"))
                    self.assertTrue(all(path.endswith(("/query", "/result.mp4")) for path, _, _ in events[event_count:]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

            uploads = [event for event in events if event[0].endswith("/media/upload/binary")]
            self.assertEqual(len(uploads), 3)
            self.assertTrue(all("multipart/form-data" in headers["Content-Type"] for _, headers, _ in uploads))
            self.assertTrue(all(b'name="file"' in body for _, _, body in uploads))
            self.assertIn(b"image/png", uploads[0][2])
            self.assertIn(b"video/mp4", uploads[1][2])
            self.assertIn(b"audio/wav", uploads[2][2])
            generation = [body for path, _, body in events if path.endswith("/reference-to-video")]
            self.assertEqual(len(generation), 1)
            payload = json.loads(generation[0])
            self.assertEqual([len(payload[name]) for name in ("imageUrls", "videoUrls", "audioUrls")], [1, 1, 1])
            self.assertTrue(all("Authorization" not in headers for path, headers, _ in events if path == "/result.mp4"))
            self.assertEqual(len(list(output_dir.glob("*.mp4"))), 2)
            self.assertEqual(list(output_dir.glob("*.part")), [])
            self.assertNotIn("dummy-test-key", (output_dir / "task_88001.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
