-- Videocut License 系统数据库架构
-- 运行方式: 在 Supabase SQL Editor 中执行

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

-- 2. 创建 activations 表 (设备激活记录)
CREATE TABLE IF NOT EXISTS activations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    license_id UUID REFERENCES licenses(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,             -- 设备唯一标识
    device_name TEXT,                    -- 设备名称
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(license_id, device_id)
);

-- 3. 创建索引
CREATE INDEX IF NOT EXISTS idx_licenses_key ON licenses(key);
CREATE INDEX IF NOT EXISTS idx_activations_license_id ON activations(license_id);
CREATE INDEX IF NOT EXISTS idx_activations_device_id ON activations(device_id);

-- 4. 添加测试数据
INSERT INTO licenses (key, user_email, max_devices, expires_at, status)
VALUES
    ('VC-TEST-1234-5678', 'test@example.com', 2, '2027-12-31 23:59:59+00', 'active'),
    ('VC-DEMO-AAAA-BBBB', 'demo@example.com', 1, '2026-06-30 23:59:59+00', 'active')
ON CONFLICT (key) DO NOTHING;

-- 5. 开启 RLS (Row Level Security)
ALTER TABLE licenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE activations ENABLE ROW LEVEL SECURITY;

-- 6. 创建服务角色策略 (Edge Functions 使用 service_role key 访问)
CREATE POLICY "Service role can access all licenses"
    ON licenses
    FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Service role can access all activations"
    ON activations
    FOR ALL
    USING (auth.role() = 'service_role');

-- 完成!
