/**
 * 自动创建 License 并发送邮件
 *
 * POST /functions/v1/create-license
 * {
 *   "email": "user@example.com",
 *   "max_devices": 2,
 *   "days": 365,
 *   "admin_key": "管理密钥"
 * }
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

// 生成 License Key: VC-XXXX-XXXX-XXXX
function generateLicenseKey(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const segment = () => Array.from({ length: 4 }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
  return `VC-${segment()}-${segment()}-${segment()}`;
}

// 发送邮件
async function sendEmail(to: string, licenseKey: string, expiresAt: string, maxDevices: number) {
  const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY");

  if (!RESEND_API_KEY) {
    console.log("RESEND_API_KEY not set, skipping email");
    return { sent: false, reason: "no_api_key" };
  }

  const html = `
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px;">
      <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #667eea; margin: 0;">Videocut</h1>
        <p style="color: #666; margin-top: 8px;">智能口播视频剪辑工具</p>
      </div>

      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; padding: 30px; text-align: center; margin-bottom: 30px;">
        <p style="color: rgba(255,255,255,0.8); margin: 0 0 10px 0; font-size: 14px;">您的 License Key</p>
        <div style="background: white; border-radius: 8px; padding: 20px; font-family: 'Monaco', 'Consolas', monospace; font-size: 24px; font-weight: bold; color: #333; letter-spacing: 2px;">
          ${licenseKey}
        </div>
      </div>

      <div style="background: #f8f9fa; border-radius: 8px; padding: 20px; margin-bottom: 30px;">
        <h3 style="margin: 0 0 15px 0; color: #333; font-size: 16px;">License 信息</h3>
        <p style="margin: 8px 0; color: #666;">📅 有效期至: <strong>${expiresAt}</strong></p>
        <p style="margin: 8px 0; color: #666;">💻 可激活设备: <strong>${maxDevices} 台</strong></p>
      </div>

      <div style="background: #e8f4fd; border-radius: 8px; padding: 20px; margin-bottom: 30px;">
        <h3 style="margin: 0 0 15px 0; color: #333; font-size: 16px;">快速开始</h3>
        <pre style="background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 6px; overflow-x: auto; font-size: 13px;">
# 1. 安装
pip install git+https://github.com/wchris8858-claude/videocut.git

# 2. 初始化（输入上面的 License Key）
videocut init

# 3. 剪辑视频
videocut cut 你的视频.mp4</pre>
      </div>

      <p style="color: #999; font-size: 12px; text-align: center;">
        如有问题，请联系技术支持
      </p>
    </div>
  `;

  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: "Videocut <onboarding@resend.dev>",
        to: [to],
        subject: "您的 Videocut License Key",
        html: html,
      }),
    });

    const data = await res.json();

    if (res.ok) {
      return { sent: true, id: data.id };
    } else {
      console.error("Email send failed:", data);
      return { sent: false, reason: data.message || "send_failed" };
    }
  } catch (e) {
    console.error("Email error:", e);
    return { sent: false, reason: "network_error" };
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { email, max_devices = 2, days = 365, admin_key } = await req.json();

    // 验证管理密钥（必须通过环境变量配置）
    const ADMIN_KEY = Deno.env.get("VIDEOCUT_ADMIN_KEY");
    if (!ADMIN_KEY || admin_key !== ADMIN_KEY) {
      return new Response(JSON.stringify({ error: "无效的管理密钥" }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
        status: 401,
      });
    }

    if (!email) {
      return new Response(JSON.stringify({ error: "缺少 email" }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
        status: 400,
      });
    }

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    // 生成唯一 License Key
    let licenseKey = generateLicenseKey();
    let attempts = 0;
    while (attempts < 10) {
      const { data: existing } = await supabase
        .from("licenses")
        .select("key")
        .eq("key", licenseKey)
        .single();

      if (!existing) break;
      licenseKey = generateLicenseKey();
      attempts++;
    }

    // 计算过期时间
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + days);
    const expiresAtStr = expiresAt.toISOString().split("T")[0];

    // 创建 License
    const { error } = await supabase
      .from("licenses")
      .insert({
        key: licenseKey,
        user_email: email,
        max_devices: max_devices,
        expires_at: expiresAt.toISOString(),
        status: "active",
      });

    if (error) {
      return new Response(JSON.stringify({ error: error.message }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
        status: 500,
      });
    }

    // 发送邮件
    const emailResult = await sendEmail(email, licenseKey, expiresAtStr, max_devices);

    return new Response(JSON.stringify({
      success: true,
      license: {
        key: licenseKey,
        email: email,
        max_devices: max_devices,
        expires_at: expiresAtStr,
      },
      email_sent: emailResult.sent,
      email_info: emailResult,
    }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });

  } catch (e) {
    console.error("Error:", e);
    return new Response(JSON.stringify({ error: "服务器错误" }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
      status: 500,
    });
  }
});
