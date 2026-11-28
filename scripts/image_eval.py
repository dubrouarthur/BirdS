"""Free-licence picture search, measured on a FIXED set of queries (docs/CANVAS.md § 12).

The same path as production: ``birds.canvas.images.search_web`` here (``--local``), or the production endpoint
``POST /api/canvas/image`` (``--url https://bird-s.vercel.app``, one query every ``--pause`` seconds: never a
burst). For each query: found or not, licence checked as free, relevant (a word of the subject in the title),
source, latency, and — locally, or when the endpoint returns it — what each source answered (``429``, ``none``
with the reasons results were refused, ``timeout``…).

    .venv/bin/python scripts/image_eval.py --local --out docs/measures/image-eval-<date>-local.json
    .venv/bin/python scripts/image_eval.py --url https://bird-s.vercel.app --pause 4 --out docs/measures/...json

Behind an HTTPS proxy (a sandbox), ``--local`` connects through it (no DNS pinning); the egress guard still checks
every URL.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# query, lang, words of the subject (any of them in the title / tags = relevant), kind; « photo: False » = a query
# no photograph answers (a statistic): the right outcome is no picture
CASES: list[dict] = [
    {"q": "albatros", "lang": "fr", "subject": ["albatros", "albatross", "diomedea", "thalassarche"], "kind": "animal"},
    {
        "q": "Albatros en vol sur l'océan",
        "lang": "fr",
        "subject": ["albatros", "albatross", "diomedea", "thalassarche"],
        "kind": "animal",
    },
    {"q": "chaton heureux", "lang": "fr", "subject": ["chaton", "kitten", "cat", "chat", "kitty"], "kind": "animal"},
    {"q": "renard roux", "lang": "fr", "subject": ["renard", "fox", "vulpes"], "kind": "animal"},
    {"q": "red fox in snow", "lang": "en", "subject": ["fox", "vulpes", "renard"], "kind": "animal"},
    {"q": "honey bee on flower", "lang": "en", "subject": ["bee", "apis", "abeille"], "kind": "animal"},
    {"q": "dauphin", "lang": "fr", "subject": ["dauphin", "dolphin", "delphin", "tursiops"], "kind": "animal"},
    {"q": "Paris skyline", "lang": "en", "subject": ["paris"], "kind": "place"},
    {"q": "Mont-Saint-Michel", "lang": "fr", "subject": ["michel"], "kind": "place"},
    {"q": "Tour Eiffel", "lang": "fr", "subject": ["eiffel"], "kind": "place"},
    {"q": "port de Marseille", "lang": "fr", "subject": ["marseille"], "kind": "place"},
    {"q": "Lyon vieille ville", "lang": "fr", "subject": ["lyon"], "kind": "place"},
    {
        "q": "vignoble en Bourgogne",
        "lang": "fr",
        "subject": ["vigne", "vignoble", "vineyard", "bourgogne", "burgundy", "vine", "wine"],
        "kind": "place",
    },
    {
        "q": "forêt de pins des Landes",
        "lang": "fr",
        "subject": ["landes", "pin", "pine", "foret", "forest"],
        "kind": "place",
    },
    {
        "q": "mountain lake in the Alps",
        "lang": "en",
        "subject": ["lake", "lac", "alps", "alpes", "mountain"],
        "kind": "place",
    },
    {"q": "tramway à Bordeaux", "lang": "fr", "subject": ["tram", "tramway", "bordeaux"], "kind": "place"},
    {
        "q": "cyclist delivering food to office",
        "lang": "en",
        "subject": ["cyclist", "bike", "bicycle", "courier", "delivery", "velo"],
        "kind": "job",
    },
    {
        "q": "infirmière à l'hôpital",
        "lang": "fr",
        "subject": ["infirmiere", "nurse", "hopital", "hospital"],
        "kind": "job",
    },
    {
        "q": "électricien au travail",
        "lang": "fr",
        "subject": ["electricien", "electrician", "electrical"],
        "kind": "job",
    },
    {
        "q": "chef cuisinier en cuisine",
        "lang": "fr",
        "subject": ["chef", "cuisinier", "cook", "kitchen", "cuisine"],
        "kind": "job",
    },
    {
        "q": "farmer with tractor in a field",
        "lang": "en",
        "subject": ["farmer", "tractor", "field", "tracteur"],
        "kind": "job",
    },
    {
        "q": "boulangerie artisanale",
        "lang": "fr",
        "subject": ["boulangerie", "bakery", "boulanger", "baker", "pain", "bread"],
        "kind": "job",
    },
    {"q": "équipe en réunion", "lang": "fr", "subject": ["reunion", "meeting", "equipe", "team"], "kind": "abstract"},
    {"q": "teamwork meeting", "lang": "en", "subject": ["meeting", "team", "teamwork"], "kind": "abstract"},
    {
        "q": "cybersécurité",
        "lang": "fr",
        "subject": ["cyber", "security", "securite", "hacker", "padlock"],
        "kind": "abstract",
    },
    {"q": "innovation", "lang": "en", "subject": ["innovation"], "kind": "abstract"},
    {
        "q": "classroom with students",
        "lang": "en",
        "subject": ["classroom", "students", "class", "school"],
        "kind": "abstract",
    },
    {
        "q": "data center servers",
        "lang": "en",
        "subject": ["data", "server", "servers", "datacenter"],
        "kind": "object",
    },
    {
        "q": "offshore wind turbines",
        "lang": "en",
        "subject": ["wind", "turbine", "turbines", "eolien", "eolienne"],
        "kind": "object",
    },
    {
        "q": "panneaux solaires sur un toit",
        "lang": "fr",
        "subject": ["solaire", "solar", "panneau", "panel", "photovoltaique"],
        "kind": "object",
    },
    {
        "q": "ordinateur portable sur un bureau",
        "lang": "fr",
        "subject": ["ordinateur", "laptop", "computer", "portable"],
        "kind": "object",
    },
    {"q": "smartphone in hand", "lang": "en", "subject": ["smartphone", "phone", "mobile"], "kind": "object"},
    {"q": "vélo cargo", "lang": "fr", "subject": ["cargo", "velo", "bike", "bicycle"], "kind": "object"},
    {"q": "train à grande vitesse", "lang": "fr", "subject": ["train", "tgv"], "kind": "object"},
    {"q": "croissant", "lang": "fr", "subject": ["croissant"], "kind": "object"},
    {"q": "cup of coffee", "lang": "en", "subject": ["coffee", "cafe", "cup", "espresso"], "kind": "object"},
    {"q": "hydrogen fuel cell bus", "lang": "en", "subject": ["hydrogen", "bus", "hydrogene"], "kind": "object"},
    {"q": "Paris bike cargo statistics", "lang": "en", "subject": [], "kind": "statistic", "photo": False},
]

FREE = re.compile(r"^(?:CC0|CC BY(?:-SA)?(?: \d(?:\.\d)?)?|Domaine public|Public domain|Licence Pexels|"
                  r"Licence Unsplash|PDM)", re.I)  # fmt: skip


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", text)


def judge_row(case: dict, media: dict | None) -> dict:
    """What the measure keeps of one answer."""
    if not media:
        return {"found": False}
    title = fold(media.get("title", ""))  # never the alt text: it is the query itself
    words = set(title.split())
    subject = [fold(w).strip() for w in case.get("subject") or []]
    relevant = any(w in words or any(x.startswith(w) for x in words) for w in subject if w)
    source = str(media.get("source") or "")
    host = re.sub(r"^https?://([^/]+).*$", r"\1", source)
    return {"found": True, "free": bool(FREE.match(str(media.get("licence") or ""))), "relevant": relevant,
            "title": str(media.get("title") or "")[:120], "licence": media.get("licence"),
            "credit": str(media.get("credit") or "")[:160], "host": host,
            "bank": "Openverse" if "Openverse" in str(media.get("credit")) else
            "Commons" if "Wikimedia Commons" in str(media.get("credit")) else
            "Pexels" if "Pexels" in str(media.get("credit")) else str(media.get("credit") or "").split(" — ")[-1][:40],
            "w": media.get("w"), "h": media.get("h")}  # fmt: skip


def run_local(cases: list[dict]) -> list[dict]:
    import httpx

    from birds.canvas import images
    from birds.harness import Config
    from birds.harness import office_media as om

    proxied = bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    cfg = Config(workspace=Path("."), audit_file=None, pin_dns=not proxied,
                 search_contact=os.environ.get("BIRD_CONTACT") or "https://bird-s.vercel.app")  # fmt: skip
    rows = []
    for c in cases:
        client = (
            httpx.Client(follow_redirects=False) if proxied else httpx.Client(trust_env=False, follow_redirects=False)
        )
        t0 = time.monotonic()
        with images.tracing() as log:
            try:
                m = images.search_web(c["q"], om.Fetcher(client, cfg), [], "w1", deadline=time.monotonic() + 12,
                                      lang=c["lang"])  # fmt: skip
            except TypeError:  # the measure « before »: search_web had no lang
                m = images.search_web(c["q"], om.Fetcher(client, cfg), [], "w1", deadline=time.monotonic() + 12)
        client.close()
        entry = images.to_entry(m, c["q"]) if m else None
        rows.append({"q": c["q"], "lang": c["lang"], "kind": c["kind"], "photo": c.get("photo", True),
                     "seconds": round(time.monotonic() - t0, 2), **judge_row(c, entry), "trace": log})  # fmt: skip
        print(_line(rows[-1]), flush=True)
    return rows


def run_remote(cases: list[dict], url: str, pause: float, burst: int = 1) -> list[dict]:
    """One query every ``pause`` seconds; with ``burst`` > 1, groups of that many at once (a deck asks its 6 to 8
    pictures together), then a pause."""
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    with httpx.Client(timeout=40.0) as client:
        if burst <= 1:
            rows = []
            for i, c in enumerate(cases):
                if i:
                    time.sleep(pause)
                rows.append(_ask(client, url, c))
            return rows
        rows = []
        with ThreadPoolExecutor(max_workers=burst) as pool:
            for i in range(0, len(cases), burst):
                if i:
                    time.sleep(pause)
                rows += list(pool.map(lambda c: _ask(client, url, c), cases[i:i + burst]))
        return rows


def _ask(client, url: str, c: dict) -> dict:
    t0 = time.monotonic()
    status, data = 0, {}
    try:
        r = client.post(url.rstrip("/") + "/api/canvas/image", json={"query": c["q"], "lang": c["lang"]},
                        headers={"Origin": url.rstrip("/")})  # fmt: skip
        status = r.status_code
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:  # noqa: BLE001 - the measure records it
        data = {"error": type(e).__name__}
    media = data.get("media") if data.get("ok") else None
    row = {"q": c["q"], "lang": c["lang"], "kind": c["kind"], "photo": c.get("photo", True),
           "seconds": round(time.monotonic() - t0, 2), "http": status,
           **({"reason": data.get("reason") or data.get("error")} if not data.get("ok") else {}),
           **judge_row(c, media), **({"trace": data["trace"]} if data.get("trace") else {})}  # fmt: skip
    print(_line(row), flush=True)
    return row


def _line(r: dict) -> str:
    if r.get("found"):
        return (f"{'ok ' if r['relevant'] and r['free'] else 'BAD'} {r['seconds']:5.1f}s {r['q'][:38]:38} "
                f"{r['bank']:10} {r['title'][:50]}")  # fmt: skip
    why = " | ".join(f"{t['source']}:{t['status']}" + (f"({t.get('results')})" if "results" in t else "")
                     for t in r.get("trace") or [])  # fmt: skip
    return f"--- {r['seconds']:5.1f}s {r['q'][:38]:38} {r.get('reason', '')} {why[:120]}"


def summary(rows: list[dict]) -> dict:
    photo = [r for r in rows if r["photo"]]
    found = [r for r in photo if r.get("found")]
    good = [r for r in found if r.get("relevant") and r.get("free")]
    statuses: dict[str, int] = {}
    for r in rows:
        for t in r.get("trace") or []:
            k = f"{t['source']}:{t['status']}"
            statuses[k] = statuses.get(k, 0) + 1
    banks: dict[str, int] = {}
    for r in found:
        banks[r["bank"]] = banks.get(r["bank"], 0) + 1
    secs = sorted(r["seconds"] for r in photo)
    return {"queries": len(rows), "photo_queries": len(photo), "found": len(found), "found_rate": round(
            len(found) / max(1, len(photo)), 3), "free": sum(1 for r in found if r.get("free")),
            "relevant": sum(1 for r in found if r.get("relevant")), "good": len(good),
            "no_photo_respected": sum(1 for r in rows if not r["photo"] and not r.get("found")),
            "median_s": secs[len(secs) // 2] if secs else None, "p90_s": secs[int(len(secs) * 0.9)] if secs else None,
            "banks": banks, "source_status": statuses,
            "by_kind": {k: f"{sum(1 for r in found if r['kind'] == k)}/{sum(1 for r in photo if r['kind'] == k)}"
                        for k in sorted({r["kind"] for r in photo})}}  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--local", action="store_true", help="search_web in this process (the production code path)")
    ap.add_argument("--url", help="the deployment to measure, e.g. https://bird-s.vercel.app")
    ap.add_argument("--pause", type=float, default=4.0, help="seconds between two calls to the endpoint")
    ap.add_argument("--burst", type=int, default=1, help="queries sent together (a deck's pictures), endpoint only")
    ap.add_argument("--only", help="a regex: run the matching queries only")
    ap.add_argument("--out", help="write the JSON measure here")
    a = ap.parse_args()
    cases = [c for c in CASES if not a.only or re.search(a.only, c["q"], re.I)]
    if not a.local and not a.url:
        ap.error("--local or --url")
    rows = run_local(cases) if a.local else run_remote(cases, a.url, a.pause, a.burst)
    out = {"date": time.strftime("%Y-%m-%d %H:%M"), "where": "local" if a.local else a.url,
           "burst": a.burst,
           "summary": summary(rows), "rows": rows}  # fmt: skip
    print(json.dumps(out["summary"], ensure_ascii=False, indent=1))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
