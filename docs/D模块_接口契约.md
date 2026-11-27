# D 模块 · 跨模块接口契约 v1.2

> 目的：D（基础动效）与 A（模板配置）/ B（剪辑）/ C（字幕断句）/ E（合成导出）配对。
> 实现位置：`videocut/render/effects.py`（Python）；CLI：`python -m videocut.render.effects`。
> 所有输入均为 JSON 可序列化对象；D 只读不改 C 的文本、只读 A 的配置。

## 1. 输入约定

**时间单位总则：字幕/章节时间一律「秒」（float，s）；动效时长一律「毫秒」（int，ms）。**

### 1.1 `segments` —— C 的字幕片段列表（必填，非空）

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `index` | int | 否 | ≥1，缺省自动按 1 起补号 | 段落序号 |
| `start` | float | 是 | ≥ 0，单位秒 | 出现时间 |
| `end` | float | 是 | > `start`，单位秒 | 消失时间 |
| `text` | str | 是 | 非空 | C 断句后的最终文本（含标点）；D 不改内容，只加特效标签；`\n` 会被当作空格处理 |

### 1.2 `template` —— A 的模板配置（必填，dict 或 JSON 文件路径）

缺字段自动用 `DEFAULT_TEMPLATE` 补齐；完整字段与默认值见 `effects.DEFAULT_TEMPLATE`
（与 `videocut/render/template_defaults.sample.json` 一致）。关键字段：

| 字段 | 类型 | 单位/取值 | 非法时行为 |
|---|---|---|---|
| `orientation` | str | `portrait` / `landscape` | 抛 `InputError` |
| `chars_per_line` | {orient: [int, int]} | 每行最少/最多字数 | 抛 `InputError` |
| `max_lines` | int | 行数上限（自检用） | — |
| `safe_area.{left,right,bottom}_pct` | number | 百分比 | — |
| `font.size_portrait` / `size_landscape` | int | PlayRes 像素字号 | — |
| `colors.*` | str | ASS 色 `&HAABBGGRR&` | — |
| `effects.fade_in_ms` | int | **毫秒**，合法区间 80–150 | 越界钳制并打警告；非数字抛 `InputError` |
| `effects.badge.enabled` / `.shrink_when_speaking` | bool | — | — |

### 1.3 `chapters` —— 章节切换点（可选，默认 `None`＝不加角标）

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `start` | float | 是 | ≥ 0，单位秒；整个列表须按 `start` 严格递增 |
| `label` | str | 是 | 非空，角标显示文字 |

CLI 未提供 `--chapters` 时 D 用 `auto_chapters(segments)` 自动生成（每节约 ≥12s 口播）。

### 1.4 `video` —— 原片路径（渲染时必填）

str/Path，指向存在的 MP4（或 ffmpeg 可解码文件）。分辨率用于判定横竖屏
（宽 ≥ 高 → landscape），可用 `orientation` 参数覆盖 `"auto"`。

## 2. 输出约定

### 2.1 `render_ass(segments, template=None, chapters=None, out_path=None, effects_on=True) -> str`

只要字幕、不碰视频。**返回 ASS 文件路径（str）**。`out_path` 缺省写
`effects_output/light.ass`（或 `noeffects.ass`）。

### 2.2 `render(video, segments, template=None, chapters=None, out_dir="effects_output", orientation="auto", run_check=True) -> RenderResult`

顶层配对入口，**返回渲染结果对象** `RenderResult`（dataclass，可 `.to_dict()`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `orientation` | str | 实际使用的方向（auto 判定后） |
| `video` | str | 输入原片路径 |
| `ass_light` / `ass_noeffects` | str | 两版 ASS 路径（时间轴逐条一致） |
| `mp4_light` / `mp4_noeffects` | str | 两版成片路径（H.264 + AAC copy，时长不变） |
| `report_path` | str \| None | 自检报告 JSON（`run_check=False` 时 None） |
| `checks` | dict | `{"face_block": int, "edge_touch": int, "over_two_lines": int}` |
| `.ok` | property | bool，checks 全 0 即通过 |

### 2.3 底层函数（保留，供细粒度调用）

`load_template` / `build_ass`（返回 `pysubs2.SSAFile`）/ `burn` /
`render_pair`（返回两版路径 dict）/ `check_frames`（返回报告 dict）。

## 3. 错误处理

所有异常继承 `EffectsError`，消息为中文、含定位信息（下标/路径/stderr 尾部）：

| 异常 | 基类 | 触发条件 | 调用方建议 |
|---|---|---|---|
| `InputError` | ValueError | 字段缺失/类型错/`end<=start`/负时间/空 segments/chapters 非递增/template 非法/SRT·JSON 读取失败 | 把消息转给使用者修正输入，可重试 |
| `MediaError` | RuntimeError | 视频不存在；ffprobe 读不出分辨率 | 检查路径与文件完整性 |
| `RenderError` | RuntimeError | ffmpeg 烧录失败（含 stderr 尾部）；ASS 落盘失败 | 检查 ffmpeg 是否在 PATH、磁盘可写 |

CLI 退出码：`0` 成功；`1` 自检有违规；`2` 上述接口错误；`64` 命令行参数用法错误。

## 4. 调用示例

```python
from videocut.render import effects as fx

# 只要 ASS（给 E 自行烧录）
ass_path = fx.render_ass(segments, template=tpl_dict, chapters=chapters)

# 完整渲染（对照两版 + 自检）
result = fx.render("input.mp4", segments, template=tpl_dict,
                   chapters=chapters, out_dir="out")
if not result.ok:
    print("自检违规:", result.checks)
print(result.to_dict())
```

CLI：

```bash
python -m videocut.render.effects --video x.mp4 --srt x.srt --template tpl.json --out out
python -m videocut.render.effects --video x.mp4 --segments segs.json --chapters chaps.json
```

## 5. 待与其它模块确认的事项

- A：`template` 最终字段名若有出入，只需在 `load_template` 里做一层映射，D 功能不动。
- C：`segments` 若带毫秒整数时间戳，请在 C→D 边界换算成秒 float（D 不做单位猜测）。
- E：若 E 统一负责烧录，用 `render_ass` 拿 ASS 即可，不必调 `render`。
