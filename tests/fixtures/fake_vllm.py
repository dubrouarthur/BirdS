"""A tiny OpenAI-compatible server standing in for vLLM in tests (stdlib only, loopback only).

  python tests/fixtures/fake_vllm.py --port 8399 [--model adubrou/Bird-S-4B] [--structured]

GET /v1/models lists one model; POST /v1/completions and /v1/chat/completions stream (SSE) or return one JSON answer
with a fixed French sentence and usage counts. With --structured, a request carrying ``structured_outputs`` gets the
router probe's expected JSON (as vLLM >= 0.10 would enforce it); without, the fields are ignored, like an engine
that does not know them.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = "Bonjour ! Ici Bird, qui tourne sur votre machine : vos messages restent chez vous."


def make_handler(model: str, structured: bool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _json(self, status: int, obj: dict) -> None:
            data = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip("/") == "/v1/models":
                return self._json(200, {"object": "list", "data": [{"id": model, "object": "model"}]})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path not in ("/v1/completions", "/v1/chat/completions"):
                return self._json(404, {"error": "not found"})
            if body.get("model") != model:
                return self._json(404, {"error": {"message": f"The model `{body.get('model')}` does not exist."}})
            text = ANSWER
            if structured and "structured_outputs" in body:
                schema = body["structured_outputs"].get("json") or {}
                enum = (((schema.get("properties") or {}).get("probe") or {}).get("enum")) or []
                text = json.dumps({"probe": enum[0]}) if enum else json.dumps({"modules": []})
            text = text[: max(1, int(body.get("max_tokens") or 64)) * 4]
            usage = {"prompt_tokens": 42, "completion_tokens": max(1, len(text) // 4), "total_tokens": 0}
            chat = self.path.endswith("/chat/completions")
            if not body.get("stream"):
                choice = {"message": {"role": "assistant", "content": text}} if chat else {"text": text}
                return self._json(200, {"choices": [{"index": 0, **choice, "finish_reason": "stop"}], "usage": usage})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i in range(0, len(text), 12):
                piece = text[i : i + 12]
                choice = {"delta": {"content": piece}} if chat else {"text": piece}
                self.wfile.write(f"data: {json.dumps({'choices': [{'index': 0, **choice}]})}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    return Handler


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8399)
    p.add_argument("--model", default="adubrou/Bird-S-4B")
    p.add_argument("--structured", action="store_true")
    a = p.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.model, a.structured)).serve_forever()


if __name__ == "__main__":
    main()
