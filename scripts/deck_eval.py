"""Live measure of canvas decks on six fixed prompts (real endpoint, real web stack, real picture search).

    BIRD_BASE_URL=https://…/v1 BIRD_MODEL=adubrou/Bird-S-4B .venv/bin/python scripts/deck_eval.py \
        --root <checkout to measure> --label after --out docs/measures/deck-eval-<date>-after.json

``--root`` is the code measured (the base checkout for « before », this one for « after »): the same six prompts,
the same counting. For each deck: slides, the layout each slide is DRAWN with (the base's canvas.js rule when the
checkout has no birds/canvas/layouts.py, else layouts.pick), distinct layouts, pictures asked / found / relevant to
their query (a query word in the picture's title), the parser's repairs, seconds and completion tokens. Nothing is
judged by hand; nothing is invented.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

PROMPTS = [
    "Fais une présentation sur la mobilité douce en ville pour un conseil municipal",
    "Prépare un pitch deck de 6 slides pour une startup de livraison de repas à vélo",
    "Fais une présentation pour former les nouveaux arrivants à la cybersécurité au bureau",
    "Fais des slides sur le bilan 2025 de notre club de sport : 320 adhérents (+12 %), budget 85 000 €, 14 bénévoles",
    "Fais une présentation qui compare le télétravail et le travail au bureau pour le comité de direction",
    "Crée une présentation sur l'histoire et l'avenir du train de nuit en Europe",
]
_STOP = set("le la les un une des de du d l et en au aux pour par sur dans avec the a an of and in on for to".split())


def words(text: str) -> set[str]:
    flat = unicodedata.normalize("NFKD", str(text or "").lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]{3,}", flat) if w not in _STOP}


def relevant(query: str, title: str) -> bool:
    want, have = words(query), words(title)
    stems = {w[:5] for w in have}
    hits = sum(1 for w in want if w in have or w[:5] in stems)
    return bool(want) and hits >= (1 if len(want) <= 2 else 2)  # the rule of birds/canvas/images.relevant


def base_layout(b: dict) -> str:
    """The base canvas.js rule (before this work): the main part's type, else picture / statement / list."""
    parts = b.get("parts") or []
    for t in ("chart", "table", "timeline", "kpi", "quote", "code"):
        if any(p.get("t") == t for p in parts):
            return t
    img = any(p.get("t") == "image" for p in parts)
    text = [p for p in parts if p.get("t") in ("list", "text", "callout", "heading")]
    if img and not text:
        return "image"
    if img:
        return "image-side"
    if len(text) == 1 and text[0].get("t") == "text" and len(text[0].get("text") or "") <= 160:
        return "statement"
    return "list"


