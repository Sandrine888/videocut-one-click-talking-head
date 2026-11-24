# D 模块（基础动效）可复用开源仓库清单

> 调研日期：2026-11-24 ｜ 目标：尽量用现成开源产品实现「字幕淡入、重点词高亮、章节角标、无动效/轻动效对照、逐帧自检」
> 宿主项目 videocut 为 **MIT 协议**，引入代码时注意许可证兼容（MIT/Apache/BSD/ISC 可直接用；GPL 只能看思路，不能抄代码）。

## 一、直接采用（核心方案，几乎不用自己造轮子）

### 1. pysubs2 —— ASS/SRT 字幕编辑库（首选，必装）
- 地址：https://github.com/tkarabela/pysubs2
- 文档：https://pysubs2.readthedocs.io
- 协议：MIT ｜ 454 star ｜ 纯 Python、零额外依赖，`pip install pysubs2`
- 用途：把 C 的 SubtitleSegment 列表转成 ASS 事件；淡入用 `\fad(80,0)` 标签、重点词高亮用 `\c&Hxxxxxx&` 标签、角标用 `\pos()` 定位事件，全部是它原生支持的 ASS 语法，不需要自己写解析器。
- 已验证：README 确认支持 ASS/SSA/SRT/VTT/Whisper 字幕互转，内部统一 ASS 表示。

### 2. libass —— ASS 渲染引擎（ffmpeg 已内置，无需新装）
- 地址：https://github.com/libass/libass
- 协议：ISC
- 用途：真正「把动效画到视频上」的引擎。现有 `output/local.py` 的 ffmpeg `subtitles` 滤镜底层就是 libass，只是目前喂的是 SRT（不支持特效标签）。改喂 ASS 文件（`-vf ass=xxx.ass` 或 `subtitles=xxx.ass`）即可激活 `\fad`/`\c`/`\t`/`\pos` 全部动效，**单次烧录、不改时长、不换编码链路**。
- 结论：淡入和高亮两个功能 = pysubs2 生成标签 + libass 渲染，零自研渲染代码。

### 3. FFmpeg 内置 drawtext / overlay（章节角标的现成方案）
- 地址：https://github.com/FFmpeg/FFmpeg
- 文档（滤镜）：https://ffmpeg.org/ffmpeg-filters.html#drawtext
- 用途：角标也可以完全不走 ASS，用 `drawtext=...:enable='between(t,起,止)'` 按时间段显示章节文字，`box=1:boxcolor=black@0.5` 自带底板；或 `overlay=...:enable='between(t,..)'` 贴 PNG 角标。这是 ffmpeg 原生能力，无第三方依赖。
- 备选建议：角标优先做成 ASS 独立事件（\pos 定位到安全区角落），与字幕同一次烧录，避免二次编码；drawtext 方案留作对照。
- 注意：Windows 下 drawtext 中文需指定 fontfile（如 C:/Windows/Fonts/msyh.ttc），且 ffmpeg 构建需含 libfreetype/libass。

## 二、可抄现成实现（MIT，代码可直接借用改造）

### 4. vorojar/bilingual-subtitle-skill —— 卡拉OK逐词高亮（与「重点词高亮」最接近的现成代码）
- 地址：https://github.com/vorojar/bilingual-subtitle-skill
- 关键文件：`scripts/process.py`（单文件脚本）
- 协议：MIT（README 标注）
- 用途：已实现「Whisper 词级时间戳 → ASS 卡拉OK高亮 → ffmpeg 烧录」全链路，含 `--highlight-color "&H00FFFF&"`、fontsize、margin 参数。我们的需求比它简单（每条只高亮一个词、静态变色即可），可参考其 ASS 高亮标签写法和烧录命令，砍掉翻译/whisper 部分。
- 已验证：仓库存在，README 确认 karaoke 模式输出 `*_karaoke.ass` + `*_karaoke.mp4`。

### 5. harry0703/MoneyPrinterTurbo —— ASS 样式生成参考（11万+ star）
- 地址：https://github.com/harry0703/MoneyPrinterTurbo
- 关键文件：`app/services/subtitle.py`（字幕样式/ASS 生成）、`app/services/video.py`（合成）
- 协议：MIT
- 用途：参考它「字体、颜色、位置、描边、背景全可配置」的 ASS 样式生成代码结构，正好对应我们「读 A 的 template_defaults.json 生成样式」的做法。只借 subtitle.py 的思路/片段，不引入整个项目（它依赖 moviepy+ImageMagick，太重）。

## 三、仅参考思路（GPL，禁止抄代码进 MIT 项目）

### 6. WEIFENG2333/VideoCaptioner（卡卡字幕助手，1.6万 star）
- 地址：https://github.com/WEIFENG2333/VideoCaptioner
- 协议：**GPL-3.0**（以仓库 LICENSE 为准，英文首页写 MIT 是错的）
- 用途：整条「识别→断句→优化→烧录」管线的产品级参考，烧录合成部分可看架构思路。videocut 是 MIT，**不能复制其代码**。

### 7. RayVentura/ShortGPT
- 地址：https://github.com/RayVentura/ShortGPT
- 用途：moviepy + whisper 字幕路线的参考。**不推荐采用**：moviepy TextClip 逐帧渲染慢、依赖 ImageMagick、且重编码会碰「不改原片时长/无损」红线。仅作反面参照。

## 四、功能 → 现成方案映射表

| D 的需求 | 现成方案 | 自研量 |
|---|---|---|
| 字幕淡入 80–150ms | pysubs2 写 `\fad(N,0)` + libass 渲染 | 几行标签拼接 |
| 每条最多 1 个重点词高亮 | pysubs2 写 `\c` 变色（参考 bilingual-subtitle-skill） | 选词规则（模块内自定） |
| 章节角标 | ASS `\pos` 独立事件（首选）或 ffmpeg drawtext enable | 时间段→事件的转换 |
| 无动效/轻动效对照样片 | 同一 segments 出两份 ASS（有/无标签），各烧一次 | 一个开关 |
| 逐帧自检（挡脸/贴边/超两行=0） | ffmpeg 抽帧（`select`/`-vf fps`）+ 安全区几何判断 | 检查脚本（无现成对口产品） |
| 读 A 的模板配置 | json 标准库 + 参考 MoneyPrinterTurbo subtitle.py 结构 | 字段映射 |

## 五、结论与待办

- **核心结论：不需要引入任何重型新产品。** 淡入+高亮 = pysubs2（MIT，纯 Python）+ ffmpeg 自带的 libass；角标 = ASS 事件或 drawtext；唯一需要自己写的是「选哪个词高亮」的规则和逐帧自检脚本。
- 新增依赖仅 1 个：`pysubs2`（可选再加 `ffmpeg-python` https://github.com/kkroening/ffmpeg-python ，Apache-2.0，但现有代码用 subprocess 已够，非必需）。
- 开发前待办：① 确认本机 ffmpeg 构建含 libass/libfreetype（`ffmpeg -filters | findstr ass`）；② 找组员要 PRD 原文与 A 的 template_defaults.json 字段约定；③ 准备一段测试口播原片。
- 本清单仅为调研存档，尚未写任何代码、未安装任何依赖。