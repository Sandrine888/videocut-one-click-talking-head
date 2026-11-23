# Videocut 技术方案

> 基于 spec.md v1.0 编写

## 1. 技术概述

### 1.1 技术栈选择

| 层级 | 技术选型 | 选择理由 |
|------|----------|----------|
| 语言 | Python 3.8+ | FunASR 依赖，跨平台支持好 |
| CLI框架 | Click | 成熟稳定，交互式配置支持好 |
| 语音识别 | FunASR | 开源免费，中文识别最优，支持字符级时间戳 |
| 视频处理 | FFmpeg | 业界标准，跨平台 |
| LLM调用 | openai/anthropic | 官方SDK，支持多种提供商 |
| HTTP客户端 | httpx | 异步支持，现代化 |
| 加密 | cryptography | API Key 本地加密存储 |
| 打包分发 | PyPI | 标准 Python 包分发 |

### 1.2 架构模式

CLI 单体应用，模块化设计：
- **命令层**：处理用户输入，调度业务逻辑
- **业务层**：转录、识别、剪辑等核心功能
- **基础层**：配置、License、工具函数

---

## 2. 系统架构

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────┐
│                      Videocut CLI                        │
├─────────────────────────────────────────────────────────┤
│  命令层 (cli.py)                                         │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐           │
│  │  init  │ │  cut   │ │ config │ │ status │           │
│  └────────┘ └────────┘ └────────┘ └────────┘           │
├─────────────────────────────────────────────────────────┤
│  业务层                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐          │
│  │ transcribe │ │ ai_rewrite │ │slip_detect │          │
│  │  (转录)    │ │ (AI重组)   │ │ (口误识别) │          │
│  └────────────┘ └────────────┘ └────────────┘          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐          │
│  │   editor   │ │output/local│ │output/jiany│          │
│  │  (剪辑)    │ │ (本地输出) │ │ (剪映输出) │          │
│  └────────────┘ └────────────┘ └────────────┘          │
├─────────────────────────────────────────────────────────┤
│  基础层                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐          │
│  │   config   │ │  license   │ │   llm      │          │
│  │  (配置)    │ │ (License)  │ │ (LLM调用)  │          │
│  └────────────┘ └────────────┘ └────────────┘          │
└─────────────────────────────────────────────────────────┘
                           │
                           ↓
              ┌────────────────────────┐
              │    Supabase (远程)     │
              │  License 验证服务      │
              └────────────────────────┘
```

### 2.2 模块划分

| 模块 | 文件 | 职责 | 依赖 |
|------|------|------|------|
| cli | cli.py | 命令行入口，参数解析 | 所有业务模块 |
| config | config.py | 配置读写、加密存储 | cryptography |
| license | license.py | License 在线验证 | httpx, config |
| llm | llm.py | 统一 LLM 调用接口 | openai, anthropic |
| transcribe | transcribe.py | 语音转录 | funasr, torch |
| ai_rewrite | ai_rewrite.py | AI 文案重组 | llm |
| slip_detect | slip_detect.py | 口误/语气词/静音识别 | 无 |
| editor | editor.py | FFmpeg 视频剪辑 | subprocess |
| output/local | output/local.py | 本地烧录字幕输出 | subprocess |
| output/jianying | output/jianying.py | 剪映草稿箱推送 | pyJianYingDraft |

---

## 3. 数据模型

### 3.1 配置文件结构

```json
// ~/.videocut/config.json
{
  "license_key": "VC-XXXX-XXXX-XXXX",
  "device_id": "auto-generated-uuid",
  "output_mode": "local",  // local | jianying
  "llm": {
    "provider": "openai",  // openai | anthropic | compatible
    "base_url": null,      // 仅 compatible 时使用
    "model": "gpt-4o"
  },
  "jianying_path": null,   // 剪映草稿目录
  "license_cache": {
    "valid": true,
    "expires_at": "2027-01-17",
    "cached_at": "2026-01-17T12:00:00"
  }
}
```

### 3.2 Supabase 表设计

#### 表: licenses
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PRIMARY KEY | 主键 |
| license_key | VARCHAR(20) | UNIQUE NOT NULL | VC-XXXX-XXXX-XXXX |
| email | VARCHAR(255) | | 购买者邮箱 |
| status | VARCHAR(20) | DEFAULT 'active' | active/expired/revoked |
| max_devices | INT | DEFAULT 2 | 最大设备数 |
| expires_at | TIMESTAMP | | 到期时间 |
| created_at | TIMESTAMP | DEFAULT now() | 创建时间 |

#### 表: activations
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PRIMARY KEY | 主键 |
| license_id | UUID | FK → licenses | 关联 License |
| device_id | VARCHAR(64) | | 设备唯一标识 |
| device_name | VARCHAR(100) | | 设备名称 |
| activated_at | TIMESTAMP | DEFAULT now() | 激活时间 |

---

## 4. 接口设计

### 4.1 License 验证 API

#### POST /functions/v1/verify-license

**请求**:
```json
{
  "license_key": "VC-XXXX-XXXX-XXXX",
  "device_id": "uuid",
  "device_name": "MacBook Pro"
}
```

**响应（成功）**:
```json
{
  "valid": true,
  "expires_at": "2027-01-17T00:00:00Z",
  "devices_used": 1,
  "devices_max": 2
}
```

**响应（失败）**:
```json
{
  "valid": false,
  "error": "License expired"
}
```

### 4.2 CLI 命令接口

| 命令 | 参数 | 说明 |
|------|------|------|
| `videocut init` | 无 | 交互式初始化 |
| `videocut cut <video>` | `--output`, `--skip-ai` | 剪辑视频 |
| `videocut config` | 无 | 修改配置 |
| `videocut status` | 无 | 查看状态 |

---

## 5. 核心流程

### 5.1 初始化流程 (videocut init)

```
1. 检查是否已初始化
   ↓
