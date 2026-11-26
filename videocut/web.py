"""Loopback HTTP adapter and a small E-replaceable integration page."""

import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import unquote, urlsplit
import uuid
import webbrowser

from .jobs import BusyError, JobManager
from .media import check_tools, inspect_media
from .pipeline import GenerateOptions, load_adapters, write_json

MAX_UPLOAD = 2 * 1024 ** 3


def create_server(workspace, port=8765, *, adapters_spec=None):
    manager = JobManager(workspace, adapters=load_adapters(adapters_spec))
    root = manager.root
    imports = root / "imports"
    imports.mkdir(exist_ok=True)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass

        def send_bytes(self, payload, status=200, content_type="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.end_headers()
            self.wfile.write(payload)

        def json(self, value, status=200):
            self.send_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"), status)

        def authorize(self, api=True):
            port = self.server.server_port
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                raise PermissionError("仅允许从本机打开工具。")
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in allowed}:
                raise PermissionError("请求来源不匹配，请从工具页面操作。")
            if api:
                cookie = self.headers.get("Cookie", "")
                supplied = self.headers.get("X-Videocut-Token", "")
                cookies = dict(pair.strip().split("=", 1) for pair in cookie.split(";") if "=" in pair)
                if not (secrets.compare_digest(supplied, token) or
                        secrets.compare_digest(cookies.get("videocut_session", ""), token)):
                    raise PermissionError("会话已失效，请刷新页面。")

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                self.authorize(api=path != "/")
                if path == "/":
                    page = (Path(__file__).parent / "webui" / "index.html").read_text(encoding="utf-8")
                    page = page.replace("__SESSION_TOKEN__", token)
                    payload = page.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Set-Cookie", f"videocut_session={token}; HttpOnly; SameSite=Strict; Path=/")
                    self.send_header("X-Frame-Options", "DENY")
                    self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'")
                    self.end_headers()
                    self.wfile.write(payload)
                elif path == "/api/advanced/settings":
                    from .advanced import public_settings
                    self.json(public_settings())
                elif path == "/api/health":
                    issues = []
                    try:
                        check_tools()
                    except Exception as exc:
                        issues.append(str(exc))
                    if importlib.util.find_spec("funasr") is None:
                        issues.append("当前 Python 环境缺少 FunASR，请使用已配置的识别环境。")
                    from .transcribe import resolve_model_name
                    if not Path(resolve_model_name("paraformer-zh")).is_dir():
                        issues.append("缺少本地模型。请把完整识别模型复制到工具目录下的 models/paraformer-zh，再刷新页面。")
                    self.json(dict(ready=not issues, issues=issues, max_upload_bytes=MAX_UPLOAD,
                                   note="语音识别使用本地模型。"))
                elif match := re.fullmatch(r"/api/jobs/([a-f0-9]{32})", path):
                    self.json(manager.snapshot(match[1]))
                elif match := re.fullmatch(r"/files/([a-f0-9]{32})/(video|srt|checks|log)", path):
                    job = manager.snapshot(match[1])
                    result = job.get("result", {})
                    kind = match[2]
                    if kind == "log":
                        directory = job.get("task_dir") or result.get("task_dir")
                        file = Path(directory) / "error.log" if directory else None
                    else:
                        file = Path(result[kind]) if job["status"] == "completed" and kind in result else None
                    if not file or not file.is_file() or not file.resolve().is_relative_to(root):
                        raise KeyError("该结果尚不可用。")
                    self.send_file(file, download=kind != "video")
                else:
                    raise KeyError("找不到该页面。")
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                self.handle_error(exc)

        def do_POST(self):
            try:
                self.authorize()
                self.connection.settimeout(120)
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length", "-1"))
                if length < 0:
                    raise ValueError("请求缺少文件长度。")
                if path == "/api/import":
                    if length <= 0 or length > MAX_UPLOAD:
                        raise ValueError("请选择非空视频，当前单文件上限为 2 GB。")
                    name = unquote(self.headers.get("X-Filename", "video.mp4"))
                    suffix = Path(name).suffix.lower()
                    if suffix not in {".mp4", ".mov"}:
                        raise ValueError("当前网页先支持 MP4 和 MOV。")
                    import_id = uuid.uuid4().hex
                    directory = imports / import_id
                    directory.mkdir()
                    target = directory / ("source" + suffix)
                    try:
                        with target.open("wb") as stream:
                            remaining = length
                            while remaining:
                                chunk = self.rfile.read(min(1024 * 1024, remaining))
                                if not chunk:
                                    raise ValueError("视频传入中断，请重新选择。")
                                stream.write(chunk)
                                remaining -= len(chunk)
                        media = inspect_media(target)
                        data = dict(import_id=import_id, name=Path(name).name, media=media)
                        write_json(directory / "media.json", data)
                        self.json(data, 201)
                    except Exception:
                        target.unlink(missing_ok=True)
                        raise
                elif path == "/api/advanced/settings":
                    if length > 16384:
                        raise ValueError("配置过长。")
                    from .advanced import configure
                    self.json(configure(json.loads(self.rfile.read(length))))
                elif path == "/api/shutdown":
                    if length > 65536:
                        raise ValueError("请求过长。")
                    self.rfile.read(length)
                    manager.begin_shutdown()
                    self.json({"message": "工具已退出。"})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                elif path == "/api/jobs":
                    if length > 65536:
                        raise ValueError("启动参数过长。")
                    data = json.loads(self.rfile.read(length))
                    import_id = data.get("import_id", "")
                    if not re.fullmatch(r"[a-f0-9]{32}", import_id):
                        raise ValueError("请先选择视频。")
                    metadata = json.loads((imports / import_id / "media.json").read_text(encoding="utf-8"))
                    trim = data.get("trim_silence", False)
                    if type(trim) is not bool:
                        raise ValueError("自动删停顿的选项无效。")
                    mode = data.get('mode', 'quick')
                    auto = data.get('auto_apply', False)
                    review = data.get('review_task')
                    ids = data.get('selected_ids', [])
                    if mode not in ('quick', 'advanced') or type(auto) is not bool or not isinstance(ids, list) or any(type(i) is not int for i in ids):
                        raise ValueError('无效的剪辑选项。')
                    if mode == 'quick' and (auto or review or ids):
                        raise ValueError('快剪不接受 AI 参数。')
                    if mode == 'advanced' and not review:
                        from .advanced import public_settings
                        if not public_settings()['configured']:
                            raise ValueError('请先测试并保存 API 设置。')
                    options = GenerateOptions(video=metadata["media"]["path"],
                                              output_dir=str(root / "results"), trim_silence=trim, mode=mode, auto_apply=auto,
                                              review_task=review, selected_ids=tuple(ids))
                    self.json(manager.start(options, request_key=f"{import_id}:{trim}:{mode}:{auto}:{review}:{ids}"), 202)
                else:
                    raise KeyError("找不到该接口。")
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                self.close_connection = True
                self.handle_error(exc)

        def handle_error(self, exc):
            status = 403 if isinstance(exc, PermissionError) else 409 if isinstance(exc, BusyError) else 404 if isinstance(exc, (KeyError, FileNotFoundError)) else 400
            self.json({"error": str(exc)}, status)

        def send_file(self, path, download=False):
            size = path.stat().st_size
            start, end, status = 0, size - 1, 200
            range_header = self.headers.get("Range")
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                if not match or (not match[1] and not match[2]):
                    self.send_bytes(b"", 416)
                    return
                if match[1]:
                    start = int(match[1])
                    end = min(int(match[2]), size - 1) if match[2] else size - 1
                else:
                    start = max(0, size - int(match[2]))
                if start >= size or start > end:
                    self.send_bytes(b"", 416)
                    return
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.manager, server.session_token = manager, token
    server.daemon_threads = True
    return server


def serve(port=8765, open_browser=True, workspace=".videocut-work", adapters_spec=None):
    # Avoid two servers changing the same job/cache workspace.
    from .workspace_lock import workspace_lock
    with workspace_lock(workspace):
        server = create_server(workspace, port, adapters_spec=adapters_spec)
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"本机口播工具：{url}\n首次加载模型可能较慢。按 Ctrl+C 停止服务。", flush=True)
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            server.manager.close()
