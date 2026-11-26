# 验证记录

核对日期：2026-11-26。版本：0.1.0。

## 已执行

- Python 3.12：`python -m unittest discover -s tests -v`，**41 项通过**。
- `python tools/build_examples.py --check`：8 个示例文件通过一致性检查。
- Python 源文件编译检查通过。
- 节点包根目录导入，确认仅注册两个节点，原生 VIDEO 返回类型及输入参数可解析。
- 三种参考模式的 API 路径及字段通过测试；首尾帧使用 `imageUrl` / `endImageUrl`。
- 真实本地 HTTP 服务联调：requests multipart 上传 PNG、MP4、WAV；提交、轮询、下载及任务续查。
- PyAV 生成并解析真实 H.264 MP4；下载文件的宽高、时长及本地保存通过检查。
- 续查仅查询/下载，同一测试中没有再次提交模型生成；已有文件保留。
- 检查工作流与仓库文件，无实际 API Key、私有素材或本机凭据。

上述 HTTP 服务是本地协议测试服务，生成的视频是测试夹具，**并非 MAGI-2 模型成片**。测试不调用付费接口。

`tests/test_http_media.py` 需要可选的 PyAV；未安装时会跳过。其余 40 项测试只需 `requirements.txt`。GitHub Actions 配置为 Python 3.10 / 3.12；是否已在远端通过，需要以仓库 Actions 运行结果为准。

## 尚需平台安装后验证

- RunningHub 自定义节点审核和安装。
- 平台对自定义节点是否注入 `shared_api_key`、模型权限及实际用户费用归属。
- 四种工作流的付费 MAGI-2 真实成片、内容质量、音轨、输出尺寸及任务历史下载。
- 平台前端中的节点控件、MP4 预览与应用输出采集。

完整验收步骤见 `RUNNINGHUB_SUBMISSION.md`。当前验证不等同于 RunningHub 平台验收通过。
