"""Live evaluation of the canvas against a real model endpoint (Bird S 4B), to run when the endpoint is up.

    BIRD_BASE_URL=https://… BIRD_MODEL=… BIRD_API_KEY=… .venv/bin/python -I scripts/canvas_eval.py [--out out/canvas_eval.json]

For each scripted case it runs the real web stack (HarnessBackend, the same code as the app) and records, without
judging style: whether a canvas document came out, by which path (the text format, or a trained tool call captured),
how many blocks, the parser's repairs, blocks of each kind, whether a patch kept the other blocks' ids, the time and
the tokens. The cases cover the canvas turns (create, add, shorten, targeted block, code, diagram) and two ordinary
prompts that must NOT open it. Nothing is invented: the numbers are counted from the events.

Compare the two modes the harness supports by running it twice: the default (the trained file tools withheld on a
canvas turn, the format spec in the user message) and BIRD_CANVAS_OFF=1 (ordinary turns: the trained make_slides
call, whose arguments the canvas adopts).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CASES = [
    {"id": "deck", "ask": "Fais une présentation de 5 diapositives sur le télétravail dans une PME"},
    {"id": "deck_add", "after": "deck", "ask": "ajoute une slide sur les risques"},
    {"id": "deck_short", "after": "deck_add", "ask": "plus court"},
    {"id": "deck_target", "after": "deck_short", "ask": "rends ce bloc plus percutant", "target": 2},
    {"id": "deck_theme", "after": "deck_target", "ask": "passe en thème chaleureux"},
    {"id": "doc", "ask": "Rédige une note de synthèse sur la sobriété numérique au bureau"},
    {"id": "page", "ask": "Crée une landing page pour une boulangerie de quartier"},
    {"id": "page_fix", "after": "page", "ask": "mets le bouton en vert et ajoute un pied de page"},
    {"id": "diagram", "ask": "Dessine le schéma du processus de validation d'une note de frais"},
    {"id": "ordinary_1", "ask": "Rédige un mail de relance pour la facture 2024-118", "expect_none": True},
    {"id": "ordinary_2", "ask": "Quelle est la différence entre un CDD et un CDI ?", "expect_none": True},
]


def main() -> int:
    from fastapi.testclient import TestClient

    from birds.web.entry import create_app_from_env

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/canvas_eval.json")
    args = ap.parse_args()
    if not os.environ.get("BIRD_BASE_URL"):
        print("set BIRD_BASE_URL (and BIRD_MODEL, BIRD_API_KEY): this script calls the real endpoint")
        return 2
    app = create_app_from_env()
    if os.environ.get("BIRD_CANVAS_OFF") == "1":
        app.state.server_backend.canvas = False
    results, docs = [], {}
    with TestClient(app) as client:
        for case in CASES:
            body = {"messages": [{"role": "user", "content": case["ask"]}], "lang": "fr"}
            prev = docs.get(case.get("after"))
            if prev:
                canvas = {"aid": prev["aid"], "version": prev["version"], "doc": prev["doc"]}
                if case.get("target") and prev["doc"].get("blocks"):
                    canvas["target"] = prev["doc"]["blocks"][min(case["target"], len(prev["doc"]["blocks"]) - 1)]["id"]
                body["canvas"] = canvas
            t0 = time.monotonic()
            r = client.post("/api/chat", json=body)
            seconds = time.monotonic() - t0
            events = [json.loads(f[6:]) for f in r.text.split("\n\n") if f.startswith("data: ")]
            finals = [e for e in events if e.get("type") == "canvas" and e.get("phase") == "final"]
            streams = [e for e in events if e.get("type") == "canvas" and e.get("phase") == "stream"]
            answer = next((e for e in events if e.get("type") == "answer"), {})
            usage = next((e for e in events if e.get("type") == "usage"), {})
            error = next((e for e in events if e.get("type") == "error"), None)
            doc = finals[-1]["doc"] if finals else (answer.get("canvas") or {}).get("doc")
            row = {"id": case["id"], "ask": case["ask"], "http": r.status_code, "seconds": round(seconds, 1),
                   "canvas": bool(doc), "streamed_snapshots": len(streams), "error": error,
                   "tokens": [usage.get("prompt_tokens"), usage.get("completion_tokens")],
                   "steps": [s.get("tool") for s in events if s.get("type") == "step" and s.get("status") != "running"],
                   "chat": str(answer.get("content") or "")[:300]}  # fmt: skip
            if doc:
                kinds = {}
                for b in doc.get("blocks") or []:
                    for p in b.get("parts") or []:
                        kinds[p["t"]] = kinds.get(p["t"], 0) + 1
                row.update(kind=doc.get("kind"), title=doc.get("title"), blocks=len(doc.get("blocks") or []),
                           parts=kinds, code_lang=(doc.get("code") or {}).get("lang"))  # fmt: skip
                if prev and doc.get("blocks") and prev["doc"].get("blocks"):
                    before = {b["id"] for b in prev["doc"]["blocks"]}
                    row["ids_kept"] = len(before & {b["id"] for b in doc["blocks"]})
                aid = finals[-1]["aid"] if finals else answer["canvas"]["aid"]
                version = (answer.get("canvas") or {}).get("version") or 1
                docs[case["id"]] = {"aid": aid, "version": version, "doc": doc}
            row["ok"] = (not row["canvas"]) if case.get("expect_none") else row["canvas"] and not error
            results.append(row)
            print(json.dumps({k: row[k] for k in ("id", "ok", "canvas", "blocks", "seconds") if k in row},
                             ensure_ascii=False))  # fmt: skip
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{sum(r['ok'] for r in results)}/{len(results)} ok — details in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
