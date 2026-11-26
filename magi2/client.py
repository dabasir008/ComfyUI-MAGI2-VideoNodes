"""RunningHub's documented v2 API. Generation submissions are never retried."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

import requests

BASE_URL = "https://www.runninghub.cn/openapi/v2"
ENDPOINTS = frozenset({
    "sand-ai/magi-2/text-to-video",
    "sand-ai/magi-2/image-to-video",
    "sand-ai/magi-2/reference-to-video",
})


class MagiError(RuntimeError):
    pass


class TransientError(MagiError):
    pass


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    timeout: float = 60
    poll_interval: float = 5
    max_wait: float = 1800

    @classmethod
    def resolve(cls, max_wait: float = 1800, poll_interval: float = 5):
        # Same hosted credential source used by HM-RunningHub/ComfyUI_RH_OpenAPI.
        # Never print, serialize, expose a widget for, or write this credential.
        shared_key = None
        try:
            from server import PromptServer

            shared_key = getattr(PromptServer.instance, "shared_api_key", None)
        except (ImportError, AttributeError):
            pass
        if not isinstance(shared_key, str) or not shared_key.strip() or shared_key.strip() == "unknown":
            shared_key = None
        key = (shared_key or os.getenv("RUNNINGHUB_API_KEY") or os.getenv("RH_API_KEY") or "").strip()
        if not key:
            raise MagiError(
                "未找到 RunningHub 企业级共享 API Key。托管环境需提供系统 shared_api_key；"
                "本地请设置 RUNNINGHUB_API_KEY 或 RH_API_KEY 后重启 ComfyUI。"
            )
        if not 30 <= max_wait <= 7200 or not 1 <= poll_interval <= 30:
            raise MagiError("等待时间必须为 30–7200 秒，查询间隔必须为 1–30 秒。")
        return cls(key, max_wait=max_wait, poll_interval=poll_interval)


def check_url(value: str) -> str:
    if not isinstance(value, str):
        raise MagiError("素材地址必须是 HTTP(S) URL。")
    value = value.strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise MagiError("素材 URL 格式无效。") from None
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise MagiError("素材地址必须是 HTTP(S) URL，且不能包含用户名或密码。")
    return value


class RunningHubClient:
    def __init__(self, settings: Settings, *, session=None, interrupt: Callable = lambda: None,
                 clock: Callable = time.monotonic, sleep: Callable = time.sleep):
        self.settings = settings
        self.session = session if session is not None else requests.Session()
        self.interrupt = interrupt
        self.clock = clock
        self.sleep = sleep

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def sanitize(self, value):
        if isinstance(value, str):
            return value.replace(self.settings.api_key, "[REDACTED]")
        if isinstance(value, list):
            return [self.sanitize(item) for item in value]
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if str(key).lower() in {
                    "authorization", "api_key", "apikey", "shared_api_key"
                } else self.sanitize(item)
                for key, item in value.items()
            }
        return value

    def _message(self, data):
        return str(self.sanitize(data.get("errorMessage") or data.get("message")
                                 or data.get("msg") or "请求失败"))[:500]

    def _post(self, path: str, *, payload=None, files=None, timeout=None):
        self.interrupt()
        try:
            response = self.session.post(
                f"{BASE_URL}/{path}",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                json=payload, files=files, timeout=timeout or self.settings.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            # Request exceptions can embed headers, query strings, and payloads.
            raise TransientError("网络请求失败。") from None
        try:
            with response:
                try:
                    data = response.json()
                except ValueError:
                    if response.status_code >= 500 or response.status_code == 429:
                        raise TransientError(f"HTTP {response.status_code}") from None
                    raise MagiError(f"HTTP {response.status_code}：服务器未返回有效 JSON。") from None
                if not isinstance(data, dict):
                    raise MagiError("服务器返回的 JSON 不是对象。")
                if response.status_code >= 500 or response.status_code == 429:
                    raise TransientError(f"HTTP {response.status_code}：{self._message(data)}")
                if not 200 <= response.status_code < 300:
                    raise MagiError(f"HTTP {response.status_code}：{self._message(data)}")
                if data.get("code") not in (None, 0, "0"):
                    raise MagiError(f"API {data['code']}：{self._message(data)}")
                return data
        except requests.RequestException:
            raise TransientError("读取服务器响应失败。") from None

    @staticmethod
    def _task(data):
        nested = data.get("data")
        if isinstance(nested, dict) and (nested.get("taskId") or nested.get("status")):
            return nested
        return data

    def upload(self, filename, stream, mime):
        data = self._post("media/upload/binary", files={"file": (filename, stream, mime)})
        url = (data.get("data") or {}).get("download_url")
        if not url:
            raise MagiError("上传结果缺少 data.download_url。")
        return check_url(url)

    def submit(self, endpoint, payload):
        if endpoint not in ENDPOINTS:
            raise MagiError("不支持的 MAGI-2 接口。")
        try:
            data = self._task(self._post(endpoint, payload=payload))
        except MagiError as error:
            raise MagiError(
                f"提交未确认：{error} 本节点没有自动重试。若为网络或服务器错误，"
                "请先检查 RunningHub API 调用记录，避免再次创建收费任务。"
            ) from None
        task_id = data.get("taskId") or data.get("task_id")
        if not task_id:
            raise MagiError("提交响应缺少 taskId。请先检查 API 调用记录，再决定是否重试。")
        if str(data.get("status", "")).upper() in {"FAILED", "CANCEL", "CANCELED", "CANCELLED"}:
            raise MagiError(f"任务 {task_id}：{self._message(data)}")
        return str(task_id)

    def _pause(self, seconds):
        deadline = self.clock() + seconds
        while self.clock() < deadline:
            self.interrupt()
            self.sleep(min(0.25, max(0, deadline - self.clock())))

    def poll(self, task_id):
        deadline = self.clock() + self.settings.max_wait
        failures = 0
        while self.clock() < deadline:
            self.interrupt()
            try:
                data = self._task(self._post(
                    "query", payload={"taskId": task_id},
                    timeout=min(self.settings.timeout, max(0.1, deadline - self.clock())),
                ))
                failures = 0
            except TransientError:
                failures += 1
                if failures >= 3:
                    raise MagiError(f"任务 {task_id}：连续三次查询失败。填入 resume_task_id 可继续查询。") from None
                self._pause(min(self.settings.poll_interval * failures, max(0, deadline - self.clock())))
                continue
            except MagiError as error:
                raise MagiError(f"任务 {task_id}：{error}。可用 resume_task_id 继续查询。") from None
            status = str(data.get("status", "")).upper()
            if status == "SUCCESS":
                results = data.get("results")
                if not isinstance(results, list):
                    raise MagiError(f"任务 {task_id} 成功，但 results 不是列表。")
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    kind = str(item.get("outputType") or "").lower().lstrip(".")
                    url = item.get("url") or item.get("outputUrl")
                    if url and (kind in {"mp4", "mov", "video", "video/mp4", "video/quicktime"}
                                or (not kind and urlsplit(url).path.lower().endswith((".mp4", ".mov")))):
                        return check_url(url), self.sanitize(data)
                raise MagiError(f"任务 {task_id} 成功，但没有视频结果。")
            if status in {"FAILED", "CANCEL", "CANCELED", "CANCELLED"}:
                raise MagiError(f"任务 {task_id} {status}：{self._message(data)}")
            if status not in {"CREATE", "CREATED", "PENDING", "QUEUED", "RUNNING"}:
                raise MagiError(f"任务 {task_id} 返回未知状态 {status!r}。请检查 API 调用记录。")
            self._pause(min(self.settings.poll_interval, max(0, deadline - self.clock())))
        raise MagiError(f"任务 {task_id}：等待超时。填入 resume_task_id 可继续查询，不会重新生成。")

    def download(self, url, destination):
        """Never send the API authorization header to a result/CDN URL."""
        check_url(url)
        try:
            with self.session.get(url, stream=True, timeout=self.settings.timeout) as response:
                response.raise_for_status()
                if "text/" in response.headers.get("Content-Type", "") or "json" in response.headers.get("Content-Type", ""):
                    raise MagiError("视频下载返回了文本或 JSON。")
                total = 0
                with open(destination, "wb") as output:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        self.interrupt()
                        if chunk:
                            total += len(chunk)
                            if total > 2 * 1024 ** 3:
                                raise MagiError("视频超过 2 GiB 下载上限。")
                            output.write(chunk)
                if total < 12:
                    raise MagiError("视频下载为空或文件不完整。")
                with open(destination, "rb") as saved:
                    header = saved.read(32)
                if header[4:8] != b"ftyp":
                    raise MagiError("下载结果不是可识别的 MP4/MOV 文件。")
        except requests.RequestException:
            raise MagiError("视频下载失败。可使用 resume_task_id 重新查询和下载。") from None
