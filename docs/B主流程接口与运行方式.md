# B 主流程接口与运行方式

## 使用

Windows 双击仓库根目录的“打开口播工具.bat”。选择视频，点击生成，在页面预览并保存 MP4 和 SRT。默认保留全部内容。

当前提供供团队接入的试运行页面，用于验证 B 的任务接口；E 可以替换页面并接入正式的预览、下载和自检。缺少 A、C、D、E 的适配器时，程序沿用已有静态字幕并标记联调版本，不代表完整成片验收通过。

需要 Python 3.11、项目依赖和 FFmpeg / FFprobe；FFmpeg 包含 libass、libx264 和 AAC。默认 FunASR 模型已缓存时直接从本地加载，新入口在模型未准备时提示复制离线模型到 `models/paraformer-zh/`。新机器可创建 .venv 环境，再在该环境执行 python -m pip install -e .。快剪不调用 init、License 校验或外部模型。进阶版通过本机页面保存模型配置后可分析转写内容。已有 cut 保持交互式兼容行为。

源码命令入口（在仓库根目录执行）：

    .\venv_build\Scripts\python.exe -m videocut.cli generate "原片.mp4" --output-dir results
    .\venv_build\Scripts\python.exe -m videocut.cli generate "原片.mp4" --trim-silence
    .\venv_build\Scripts\python.exe -m videocut.cli serve

新环境安装后可用 videocut generate 和 videocut serve。

自动删停顿仅取持续低音量的长停顿，排除识别文字相交区间。内部起始配置为 -45 dB、持续 1.8 秒、两端各保留 0.25 秒，是保守试验起点，不能替代真人样片验证。不会删除语气词、重复话语或调用 AI 建议。

## 进阶版建议与应用

`GET /api/advanced/settings` 返回服务商、模型、地址和配置状态。`POST /api/advanced/settings` 接受 provider、model、key、base_url，测试成功后才替换本机设置。任务参数和状态中不包含 Key。

`POST /api/jobs` 支持 `mode`（默认 `quick`）和 `auto_apply`（默认 false）。`advanced` 默认返回一份保留发言的成片和 `suggestions`。用户确认后用同一 `import_id`、`mode=advanced`、来源 `review_task` 和勾选的 `selected_ids` 创建新成片，复用转写和原建议。各建议的 start、end 按原片秒数记录。`applied_ids` 表明实际执行的建议。

## 文件交付

命令输出位于 results/<task_id>/；网页默认位于 .videocut-work/results/<task_id>/。每次运行使用独立目录。

- final.mp4：烧录字幕的 H.264 / AAC 视频。
- subtitles.srt 与 subtitles.json：同一份最终字幕条目。
- transcript.json、mapped_transcript.json：原始和映射后的识别结果。
- deletions.json：删段区间，默认空列表。
- effective_config.json、input_media.json：有效参数和媒体信息。
- progress.json、result.json：事件和成功结果。
- error.json、error.log：失败原因，失败不产生正常 result.json。
- checks.json：检查状态；E 未接入时为 B 的基础交接记录，人工项目为未测。

缓存位于输出目录的 cache 子目录。缓存键包含文件内容 SHA256 和识别配置 SHA256。配置涵盖后端、模型路径或名称、FunASR 版本、本地权重版本和分段长度。改画面样式不重复识别。旧同名 transcript.json 不直接信任。

## 共用 Python 接口

videocut.pipeline.generate(options, adapters=..., on_event=...) 是网页与命令共用的唯一主链。

GenerateOptions 包括 video、output_dir、trim_silence、template、model_name、segment_length、silence_threshold、silence_padding；trim_silence 默认 False。内部时间统一为秒。

进度事件含 task_id、stage、status、message、elapsed_seconds 和 UTC timestamp。校验是前置步骤；四阶段为识别、字幕、动效、导出。事件 status 为 running、completed、failed。动效阶段准备渲染文件，导出阶段实际编码。

成功结果含产物路径、媒体信息、耗时、缓存命中、删段记录、警告和模块接入状态。completion_level=integration 表示正式适配器未齐；integrated 仅表示适配器已接入，不表示质量通过。失败抛出 GenerationError，可读取 stage、task_dir。

## A C D E 适配器

启动可传 --adapters 团队模块:工厂函数，工厂返回 videocut.pipeline.PipelineAdapters。

