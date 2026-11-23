"""本地 OpenAI 兼容 mock 服务：模拟 ChatGPT 的 /v1/chat/completions 响应。

仅用于验证 VideoCut 的 AI 文案重组链路，不产生任何真实 API 调用或费用。
"""
import json
import http.server
from datetime import datetime

PORT = 8765
LOG = r"C:\Users\Lenovo\AppData\Local\Temp\videocut_demo\mock_requests.log"

CONTENT = """```json
{
  "analysis": "演示口播含重复词与语气词，节奏偏松散。",
  "plans": [
    {
      "name": "A-轻度优化",
      "description": "仅删除明显重复的口误",
      "deletions": [
        {"text": "这个这个", "reason": "重复口误，语义无增益"}
      ],
      "result_preview": "大家好，今天给大家介绍一下智能口播剪辑工具……"
    },
    {
      "name": "B-深度优化",
      "description": "再删掉结尾套话和多余语气词",
      "deletions": [
        {"text": "非常方便", "reason": "结尾套话"},
        {"text": "呃", "reason": "语气词"}
      ],
      "result_preview": "工具可自动识别重复词和长静音并剪掉，还能生成字幕。"
    }
  ]
}
```"""


class Handler(http.server.BaseHTTPRequestHandler):
    def _reply(self, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._reply({"object": "list", "data": [{"id": "gpt-4o", "object": "model"}]})

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            model = data.get("model", "?")
            messages = data.get("messages", [])
            preview = messages[-1].get("content", "")[:100] if messages else ""
        except Exception:
            model, preview = "?", body[:100].decode("utf-8", "replace")

        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} path={self.path} model={model} "
                    f"prompt_head={preview!r}\n")

        self._reply({
            "id": "chatcmpl-videocut-mock",
            "object": "chat.completion",
            "created": 1730000000,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": CONTENT},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 220, "completion_tokens": 160, "total_tokens": 380},
        })

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"mock ChatGPT 服务已启动: http://127.0.0.1:{PORT}/v1", flush=True)
    server.serve_forever()