2. 输入 License Key
   ↓
3. 在线验证 License → Supabase
   ├─ 失败 → 提示错误，重试
   └─ 成功 ↓
4. 配置 LLM 服务
   ├─ 选择提供商
   ├─ 输入 API Key / Base URL
   └─ 测试连接
   ├─ 失败 → 提示错误，重试
   └─ 成功 ↓
5. 选择默认输出方式
   ↓
6. 检测依赖（FFmpeg）
   ↓
7. 下载语音识别模型（首次）
   ↓
8. 保存配置 → ~/.videocut/config.json
   ↓
9. 完成
```

### 5.2 剪辑流程 (videocut cut)

```
1. 验证 License（读缓存或在线验证）
   ├─ 失败 → 提示重新激活
   └─ 成功 ↓
2. 转录视频
   ├─ 提取音频
   ├─ 30s 分段转录
   └─ 合并时间戳
   ↓
3. AI 文案重组（可跳过）
   ├─ 调用 LLM 分析
   ├─ 生成 2 个方案
   └─ 用户选择
   ↓
4. 口误识别
   ├─ 逐句检查口误
   ├─ VAD 检测微口误
   ├─ 扫描语气词
   └─ 识别长静音
   ↓
5. 显示删除任务清单
   ↓
6. 用户确认
   ↓
7. 执行剪辑
   ├─ 生成 filter.txt
   └─ FFmpeg 剪辑
   ↓
8. 输出
   ├─ local → 烧录字幕
   └─ jianying → 推送草稿箱
```

### 5.3 异常处理

| 异常类型 | 处理方式 |
|----------|----------|
| License 无效 | 提示错误信息，引导重新激活 |
| License 过期 | 提示续费 |
| 设备数超限 | 提示已激活设备列表 |
| LLM 调用失败 | 重试3次，失败后提示跳过 AI 重组 |
| 网络错误 | 使用缓存（24小时内有效） |
| FFmpeg 未安装 | 提示安装命令 |
| 视频格式不支持 | 提示支持的格式 |

---

## 6. 目录结构

```
videocut/
├── pyproject.toml           # 包配置（pip install 用）
├── README.md
├── LICENSE
├── videocut/
│   ├── __init__.py          # 版本信息
│   ├── cli.py               # 命令行入口（Click）
│   ├── config.py            # 配置管理
│   ├── license.py           # License 验证
│   ├── llm.py               # LLM 统一接口
│   ├── transcribe.py        # 语音转录
│   ├── ai_rewrite.py        # AI 文案重组
│   ├── slip_detect.py       # 口误识别
│   ├── editor.py            # FFmpeg 剪辑
│   ├── output/
│   │   ├── __init__.py
│   │   ├── local.py         # 本地输出
│   │   └── jianying.py      # 剪映输出
│   └── utils/
│       ├── __init__.py
│       ├── device.py        # 设备ID生成
│       └── crypto.py        # 加密工具
├── tests/
│   ├── test_config.py
│   ├── test_license.py
│   ├── test_transcribe.py
│   └── ...
└── docs/
    ├── spec.md
    ├── plan.md
    └── tasks.md
```

---

## 7. 安全设计

### 7.1 API Key 存储
- 使用 Fernet 对称加密
- 密钥基于设备 ID 生成
- 存储在 `~/.videocut/.credentials`

### 7.2 License 验证
- HTTPS 通信
- 设备 ID 绑定
- 24小时本地缓存，离线可用

### 7.3 用户隐私
- 视频内容不上传
- 转录在本地完成
- 仅上传 License 验证信息

---

## 8. 测试策略

### 8.1 测试类型

| 类型 | 覆盖范围 | 工具 |
|------|----------|------|
| 单元测试 | 核心函数 | pytest |
| 集成测试 | 完整流程 | pytest |
| 手动测试 | 用户体验 | - |

### 8.2 关键测试用例

| 模块 | 测试点 |
|------|--------|
| license | 验证成功/失败/过期/设备超限 |
| config | 读写/加密/迁移 |
| transcribe | 短视频/长视频/各种格式 |
| slip_detect | 各类口误识别 |
| editor | 剪辑准确性 |

---

## 9. 部署方案

### 9.1 PyPI 发布

```bash
# 构建
python -m build

# 发布
twine upload dist/*
```

### 9.2 用户安装

```bash
# 安装
pip install videocut

# 首次使用
videocut init
```

### 9.3 依赖说明

| 依赖 | 安装方式 | 说明 |
|------|----------|------|
| FFmpeg | 系统安装 | brew/apt/choco |
| 语音模型 | 自动下载 | ~/.videocut/models/ |

---

## 10. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 语音模型大（2GB） | 首次下载慢 | 显示进度，支持断点续传 |
| FunASR 仅支持中文 | 无法处理英文视频 | 文档说明，未来可加 Whisper |
| 剪映版本更新 | 草稿格式变化 | 版本检测，及时适配 |
| LLM API 费用 | 用户承担 | 明确告知，支持跳过 |

---

## 11. 里程碑

| 阶段 | 内容 | 交付物 |
|------|------|--------|
| M1 | 项目骨架 + License 验证 | 可验证的 CLI 框架 |
| M2 | 转录 + 口误识别 | 能识别口误 |
| M3 | 剪辑 + 本地输出 | MVP 完成 |
| M4 | AI 重组 + 剪映输出 | 完整版本 |
| M5 | 测试 + 发布 PyPI | 可分发版本 |
