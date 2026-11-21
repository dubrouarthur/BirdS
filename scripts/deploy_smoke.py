"""Smoke test of the Vercel entrypoint, runnable with ANY interpreter that has requirements.txt installed.

    python scripts/deploy_smoke.py            # prints one JSON line; exit code 0 when everything passed

It imports ``app`` exactly as Vercel does (module ``app``, variable ``app``, from the repository root), refuses
to let transformers / torch / datasets / tokenizers be imported, then exercises the demo, the stateless confirm
flow across two app instances, and a configured model endpoint (prompt rendering without transformers).
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("transformers", "torch", "datasets", "tokenizers", "huggingface_hub", "peft", "accelerate", "numpy")


class _Blocker:
    """Fails any import of a heavy package: the deployed function must never need one."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in HEAVY:
            raise ImportError(f"{name} must not be imported by the deployed app")
        return None


def events(response):
    return [json.loads(f[6:]) for f in response.text.split("\n\n") if f.startswith("data: ")]


def main() -> int:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    sys.meta_path.insert(0, _Blocker())
    for key in [k for k in os.environ if k.startswith("BIRD_")]:
        del os.environ[key]
    os.environ["BIRD_SIGNING_SECRET"] = "smoke"
    os.environ["BIRD_DEMO_DELAY"] = "0"

    t0 = time.perf_counter()
    entry = importlib.import_module("app")  # what Vercel loads: app.py -> `app`
    import_seconds = time.perf_counter() - t0
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    assert isinstance(entry.app, FastAPI)
    checks = {}
    body = {"messages": [{"role": "user", "content": "Prépare un mail de réponse à Camille"}]}
    with TestClient(entry.app) as client:
        health = client.get("/api/health").json()
        checks["demo_out_of_the_box"] = health["backend"] == "demo" and health["modes"]["user"] is True
        index = client.get("/")
        checks["index_and_csp"] = (
            index.status_code == 200 and "default-src 'none'" in index.headers["content-security-policy"]
        )
        checks["static"] = all(client.get(f"/static/{n}").status_code == 200 for n in ("app.js", "app.css", "bird.svg"))
        first = events(client.post("/api/chat", json=body))
        token = next(e for e in first if e["type"] == "confirm")["token"]
        slides = events(
            client.post("/api/chat", json={"messages": [{"role": "user", "content": "Prépare des diapositives"}]})
        )
        file = next(e for e in slides if e["type"] == "answer")["files"][0]
        checks["inline_pptx"] = file["name"].endswith(".pptx") and file["size"] > 1000 and bool(file["data"])
    # a second, independent app instance (another serverless instance) resumes the paused run
    from birds.web.entry import create_app_from_env

    with TestClient(create_app_from_env()) as other:
        second = events(other.post("/api/chat", json={**body, "approved": [token]}))
        checks["stateless_confirm"] = any(e["type"] == "answer" and e["draft_email"] for e in second)
    # a configured endpoint: the prompt is rendered with the vendored template, no tokenizer download
    os.environ["BIRD_BASE_URL"] = "https://bird.example.invalid"
    os.environ["BIRD_MODEL"] = "bird-4b"
    os.environ["BIRD_API_KEY"] = "not-a-real-key"
    with TestClient(create_app_from_env()) as real:
        health = real.get("/api/health").json()
        checks["server_mode"] = (
            health["backend"] == "completions" and health["model"] == "bird-4b" and health["modes"]["user"] is False
        )
    from birds.harness.template import TemplateTokenizer
    from birds.render import prompt
    from birds.tools import BIRD_TOOLS

    rendered = prompt(TemplateTokenizer(), [{"role": "user", "content": "Bonjour"}], BIRD_TOOLS, False)
    checks["prompt_rendering"] = "<|im_start|>user\nBonjour<|im_end|>" in rendered and "web_search" in rendered
    loaded = sorted(m for m in HEAVY if m in sys.modules)
    checks["no_heavy_module"] = not loaded
    report = {
        "ok": all(checks.values()),
        "python": sys.version.split()[0],
        "import_seconds": round(import_seconds, 3),
        "modules_loaded": len(sys.modules),
        "heavy_loaded": loaded,
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
