# 角色 A 字幕样式试验

## 运行

从源码目录执行。需要 FFmpeg 及 FFprobe，FFmpeg 构建应包含 libass 和 libx264。输入为方形像素的 SDR 视频，以及有序、互不重叠的 UTF-8 纯文本 SRT。

```powershell
python -m videocut.output.local "input.mp4" "captions.srt" "styled.mp4" --report "layout.json" --protect-term "纳斯达克交易所" --accent-term "IPO"
python -m unittest tests.test_subtitle_style -v
```

默认读取 `videocut/template_defaults.json`。Windows 使用 Microsoft YaHei，其余系统使用 Noto Sans CJK SC。指定其他已安装字体时用 `--font`，并在目标机器复核字形和边距。成功输出 H.264 MP4。首路 AAC 音轨直接复制，其他音频转 AAC。字幕样式大小和边距由最终显示画幅计算。

这一版使用暖白、细描边和柔阴影。重复传入 `--accent-term` 可指定待强调的术语，按传入顺序选每条字幕中第一个匹配词组；没有匹配时整条显示暖白。强调词也参与换行保护。原 SRT 的文字和时间不变，自检逐条记录实际采用的强调词。

### 思源字体试样

从 Adobe 的官方发行页取得三个简体中文 OTF 文件，放在同一个仓库外目录。正文使用 `SourceHanSansSC-Medium.otf`，重点词使用 `SourceHanSansSC-Bold.otf`，可选片头使用 `SourceHanSerifSC-SemiBold.otf`。

```powershell
python -m videocut.output.local "试验3.mp4" "portrait.srt" "styled-font.mp4" `
  --source-han-dir "..\fonts" --opening-title "视频剪辑" --report "layout.json" `
  --accent-term "视频剪辑" --accent-term "停顿、口误和重复" --accent-term "ASR" `
  --accent-term "LLM" --accent-term "时间戳" --accent-term "转录的准确性" `
  --accent-term "跳切" --protect-term "自动语音识别" --protect-term "大语言模型"
```

`--source-han-dir` 将字体提供给当前渲染进程。省略 `--opening-title` 时只渲染字幕。片头持续 0.25–3.05 秒，独立于 SRT 时间轴。自检记录字体配置和片头文字。

[思源黑体官方发行页](https://github.com/adobe-fonts/source-han-sans/releases) · [思源宋体官方发行页](https://github.com/adobe-fonts/source-han-serif/releases)

## 与 B、C、D、E 对接

| 对接方 | 输入或调用 | 约定 |
| --- | --- | --- |
| B | `videocut.output.local.burn_subtitles(video, srt, output, report_path=...)` | 拿到 C 导出的 SRT 后烧录。当前分支缺少旧 `cut` 调用的 `generate_srt` 和剪映模块，独立命令可直接运行。 |
| C | 提供 SRT 和可选术语保护清单 `protected_terms` | 现有的两行按原排版检查。A 只在单行超限时尝试将一个字幕条显示为两行，不拆成新字幕条或改动 SRT。不可排版时按字幕条 ID 回报。 |
| D | `videocut.subtitle_style.load_style(width, height)` | 返回静态样式、安全区、强调色、淡入 120 ms 和章节角标 1200 ms。动效由 D 的渲染层读取这些值。 |
| E | `check_layout(cue, lines, style)`，或读取烧录报告 | `ok` 表示排版通过，`rendered` 表示成片已写入。逐条结果含 `cue_id`、`start_ms`、`end_ms`、实际显示行和 `issues`。问题含具体错误码、实际值、上限和适用行号。 |

字数按可见基础字符计，标点算一字，组合标记和空白不计字数。排版宽度为估算，样片的安全区以实际像素核验。保护词表中的术语、常见英文 token 与数字单位尽量整组换行。超限会返回诊断并保留已有输出。ASS 渲染边界取最接近的 10 ms，原 SRT 与自检报告保留毫秒。

## 本次验收范围

试验3使用原始 720×1280 竖屏素材，试验1使用原片 00:16.05 起约 17 秒的 1280×720 横屏片段。字幕采用本地识别辅助整理的测试 SRT，供排版和烧录验收。正式识别、断句准确率和动效由团队模块联调时复核。运行样片、字幕和自检 JSON 存放在仓库旁的 `role-a-trial`。

竖屏成片 62.833 秒，23 条字幕，横屏成片 17.300 秒，5 条字幕。新版和原版的分辨率、帧数、时长及解码音频 SHA-256 一致。32 个单独渲染的字幕外框通过安全区像素检查，包含两种画幅的行长上限与两行上限。