| 提供者 | 回调字段与参数 | 输出 |
| --- | --- | --- |
| A | template_loader() | 可保存为 JSON 的模板 dict |
| C | subtitle_builder(transcript, template) | SubtitleSegment 列表，字段 index/start/end/text，单位秒 |
| D | effect_builder(segments, template, task_dir, media) | 已存在的 ASS 或 SRT 路径 |
| E | verifier(result_manifest) | JSON 报告 dict，含六类 checks |

识别沿用 TranscriptResult(video_file, full_text, duration, chars)，逐字项 CharTimestamp(char, start, end)。C 收到的是实际剪辑映射后的结果，不重复映射。

最终字幕规范化一次，保存 JSON、写出 SRT，并把同一份条目传给 D。D 的 ASS 应保留正文和起止时间，只添加样式动效。独立 ASS 的语义与时间一致性仍由 D、E 对照核验，B 不声称未经测量的视觉一致。

E 报告约定：checks 为列表，每项含 category、status、message。六类为字幕准确、断句与标点、同步与时间轴、视觉与动效、输出完整、速度与可靠性。状态为 passed、failed、partial、not_tested。自检运行失败不丢弃成片，另标错误。

## 本机 HTTP 接口

只绑定 127.0.0.1。页面设置 HttpOnly 和 SameSite=Strict 会话 cookie；修改请求检查来源。客户端也可用页面注入的 X-Videocut-Token。服务重启后刷新页面取得新会话。

| 接口 | 输入 | 输出 |
| --- | --- | --- |
| GET / | 无 | 页面和会话 |
| GET /api/health | 会话 | ready、issues、模型提示 |
| POST /api/import | 视频原始字节；URL 编码的 X-Filename；Content-Length 必填 | import_id、name、media |
| POST /api/jobs | JSON 的 import_id、trim_silence | task_id、status、message |
| GET /api/jobs/{task_id} | 任务标识 | 持久化状态、事件、成功结果 |
| GET /files/{task_id}/video | 完成任务 | MP4，支持单区间 Range |
| GET /files/{task_id}/srt | 完成任务 | SRT 下载 |
| GET /files/{task_id}/checks | 完成任务 | 检查记录 |
| GET /files/{task_id}/log | 失败任务 | 详细错误记录 |
| POST /api/shutdown | 会话、当前无运行任务 | 退出工具 |

任务状态为 queued、running、completed、failed。页面刷新继续查同一 task_id。服务重启把旧未完成任务标为中断失败，不实现断点恢复。同一导入正在处理时重复提交返回原任务，不同视频并发提交返回 409。

网页先限定 MP4 / MOV、最大 2 GB。传给本机的副本保存在 imports；副本和结果占用磁盘，首版不自动清理。下载只读取任务清单里的结果，不接受任意文件路径。

## 验证界限

B 自动检查媒体结构、编码、尺寸、预期时长和基本字幕数据；不能替代 CER 金标、语义断句、字幕与说话的人工对齐、嘴部遮挡检查或 30 次性能统计。未完成指标如实标未测。

## 本次验证结果

验证日期：2026年11月24日。

- 自动测试：66 项通过，包含主流程失败、无删段继续导出、缓存失效、任务去重、服务中断状态、本机会话、视频 Range、非 AAC 音轨转换、中文和空格及单引号路径、旋转信息。
- 页面脚本通过语法检查；浏览器人工操作因电脑控制工具访问限制中止，按钮和视觉排版没有计为人工验收通过。
- 使用仓库的 26.631125 秒合成演示片及其口播音轨，真实调用本地 FunASR。它不是一段新真人拍摄原片，不能据此证明所有真实场景可用。
- 默认不剪的本地 HTTP 全链运行：24.062 秒，原片未删段，输出 26.632 秒；MP4 为 H.264 与 AAC，SRT 实际可下载，音视频均可完整解码。
- 同一原片开启删停顿：识别缓存命中，2.313 秒，删除两处检测停顿，输出 22.764 秒。删段和映射结果已落盘。
- 上述为单次观测，不能宣称 P90 或 30 次成功率达标。未做字幕金标、真人误删率、嘴部遮挡或两位评审测试。

运行证据位于 results/b-validation/http_smoke.json；网页两次任务结果分别位于 .videocut-work/results/8cc26f95dc7741c582b193ef1750787c/ 和 .videocut-work/results/e1f17146f85041efb39cc7a3fa728410/。

剩余依赖：A 的正式模板、C 的语义字幕、D 的基础动效、E 的正式页面与自检；提供对应适配器后继续联调。新真人原片和环形互检仍待完成。