def replay(path: Path) -> int:
    """The raw answers of a live measure, parsed again by this checkout (a parser repair measured on the same
    generations): layouts, cover query and repairs. Rows without a raw answer are printed as they were."""
    from birds.canvas import dsl, layouts, turn

    for row in json.loads(path.read_text("utf-8")):
        raw = row.get("raw") or ""
        if not raw:
            print(json.dumps({"n": row["n"], "path": row.get("path"), "layouts": row.get("layouts")}, ensure_ascii=False))
            continue
        repairs: list[str] = []
        before, content, _ = dsl.split_answer(raw)
        doc = dsl.parse(content, "deck", "fr", repairs)
        turn.finish_doc(doc, "deck", row["ask"], "fr")
        blocks = doc["blocks"]
        drawn = ["cover"] + [layouts.pick(b, j, len(blocks)) for j, b in enumerate(blocks)]
        print(json.dumps({"n": row["n"], "slides": len(drawn), "distinct": len(set(drawn)), "layouts": drawn,
                          "cover": (doc.get("cover") or {}).get("query"), "repairs": len(repairs)},
                         ensure_ascii=False))  # fmt: skip
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--label", default="after")
    ap.add_argument("--out", default="out/deck_eval.json")
    ap.add_argument("--only", default="", help="comma-separated prompt numbers (1-6)")
    ap.add_argument("--replay", default="", help="re-parse the raw answers of a measure file (no generation)")
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.root).resolve()))
    if args.replay:
        return replay(Path(args.replay))
    if not os.environ.get("BIRD_BASE_URL"):
        print("set BIRD_BASE_URL (and BIRD_MODEL): this script calls the real endpoint")
        return 2
    from fastapi.testclient import TestClient

    from birds.web import canvas_web
    from birds.web.entry import create_app_from_env

    try:
        from birds.canvas import layouts as lay
    except ImportError:
        lay = None
    seen: list[dict] = []
    real = canvas_web.run_canvas

    def spy(*a, **kw):
        run = real(*a, **kw)
        seen.append(dict(getattr(run, "canvas", None) or {}))
        return run

    canvas_web.run_canvas = spy
    app = create_app_from_env()
    only = {int(x) for x in args.only.split(",") if x}
    rows = []
    with TestClient(app) as client:
        for k, ask in enumerate(PROMPTS, 1):
            if only and k not in only:
                continue
            seen.clear()
            t0 = time.monotonic()
            r = client.post("/api/chat", json={"messages": [{"role": "user", "content": ask}], "lang": "fr"})
            seconds = time.monotonic() - t0
            events = [json.loads(f[6:]) for f in r.text.split("\n\n") if f.startswith("data: ")]
            finals = [e for e in events if e.get("type") == "canvas" and e.get("phase") == "final"]
            streams = [e for e in events if e.get("type") == "canvas" and e.get("phase") == "stream"]
            usage = next((e for e in events if e.get("type") == "usage"), {})
            media = [m for e in events if e.get("type") == "canvas_media" for m in e.get("media") or []]
            answer = next((e for e in events if e.get("type") == "answer"), {})
            adopted = (answer.get("canvas") or {}).get("doc")
            doc = finals[-1]["doc"] if finals else adopted
            path = "canvas_text" if finals else "file_tool_adopted" if adopted else "chat_only"
            row = {"n": k, "ask": ask, "label": args.label, "seconds": round(seconds, 1), "canvas": bool(doc),
                   "snapshots": len(streams), "completion_tokens": usage.get("completion_tokens"),
                   "repairs": (seen[-1].get("repairs") if seen else []) or [],
                   "raw": ((seen[-1].get("raw") if seen else "") or "")[:6000], "path": path,
                   "steps": [e.get("tool") for e in events if e.get("type") == "step" and e.get("status") != "running"],
                   "chat": str(answer.get("content") or "")[:400]}  # fmt: skip
            if doc:
                blocks = doc.get("blocks") or []
                drawn = [lay.pick(b, j, len(blocks)) for j, b in enumerate(blocks)] if lay else [base_layout(b)
                                                                                               for b in blocks]  # fmt: skip
                asked = [p for b in blocks for p in b.get("parts") or [] if p.get("t") == "image"]
                cover = doc.get("cover") or {}
                queries = {m["id"]: m.get("query") or "" for m in media}
                found = [m for m in media]
                row.update(
                    slides=len(blocks) + 1, layouts=["cover"] + drawn, distinct=len(set(drawn)) + 1,
                    parts=sorted({p["t"] for b in blocks for p in b.get("parts") or []}),
                    images_asked=len(asked) + (1 if cover.get("query") else 0), images_found=len(found),
                    images_relevant=sum(relevant(queries.get(m["id"], ""), m.get("title") or "") for m in found),
                    image_credits=[m.get("credit") for m in found], image_titles=[m.get("title") for m in found],
                    image_queries=[m.get("query") for m in found], cover_query=cover.get("query") or "",
                    title=doc.get("title"),
                )  # fmt: skip
            rows.append(row)
            print(json.dumps({x: row.get(x) for x in ("n", "path", "canvas", "slides", "distinct", "layouts", "images_asked",
                                                      "images_found", "images_relevant", "seconds")},
                             ensure_ascii=False))  # fmt: skip
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
