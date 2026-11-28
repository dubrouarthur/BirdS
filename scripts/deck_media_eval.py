"""Live measure of pictures and charts in canvas decks: eight fixed prompts, real endpoint, real picture search.

    BIRD_BASE_URL=https://…/v1 BIRD_MODEL=adubrou/Bird-S-4B BIRD_PIN_DNS=0 \
        .venv/bin/python scripts/deck_media_eval.py --label after --out docs/measures/deck-media-<date>-after.json

For each deck, counted from what the harness and the files really hold (nothing judged by hand here):
* pictures: asked (cover + image parts), found (a picture reached the browser), with a licence AND a credit, that
  decode (the bytes the panel shows: Pillow opens them), relevant to their query (birds/canvas/images.relevant),
  in the .pptx (pictures of the exported file, made from the browser's bytes as the app does), seconds spent;
* charts: chart parts, their values found in the request or a tool result of the turn (« provenance »: a value
  the model made up counts as unsourced), native charts in the .pptx.
``--thumbs DIR`` writes each found picture small, to be looked at (relevance by eye is noted in docs/CANVAS.md).
``--replay FILE`` re-resolves the pictures of a measure's raw answers with this checkout (no generation): the
same model queries, today's search.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROMPTS = [
    "Fais une présentation sur la mobilité douce en ville pour un conseil municipal",
    "Prépare un pitch deck de 6 slides pour une startup de livraison de repas à vélo",
    "Crée une présentation sur l'histoire et l'avenir du train de nuit en Europe",
    "Fais une présentation pour promouvoir le tourisme en Bretagne auprès d'une agence de voyage",
    "Fais une présentation pour des collégiens sur les abeilles et la pollinisation",
    "Fais une présentation du bilan de notre club de sport : adhérents 250 en 2023, 286 en 2024 et 320 en 2025 ; "
    "budget 85 000 € ; 14 bénévoles",
    "Prépare 5 slides pour le comité : chiffre d'affaires T1 120 k€, T2 135 k€, T3 150 k€, T4 170 k€, objectif "
    "2026 : 200 k€",
    "Fais une présentation sur la forêt française et son rôle face au changement climatique",
]


def numbers(text: str) -> set[float]:
    from birds.canvas import figures

    return figures.numbers(text)


def pptx_counts(data: bytes) -> tuple[int, int]:
    """(pictures, native charts) of a .pptx."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        charts = sum(1 for n in names if re.match(r"ppt/charts/chart\d+\.xml$", n))
        pics = 0
        for n in names:
            if re.match(r"ppt/slides/slide\d+\.xml$", n):
                pics += z.read(n).decode("utf-8", "replace").count("<p:pic>")
    return pics, charts


def measure_doc(doc: dict, media: list[dict], ask: str, tool_text: str, thumbs: Path | None, tag: str) -> dict:
    from PIL import Image

    from birds.canvas import dsl, export, images

    blocks = doc.get("blocks") or []
    asked = [p for b in blocks for p in b.get("parts") or [] if p.get("t") == "image"]
    cover = doc.get("cover") or {}
    n_asked = len(asked) + (1 if cover.get("query") else 0)
    decoded = credited = rel = 0
    titles = []
    for m in media:
        ok = False
        try:
            Image.open(io.BytesIO(base64.b64decode(m["data"]))).load()
            ok = True
        except Exception:  # noqa: BLE001 - counted as not loading
            pass
        decoded += ok
        credited += bool(m.get("licence") and m.get("credit"))
        r = images.relevant(m.get("query") or "", m.get("title") or "")
        rel += r
        titles.append(f"{m.get('query')} -> {m.get('title')} [{m.get('licence')}] {'ok' if r else 'OFF'}")
        if thumbs and ok:
            thumbs.mkdir(parents=True, exist_ok=True)
            im = Image.open(io.BytesIO(base64.b64decode(m["data"]))).convert("RGB")
            im.thumbnail((360, 240))
            im.save(thumbs / f"{tag}-{m['id']}.jpg", "JPEG", quality=80)
    charts = [p for b in blocks for p in b.get("parts") or [] if p.get("t") == "chart"]
    said = numbers(ask) | numbers(tool_text)
    values = [v for c in charts for r in c.get("rows") or [] for v in r[1:] if isinstance(v, (int, float))]
    sourced = sum(1 for v in values if float(v) in said)
    pics = nch = 0
    try:
        valid = dsl.validate(doc)
        data, _, _ = export.export(valid, "pptx", {m["id"]: m["data"] for m in media})
        pics, nch = pptx_counts(data)
    except Exception as e:  # noqa: BLE001 - reported
        titles.append(f"pptx failed: {e}")
    return {"slides": len(blocks) + 1, "images_asked": n_asked, "images_found": len(media), "images_decode": decoded,
            "images_credited": credited, "images_relevant": rel, "pptx_pictures": pics, "charts": len(charts),
            "chart_values": len(values), "chart_values_sourced": sourced, "pptx_charts": nch, "images": titles,
            "cover_query": cover.get("query") or "",
            "part_queries": [p.get("query") for p in asked]}  # fmt: skip


class _Remote:
    """A deployed Bird (``--url``, e.g. production): the same /api/chat call over HTTP."""

    def __init__(self, url: str):
        import httpx

        self.url, self.http = url.rstrip("/"), httpx.Client(timeout=300.0)

    def post(self, path: str, json: dict):
        return self.http.post(self.url + path, json=json)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.http.close()


