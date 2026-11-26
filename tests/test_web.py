"""HTTP boundary regression: local session, imports, jobs and playable ranges."""
import http.cookiejar
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request, urlopen

import pytest

from videocut import web


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "inspect_media", lambda path: {"path": str(path), "duration": 2,
                        "width": 640, "height": 360, "direction": "横屏"})
    server = web.create_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with client.open(url + "/") as response:
        assert "__SESSION_TOKEN__" not in response.read().decode("utf-8-sig")
    try:
        yield server, url, client
    finally:
        server.shutdown(); server.server_close(); server.manager.close(); thread.join(3)


def test_api_rejects_missing_session(service):
    _, url, _ = service
    with pytest.raises(HTTPError) as error:
        urlopen(url + "/api/health")
    assert error.value.code == 403


def test_post_rejects_cross_origin_even_with_cookie(service):
    _, url, client = service
    request = Request(url + "/api/jobs", data=b"{}",
                      headers={"Origin": "https://other.example"})
    with pytest.raises(HTTPError) as error:
        client.open(request)
    assert error.value.code == 403


def test_import_keeps_unicode_filename_and_reports_media(service):
    _, url, client = service
    from urllib.parse import quote
    request = Request(url + "/api/import", data=b"test video",
                      headers={"X-Filename": quote("中文 视频.mp4")})
    data = json.loads(client.open(request).read())
    assert data["name"] == "中文 视频.mp4"
    assert data["media"]["duration"] == 2
    assert Path(data["media"]["path"]).read_bytes() == b"test video"


def test_import_rejects_non_video_extension(service):
    _, url, client = service
    with pytest.raises(HTTPError) as error:
        client.open(Request(url + "/api/import", data=b"text", headers={"X-Filename": "file.txt"}))
    assert error.value.code == 400


def test_jobs_reject_truthy_string_for_trim_switch(service):
    _, url, client = service
    imported = json.loads(client.open(Request(url + "/api/import", data=b"video",
                                             headers={"X-Filename": "source.mp4"})).read())
    with pytest.raises(HTTPError) as error:
        client.open(Request(url + "/api/jobs", data=json.dumps({
            "import_id": imported["import_id"], "trim_silence": "false"}).encode()))
    assert error.value.code == 400


def test_result_supports_video_seeking_and_subtitle_download(service):
    server, url, client = service
    def runner(options, **kwargs):
        directory = Path(options.output_dir) / kwargs["task_id"]
        directory.mkdir(parents=True)
        video, srt = directory / "final.mp4", directory / "subtitles.srt"
        video.write_bytes(b"0123456789")
        srt.write_text("你好", encoding="utf-8")
        return {"video": str(video), "srt": str(srt), "task_dir": str(directory)}
    server.manager.runner = runner
    imported = json.loads(client.open(Request(url + "/api/import", data=b"video",
                                             headers={"X-Filename": "source.mp4"})).read())
    job = json.loads(client.open(Request(url + "/api/jobs",
                    data=json.dumps({"import_id": imported["import_id"]}).encode())).read())
    for _ in range(100):
        status = json.loads(client.open(url + "/api/jobs/" + job["task_id"]).read())
        if status["status"] == "completed":
            break
        time.sleep(0.01)
    assert status["status"] == "completed"
    base = url + "/files/" + job["task_id"]
    with client.open(Request(base + "/video", headers={"Range": "bytes=2-5"})) as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == "bytes 2-5/10"
        assert response.read() == b"2345"
    with client.open(base + "/srt") as response:
        assert "attachment" in response.headers["Content-Disposition"]
        assert response.read().decode() == "你好"
    with pytest.raises(HTTPError) as error:
        client.open(Request(base + "/video", headers={"Range": "bytes=99-100"}))
    assert error.value.code == 416
