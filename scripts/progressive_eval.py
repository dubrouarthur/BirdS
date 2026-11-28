"""Live measure of the progressive deck / document pipeline on eight fixed prompts (docs/CANVAS.md § 11).

    .venv/bin/python scripts/progressive_eval.py --url https://bird-s.vercel.app --label before \
        --out docs/measures/progressive-2026-11-28-before.json
    BIRD_BASE_URL=… .venv/bin/python scripts/progressive_eval.py --label after --out …   # an app built from env

Each prompt is ONE chat request (one « live generation » of the budget; the server may run several model calls
inside it). Counted from the events alone, nothing judged by hand: slides or sections, those with a visual (a
picture shown, a chart, key figures, a table, a timeline, steps, a comparison, cards), pictures asked / found /
relevant to their query (a query word in the picture's title, the rule of birds/canvas/images.relevant), designed
placeholders left, charts and those drawn from real data (a chart that names its provider), citations and how many
point to a listed source with an https address, progress lines, the time to the first slide shown and in total.
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
    ("deck", "Fais une présentation sur l'évolution du chômage en France depuis 2015 pour des lycéens"),
    ("deck", "Fais une présentation sur la mobilité douce en ville pour un conseil municipal"),
    ("deck", "Prépare un pitch deck pour une startup de livraison de repas à vélo"),
    ("deck", "Crée une présentation sur l'histoire et l'avenir du train de nuit en Europe"),
    ("deck", "Fais une présentation sur l'inflation en zone euro depuis 2019 pour un comité de direction"),
    ("doc", "Rédige un rapport sur la population des grandes villes françaises depuis 2010"),
    ("doc", "Rédige une note de synthèse sur le vélo en ville pour un élu"),
    ("doc", "Rédige un document de cadrage pour un projet de jardin partagé dans un quartier"),
]
FIXED = (1, 2, 3, 6, 7, 8)  # the fixed set of docs/CANVAS.md § 11: three decks, three documents
VISUAL = {"chart", "kpi", "table", "timeline", "steps", "compare", "cards", "quote", "code"}
_STOP = set("le la les un une des de du d l et en au aux pour par sur dans avec the a an of and in on for to".split())
_CITE = re.compile(r"\[\^?(\d{1,2})\]")


def words(text: str) -> set[str]:
    flat = unicodedata.normalize("NFKD", str(text or "").lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]{3,}", flat) if w not in _STOP}


def relevant(query: str, title: str) -> bool:
    want, have = words(query), words(title)
    stems = {w[:5] for w in have}
    hits = sum(1 for w in want if w in have or w[:5] in stems)
    return bool(want) and hits >= (1 if len(want) <= 2 else 2)


def texts(part: dict) -> list[str]:
    out = [str(part.get(k) or "") for k in ("text", "caption", "by")]
    for it in part.get("items") or []:
        out += [str(v) for v in (it.values() if isinstance(it, dict) else [it])]
    out += [str(c) for r in part.get("rows") or [] for c in r if isinstance(c, str)]
    for col in part.get("columns") or []:
        if isinstance(col, dict):
            out += [str(col.get("title") or "")] + [str(x) for x in col.get("items") or []]
    return out


_LEAK = re.compile(r"\[(?!\^?\d{1,2}\])[^\]\n]{2,}\]|\bImage\s*:|^:::|\{\{|<[a-z_]{3,}>|\b(?:TODO|lorem)\b", re.I | re.M)
_PROPER = re.compile(r"(?<=[\w,;:] )[A-ZÉÈÀÂÎ][\wÀ-ÿ'-]{2,}")


def content(body: list[dict]) -> dict:
    """Content specificity, counted: words per slide or section, the share of points and sentences that carry a
    figure or a proper name (a named fact), those citing a source, and notation leaks (« [Paris bike cargo] »,
    « Image : », a ``:::`` left as text, a ``<placeholder>``)."""
    units, words_n, leaks = [], [], 0
    for b in body:
        n = 0
        for p in b.get("parts") or []:
            if p.get("t") in ("image", "chart"):
                continue
            for t in texts(p):
                leaks += len(_LEAK.findall(t))
                n += len(t.split())
                units += [u for u in re.split(r"(?<=[.!?])\s+", t) if len(u.split()) >= 3]
        words_n.append(n)
    specific = [u for u in units if re.search(r"\d", _CITE.sub("", u)) or _PROPER.search(u)]
    return {"words_per_block": round(sum(words_n) / len(words_n), 1) if words_n else 0, "units": len(units),
            "specific_share": round(len(specific) / len(units), 2) if units else 0.0,
            "units_cited": sum(1 for u in units if _CITE.search(u)), "leaks": leaks}  # fmt: skip


def measure(doc: dict, media: list[dict]) -> dict:
    blocks = doc.get("blocks") or []
    shown = {m["id"] for m in media}
    body = [b for b in blocks if not re.match(r"(?i)^\s*(sources?|références?|references?)\s*$", b.get("title") or "")]
    with_visual = 0
    for b in body:
        parts = b.get("parts") or []
        if any(p.get("t") in VISUAL or (p.get("t") == "image" and p.get("media") in shown) for p in parts):
            with_visual += 1
    images = [p for b in blocks for p in b.get("parts") or [] if p.get("t") == "image"]
    cover = doc.get("cover") or {}
    asked = len(images) + (1 if cover.get("query") else 0)
    charts = [p for b in blocks for p in b.get("parts") or [] if p.get("t") == "chart"]
    real = [c for c in charts if str(c.get("source") or "").strip()]
    listed = {}
    for s in doc.get("sources") or []:
        listed[str(s.get("n"))] = str(s.get("url") or "")
    for b in blocks:  # a deck's « Sources » slide: « [1] Title — https://… »
        if b in body:
            continue
        for p in b.get("parts") or []:
            for it in p.get("items") or []:
                m = re.match(r"\s*\[(\d{1,2})\].*?(https://\S+)", str(it))
                if m:
                    listed.setdefault(m.group(1), m.group(2))
    for f in doc.get("footnotes") or []:
        m = re.search(r"https?://\S+", str(f.get("text") or ""))
        listed.setdefault(str(f.get("n")), m.group(0) if m else "")
    cited = set()
    for b in body:
        for p in b.get("parts") or []:
            for t in texts(p):
                cited.update(_CITE.findall(t))
    valid = sum(1 for n in cited if listed.get(n, "").startswith("https://"))
    placeholders = sum(1 for p in images if not p.get("media") or p.get("media") not in shown)
    leaks_q = sum(1 for p in images if re.search(r"[\[\]{}<>]|statisti|chart|graph", str(p.get("query") or ""), re.I))
    return {
        "kind": doc.get("kind"), "title": doc.get("title"), "blocks": len(blocks), "body": len(body),
        "with_visual": with_visual, "images_asked": asked, "images_found": len(media),
        "images_relevant": sum(relevant(m.get("query") or "", m.get("title") or "") for m in media),
        "placeholders": placeholders, "charts": len(charts), "charts_real": len(real),
        "chart_sources": [str(c.get("source") or "")[:80] for c in real],
        "cited": len(cited), "cited_valid": valid, "sources_listed": len(listed),
        "image_titles": [m.get("title") for m in media], "image_queries": [m.get("query") for m in media],
        "placeholder_queries": [p.get("query") for p in images if not p.get("media") or p.get("media") not in shown],
        "query_leaks": leaks_q, **content(body),
    }  # fmt: skip


def events_of(text: str) -> list[dict]:
    out = []
    for f in text.split("\n\n"):
        f = f.strip()
        if f.startswith("data: "):
            try:
                out.append(json.loads(f[6:]))
            except ValueError:
                pass
    return out


def run_one(post, n: int, kind: str, ask: str, label: str, reflexion: str) -> dict:
    t0 = time.monotonic()
    first = None
    events: list[dict] = []
    for ev, at in post({"messages": [{"role": "user", "content": ask}], "lang": "fr", "reflexion": reflexion}):
        events.append(ev)
        if first is None and ev.get("type") == "canvas" and ev.get("phase") in ("stream", "final") and ev.get("doc"):
            if any(b.get("parts") for b in ev["doc"].get("blocks") or []):
                first = at - t0
    seconds = time.monotonic() - t0
    finals = [e for e in events if e.get("type") == "canvas" and e.get("phase") == "final"]
    media = [m for e in events if e.get("type") == "canvas_media" for m in e.get("media") or []]
    answer = next((e for e in events if e.get("type") == "answer"), {})
    progress = [ln.get("text") for e in events if e.get("type") == "canvas_progress" for ln in e.get("lines") or []]
    doc = finals[-1]["doc"] if finals else (answer.get("canvas") or {}).get("doc")
    row = {"n": n, "ask": ask, "want": kind, "label": label, "reflexion": reflexion, "seconds": round(seconds, 1),
           "first_slide_s": round(first, 1) if first is not None else None, "canvas": bool(doc),
           "snapshots": sum(1 for e in events if e.get("type") == "canvas" and e.get("phase") == "stream"),
           "progress": list(dict.fromkeys(progress)), "error": next((e.get("code") for e in events
                                                                     if e.get("type") == "error"), None),
           "chat": str(answer.get("content") or "")[:300]}  # fmt: skip
    if doc:
        row.update(measure(doc, media))
        row["doc"] = doc
    return row


def http_post(url: str):
    import httpx

    def post(body: dict):
        headers = {"Origin": url, "Content-Type": "application/json", "Accept": "text/event-stream"}
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)) as c:
            with c.stream("POST", url.rstrip("/") + "/api/chat", json=body, headers=headers) as r:
                buf = ""
                for chunk in r.iter_text():
                    buf += chunk
                    while "\n\n" in buf:
                        frame, buf = buf.split("\n\n", 1)
                        for ev in events_of(frame + "\n\n"):
                            yield ev, time.monotonic()

    return post


def app_post():
    from fastapi.testclient import TestClient

    from birds.web.entry import create_app_from_env

    client = TestClient(create_app_from_env())

    def post(body: dict):
        with client.stream("POST", "/api/chat", json=body) as r:
            buf = ""
            for chunk in r.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    frame, buf = buf.split("\n\n", 1)
                    for ev in events_of(frame + "\n\n"):
                        yield ev, time.monotonic()

    return post


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="a deployed Bird (https://…); else an app built from the environment")
    ap.add_argument("--label", default="after")
    ap.add_argument("--reflexion", default="faucon")
    ap.add_argument("--out", default="out/progressive_eval.json")
    ap.add_argument("--only", default=",".join(map(str, FIXED)), help="comma-separated prompt numbers (1-8); "
                    "default: the fixed set")  # fmt: skip
    args = ap.parse_args()
    if not args.url and not os.environ.get("BIRD_BASE_URL"):
        print("give --url or set BIRD_BASE_URL: this script measures the real model")
        return 2
    post = http_post(args.url) if args.url else app_post()
    only = {int(x) for x in args.only.split(",") if x}
    rows = []
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for n, (kind, ask) in enumerate(PROMPTS, 1):
        if only and n not in only:
            continue
        try:
            row = run_one(post, n, kind, ask, args.label, args.reflexion)
        except Exception as e:  # noqa: BLE001 - a failed request is a row, not a crash
            row = {"n": n, "ask": ask, "label": args.label, "error": f"{type(e).__name__}: {e}"[:200]}
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("n", "canvas", "kind", "body", "with_visual", "images_asked",
                                                  "images_found", "images_relevant", "placeholders", "charts",
                                                  "charts_real", "cited", "cited_valid", "words_per_block", "specific_share",
                                                  "leaks", "query_leaks", "first_slide_s", "seconds",
                                                  "error")}, ensure_ascii=False), flush=True)  # fmt: skip
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
