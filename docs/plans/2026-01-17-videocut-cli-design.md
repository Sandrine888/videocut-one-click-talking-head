# Videocut CLI 产品设计文档

> 口播视频智能剪辑工具 - 跨平台 CLI 版本

## 一、产品概览

**核心价值：**
上传视频 → AI 自动识别口误 → 一键剪辑输出

**目标用户：**
短视频创作者、知识博主、培训讲师

**核心流程：**
```
1. videocut init     → 配置 license、LLM、输出方式
2. videocut cut      → 转录 → AI文案 → 口误识别 → 剪辑
3. 输出成品          → 本地视频 或 剪映草稿箱
```

**收费模式：**
- 用户购买 License Key（定价自定，如 ¥99/年）
- 用户自配 LLM API Key（OpenAI/Claude/其他）
- 成本：仅 Supabase 验证服务（几乎免费）

**跨平台支持：**
- macOS：`pip install videocut`
- Windows：`pip install videocut`
- 依赖：Python 3.8+、FFmpeg

---

## 二、安装流程

### 安装命令

```bash
pip install videocut
```

### 首次运行 `videocut init`

```
$ videocut init

欢迎使用 Videocut 口播视频剪辑工具！

第1步：License 验证
请输入 License Key: VC-XXXX-XXXX-XXXX
✓ License 验证成功，有效期至 2027-01-17

第2步：配置 AI 服务（用于文案重组）
选择 LLM 提供商:
  [1] OpenAI
  [2] Anthropic (Claude)
  [3] OpenAI 兼容服务（DeepSeek/Moonshot/硅基流动等）
请选择 (1-3): 3

请输入 API Base URL: https://api.deepseek.com/v1
请输入 API Key: sk-xxxxx
请输入模型名称: deepseek-chat

⏳ 测试 AI 服务连接...
✓ 连接成功，模型响应正常

✓ AI 服务配置成功

第3步：选择默认输出方式
  [1] 剪辑到本地（烧录字幕，直接分享）
  [2] 推送到剪映（在剪映中加字幕）
请选择 (1-2): 1
✓ 默认输出：本地

第4步：检测依赖
✓ FFmpeg 已安装
✓ Python 3.10
⏳ 下载语音识别模型（约2GB，首次需要）...
✓ 模型下载完成

配置完成！运行 `videocut cut video.mp4` 开始剪辑
```

### AI 服务配置项

| 提供商 | 需要配置 |
|--------|----------|
| OpenAI | api_key, model |
| Anthropic | api_key, model |
| OpenAI 兼容 | base_url, api_key, model |

### 测试失败处理

```
⏳ 测试 AI 服务连接...
✗ 连接失败：Invalid API Key

是否重新配置？(Y/n): Y
```

### 配置文件位置

- `~/.videocut/config.json` - 存储配置（不含敏感信息明文）
- `~/.videocut/.credentials` - 加密存储 API Key

---

## 三、核心命令

### 命令列表

| 命令 | 用途 |
|------|------|
| `videocut init` | 首次配置（license、AI、输出方式） |
| `videocut cut <video>` | 剪辑视频（主命令） |
| `videocut config` | 修改配置 |
| `videocut status` | 查看 license 状态 |

### 主命令 `videocut cut`

```bash
$ videocut cut 口播视频.mp4

[1/5] 转录视频...
⏳ 正在识别语音...
✓ 转录完成，共 2006 字

[2/5] AI 文案重组...
⏳ 分析文案，生成方案...

┌─────────────────────────────────────┐
│ 方案A：如何用AI提升工作效率          │
│ 时长预估：2分30秒                    │
│ 删除：重复观点3处、冗余表达5处        │
├─────────────────────────────────────┤
│ 方案B：AI工具实战指南                │
│ 时长预估：3分钟                      │
│ 删除：重复观点1处                    │
└─────────────────────────────────────┘

请选择方案 (A/B/跳过): A

[3/5] 识别口误...
✓ 发现：口误3处、语气词5处、静音2处

[4/5] 确认删除任务...
（显示删除清单，用户确认）

[5/5] 执行剪辑...
✓ 输出：口播视频_cut.mp4

完成！
```

### 可选参数

```bash
videocut cut video.mp4 --output local     # 强制输出到本地
videocut cut video.mp4 --output jianying  # 强制推送剪映
videocut cut video.mp4 --skip-ai          # 跳过AI文案重组
```

---

## 四、License 系统

### Supabase 表结构

```sql
-- licenses 表
CREATE TABLE licenses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  license_key VARCHAR(20) UNIQUE NOT NULL,  -- VC-XXXX-XXXX-XXXX
  email VARCHAR(255),                        -- 购买者邮箱
  status VARCHAR(20) DEFAULT 'active',       -- active/expired/revoked
  max_devices INT DEFAULT 2,                 -- 最多激活设备数
  expires_at TIMESTAMP,                      -- 到期时间
  created_at TIMESTAMP DEFAULT now()
);

-- activations 表（记录激活的设备）
CREATE TABLE activations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  license_id UUID REFERENCES licenses(id),
  device_id VARCHAR(64),                     -- 设备唯一标识
  device_name VARCHAR(100),                  -- 如 "MacBook Pro"
  activated_at TIMESTAMP DEFAULT now()
);
```

### 验证 API（Supabase Edge Function）

```
POST /verify
请求：{ license_key, device_id, device_name }
响应：{ valid: true, expires_at, devices_remaining }
     或 { valid: false, error: "License expired" }
```

### 验证时机

- `videocut init` - 首次激活
- `videocut cut` - 每次运行时验证（缓存24小时，离线可用）

### License Key 格式

```
VC-XXXX-XXXX-XXXX
```

由后台生成，用户购买后邮件发送。

---

## 五、技术架构

### 项目结构

```
videocut/
├── pyproject.toml          # 包配置（pip install 用）
├── README.md
├── videocut/
│   ├── __init__.py
│   ├── cli.py              # 命令行入口
│   ├── config.py           # 配置管理
│   ├── license.py          # License 验证
│   ├── transcribe.py       # 语音转录
│   ├── ai_rewrite.py       # AI 文案重组
│   ├── slip_detect.py      # 口误识别
│   ├── editor.py           # FFmpeg 剪辑
│   └── output/
│       ├── local.py        # 输出到本地
│       └── jianying.py     # 推送剪映
└── tests/
```

### 依赖清单

| 依赖 | 用途 | 大小 |
|------|------|------|
| funasr | 语音转录 | ~50MB |
| torch | 模型推理 | ~200MB |
| openai | LLM 调用 | 轻量 |
| anthropic | Claude 调用 | 轻量 |
| click | CLI 框架 | 轻量 |
| httpx | HTTP 请求 | 轻量 |

### 模型文件

首次运行下载，存储在 `~/.videocut/models/`：
- 语音识别模型：~2GB

### 配置文件格式

```json
// ~/.videocut/config.json
{
  "output_mode": "local",
  "llm": {
    "provider": "openai",
    "base_url": null,
    "model": "gpt-4o"
  },
  "jianying_path": "/Users/xxx/Movies/JianyingPro/..."
}
```

---

## 六、后续规划

### Phase 1: CLI 工具（当前）
- Python CLI，pip 分发
- License 在线验证
- 支持 macOS + Windows

### Phase 2: Claude Code Skill
- 将 CLI 封装为 Skill
- 触发词：`剪口播`、`videocut`

### Phase 3: Web 应用
- 在线上传视频处理
- 订阅制收费

---

v1.0 - 2026-01-17
