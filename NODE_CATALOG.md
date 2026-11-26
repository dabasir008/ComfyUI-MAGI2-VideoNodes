# MAGI-2 全部节点清单（v0.2.1）

**RunningHub 申请添加时填写仓库地址：**

https://github.com/dabasir008/ComfyUI-MAGI2-VideoNodes

同一仓库包含全部八个节点。节点共用官方三类生成接口；以下列出的是工作流入口及工具，模型仍是 MAGI-2。

| 节点 | 注册类名 | 核心输入 | 官方接口 / 行为 |
| --- | --- | --- | --- |
| 文生视频 | `Magi2TextToVideoRH` | 提示词 | `text-to-video` |
| 图片·多模态参考（通用） | `Magi2ReferenceVideoRH` | 模式、原生媒体或 URL | `image-to-video` / `reference-to-video` |
| 单图图生视频 | `Magi2ImageToVideoRH` | 一个 IMAGE | `image-to-video` |
| 首尾帧视频 | `Magi2FirstLastFrameRH` | 首帧 IMAGE + 尾帧 IMAGE | `image-to-video`，分别传首尾帧 |
| 多图参考视频 | `Magi2MultiImageReferenceRH` | `image_1` … `image_10` | `reference-to-video` |
| 多视频参考 | `Magi2VideoReferenceRH` | `video_1` … `video_5`，可附加 IMAGE/AUDIO | `reference-to-video` |
| 多音频参考 | `Magi2AudioReferenceRH` | `audio_1` … `audio_5`，可附加 IMAGE/VIDEO | `reference-to-video` |
| 任务结果恢复 | `Magi2TaskResultRH` | 已有任务 ID | 只调用 `query` 和下载 |

生成节点支持 1080p、4–30 秒、六种比例和音效开关。所有节点输出 `VIDEO`、视频 URL、任务 ID 和结果 JSON，并保存 MP4。模型能力与最终质量以平台真实生成结果为准。

## Magi2TextToVideoRH

**MAGI-2 文生视频**。文字提示词直接生成视频，适合不需要参考素材的创作。

[源码](magi2/nodes.py) · [工作流](examples/magi2_text_to_video.workflow.json) · [API 格式](examples/magi2_text_to_video.api.json)

## Magi2ReferenceVideoRH

**MAGI-2 图片·多模态参考（通用）**。保留原有三种模式，支持原生媒体与 URL 列表，适合已有工作流和 URL 驱动任务。

[源码](magi2/nodes.py) · [多模态工作流](examples/magi2_multimodal_reference.workflow.json) · [API 格式](examples/magi2_multimodal_reference.api.json)

## Magi2ImageToVideoRH

**MAGI-2 单图图生视频（新增）**。只需连接 `image`，无需配置模式或 URL。单张 IMAGE，可选提示词。多张图片批次会报错，不会只取第一张。

[源码](magi2/nodes.py) · [工作流](examples/magi2_image_to_video.workflow.json) · [API 格式](examples/magi2_image_to_video.api.json)

## Magi2FirstLastFrameRH

**MAGI-2 首尾帧视频（新增）**。`first_frame` 和 `last_frame` 均为必接 IMAGE，提示词可留空。真实传递 `imageUrl` 和 `endImageUrl`。

[源码](magi2/nodes.py) · [工作流](examples/magi2_first_last_frame_dedicated.workflow.json) · [API 格式](examples/magi2_first_last_frame_dedicated.api.json)

## Magi2MultiImageReferenceRH

**MAGI-2 多图参考视频（新增）**。`image_1` 必接，`image_2` … `image_10` 可选。各入口可用不同尺寸图片，也支持 IMAGE 批次；所有批次合计最多十张。按输入编号和批次顺序上传，不强制缩放或合并图片。

这是多图参考生成；要指定首尾帧，请使用首尾帧节点。

[源码](magi2/nodes.py) · [工作流](examples/magi2_multi_image_reference.workflow.json) · [API 格式](examples/magi2_multi_image_reference.api.json)

## Magi2VideoReferenceRH

**MAGI-2 多视频参考（新增）**。`video_1` 必接，其余四个 VIDEO 入口可选；可附加 `reference_images` 和 `reference_audio`。每段视频 2–30 秒，视频合计不超过三十秒，每段不超过 200 MB。会导出上游裁剪后的 VIDEO；每段临时文件单独保存并在上传后清理。

视频作为生成参考，不保证逐帧动作复刻、身份锁定或视频编辑式原样保留。

[源码](magi2/nodes.py) · [工作流](examples/magi2_video_reference.workflow.json) · [API 格式](examples/magi2_video_reference.api.json)

## Magi2AudioReferenceRH

**MAGI-2 多音频参考（新增）**。`audio_1` 必接，其余四个 AUDIO 入口可选；可附加 `reference_images` 和 `reference_video`。每段音频 2–30 秒，音频合计不超过三十秒，每段编码后不超过 15 MB。

音频作为生成参考，不保证原声复制、声纹克隆或精确口型同步。

[源码](magi2/nodes.py) · [工作流](examples/magi2_audio_reference.workflow.json) · [API 格式](examples/magi2_audio_reference.api.json)

## Magi2TaskResultRH

**MAGI-2 任务结果恢复（新增工具）**。仅填写已有 `task_id`，不需要提示词或素材。查询结果并保存视频，不上传素材、不创建新生成任务，也不改写已有回执记录的模型接口。

适合等待超时、工作流中断或下载失败后的取回操作。官方结果 URL 通常仅保留二十四小时，请及时下载。查询下载本身不会重新调用模型生成；平台工作流运行费用仍按平台规则计算。

[源码](magi2/nodes.py) · [工作流](examples/magi2_task_result.workflow.json) · [API 格式](examples/magi2_task_result.api.json)

## 平台提交

直接复制 [RUNNINGHUB_SUBMISSION.md](RUNNINGHUB_SUBMISSION.md) 的仓库地址、注册类名、版本和用途说明。平台审核、共享密钥注入、用户费用归属和真实生成均需在 RunningHub 安装后验证。