def live(args) -> list[dict]:
    seen: list[dict] = []
    if args.url:
        client_cm = _Remote(args.url)
    else:
        from fastapi.testclient import TestClient

        from birds.web import canvas_web
        from birds.web.entry import create_app_from_env

        real = canvas_web.run_canvas

        def spy(*a, **kw):
            run = real(*a, **kw)
            seen.append(dict(getattr(run, "canvas", None) or {}))
            return run

        canvas_web.run_canvas = spy
        client_cm = TestClient(create_app_from_env())
    only = {int(x) for x in args.only.split(",") if x}
    rows = []
    with client_cm as client:
        for k, ask in enumerate(PROMPTS, 1):
            if only and k not in only:
                continue
            seen.clear()
            t0 = time.monotonic()
            # Mode Agent off: the product decision of 28/11/2026 (no automatic team); a deck is the canvas's
            r = client.post("/api/chat", json={"messages": [{"role": "user", "content": ask}], "lang": "fr",
                                               "agent": "off"})
            seconds = time.monotonic() - t0
            events = [json.loads(f[6:]) for f in r.text.split("\n\n") if f.startswith("data: ")]
            finals = [e for e in events if e.get("type") == "canvas" and e.get("phase") == "final"]
            media = [m for e in events if e.get("type") == "canvas_media" for m in e.get("media") or []]
            answer = next((e for e in events if e.get("type") == "answer"), {})
            adopted = (answer.get("canvas") or {}).get("doc")
            doc = finals[-1]["doc"] if finals else adopted
            tools = " ".join(json.dumps(e.get("result") or e.get("output") or "", ensure_ascii=False)
                             for e in events if e.get("type") == "step")  # fmt: skip
            raw = ((seen[-1].get("raw") if seen else "") or "") or (dsl_text(doc) if doc else "")
            row = {"n": k, "ask": ask, "label": args.label, "seconds": round(seconds, 1),
                   "path": "canvas" if finals else "adopted" if adopted else "chat", "where": args.url or "local",
                   "raw": raw[:6000],
                   "chat": str(answer.get("content") or "")[:300]}  # fmt: skip
            if doc:
                row.update(measure_doc(doc, media, ask, tools, Path(args.thumbs) if args.thumbs else None,
                                       f"{args.label}-{k}"))  # fmt: skip
            rows.append(row)
            print(json.dumps({x: row.get(x) for x in ("n", "path", "seconds", "images_asked", "images_found",
                                                      "images_relevant", "pptx_pictures", "charts",
                                                      "chart_values_sourced", "chart_values", "pptx_charts")},
                             ensure_ascii=False), flush=True)  # fmt: skip
    return rows


def dsl_text(doc: dict) -> str:
    """A deployed Bird does not send the model's raw text: the deck written back in the format (same queries)."""
    from birds.canvas import dsl

    try:
        return dsl.to_dsl(dsl.validate(doc), ids=False)
    except Exception:  # noqa: BLE001 - the measure keeps going
        return ""


def replay(args) -> list[dict]:
    """The raw answers of a measure, parsed and their pictures searched again by this checkout."""
    import tempfile

    import httpx

    from birds.canvas import dsl, images, turn
    from birds.harness import office_media as om
    from birds.harness.config import Config

    pin = os.environ.get("BIRD_PIN_DNS", "1") != "0"
    cfg = Config(workspace=Path(tempfile.mkdtemp(prefix="deck-media-")), pin_dns=pin)
    http = httpx.Client(trust_env=False, follow_redirects=False) if pin else httpx.Client(follow_redirects=False)
    fetch = om.Fetcher(http, cfg)
    rows = []
    for old in json.loads(Path(args.replay).read_text("utf-8")):
        raw = old.get("raw") or ""
        if not raw:
            continue
        repairs: list[str] = []
        _, content, _ = dsl.split_answer(raw)
        doc = turn.finish_doc(dsl.parse(content, "deck", "fr", repairs), "deck", old["ask"], "fr")
        t0 = time.monotonic()
        found = images.resolve(doc, images.finder("web", fetch, doc.get("theme"), "fr"), limit=turn.IMAGE_LIMIT,
                               deadline=time.monotonic() + turn.IMAGE_SECONDS)  # fmt: skip
        row = {"n": old["n"], "ask": old["ask"], "label": args.label, "image_seconds": round(time.monotonic() - t0, 1),
               "raw": raw}  # fmt: skip
        row.update(measure_doc(doc, found, old["ask"], "", Path(args.thumbs) if args.thumbs else None,
                               f"{args.label}-{old['n']}"))  # fmt: skip
        rows.append(row)
        print(json.dumps({x: row.get(x) for x in ("n", "image_seconds", "images_asked", "images_found",
                                                  "images_relevant", "pptx_pictures", "images")},
                         ensure_ascii=False), flush=True)  # fmt: skip
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="after")
    ap.add_argument("--out", default="out/deck_media_eval.json")
    ap.add_argument("--only", default="")
    ap.add_argument("--thumbs", default="")
    ap.add_argument("--replay", default="")
    ap.add_argument("--url", default="", help="a deployed Bird to measure (production) instead of this checkout")
    args = ap.parse_args()
    if not args.replay and not args.url and not os.environ.get("BIRD_BASE_URL"):
        print("set BIRD_BASE_URL (and BIRD_MODEL): this script calls the real endpoint")
        return 2
    rows = replay(args) if args.replay else live(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tot = {k: sum(r.get(k) or 0 for r in rows) for k in ("images_asked", "images_found", "images_decode",
                                                         "images_credited", "images_relevant", "pptx_pictures",
                                                         "charts", "chart_values", "chart_values_sourced",
                                                         "pptx_charts")}  # fmt: skip
    print(json.dumps({"total": tot, "decks": sum(1 for r in rows if r.get("slides"))}, ensure_ascii=False))
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
