"""R1 — does a document attached earlier hijack later turns? Fixed set: tests/fixtures/attach_followups.json.

Offline (default): each two-turn conversation runs through the real server and harness with a scripted model
(FakeClient) that records the prompts; turn 2 is measured on what the model is given:

* ``note``   the turn-2 user message carries « [Fichier joint : …] » (the model is told the file comes with THIS
             message, so it reads it first and answers « d'après le fichier »);
* ``plan``   the task plan asks for « lecture de … » on turn 2;
* ``nowebs`` the web tools are withdrawn on turn 2 as for a request about a document.

Live (``--live URL``, at most 2 generations per conversation): the same conversations against a Bird server,
counting turn-2 ``read_file`` steps (shown as « Lecture du document » and « D'après : … »).

    .venv/bin/python scripts/attach_context_bench.py            # offline
    .venv/bin/python scripts/attach_context_bench.py --live https://… --only 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "attach_followups.json"
sys.path.insert(0, str(ROOT))


def _sse(text: str) -> list[dict]:
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


class _Tok:
    def apply_chat_template(self, messages, tools=None, **_):
        return json.dumps({"tools": [t["function"]["name"] for t in tools or []], "messages": messages})


def _main_prompt(prompts: list[str]) -> dict:
    """The agent's own generation (it offers tools), not a router or a reflexion call."""
    for p in prompts:
        try:
            data = json.loads(p)
        except ValueError:
            continue
        if data.get("tools"):
            return data
    return {"tools": [], "messages": []}


def offline(fixture: dict) -> list[dict]:
    from fastapi.testclient import TestClient

    from birds.harness import FakeClient
    from birds.web.backends import HarnessBackend
    from birds.web.server import create_app
    from birds.web.settings import Settings

    doc = fixture["doc"]
    rows = []
    for conv in fixture["conversations"]:
        llm = FakeClient(["Réponse au premier tour.", "Réponse au second tour."] * 4)
        app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(llm, _Tok()))
        with TestClient(app) as c:
            att = [{**doc, "fresh": True}]
            ev1 = _sse(c.post("/api/chat", json={"messages": [{"role": "user", "content": conv["t1"]}],
                                                 "attachments": att}).text)  # fmt: skip
            sent1 = next(e["content"] for e in ev1 if e["type"] == "user")
            answer1 = next(e["content"] for e in ev1 if e["type"] == "answer")
            llm.prompts.clear()
            history = [{"role": "user", "content": sent1}, {"role": "assistant", "content": answer1}]
            c.post("/api/chat", json={"messages": [*history, {"role": "user", "content": conv["t2"]}],
                                      "attachments": [{**doc, "fresh": False}]})  # fmt: skip
        main = _main_prompt(llm.prompts)
        user2 = str((main["messages"] or [{}])[-1].get("content") or "")
        rows.append({
            "t2": conv["t2"],
            "about_doc": conv["about_doc"],
            "note": "[Fichier joint" in user2,
            "plan": "lecture de" in user2,
            "nowebs": "web_search" not in main["tools"],
            "readable": "read_file" in main["tools"],
        })  # fmt: skip
    return rows


def live(fixture: dict, url: str, only: int, access: str) -> list[dict]:
    import httpx

    doc = fixture["doc"]
    head = {"Content-Type": "application/json", "Accept": "text/event-stream", "X-Bird-Lang": "fr"}
    if access:
        head["X-Bird-Access"] = access
    rows = []
    with httpx.Client(timeout=180) as c:
        for conv in fixture["conversations"][: only or None]:
            r1 = c.post(f"{url.rstrip('/')}/api/chat", headers=head,
                        json={"messages": [{"role": "user", "content": conv["t1"]}], "lang": "fr",
                              "attachments": [{**doc, "fresh": True}]})  # fmt: skip
            ev1 = _sse(r1.text)
            sent1 = next((e["content"] for e in ev1 if e["type"] == "user"), conv["t1"])
            answer1 = next((e["content"] for e in ev1 if e["type"] == "answer"), "")
            history = [{"role": "user", "content": sent1}, {"role": "assistant", "content": answer1}]
            r2 = c.post(f"{url.rstrip('/')}/api/chat", headers=head,
                        json={"messages": [*history, {"role": "user", "content": conv["t2"]}], "lang": "fr",
                              "attachments": [{**doc, "fresh": False}]})  # fmt: skip
            ev2 = _sse(r2.text)
            reads = [
                e for e in ev2 if e["type"] == "step" and e.get("tool") == "read_file" and e.get("status") == "done"
            ]
            answer2 = next((e["content"] for e in ev2 if e["type"] == "answer"), "")
            rows.append({"t2": conv["t2"], "about_doc": conv["about_doc"], "read": bool(reads),
                         "mentions_file": "fichier" in answer2.lower()[:200], "answer": answer2[:160]})  # fmt: skip
    return rows


def summary(rows: list[dict], keys: list[str]) -> dict:
    out = {}
    for about in (False, True):
        part = [r for r in rows if r["about_doc"] is about]
        out["about_doc" if about else "general"] = {k: f"{sum(bool(r[k]) for r in part)}/{len(part)}" for k in keys}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", default="")
    ap.add_argument("--only", type=int, default=0)
    ap.add_argument("--access", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if a.live:
        rows, keys = live(fixture, a.live, a.only, a.access), ["read", "mentions_file"]
    else:
        rows, keys = offline(fixture), ["note", "plan", "nowebs", "readable"]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    print(json.dumps(summary(rows, keys), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
