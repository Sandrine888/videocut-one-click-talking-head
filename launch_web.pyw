"""Double-click local launcher. Detailed output stays in the workspace."""
from pathlib import Path
import os
import sys
import traceback
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
WORK = ROOT / ".videocut-work"
WORK.mkdir(exist_ok=True)
log = (WORK / "server.log").open("a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log

try:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/", timeout=2) as response:
            existing = response.read(2048).decode("utf-8", errors="replace")
        if 'name="application-name" content="videocut-local"' in existing:
            webbrowser.open("http://127.0.0.1:8765/")
            raise SystemExit(0)
    except (OSError, ValueError):
        pass
    from videocut.web import serve
    serve(workspace=WORK)
except Exception:
    traceback.print_exc()
    from tkinter import Tk, messagebox
    window = Tk()
    window.withdraw()
    messagebox.showerror("口播工具未能启动", f"请检查处理环境或正在运行的工具。\n详细记录：{WORK / 'server.log'}")
    window.destroy()
