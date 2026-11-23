#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VideoCut 显式配置启动器

读取同目录 llm_profiles.json，把选中的 API / 模型写进 ~/.videocut/config.json，
并按方案取用加密保存的 API Key，然后调用 videocut.exe（或源码 CLI）。

不需要重新打包 exe，也不需要运行 videocut config 交互菜单。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PROFILES_FILE = ROOT / "llm_profiles.json"
CONFIG_DIR = Path.home() / ".videocut"
CONFIG_FILE = CONFIG_DIR / "config.json"
CRED_FILE = CONFIG_DIR / ".credentials"
PROFILE_KEYS_FILE = CONFIG_DIR / "profile_keys.json"

VALID_PROVIDERS = ("openai", "anthropic", "compatible")


def die(msg: str):
    print("[错误] " + msg)
    sys.exit(1)


def ensure_crypto():
    """保证 cryptography 可用；必要时用项目自带 venv 重新执行自身。"""
    try:
        import cryptography  # noqa: F401
        return
    except ImportError:
        pass

    venv_py = ROOT / "venv_build" / "Scripts" / "python.exe"
    if (venv_py.exists()
            and Path(sys.executable).resolve() != venv_py.resolve()
            and os.environ.get("VIDEOCUT_RUNNER_REEXEC") != "1"):
        os.environ["VIDEOCUT_RUNNER_REEXEC"] = "1"
        os.execv(str(venv_py),
                 [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])

    die("缺少 cryptography，无法读写加密 API Key。请用项目内 "
        "venv_build\\Scripts\\python.exe 运行，或执行 pip install cryptography")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        die(f"读取 {path} 失败：{e}")


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def load_profiles():
    data = read_json(PROFILES_FILE)
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        die(f"{PROFILES_FILE} 不存在或缺少 profiles 配置")
    return data, profiles


def validate(name: str, p: dict):
    if p.get("provider") not in VALID_PROVIDERS:
        die(f"方案 {name} 的 provider 非法：{p.get('provider')}，"
            f"只能是 {' / '.join(VALID_PROVIDERS)}")
    if not p.get("model"):
        die(f"方案 {name} 缺少 model")
    if p["provider"] == "compatible" and not p.get("base_url"):
        die(f"方案 {name} 是 compatible，必须填写 base_url")


def resolve_key(name: str, p: dict, decrypt):
    """返回 (明文key 或 None, 来源说明, 状态)。状态: ok / reuse / missing"""
    env_name = p.get("api_key_env")
    if env_name:
        val = os.environ.get(env_name, "").strip()
        if val:
            return val, f"环境变量 {env_name}", "ok"
        # 环境变量名写了但没设值：继续回退到专用 Key / 已有 Key

    if p.get("api_key"):
        return str(p["api_key"]).strip(), "配置文件明文（建议改用 --set-key）", "ok"

    saved = read_json(PROFILE_KEYS_FILE)
    if saved.get(name):
        try:
            return decrypt(saved[name]), f"本机加密保存的专用 Key（{PROFILE_KEYS_FILE.name}）", "ok"
        except Exception:
            return None, "专用 Key 解密失败，请重新执行 --set-key", "missing"

    cred = read_json(CRED_FILE)
    if cred.get(f"api_key_{p['provider']}"):
        return None, "沿用 .credentials 中已有的同类型 Key", "reuse"

    hint = f"（环境变量 {env_name} 未设置）" if env_name else ""
    return None, f"未找到 API Key{hint}，剪视频前请设置", "missing"


def pin_reuse_key(name: str, provider: str) -> bool:
    """把当前复用的 Key 密文固化为本方案专用，避免同 provider 的多个服务串号。"""
    enc = read_json(CRED_FILE).get(f"api_key_{provider}")
    if not enc:
        return False
    keys = read_json(PROFILE_KEYS_FILE)
    if keys.get(name):
        return False
    keys[name] = enc
    write_json(PROFILE_KEYS_FILE, keys)
    return True


def show_profile(name: str, p: dict, key_info):
    key, source, status = key_info
    llm = {
        "provider": p["provider"],
        "base_url": p.get("base_url") if p["provider"] == "compatible" else None,
        "model": p["model"],
    }
    print(f"[方案] {name}  -  {p.get('description', '')}")
    print(f"    provider : {llm['provider']}")
    print(f"    base_url : {llm['base_url'] or '(官方默认)'}")
    print(f"    model    : {llm['model']}")
    print(f"    api_key  : {source}")
    if status == "missing":
        print("    [!] 该方案当前没有可用 Key，AI 剪辑会失败；用 --set-key 或环境变量补上。")
    return llm


