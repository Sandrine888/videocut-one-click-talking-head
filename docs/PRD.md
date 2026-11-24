# PRD：D 模块 · 基础动效（render/effects.py）

> 版本：v1.0 ｜ 定稿日期：2026-11-24
> 地位：本文件是 D 模块后续所有开发的唯一依据。与《一键口播成片_五人分工说明.docx》冲突时，以分工说明的硬约束为准，其余以本 PRD 为准。
> 宿主项目：videocut（MIT，本地已克隆于 `videocut/`）｜ 负责人：D ｜ 互检人：B（B 看 D 的产出）

---

## 1. 产品目标和使用场景

### 1.1 产品目标

在「一键口播成片」流水线中，D 模块负责让字幕**克制地动起来**：给静态字幕加上淡入、重点词高亮、章节角标三种轻动效，使成片达到「能直接发」的观感，同时**绝不改变原片时长、不挡脸、不贴边、不超两行**。

一句话：观众感觉字幕「舒服、有重点」，但说不出哪里动了特效。

### 1.2 使用场景

- **场景一（主链）**：B 的一键命令跑完转录、轻剪、字幕断句后，调用 D 模块，把 C 产出的字幕片段烧录成带轻动效的成片。
- **场景二（对照演示）**：同一段片子、同一条时间轴，输出「无动效版」和「轻动效版」两个 MP4，供互检和验收时肉眼对比，证明动效带来的观感差异。
- **场景三（自检）**：每次渲染后自动抽帧检查，产出「挡脸／贴边／超两行 = 0」的逐帧记录，作为交付物之一。
- **场景四（独立开发）**：A 的配置、C 的断句尚未就绪时，D 用自造的样例数据（假配置 + 假字幕片段）独立跑通全部功能，不排队等待。

### 1.3 明确不做产品级的事

本模块不做预览界面、不做下载入口（归 E）、不做断句（归 C）、不做静态样式定义（归 A）、不串主流程（归 B）。

---

## 2. 模块的用途

### 2.1 在流水线中的位置

```
C 的字幕片段(segments) ──┐
A 的模板配置(template) ──┼──> 【D: render/effects.py】 ──> 带动效 ASS ──> ffmpeg/libass 烧录 ──> 成片 MP4
章节切换点(chapters) ────┘                                    │
                                                              └──> 无动效 ASS ──> 对照版 MP4
                                                              └──> 逐帧自检报告(JSON/文本)
```

### 2.2 技术路线（已调研确认，不再变更）

| 决策 | 内容 | 依据 |
|---|---|---|
| 字幕载体 | **ASS 格式**（放弃纯 SRT 烧录） | libass 原生支持 `\fad`/`\c`/`\pos` 特效标签；SRT+force_style 做不了逐词特效 |
| ASS 生成 | **pysubs2**（MIT，纯 Python，零依赖） | https://github.com/tkarabela/pysubs2 |
| 渲染引擎 | **ffmpeg 内置 libass**（`-vf ass=` 或 `subtitles=` 喂 .ass） | 现有 `output/local.py` 已走此链路，只换输入格式，单次烧录、`-c:a copy`、不改时长 |
| 高亮实现参考 | vorojar/bilingual-subtitle-skill 的 `scripts/process.py`（MIT，可抄改） | https://github.com/vorojar/bilingual-subtitle-skill |
| 样式配置结构参考 | MoneyPrinterTurbo 的 `app/services/subtitle.py`（MIT，仅借思路） | https://github.com/harry0703/MoneyPrinterTurbo |
| 角标实现 | ASS 独立定位事件（首选）；ffmpeg `drawtext enable='between(t,..)'` 仅作备选对照 | ffmpeg 原生能力，无新依赖 |
| 新增依赖 | 仅 `pysubs2` 一个 | 不引入 moviepy/ImageMagick（重编码、慢、碰无损红线） |

### 2.3 许可证红线

