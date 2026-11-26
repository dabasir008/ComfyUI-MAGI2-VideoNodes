# RunningHub 自定义节点提交说明

## 建议填写内容

**GitHub 仓库地址：** https://github.com/dabasir008/ComfyUI-MAGI2-RunningHub

**插件名称：** MAGI-2 for RunningHub

**一句话介绍：** MAGI-2 文生视频与图片/多模态参考视频节点，支持首尾帧、原生声音和 ComfyUI 媒体连线。

**详细介绍：**

> 本插件提供两个 ComfyUI 节点：MAGI-2 文生视频、MAGI-2 图片·多模态参考。通过 RunningHub 官方 OpenAPI v2 接入文生、图生/首尾帧、多模态参考三类 MAGI-2 接口，支持 1080p、4–30 秒及六种画幅。支持 IMAGE/VIDEO/AUDIO 素材自动上传，输出原生 VIDEO、MP4 预览、视频 URL、任务 ID 和结果 JSON。包含任务回执、超时继续查询及四套工作流示例。生成提交不自动重试。密钥从托管环境共享凭据或环境变量读取，不写入工作流。本插件独立开发，模型调用按平台规则收费。

**注册类名：**

```text
Magi2TextToVideoRH
Magi2ReferenceVideoRH
```

**节点分类：** `RunningHub/MAGI-2`

**版本：** `0.1.0`

**许可：** MIT（仅节点代码）

## 部署要求

- Python 3.10+；支持原生 `VIDEO` 和 `comfy_api.input_impl.VideoFromFile`。
- 依赖：`requests`、`numpy`、`Pillow`；无需下载模型权重，无额外 GPU 推理服务。
- 出站接口：`https://www.runninghub.cn/openapi/v2/`，及接口返回的视频下载/CDN 地址。
- 有效的 RunningHub 企业级共享 API Key，具有标准模型调用权限及余额。
- 凭据优先读取 `PromptServer.instance.shared_api_key`，与 RunningHub 官方 OpenAPI 插件的托管凭据来源一致。若自定义节点运行环境未注入该属性，需要平台部署方确认如何提供。
- 也可从环境变量 `RUNNINGHUB_API_KEY` / `RH_API_KEY` 读取；不提供密钥工作流输入框。
- API 模型费用和外层 ComfyUI 工作流运行费用须按平台实际计费方式核对，不应假设共享密钥一定能自动完成应用用户归属结算。

## 使用的官方 API

| 用途 | POST 路径 |
| --- | --- |
| 文生视频 | `/openapi/v2/sand-ai/magi-2/text-to-video` |
| 首帧 / 首尾帧图生 | `/openapi/v2/sand-ai/magi-2/image-to-video` |
| 多模态参考 | `/openapi/v2/sand-ai/magi-2/reference-to-video` |
| 素材上传 | `/openapi/v2/media/upload/binary` |
| 任务查询 | `/openapi/v2/query` |

认证为服务端 `Authorization: Bearer ...`；下载成片时不向 CDN 转发该认证头。

## 安装后的验收

1. 搜索 MAGI-2，确认两个类名均已注册且无依赖导入错误。
2. 导入四个 `.workflow.json` 示例，替换示例图片，确认连线及控件正确。
3. 用 4 秒文生任务验证共享凭据、计费、声音和实际 MP4 输出。
4. 用首帧、首尾帧、多模态参考分别验证真实接口；多模态再连接一次 VIDEO 和 AUDIO 验证上传。
5. 从任务历史下载 MP4，核对时长、实际像素尺寸和音轨。
6. 将已有任务 ID 填入 `resume_task_id`，确认只调用 `/query`，没有重复生成任务。
7. 核对中断和失败后的任务回执、已有成片保留，以及应用用户的费用归属。

这些是安装后需要执行的验收项，不代表当前已经完成。离线测试通过不能替代平台真实生成验证。