def apply_profile(name: str, p: dict, key_info, encrypt, dry_run=False):
    key, source, status = key_info
    llm = show_profile(name, p, key_info)

    if dry_run:
        print("[dry-run] 未写入任何文件，也未运行 videocut。")
        return

    if status == "reuse" and pin_reuse_key(name, llm["provider"]):
        print(f"    [自动固化] 已把当前 Key 绑定为方案 [{name}] 专用，"
              f"避免与其他 {llm['provider']} 服务串号（{PROFILE_KEYS_FILE.name}）")

    cfg = read_json(CONFIG_FILE)
    if not cfg:
        die(f"{CONFIG_FILE} 不存在，请先运行 videocut init 完成初始化")
    cfg["llm"] = llm
    write_json(CONFIG_FILE, cfg)

    if key:
        cred = read_json(CRED_FILE)
        cred[f"api_key_{llm['provider']}"] = encrypt(key)
        write_json(CRED_FILE, cred)
        print(f"[已写入] {CONFIG_FILE}  (+ 更新 {CRED_FILE} 的 api_key_{llm['provider']})")
    else:
        print(f"[已写入] {CONFIG_FILE}  (Key 未改动)")


def list_profiles(data: dict, profiles: dict, decrypt):
    cfg = read_json(CONFIG_FILE)
    cur = cfg.get("llm", {}) if cfg else {}
    print(f"配置文件: {PROFILES_FILE}")
    print(f"默认方案: {data.get('default_profile', '(未设置)')}")
    print("")
    print("可用方案:")
    for name, p in profiles.items():
        validate(name, p)
        _, _, status = resolve_key(name, p, decrypt)
        base = p.get("base_url") or "-"
        mark = ""
        if (cur.get("provider") == p.get("provider")
                and cur.get("model") == p.get("model")
                and cur.get("base_url") == (p.get("base_url") if p["provider"] == "compatible" else None)):
            mark = "   <== 当前生效"
        key_flag = {"ok": "", "reuse": "  [复用已有 Key]",
                    "missing": "  [缺 Key]"}.get(status, "")
        print(f"  {name:<12} {p['provider']:<11} {p['model']:<32} {base}{mark}{key_flag}")
    print("")
    if cur:
        print(f"当前 ~/.videocut/config.json : provider={cur.get('provider')}, "
              f"base_url={cur.get('base_url') or '-'}, model={cur.get('model')}")
    else:
        print("当前 ~/.videocut/config.json : 尚未初始化")
    print("")
    print("切换: vc.bat --use <方案名>   或   vc.bat -p <方案名> cut \"视频路径\"")


def do_set_key(name: str, profiles: dict, encrypt):
    if name not in profiles:
        die(f"没有名为 {name} 的方案；可用：{', '.join(profiles)}")
    # 管道 / 脚本化输入时直接读 stdin；交互式终端才隐藏回显。
    # 可用 VIDEOCUT_KEY_FROM_STDIN=1 强制走 stdin（便于 CI 或批处理）。
    from_stdin = (os.environ.get("VIDEOCUT_KEY_FROM_STDIN") == "1"
                  or not sys.stdin.isatty())
    try:
        if from_stdin:
            print(f"请为方案 [{name}] 提供 API Key（从 stdin 读取）...")
            val = sys.stdin.readline()
        else:
            val = getpass.getpass(f"请输入方案 [{name}] 的 API Key（输入不回显）: ")
    except (EOFError, KeyboardInterrupt):
        die("已取消")
    val = (val or "").strip()
    if not val:
        die("Key 不能为空")

    keys = read_json(PROFILE_KEYS_FILE)
    keys[name] = encrypt(val)
    write_json(PROFILE_KEYS_FILE, keys)
    print(f"[已加密保存] {PROFILE_KEYS_FILE} -> {name}")
    print(f"下次运行 vc.bat -p {name} ... 会自动使用这份 Key。")


def resolve_target(exe_opt: str | None):
    if exe_opt:
        return [exe_opt]
    for rel in ("installer/videocut.exe", "dist/videocut.exe"):
        p = ROOT / rel
        if p.exists():
            return [str(p)]
    return [sys.executable, "-m", "videocut.cli"]


