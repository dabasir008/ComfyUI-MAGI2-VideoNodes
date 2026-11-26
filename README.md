# MAGI-2 for ComfyUI / RunningHub

两个独立 ComfyUI 节点，通过 **RunningHub 官方 OpenAPI v2** 调用 MAGI-2，便于搭建视频工作流。

| 节点 | 支持的任务 | 注册类名 |
| --- | --- | --- |
| MAGI-2 文生视频 | 提示词生成视频 | `Magi2TextToVideoRH` |
| MAGI-2 图片·多模态参考 | 首帧图生、首尾帧过渡、图片/视频/音频参考 | `Magi2ReferenceVideoRH` |

这是 API 节点包，模型运行在服务端；需要具备标准模型调用权限和余额的 RunningHub **企业级共享 API Key**。代码的 MIT 许可不包含模型服务的使用权，接口按 RunningHub 的规则计费。本项目独立开发，并非 RunningHub 或 MAGI 官方出品。

## 功能

- 原生 `IMAGE`、`VIDEO`、`AUDIO` 连线；本地参考素材自动编码并上传。
- 多模态图片可以输入 `IMAGE` 批次；还可通过逐行 URL 或 JSON 数组添加参考素材。
- `VIDEO` 输出可接 `SaveVideo`、`GetVideoComponents` 等原生视频节点，保留生成视频自带的音轨。
- 自动下载视频至 `ComfyUI/output/magi2/`，返回视频预览、原始视频 URL、任务 ID 和结果 JSON。
- 在查询前保存任务回执；超时、重启或下载失败后，可按任务 ID 继续查询，避免重新生成。
- 密钥从服务端读取，不提供会被保存到工作流里的密钥输入框。

## 安装

需要 Python 3.10+，以及支持原生 `VIDEO` / `comfy_api.input_impl.VideoFromFile` 的 ComfyUI。

在 ComfyUI 根目录克隆：

```bash
git clone https://github.com/dabasir008/ComfyUI-MAGI2-RunningHub.git custom_nodes/ComfyUI-MAGI2-RunningHub
```

1. 将本仓库放入 `ComfyUI/custom_nodes/ComfyUI-MAGI2-RunningHub/`。根目录应直接包含 `__init__.py`，避免多嵌套一层文件夹。
2. 在 **ComfyUI 自己的 Python 环境**中执行：

   ```bash
   python -m pip install -r custom_nodes/ComfyUI-MAGI2-RunningHub/requirements.txt
   ```

3. 配置凭据后重启 ComfyUI；搜索 `MAGI-2`，或进入 `RunningHub/MAGI-2` 分类。

Windows 便携版请从其根目录使用：

```powershell
.\python_embeded\python.exe -m pip install -r .\ComfyUI\custom_nodes\ComfyUI-MAGI2-RunningHub\requirements.txt
```

### 凭据

按以下顺序读取，均在服务端完成：

1. RunningHub 托管运行环境的 `PromptServer.instance.shared_api_key`。这是官方 `ComfyUI_RH_OpenAPI` 使用的同一凭据来源；是否为自定义插件开放，需由平台部署环境确认。
2. 环境变量 `RUNNINGHUB_API_KEY`。
3. 环境变量 `RH_API_KEY`。

本地在启动 ComfyUI 的终端里设置变量，例如 PowerShell：

```powershell
$env:RUNNINGHUB_API_KEY = '<你的RunningHub企业级共享API Key>'
# 然后在同一个终端启动 ComfyUI
```

不要将真实密钥放入工作流、示例、公开仓库或提交说明。本插件不读取 `.env` 文件，也不要求安装其他 RunningHub 插件。

## 使用

将 `examples/` 中的 **`.workflow.json`** 拖入 ComfyUI。**`.api.json`** 是对应的后端 API 格式，供程序调用使用。

| 工作流 | 用途 | 运行前需要处理 |
| --- | --- | --- |
| `magi2_text_to_video.workflow.json` | 文生视频 | 修改提示词 |
| `magi2_first_frame.workflow.json` | 首帧图生视频 | 在 LoadImage 上传首帧 |
| `magi2_first_last_frame.workflow.json` | 首尾帧过渡 | 上传首帧和尾帧 |
| `magi2_multimodal_reference.workflow.json` | 多模态参考，示例默认以图片参考起步 | 上传参考图片；按需连接视频/音频或填写 URL |

### 文生视频

设置 `prompt`、时长、比例、音效和随机种子，直接运行即可。节点本身会保存并预览视频，不必额外接保存器。要继续编辑，可将 `video` 输出接到原生视频节点。

### 图片与多模态参考节点

`mode` 必须与输入相匹配：

| mode | 输入 | 真实调用接口 |
| --- | --- | --- |
| `first_frame` | `first_frame` 或 `first_frame_url`，二选一 | `sand-ai/magi-2/image-to-video` |
| `first_last_frame` | 首帧，加上 `last_frame` 或 `last_frame_url` | `sand-ai/magi-2/image-to-video`，包含 `endImageUrl` |
| `multimodal_reference` | `reference_images` / `reference_video` / `reference_audio`，或对应 URL 字段；至少一类 | `sand-ai/magi-2/reference-to-video` |

首尾帧模式会传递专门的首帧和尾帧参数。多参考图片的顺序本身不等同于首尾帧约束。

