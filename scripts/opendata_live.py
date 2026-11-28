"""Live check of the open-data providers: one real call per provider, through the same tool code and egress guard.

  .venv/bin/python scripts/opendata_live.py [--record birds/web/demo_data/opendata.json] [--json out.json] [--demo]

Each case runs the real tool (birds/harness/tools/opendata) with a live HTTP client; the table says, per provider,
whether it answered, how long it took and what the card holds. ``--record`` keeps every provider answer (URL ->
JSON) so the scripted demo (birds/web/demo_widgets.py) replays exactly what a live run shows, with no network;
``--demo`` runs the demo's own asks (``DEMO_ASKS``, read by the open-data parsers) instead of the provider cases.
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

# the scripted demo's asks (birds/web/backends.py, scenario_opendata) and the next asks their cards offer
DEMO_ASKS = [
    ("jours fériés de mai 2027", "fr"),
    ("quels sont les jours fériés en 2027 ?", "fr"),
    ("Jours fériés 2028", "fr"),
    ("public holidays in Germany in 2027", "en"),
    ("c'est quoi l'Unesco ?", "fr"),
    ("le chômage en France et en Allemagne depuis 2015", "fr"),
    ("PIB de la France et du Japon depuis 2010", "fr"),
    ("population de Roubaix depuis 1968", "fr"),
    ("Évolution de la population de Roubaix", "fr"),
    ("appels d'offres maintenance informatique", "fr"),
    ("Appels d'offres maintenance informatique publiés cette semaine", "fr"),
    ("articles scientifiques sur les batteries sodium-ion", "fr"),
    ("Articles les plus cités sur batteries sodium-ion", "fr"),
    ("Publications récentes sur batteries sodium-ion", "fr"),
    ("vérifie ce DOI 10.1038/nature14539", "fr"),
    ("code postal de Roubaix", "fr"),
    ("normalise cette adresse : 20 av de segur paris", "fr"),
]


def _demo_cases() -> list:
    from birds.harness import opendata_intents

    out = []
    for q, lang in DEMO_ASKS:
        got = next((i for i in opendata_intents.detect(q, False, lang) if i.args), None)
        if got is None:
            raise SystemExit(f"no open-data call for the demo ask {q!r}")
        out.append((q, got.tool, dict(got.args), lang))
    return out


_CROSSREF_KEEP = {"title", "author", "issued", "published", "DOI", "container-title", "publisher",
                  "is-referenced-by-count", "type", "URL"}  # fmt: skip


def _slim(url: str, data):
    """What the tools read of a recorded answer (OpenAlex authorships, Crossref references are heavy): the demo
    replays the same cards from a file a tenth of the size. Checked: the card built from the slim answer is equal."""
    if "api.openalex.org" in url and isinstance(data, dict):
        for r in data.get("results") or []:
            r["authorships"] = [{"author": {"display_name": (a.get("author") or {}).get("display_name")}}
                                for a in r.get("authorships") or []]  # fmt: skip
            src = ((r.get("primary_location") or {}).get("source") or {}).get("display_name")
            r["primary_location"] = {"source": {"display_name": src}} if src else {}
    if "api.crossref.org/works/" in url and isinstance(data, dict) and isinstance(data.get("message"), dict):
        data["message"] = {k: v for k, v in data["message"].items() if k in _CROSSREF_KEEP}
    return data


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
    ap.add_argument("--demo", action="store_true", help="the demo's asks instead of one case per provider")
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
    for provider, tool, args, lang in _demo_cases() if a.demo else CASES:
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
        from birds.web.demo_widgets import opendata_key

        old = json.loads(Path(a.record).read_text()) if Path(a.record).is_file() else {}
        old.update({opendata_key(u): _slim(u, v) for u, v in seen.items()})
        Path(a.record).write_text(json.dumps(old, ensure_ascii=False, sort_keys=True, indent=0))
        print(f"recorded {len(seen)} answers in {a.record}")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
