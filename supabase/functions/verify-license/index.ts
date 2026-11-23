/**
 * Videocut License 验证 Edge Function
 *
 * 功能:
 * 1. 验证 License Key 是否有效
 * 2. 检查设备数是否超限
 * 3. 记录设备激活信息
 *
 * 请求:
 * POST /functions/v1/verify-license
 * {
 *   "license_key": "VC-XXXX-XXXX-XXXX",
 *   "device_id": "设备唯一ID",
 *   "device_name": "设备名称"
 * }
 *
 * 响应:
 * {
 *   "valid": true/false,
 *   "expires_at": "2027-12-31",
 *   "devices_used": 1,
 *   "devices_max": 2,
 *   "error": "错误信息"
 * }
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// CORS 头
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  // 处理 CORS 预检请求
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    // 解析请求体
    const { license_key, device_id, device_name } = await req.json();

    if (!license_key || !device_id) {
      return new Response(
        JSON.stringify({
          valid: false,
          error: "缺少 license_key 或 device_id",
        }),
        {
          headers: { ...corsHeaders, "Content-Type": "application/json" },
          status: 400,
        }
      );
    }

    // 创建 Supabase 客户端 (使用 service_role key 以绕过 RLS)
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, supabaseServiceKey);

    // 1. 查询 License
    const { data: license, error: licenseError } = await supabase
      .from("licenses")
      .select("*")
      .eq("key", license_key)
      .single();

    if (licenseError || !license) {
      return new Response(
        JSON.stringify({
          valid: false,
          error: "License Key 不存在",
        }),
        {
          headers: { ...corsHeaders, "Content-Type": "application/json" },
          status: 200,
        }
      );
    }

    // 2. 检查 License 状态
    if (license.status !== "active") {
      return new Response(
        JSON.stringify({
          valid: false,
          error: `License 状态: ${license.status}`,
        }),
        {
          headers: { ...corsHeaders, "Content-Type": "application/json" },
          status: 200,
        }
      );
    }

    // 3. 检查过期时间
    if (license.expires_at && new Date(license.expires_at) < new Date()) {
      return new Response(
        JSON.stringify({
          valid: false,
          error: "License 已过期",
          expires_at: license.expires_at,
        }),
        {
          headers: { ...corsHeaders, "Content-Type": "application/json" },
          status: 200,
        }
      );
    }

    // 4. 查询已激活设备数
    const { data: activations, error: activationsError } = await supabase
      .from("activations")
      .select("device_id")
      .eq("license_id", license.id);

    const devicesUsed = activations?.length || 0;
    const maxDevices = license.max_devices || 2;

    // 5. 检查设备是否已激活
    const existingDevice = activations?.find((a) => a.device_id === device_id);

    if (!existingDevice) {
      // 新设备，检查是否超限
      if (devicesUsed >= maxDevices) {
        return new Response(
          JSON.stringify({
            valid: false,
            error: `设备数已达上限 (${devicesUsed}/${maxDevices})`,
            devices_used: devicesUsed,
            devices_max: maxDevices,
          }),
          {
            headers: { ...corsHeaders, "Content-Type": "application/json" },
            status: 200,
          }
        );
      }

      // 记录新设备激活
      await supabase.from("activations").insert({
        license_id: license.id,
        device_id: device_id,
        device_name: device_name || "Unknown Device",
      });
    } else {
      // 已有设备，更新 last_seen_at
      await supabase
        .from("activations")
        .update({ last_seen_at: new Date().toISOString() })
        .eq("license_id", license.id)
        .eq("device_id", device_id);
    }

    // 6. 返回成功结果
    const finalDevicesUsed = existingDevice ? devicesUsed : devicesUsed + 1;

    return new Response(
      JSON.stringify({
        valid: true,
        expires_at: license.expires_at
          ? license.expires_at.split("T")[0]
          : null,
        devices_used: finalDevicesUsed,
        devices_max: maxDevices,
      }),
      {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
        status: 200,
      }
    );
  } catch (error) {
    console.error("Error:", error);
    return new Response(
      JSON.stringify({
        valid: false,
        error: "服务器内部错误",
      }),
      {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
        status: 500,
      }
    );
  }
});
