"""Live evaluation of the canvas in code mode (a page, an app, a component), on six fixed requests.

    BIRD_BASE_URL=https://… BIRD_MODEL=… BIRD_API_KEY=… BIRD_RATE_LIMIT=0 \\
      .venv/bin/python scripts/code_eval.py --frame http://127.0.0.1:9251/ --label after --out out/code_eval.json

Runs the real web stack (the same code as the app) against the real endpoint, then runs every page the canvas got in
the real preview frame of a running Bird server (``--frame``: ``scripts/serve.py --demo``) with
``scripts/code_check.cjs``: renders, JavaScript errors (load and one click on each button), resources the frame's CSP
blocked, horizontal overflow at 390 / 768 / 1280 px. When a page has an error, the fix loop sends what « Corriger
avec Bird » sends (the first error, the canvas document) once, and checks the new version the same way. Each chat
turn counts as one generation of the budget (``--max-gens``). Nothing is judged by eye.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]

CASES = [
    {"id": "landing", "ask": "Crée une landing page pour une boulangerie de quartier"},
    {"id": "calc", "ask": "Code une calculatrice simple en HTML et JavaScript"},
    {"id": "game", "ask": "Crée un mini-jeu : attraper un carré qui bouge, avec un score et un chrono de 30 secondes"},
    {
        "id": "card",
        "ask": "Fais un composant HTML et CSS de carte de profil, avec photo ronde, nom, rôle et deux boutons",
    },
    {"id": "pomodoro", "ask": "Crée une page web avec un minuteur pomodoro : démarrer, pause, réinitialiser"},
    {"id": "todo", "ask": "Fais une todo list en HTML, CSS et JavaScript : ajouter, cocher, supprimer une tâche"},
]
FIX = "Corrige cette erreur de l'aperçu : {err}"  # canvas-i18n.js « cv.fix.msg »


def chat(client, ask: str, canvas: dict | None = None) -> dict:
    body = {"messages": [{"role": "user", "content": ask}], "lang": "fr"}
    if canvas:
        body["canvas"] = canvas
    t0 = time.monotonic()
    r = client.post("/api/chat", json=body)
    events = [json.loads(f[6:]) for f in r.text.split("\n\n") if f.startswith("data: ")]
    finals = [e for e in events if e.get("type") == "canvas" and e.get("phase") == "final"]
    streams = [e for e in events if e.get("type") == "canvas" and e.get("phase") == "stream"]
    answer = next((e for e in events if e.get("type") == "answer"), {})
    usage = next((e for e in events if e.get("type") == "usage"), {})
    return {
        "seconds": round(time.monotonic() - t0, 1),
        "doc": finals[-1]["doc"] if finals else None,
        "aid": finals[-1]["aid"] if finals else None,
        "version": (answer.get("canvas") or {}).get("version") or 1,
        "snapshots": len(streams),
        "files_seen": sorted(
            {
                f.get("name")
                for e in streams
                for f in ((e.get("doc") or {}).get("code") or {}).get("files") or []
                if isinstance(f, dict)
            }
        ),
        "chat": str(answer.get("content") or "")[:400],
        "tokens": [usage.get("prompt_tokens"), usage.get("completion_tokens")],
        "steps": [s.get("tool") for s in events if s.get("type") == "step" and s.get("status") != "running"],
        "error": next((e for e in events if e.get("type") == "error"), None),
    }


def check(frame: str, rows: list[dict]) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(rows, f)
        name = f.name
    try:
        out = subprocess.run(["node", str(ROOT / "scripts" / "code_check.cjs"), frame, name], capture_output=True,
                             text=True, timeout=300, check=True).stdout  # fmt: skip
    finally:
        os.unlink(name)
    return {r["id"]: r for r in json.loads(out)}


def files_of(doc: dict | None) -> list[str]:
    c = (doc or {}).get("code") or {}
    return [f.get("name") for f in c.get("files") or []] or ([c.get("lang")] if c.get("text") else [])


def main() -> int:
    from fastapi.testclient import TestClient

    from birds.web.entry import create_app_from_env

    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True, help="a running Bird server whose /canvas/frame runs the pages")
    ap.add_argument("--out", default="out/code_eval.json")
    ap.add_argument("--label", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--max-gens", type=int, default=12)
    ap.add_argument("--no-fix", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("BIRD_BASE_URL"):
        print("set BIRD_BASE_URL (and BIRD_MODEL, BIRD_API_KEY): this script calls the real endpoint")
        return 2
    only = {x for x in a.only.split(",") if x}
    gens = 0
    results = []
    app = create_app_from_env()
    with TestClient(app) as client:
        for case in CASES:
            if only and case["id"] not in only:
                continue
            if gens >= a.max_gens:
                print("generation budget reached")
                break
            gens += 1
            got = chat(client, case["ask"])
            row = {"id": case["id"], "ask": case["ask"], "label": a.label, **{k: got[k] for k in got if k != "doc"},
                   "canvas": bool(got["doc"]), "files": files_of(got["doc"])}  # fmt: skip
            if got["doc"]:
                row["code"] = got["doc"].get("code")
                rep = check(a.frame, [{"id": case["id"], "doc": got["doc"]}]).get(case["id"], {})
                row["check"] = rep
                errs = rep.get("errors") or []
                if errs and not a.no_fix and gens < a.max_gens:
                    gens += 1
                    canvas = {"aid": got["aid"], "version": got["version"], "doc": got["doc"], "open": True}
                    fx = chat(client, FIX.format(err=errs[0][:300]), canvas)
                    row["fix"] = {k: fx[k] for k in fx if k != "doc"} | {"canvas": bool(fx["doc"]),
                                                                       "files": files_of(fx["doc"])}  # fmt: skip
                    if fx["doc"]:
                        row["fix"]["code"] = fx["doc"].get("code")
                        row["fix"]["check"] = check(a.frame, [{"id": case["id"], "doc": fx["doc"]}]).get(case["id"])
            results.append(row)
            c = row.get("check") or {}
            print(json.dumps({"id": row["id"], "canvas": row["canvas"], "files": row["files"],
                              "renders": c.get("renders"), "errors": len(c.get("errors") or []),
                              "blocked": c.get("blocked"), "responsive": c.get("responsive"),
                              "fixed": (None if "fix" not in row else not ((row["fix"].get("check") or {}).get("errors")
                                                                          or not row["fix"]["canvas"])),
                              "s": row["seconds"]}, ensure_ascii=False))  # fmt: skip
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{gens} generations — details in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
