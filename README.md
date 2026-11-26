# 基于 VideoCut 的二次开发，一键剪辑口播视频

> 目标：导入一段口播原片 → 一键生成 → 预览 → 下载，产出可直接发布的成片（规范字幕 + 基础动效 + 可选轻剪）。

本仓库在 VideoCut 现有代码上做二次开发，按《一键口播字幕与动效需求报告》整改，不做模型选型评测。当前四个整改方向：

1. **一键流程**：把 `cut` 的三次人工确认收敛为一次调用，串起导入 → 转录 → 轻剪 → 字幕 → 动效 → 导出。
2. **字幕可读**：替掉「满 15 字硬切」，按意思断句、恢复标点、术语专名不跨条，剪辑后时间轴对齐。
3. **基础动效**：字幕淡入、重点词强调、章节角标、横竖屏安全区，做成默认模板而非每次靠模型发挥。
4. **交付闭环**：预览、下载 MP4 / SRT、每次跑完自动核验。

## B 主流程当前可试用

Windows 下准备好项目依赖、FFmpeg 和模型后，双击根目录的 **打开口播工具.bat**。网页接受 MP4 / MOV，可预览成片、保存 MP4 和 SRT。

- **快剪**是默认模式。本地识别语音、添加字幕，保留全部发言。可以选择删除长停顿。识别直接读取本机 FunASR 模型。新电脑可将准备好的完整 `speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` 模型目录复制为 `models/paraformer-zh/`，已有的默认模型缓存也可使用。
- **进阶版**使用同一套本地识别和导出流程。首次进入时，选择服务商、填写模型与自己的 API Key，兼容服务另填地址，再点“测试并保存”。分析只发送片段编号和转写文字。默认生成重说、重复和冗余的删减建议，显示原话、原片时间和理由。勾选后点击“应用所选建议并导出”，也可在生成前开启“自动应用精简”。服务失败时点击“用快剪继续”，可复用已有转写。

网页使用 `python -m videocut.cli serve` 启动。命令行 `python -m videocut.cli generate 原片.mp4` 默认快剪。进阶模式使用 `--mode advanced`，需要先在本机网页配置，选加 `--auto-apply` 执行自动精简。

**当前是 B 的联调版本：** 正式 A/C/D/E 模块尚未接入，现有静态字幕可导出，动效和完整质量验收仍待接入。未测指标会明确标记。环境准备、产物位置及团队接入约定见 [B 主流程接口与运行方式](docs/B主流程接口与运行方式.md)。

## 环境与约定

- Python 3.11 + FFmpeg（含 libass / libx264）；转写默认用本地 FunASR，离线、免费、自带逐字时间戳。
- 旧 `cut` 命令保留原有交互，`--skip-ai` 仅适用于该命令。
- 旧命令的 API 与模型在 `llm_profiles.json` 中按方案名配置，用 `vc.bat -p 方案名` 切换；Key 用 `vc.bat --set-key 方案名` 加密保存，不要写进仓库。
- 构建环境 `venv/`、`venv_build/`、`installer/`、`dist/`、`build/`，以及 `output/`、`results/`、演示视频和字幕产物均不入库。

---

## 上游 README（VideoCut 原版）

> 智能口播视频剪辑工具 - 自动识别口误，一键生成精剪视频

## 功能特点

- **智能转录** - 自动将视频语音转为文字，带精确时间戳
- **AI 文案重组** - 分析转录内容，生成精简方案（可选）
- **口误识别** - 自动识别口误、语气词、长静音
- **一键剪辑** - 确认后自动剪辑，输出成品视频
- **多种输出** - 支持本地烧录字幕或推送剪映草稿箱

## 安装

```bash
pip install videocut
```

### 系统要求

- Python 3.10+
- FFmpeg（视频处理）
- 约 2GB 磁盘空间（语音识别模型）

### 安装 FFmpeg

```bash
# macOS
brew install ffmpeg

# Windows (使用 Chocolatey)
choco install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

## 快速开始

### 1. 首次配置

```bash
videocut init
```

按提示完成：
1. 输入 License Key
2. 配置 AI 服务（OpenAI/Claude/兼容服务）
3. 选择默认输出方式（本地/剪映）

### 2. 剪辑视频

```bash
videocut cut 口播视频.mp4
```

工具会自动：
1. 转录视频内容（首次运行会下载模型）
2. AI 分析生成重组方案（可选）
3. 识别口误、语气词、静音
4. 显示删除任务，等待确认
5. 执行剪辑，输出成品

### 3. 查看状态

```bash
videocut status
```

显示 License 有效期和当前配置。

## 命令参考

### videocut cut

剪辑视频的主命令。

```bash
videocut cut <video> [OPTIONS]

Options:
  -o, --output [local|jianying]  输出方式
                                 local: 本地输出（可烧录字幕）
                                 jianying: 推送到剪映草稿箱
  --skip-ai                      跳过 AI 文案重组
  --help                         显示帮助
```

示例：

```bash
# 基础用法
videocut cut video.mp4

# 跳过 AI 分析（更快）
videocut cut video.mp4 --skip-ai

# 输出到剪映
videocut cut video.mp4 -o jianying
```

### videocut init

首次配置向导。

### videocut status

查看 License 和配置状态。

### videocut config

修改现有配置。

## 识别能力

| 类型 | 说明 | 示例 |
|------|------|------|
| 重复型口误 | 连续重复的短语 | "这是这是一个" |
| 卡顿型口误 | 连续重复的字 | "我是是测试" |
| 语气词 | 无意义的填充词 | "嗯"、"啊"、"呃" |
| 长静音 | 超过1秒的停顿 | 句间超长停顿 |

## 输出文件

本地输出时，会生成以下文件：

```
原视频.mp4
├── 原视频_cut.mp4      # 剪辑后的视频
├── 原视频_cut.srt      # SRT 字幕文件
└── 原视频_final.mp4    # 烧录字幕后的最终视频
```

## 配置文件

配置存储在 `~/.videocut/config.json`：

```json
{
  "license_key": "VC-XXXX-XXXX-XXXX",
  "output_mode": "local",
  "llm": {
    "provider": "openai",
    "model": "gpt-4o"
  }
}
```

## 常见问题

### Q: 首次运行很慢？

A: 首次运行会下载语音识别模型（约1GB），后续会使用缓存。

### Q: 如何跳过 AI 分析？

A: 使用 `--skip-ai` 参数：`videocut cut video.mp4 --skip-ai`

### Q: 支持哪些视频格式？

A: 支持 FFmpeg 能处理的所有格式，包括 MP4、MOV、AVI、MKV 等。

### Q: 剪映输出失败？

A: 确保剪映已安装并至少打开过一次，让它创建草稿目录。

### Q: API Key 安全吗？

A: API Key 使用设备特定密钥加密存储，不会明文保存。

## 效率数据

- **手动剪辑**: 约 30-60 分钟/视频
- **使用 Videocut**: 约 3-5 分钟/视频
- **时间节省**: 约 90%

## License

MIT License

---

Made with Claude Code
