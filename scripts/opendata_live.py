"""Live check of the open-data providers: one real call per provider, through the same tool code and egress guard.

  .venv/bin/python scripts/opendata_live.py [--record birds/web/demo_data/opendata.json] [--json out.json]

Each case runs the real tool (birds/harness/tools/opendata) with a live HTTP client; the table says, per provider,
whether it answered, how long it took and what the card holds. ``--record`` keeps every provider answer (URL ->
JSON) so the scripted demo (birds/web/demo_widgets.py) replays exactly what a live run shows, with no network.
Behind a filtering egress proxy set BIRD_PIN_DNS=0 (the proxy then resolves names).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from birds.harness import Config, Context, guard  # noqa: E402
from birds.harness.tools.opendata import OPENDATA_TOOLS  # noqa: E402

# (provider, tool, args, lang): one call each; together they cover every host of opendata/http.py
CASES = [
    ("calendrier.api.gouv.fr", "work_calendar", {"period": "2027-05"}, "fr"),
    ("Nager.Date", "work_calendar", {"period": "2027", "zone": "DE"}, "fr"),
    ("Wikipedia + Wikidata", "lookup_entity", {"name": "Airbus"}, "fr"),
    ("Eurostat", "get_statistics", {"indicator": "chômage", "places": "France, Allemagne", "since": "2015"}, "fr"),
    ("Banque mondiale", "get_statistics", {"indicator": "PIB", "places": "France, Japon", "since": "2010"}, "fr"),
    ("INSEE Melodi", "get_statistics", {"indicator": "population", "places": "Roubaix"}, "fr"),
    ("BOAMP", "find_tenders", {"query": "nettoyage de locaux", "where": "59"}, "fr"),
    ("OpenAlex", "find_papers", {"query": "sodium-ion batteries", "order": "recent"}, "en"),
    ("Crossref", "find_papers", {"query": "10.1038/nature14539"}, "en"),
    ("geo.api.gouv.fr", "find_commune", {"name": "Roubaix"}, "fr"),
    ("Base Adresse Nationale", "find_commune", {"name": "20 avenue de Ségur 75007 Paris"}, "fr"),
]


def _summary(tool: str, ctx) -> str:
    info = ctx.step_info or {}
    w = info.get("widget") or {}
    if tool == "get_statistics":
        c = ctx.charts[-1] if ctx.charts else {}
        return f"chart {info.get('series')} series, {info.get('values')} values, {len(c.get('rows') or [])} rows"
    if tool == "work_calendar":
        return f"{len(w.get('holidays') or [])} holidays, mode {w.get('mode')}"
    if tool == "lookup_entity":
        return f"{w.get('title')} ({len(w.get('facts') or [])} facts, picture {'yes' if w.get('image') else 'no'})"
    if tool == "find_tenders":
        return f"{len(w.get('items') or [])} notices"
    if tool == "find_papers":
        return f"{len(w.get('items') or [])} works"
    if tool == "find_commune":
        return f"mode {w.get('mode')}, {len(w.get('communes') or [])} communes"
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", help="write provider answers (URL -> JSON) for the scripted demo")
    ap.add_argument("--json", help="write the results table as JSON")
    a = ap.parse_args(argv)
    pin = os.environ.get("BIRD_PIN_DNS", "0") not in ("0", "false", "")
    cfg = Config(workspace=Path(tempfile.gettempdir()), audit_file=None, pin_dns=pin)
    http = httpx.Client(trust_env=not pin, follow_redirects=False, timeout=15.0)
    seen: dict[str, object] = {}
    real = guard.fetch_bytes

    def spy(client, c, url, **kw):
        out = real(client, c, url, **kw)
        try:
            seen[url] = json.loads(out[2])
        except ValueError:
            pass
        return out

    guard.fetch_bytes = spy
    rows = []
    for provider, tool, args, lang in CASES:
        ctx = Context(config=cfg, http=http, lang=lang)
        t0 = time.monotonic()
        try:
            OPENDATA_TOOLS[tool](dict(args), ctx)
            ok, what = bool((ctx.step_info or {}).get("widget") or ctx.charts), _summary(tool, ctx)
        except Exception as e:  # a provider down is a row of the table, not a crash
            ok, what = False, f"{type(e).__name__}: {e}"[:160]
        rows.append({"provider": provider, "tool": tool, "ok": ok, "seconds": round(time.monotonic() - t0, 2),
                     "result": what})  # fmt: skip
        print(f"{'OK  ' if ok else 'FAIL'} {provider:<24} {tool:<15} {rows[-1]['seconds']:>5}s  {what}")
    guard.fetch_bytes = real
    print(f"{sum(r['ok'] for r in rows)}/{len(rows)} providers answered")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    if a.record:
        Path(a.record).write_text(json.dumps(seen, ensure_ascii=False, sort_keys=True))
        print(f"recorded {len(seen)} answers in {a.record}")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