- videocut 为 MIT。**只允许引入 MIT/Apache/BSD/ISC 代码**。
- VideoCaptioner 实际为 GPL-3.0（其首页标 MIT 是错的）：**禁止复制任何代码**，仅可看架构思路。
- 抄用 bilingual-subtitle-skill / MoneyPrinterTurbo 代码片段时保留 MIT 版权声明。

### 2.4 与他人的边界（分工说明原文约束）

- A 管静止的样子（字号、行数、边距、配色、底板），D 管随时间变化的效果（淡入、高亮、角标）。**D 只读 A 的配置，不写 A 的文件**（`subtitle_style.py`、`template_defaults.json` 归 A）。
- D 的动效必须基于 C 的同一条时间轴，不另造时间。
- D 不改 `output/local.py` 的断句函数（归 C）、不改 `cut_cmd.py`/`generate_cmd.py`（归 B）、不写 `preview.py`/`verify.py`（归 E）。

---

## 3. v1 里模块最必需的数据和操作

### 3.1 输入数据（v1 用自造样例，字段约定即内部接口）

**① 字幕片段列表 segments**（与现有 `output/local.py` 的 `SubtitleSegment` 同构）：

```json
[
  {"index": 1, "start": 1.00, "end": 3.20, "text": "大家好，欢迎来到我的频道。"},
  {"index": 2, "start": 3.40, "end": 6.10, "text": "今天聊聊 FunASR 的用法。"}
]
```

- `start`/`end`：秒，浮点；`text`：已断句、已含标点的最终文本（C 负责，D 不改文本内容，只加特效标签）。

**② 模板配置 template**（v1 自造 `template_defaults.sample.json`，字段名与 A 未来对齐；数值直接用 PRD 数字）：

```json
{
  "orientation": "portrait",
  "chars_per_line": {"portrait": [12, 16], "landscape": [16, 22]},
  "max_lines": 2,
  "safe_area": {"left_pct": 8, "right_pct": 8, "bottom_pct": 15},
  "font": {"name": "Microsoft YaHei", "size_portrait": 48, "size_landscape": 36},
  "colors": {"primary": "&H00FFFFFF", "outline": "&H00000000", "highlight": "&H0000FFFF"},
  "effects": {
    "fade_in_ms": 120,
    "highlight_max_per_segment": 1,
    "badge": {"enabled": true, "position": "top_right", "shrink_when_speaking": true}
  }
}
```

- `fade_in_ms` 合法区间 **80–150**，越界时钳制到区间内并在日志提示。

**③ 章节切换点 chapters**（v1 自造样例）：

```json
[{"start": 0.0, "label": "开场"}, {"start": 62.5, "label": "第2节 · 实操"}]
```

**④ 输入视频**：一段口播原片 MP4（开发期自备测试片；竖屏、横屏各一段）。

### 3.2 输出数据

| 输出 | 格式 | 说明 |
|---|---|---|
| 轻动效字幕 | `.ass` | 含 `\fad`、高亮 `\c`、角标事件 |
| 无动效字幕 | `.ass` | 同时间轴、同样式，无任何特效标签 |
| 轻动效成片 | `.mp4` | H.264 + AAC（音频 copy），时长与输入一致 |
| 无动效成片 | `.mp4` | 同上，对照用 |
| 自检报告 | `.json` + 控制台摘要 | 逐帧检查记录：挡脸/贴边/超两行违规数、抽帧总数、每条字幕高亮数统计 |

### 3.3 最必需的操作（v1 函数清单，全部落在 `render/effects.py`）

1. `load_template(path) -> dict`：读配置、校验区间、缺字段用默认值补齐。
2. `build_ass(segments, template, chapters, effects_on: bool) -> SSAFile`：核心。同一份输入，开关决定有无特效标签。
3. `pick_highlight_word(text, glossary) -> str|None`：选词规则（见 4.2），每条最多返回 1 个词。
4. `burn(video, ass_path, out_path) -> bool`：调 ffmpeg 单次烧录，`-c:a copy`，失败时输出 stderr 尾部。
5. `render_pair(video, segments, template, chapters, out_dir) -> dict`：一键出「无动效/轻动效」两版成片 + 两份 ASS。
6. `check_frames(video, ass_path, template, report_path) -> dict`：抽帧 + 几何自检，写报告。
7. `python -m videocut.render.effects --demo`：用内置样例数据独立跑通 1–6（不依赖 A/C/B/E）。