- `LoadImage.IMAGE` → `first_frame` / `last_frame` / `reference_images`。
- `LoadVideo.VIDEO` → `reference_video`。视频输入支持上游裁剪结果；插件导出处理后的视频再上传。
- `LoadAudio.AUDIO` → `reference_audio`。
- 多参考图可先用图片批次节点合并，再接入 `reference_images`。
- `image_urls`、`video_urls`、`audio_urls`：每行一个 HTTP(S) URL，或一个 JSON 字符串数组。
- 同一类别中，连线素材排在 URL 素材之前。数量上限按两者合计检查。
- URL 素材必须能被 RunningHub 服务端直接访问；本地磁盘路径和 `file://` 地址不适用。

多条参考视频和音频可通过 URL 列表提供。本地连线入口各支持一个原生 VIDEO 和 AUDIO；图片入口支持批次。

### 参数与限制

以下参数来自 RunningHub 文档，核对日期为 **2026-11-26**。服务端限制更新时，以官方文档为准。

| 参数 | 支持范围 |
| --- | --- |
| `duration` | 4–30 秒，整数，默认 5 秒 |
| `resolution` | 仅 `1080p` |
| `aspect_ratio` | `21:9`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16` |
| `prompt` | 最多 15000 字；文生和多模态模式必填，图生模式可留空 |
| `generate_audio` | 布尔值，默认开启 |
| `seed` | 0–2147483647；工作流里默认固定，按需选择随机或递增 |
| 参考图片 | 最多 10 张，每张 ≤30 MB，JPG/JPEG/PNG/WEBP；原生 IMAGE 上传为 PNG |
| 参考视频 | 最多 5 段，每段 2–30 秒、≤200 MB，单类总时长 ≤30 秒；MP4/MOV |
| 参考音频 | 最多 5 段，每段 2–30 秒、≤15 MB，单类总时长 ≤30 秒；MP3/WAV |

本地连线素材的时长、编码后大小和合计数量会先校验。URL 引用素材的真实大小、时长以及所有素材的合计时长，由服务端最终校验。插件不暗中裁剪、缩短或截取第一张图片。

`1080p` 是接口使用的分辨率档位，最终像素宽高随画幅和服务端输出而定；成功后会在节点和任务回执中显示实际宽高。插件不会伪造 4K 或 60 秒选项。

### 超时与继续取回结果

默认每 5 秒查询，最多等待 1800 秒；可以调整 `poll_interval` 和 `max_wait_seconds`。

1. 在错误信息、后台日志或 `output/magi2/task_<任务ID>.json` 中找到任务 ID。
2. 将该 ID 填到节点的 `resume_task_id`。
3. 再次运行：只查询和下载已有任务，跳过上传和新建生成。
4. 要生成新视频，请清空 `resume_task_id`，再修改提示词或种子等输入。

**生成提交不自动重试。** 如果提交时网络中断且没有拿到任务 ID，请先检查 RunningHub API 调用记录。任务可能已创建，直接重新生成可能再次计费。查询中的临时网络错误会有限重试；中断本地等待不会取消服务端任务。

官方说明结果 URL 通常只保留 24 小时。插件会立即下载至输出目录；请保留需要的视频文件。文件名含任务 ID 和随机后缀，不会覆盖其他视频。

## 提交 RunningHub

仓库根目录包含 `__init__.py`、`requirements.txt`、MIT 许可、节点映射和示例工作流，可作为自定义节点仓库提交。

审核用途说明、接口清单和部署要求见 [RUNNINGHUB_SUBMISSION.md](RUNNINGHUB_SUBMISSION.md)。平台审核、安装和共享密钥注入都由 RunningHub 决定；仓库上传成功并不代表平台已审核通过。

## 开发与验证

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/build_examples.py --check
```

测试覆盖节点注册、参数限制、三种参考模式分流、图片/音频编码、视频导出调用、API 请求协议、续查、重试边界、结果下载、密钥脱敏和任务文件保留。API 测试使用离线响应，不产生模型费用。GitHub Actions 在 Python 3.10 / 3.12 下运行同一套检查。

## 官方资料

- [MAGI-2 文生视频](https://www.runninghub.cn/call-api/api-detail/2134110200000200038)
- [MAGI-2 图生视频及首尾帧](https://www.runninghub.cn/call-api/api-detail/2134110200000200039)
- [MAGI-2 多模态参考生视频](https://www.runninghub.cn/call-api/api-detail/2134110200000200040)
- [RunningHub 官方 ComfyUI OpenAPI 插件及共享凭据机制](https://github.com/HM-RunningHub/ComfyUI_RH_OpenAPI)

## English

Two independent ComfyUI nodes for MAGI-2 through RunningHub OpenAPI v2:

- **Text to Video**: 1080p, 4–30 seconds, six aspect ratios, optional generated audio.
- **Image / Multimodal Reference Video**: first frame, first + last frame, or image/video/audio references. Native IMAGE, VIDEO and AUDIO inputs are uploaded automatically; additional references can be supplied as URLs.

Install this folder under `ComfyUI/custom_nodes`, install `requirements.txt` using ComfyUI's Python, set `RUNNINGHUB_API_KEY` or `RH_API_KEY`, and restart. Hosted RunningHub deployments can supply `PromptServer.instance.shared_api_key`. The service requires an enterprise shared key with model access and sufficient balance.

Import the `.workflow.json` examples and replace placeholder images. Both nodes save an MP4 and return a native VIDEO, URL, task ID and response JSON. Use `resume_task_id` to retrieve an existing task without generating again. Generation submissions are never automatically retried. The included tests use offline API responses; a hosted generation smoke test is still required after platform installation.

Independent project. MIT covers this node code only; model/API service terms and fees are separate.