def snapshot():
    return {
        CONFIG_FILE: CONFIG_FILE.read_bytes() if CONFIG_FILE.exists() else None,
        CRED_FILE: CRED_FILE.read_bytes() if CRED_FILE.exists() else None,
    }


def restore(snap):
    for path, raw in snap.items():
        if raw is None:
            if path.exists():
                path.unlink()
        else:
            path.write_bytes(raw)


def print_runner_help():
    print("""VideoCut 显式配置启动器（vc.bat）

  vc.bat --list                          查看全部方案与当前生效配置
  vc.bat --current                       只看当前生效配置
  vc.bat --use <方案名>                  仅切换配置，不运行视频
  vc.bat -p <方案名> cut "视频.mp4"      用指定方案剪视频
  vc.bat -p <方案名> --model <模型名> ... 临时覆盖模型名
  vc.bat --set-key <方案名>              交互式录入并加密保存该方案专用 Key
  vc.bat --dry-run -p <方案名>           只预览将生效的配置
  vc.bat --no-persist -p <方案名> ...    用一次，运行后恢复原配置

启动器参数:
  -p / --profile NAME    选择 llm_profiles.json 中的方案（默认用 default_profile）
  --provider NAME        覆盖 provider: openai | anthropic | compatible
  --base-url URL         覆盖 API 地址（传空字符串可清空）
  --model NAME           覆盖模型名称
  --exe PATH             指定 videocut.exe 路径（默认 installer/videocut.exe）
  --list / --current / --use / --set-key / --dry-run / --no-persist / --runner-help

其余参数原样透传给 videocut：cut / status / config / init / --help / -o local / --skip-ai ...
不带任何 videocut 命令时，默认执行 status 以确认配置生效。
配置文件: llm_profiles.json
""")


def main():
    # add_help=False：让 -h / --help 原样透传给 videocut
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("-p", "--profile")
    ap.add_argument("--provider", choices=VALID_PROVIDERS)
    ap.add_argument("--base-url")
    ap.add_argument("--model")
    ap.add_argument("--exe")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--current", action="store_true")
    ap.add_argument("--use", metavar="NAME")
    ap.add_argument("--set-key", metavar="NAME")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-persist", action="store_true")
    ap.add_argument("--runner-help", action="store_true")
    args, rest = ap.parse_known_args()

    ensure_crypto()
    from videocut.utils.crypto import encrypt, decrypt

    data, profiles = load_profiles()

    if args.runner_help:
        print_runner_help()
        return
    if args.list:
        list_profiles(data, profiles, decrypt)
        return
    if args.current:
        cfg = read_json(CONFIG_FILE)
        cur = cfg.get("llm") if cfg else None
        print(json.dumps(cur, indent=2, ensure_ascii=False) if cur else "尚未初始化")
        return
    if args.set_key:
        do_set_key(args.set_key, profiles, encrypt)
        return

    name = args.profile or args.use or data.get("default_profile")
    if not name:
        die("未指定方案，且 llm_profiles.json 里没有 default_profile")
    if name not in profiles:
        die(f"没有名为 [{name}] 的方案；可用：{', '.join(profiles)}")

    p = dict(profiles[name])
    if args.provider:
        p["provider"] = args.provider
    if args.base_url is not None:
        p["base_url"] = args.base_url or None
    if args.model:
        p["model"] = args.model
    validate(name, p)

    key_info = resolve_key(name, p, decrypt)

    if args.dry_run:
        apply_profile(name, p, key_info, encrypt, dry_run=True)
        return

    snap = snapshot() if (args.no_persist and not args.use) else None
    try:
        apply_profile(name, p, key_info, encrypt)

        if args.use:
            print("[完成] 配置已切换，未运行 videocut。")
            return

        cmd = resolve_target(args.exe) + (rest or ["status"])
        if not rest:
            print("[提示] 未指定 videocut 命令，默认执行 status 确认生效配置。")
        print("[运行] " + " ".join(cmd))
        print("-" * 60)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        rc = subprocess.call(cmd, env=env)
        print("-" * 60)
        print(f"[videocut 退出码] {rc}")
        sys.exit(rc)
    finally:
        if snap is not None:
            restore(snap)
            print("[no-persist] 已恢复运行前的配置。")


if __name__ == "__main__":
    main()