---

## 4. v1 必须完成的功能

### F1 字幕淡入
- 每条字幕出现时以 `\fad(fade_in_ms, 0)` 淡入，时长读配置，落在 80–150ms。
- 不做淡出（分工说明只要求淡入）；消失为硬切，与 SRT 时间轴一致。

### F2 重点词高亮（每条最多 1 个）
- **选词规则（v1 定死，机械可验证）**：按优先级取第一个命中者——① 术语表（glossary，v1 内置样例表，含专业词/公司名/英文缩写）；② 数字（含百分数、年份）；③ 都没有则**不高亮**。
- 高亮 = 该词换 `colors.highlight` 颜色（可加 `\b1`），其余文字保持 A 的静态样式。
- 硬约束：任何一条字幕的高亮词数 ≤ 1，由代码保证（不是靠自觉）。
- 高亮不改变文本内容、不改变字数统计口径。

### F3 章节角标
- 在 chapters 每个切换点起，显示小角标（默认右上角，位于安全区内），内容为 `label`。
- **有人说话时缩成小角标**：角标事件与任一字幕时间段重叠时，字号缩小（默认 60%）并降低不透明度；无人说话时段可正常大小。纯时间轴逻辑，不检测音频。
- 角标不遮挡字幕区（底部 15% 安全区）、不超出左右 8% 边距。
- **不改原片时长**：角标只是叠加事件，不插入任何帧。
- 全屏章节卡：只留 `render_fullscreen_card()` 空函数占位 + docstring 注明「v2 可选」，v1 不实现。

### F4 无动效／轻动效对照
- `render_pair` 对同一输入产出两版成片，**时间轴逐条一致**（两份 ASS 的 Dialogue 起止时间完全相同，仅特效标签有无之差）。
- 两版均保持原画幅、原声（音频 copy）、原时长。

### F5 逐帧自检
- 抽帧策略：每条字幕的 start、start+fade_in_ms、end 附近各抽 1 帧，角标出现/缩小切换点各抽 1 帧，其余按 1fps 兜底。
- 检查三项（几何判断，不引入人脸检测模型）：
  - **贴边**：字幕/角标渲染包围盒是否越出安全区（左右 8%、底部 15%）；
  - **超两行**：ASS 事件文本按配置每行字数折行后行数 ≤ 2；
  - **挡脸**：角标包围盒是否侵入画面中央人脸保守区（v1 定义为画面中央 50% 宽 × 上半 60% 高的矩形；角标在角落即天然通过）。
- 输出报告：每项违规帧数、违规明细（时间戳+原因）、抽帧总数。目标全部为 0。

### F6 独立可跑
- `--demo` 模式用内置样例（假 segments/假配置/假 chapters + 一段测试视频或 ffmpeg 生成的纯色测试片）完整跑通 F1–F5，不依赖其他四人的代码。

---

## 5. v1 刻意不做的功能

| 不做 | 原因/归属 |
|---|---|
| 与 A/C/B/E 的正式接口联调、接口格式文档 | 用户明确：v1 暂不做输入输出接口对齐；字段约定先按 3.1 内部执行 |
| 静态样式定义（字号/行数/边距/底板本身的生成） | 归 A（`subtitle_style.py`） |
| 断句、标点恢复、术语表维护、时间轴重映射 | 归 C（`output/local.py`） |
| 一键主流程、去三次确认、进度条、转录缓存 | 归 B（`cut_cmd.py`/`generate_cmd.py`） |
| 预览界面、下载入口、6 条标准自动打勾脚本 | 归 E（`preview.py`/`verify.py`）；D 只保证自己的报告可被 E 调用 |
| 全屏章节卡 | 只留空接口占位 |
| 淡出、弹跳、缩放、逐字卡拉OK擦除等花哨动效 | 超出「轻动效」定位 |
| 每条高亮多个词、AI 语义选重点词 | v1 用机械规则；AI 选词留 v2 |
| 真实人脸检测模型 | v1 用保守几何区代替，避免重依赖 |
| moviepy / ImageMagick / 逐帧贴图渲染路线 | 重编码、慢、碰无损红线（ShortGPT 路线明确弃用） |
| 复制 VideoCaptioner 等 GPL 代码 | 许可证不兼容（MIT 宿主） |
| 批量处理、多说话人、自动配乐、字幕编辑纠错 | 分工说明「范围之外」原文 |
| 改原片时长、重编码音频 | 分工说明硬约束 |
| 周报/PPT/总结文档 | 分工说明：代码和片子就是交付物（本 PRD 除外，系用户要求） |

