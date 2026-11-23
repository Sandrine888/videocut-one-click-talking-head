# Supabase License 系统配置指南

本文档介绍如何在 Supabase 中配置 Videocut 的 License 验证系统。

## 概述

Videocut 使用 Supabase 作为 License 验证后端：
- **licenses 表**: 存储 License Key 及其配置
- **activations 表**: 记录设备激活信息
- **verify-license Edge Function**: 处理验证请求

## 第一步：创建 Supabase 项目

1. 访问 [Supabase](https://supabase.com) 并登录
2. 点击 "New Project" 创建新项目
3. 记录以下信息：
   - **Project URL**: `https://your-project-id.supabase.co`
   - **anon key**: 在 Settings > API 中找到

## 第二步：创建数据库表

在 Supabase SQL Editor 中执行 `supabase/migrations/001_create_licenses.sql`：

```sql
-- 1. 创建 licenses 表
CREATE TABLE IF NOT EXISTS licenses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,           -- License Key (VC-XXXX-XXXX-XXXX)
    user_email TEXT,                     -- 用户邮箱
    max_devices INTEGER DEFAULT 2,       -- 最大设备数
    expires_at TIMESTAMPTZ,              -- 过期时间
    created_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'expired', 'revoked'))
);

-- 2. 创建 activations 表
CREATE TABLE IF NOT EXISTS activations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    license_id UUID REFERENCES licenses(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    device_name TEXT,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(license_id, device_id)
);

-- 3. 创建索引
CREATE INDEX IF NOT EXISTS idx_licenses_key ON licenses(key);
CREATE INDEX IF NOT EXISTS idx_activations_license_id ON activations(license_id);

-- 4. 添加测试数据
INSERT INTO licenses (key, user_email, max_devices, expires_at, status)
VALUES ('VC-TEST-1234-5678', 'test@example.com', 2, '2027-12-31 23:59:59+00', 'active')
ON CONFLICT (key) DO NOTHING;

-- 5. 开启 RLS
ALTER TABLE licenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE activations ENABLE ROW LEVEL SECURITY;

-- 6. 创建服务角色策略
CREATE POLICY "Service role can access all licenses" ON licenses
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role can access all activations" ON activations
    FOR ALL USING (auth.role() = 'service_role');
```

## 第三步：部署 Edge Function

### 方法一：使用 Supabase CLI（推荐）

```bash
# 安装 Supabase CLI
npm install -g supabase

# 登录
supabase login

# 关联项目
supabase link --project-ref your-project-id

# 部署函数
supabase functions deploy verify-license
```

### 方法二：在控制台手动创建

1. 进入 Supabase Dashboard > Edge Functions
2. 点击 "Create a new function"
3. 名称填写 `verify-license`
4. 将 `supabase/functions/verify-license/index.ts` 的内容粘贴进去
5. 点击 Deploy

## 第四步：配置环境变量

在使用 Videocut 的机器上设置环境变量：

```bash
# macOS/Linux - 添加到 ~/.zshrc 或 ~/.bashrc
export VIDEOCUT_SUPABASE_URL="https://your-project-id.supabase.co"
export VIDEOCUT_SUPABASE_ANON_KEY="your-anon-key"

# 生效配置
source ~/.zshrc
```

```powershell
# Windows PowerShell
[System.Environment]::SetEnvironmentVariable("VIDEOCUT_SUPABASE_URL", "https://your-project-id.supabase.co", "User")
[System.Environment]::SetEnvironmentVariable("VIDEOCUT_SUPABASE_ANON_KEY", "your-anon-key", "User")
```

## 第五步：验证配置

```bash
# 运行状态检查
videocut status

# 应显示 License 有效期和设备信息
```

## 生成新 License

在 Supabase Table Editor 中向 `licenses` 表添加记录：

| 字段 | 示例值 | 说明 |
|------|--------|------|
| key | VC-PROD-1234-5678 | 唯一 License Key |
| user_email | customer@example.com | 客户邮箱 |
| max_devices | 2 | 最大激活设备数 |
| expires_at | 2027-12-31T23:59:59Z | 过期时间 |
| status | active | 状态: active/expired/revoked |

## 开发/测试模式

不配置 Supabase 环境变量时，Videocut 自动使用 mock 模式：

- `VC-TEST-*` 格式的 Key 视为有效
- `VC-*` 格式的其他 Key 也暂时视为有效
- 无需网络连接

强制使用 mock 模式：

```bash
export VIDEOCUT_LICENSE_MOCK=1
```

## 常见问题

### Q: Edge Function 调用失败？

检查：
1. Function 是否正确部署
2. 环境变量是否配置正确
3. 使用 `supabase functions logs verify-license` 查看日志

### Q: 设备数超限？

在 `activations` 表中删除不再使用的设备记录。

### Q: License 过期？

更新 `licenses` 表中对应记录的 `expires_at` 字段。