---

## 6. 真的能检查的验收标准

每条都给出可执行的检查方式；全部通过才算 v1 完成。检查命令在 `videocut/` 目录下执行。

### AC1 淡入存在且时长合规
- 检查：`grep -c "fad(" 输出.ass` 等于字幕条数；解析每个 `\fad(N,0)` 的 N，断言全部 80 ≤ N ≤ 150。
- 人眼：轻动效版逐条字幕出现为渐变而非闪现（抽 start+40ms 帧应为半透明）。

### AC2 高亮每条 ≤ 1
- 检查：脚本统计每行 Dialogue 中高亮颜色标签出现次数，断言 max ≤ 1；对内置样例跑 `pick_highlight_word` 单元测试：含术语词→命中该词；纯数字句→命中数字；无命中→None。

### AC3 角标正确且不越界
- 检查：ASS 中角标事件数 = chapters 数；每个角标 `\pos` 坐标落在安全区内；与字幕时间重叠的角标事件带缩小/降透明标签。
- 人眼：对照版中话题切换处出现角标，说话时角标变小。

### AC4 两版对照时间轴一致、时长不变
- 检查：脚本逐条 diff 两份 ASS 的 start/end，断言完全相等；`ffprobe` 读输入与两版输出时长，断言差值 < 0.05s；`ffprobe` 确认音频流 codec 与输入一致（copy）、分辨率不变。

### AC5 逐帧自检违规为 0
- 检查：运行 `check_frames`，报告 JSON 中 `face_block=0, edge_touch=0, over_two_lines=0`；报告含抽帧总数 > 0 和每条字幕的覆盖记录。
- 交付物：竖屏、横屏各一份报告。

### AC6 独立 demo 一键跑通
- 检查：全新环境 `pip install pysubs2`（+系统 ffmpeg）后，`python -m videocut.render.effects --demo` 退出码 0，产出两版 MP4、两份 ASS、一份报告，全程无 A/B/C/E 代码参与。

### AC7 依赖与许可证干净
- 检查：`pyproject.toml` 新增依赖仅 pysubs2；`git diff` 确认未改动 A/B/C/E 归属文件；引入的第三方片段保留 MIT 声明；无 GPL 代码。

### AC8 互检通过
- 检查：B 看过「无动效/轻动效」两版样片后说一声 OK（分工说明第四节：B 看 D）。同时 D 完成对 A 产出的一次互检（D 看 A）。

### 交付物清单（对齐分工说明）
1. `render/effects.py` 动效渲染模块 + 默认模板样例配置；
2. 同一段片子的「无动效/轻动效」两版样片（竖屏、横屏各一套）；
3. 逐帧记录：挡脸/贴边/超两行 = 0 的自检报告；
4. 本 PRD 与《D模块_可复用开源仓库清单.md》作为开发依据存档。

---

## 附：开发前置待办（不阻塞 v1 功能开发）
- [ ] 确认本机 ffmpeg 含 libass/libfreetype：`ffmpeg -filters | findstr /i "ass drawtext"`
- [ ] 准备竖屏、横屏测试口播原片各一段（可用 ffmpeg 生成带人声的测试片替代）
- [ ] 向组员索取 PRD 原文与 A 的 `template_defaults.json` 最终字段（到位后仅改字段映射，不动功能）