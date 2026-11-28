"""Scripted demo of the widget tools: the REAL tool functions run on provider answers recorded on 2026-11-22
(``demo_data/``), so the demo shows exactly what a live run shows, with no network request. Maps are pre-rendered
images in ``static/demo/`` (made by ``scripts/demo_maps.py`` from OSM tiles, attribution burnt in). MET Norway
forecasts (``met_*.json``) were recorded on 2026-11-23 at 07:25 UTC: weather replays run at that instant
(``MET_RECORDED``), so « demain » is the 24th and the card says which day it shows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DATA = Path(__file__).parent / "demo_data"
MET_RECORDED = "2026-11-23T07:30:00+00:00"
_MET = {
    (45.7578, 4.832): "lyon",
    (50.6366, 3.0635): "lille",
    (51.5074, -0.1278): "london",
    (47.2186, -1.5541): "nantes",
}
STATIC_DEMO = Path(__file__).parent / "static" / "demo"


def _load(name: str):
    p = DATA / name
    return p.read_text(encoding="utf-8") if name.endswith(".xml") else json.loads(p.read_text(encoding="utf-8"))


def opendata_key(url: str) -> str:
    """A recorded open-data URL without the dates the tools compute from today (BOAMP « published since »,
    OpenAlex « from »), so a replay matches on any day."""
    import re

    return re.sub(r"(?:19|20)\d\d-\d\d-\d\d", "DATE", url)


_OPENDATA: dict | None = None


def _opendata(url: str):
    global _OPENDATA
    if _OPENDATA is None:
        p = DATA / "opendata.json"
        _OPENDATA = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    return _OPENDATA.get(opendata_key(url))


def recorded(url: str):
    """The recorded answer for a provider URL built by the tools (unknown queries: nothing found)."""
    from birds.harness.tools.opendata.http import HOSTS as OPENDATA_HOSTS

    u = urlsplit(url)
    if (u.hostname or "") in OPENDATA_HOSTS:  # open data, recorded by scripts/opendata_live.py --demo
        got = _opendata(url)
        if got is not None:
            return got
        if u.hostname in ("fr.wikipedia.org", "en.wikipedia.org", "api.crossref.org"):
            from birds.harness.guard import ToolError

            raise ToolError("HTTP 404")  # not recorded: as a missing page, never invented
        if u.hostname not in ("calendrier.api.gouv.fr", "data.geopf.fr"):
            return {}
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    host, text = u.hostname or "", (q.get("q") or "").lower()
    if host.endswith("ecb.europa.eu"):
        return _load("ecb_daily.xml")
    if host == "calendrier.api.gouv.fr":
        return _load("feries_metropole_2026.json") if "2026" in u.path else {}
    if host == "recherche-entreprises.api.gouv.fr":
        return _load("entreprises_siren.json") if text.isdigit() else _load("entreprises_airbus.json")
    if host == "data.geopf.fr" or host == "api-adresse.data.gouv.fr":
        # lists of addresses and towns (« montre sur une carte : 10 rue de Rivoli Paris ; … »), recorded 2026-11-27
        lists = _load("geopf_lists.json")
        key = f"{text}|{q.get('type', '')}"
        if key in lists:
            return lists[key]
        return _load("geopf_segur.json") if "ségur" in text or "segur" in text else {"features": []}
    if host == "photon.komoot.io":
        return _load("photon_tour_eiffel.json") if "eiffel" in text else {"features": []}
    if host == "nominatim.openstreetmap.org":
        if "viewbox" in q and "restaurant" in text:
            return _load("nominatim_restaurants_viewbox.json")
        for key, name in (("gare de lyon", "gare_de_lyon"), ("part-dieu", "lyon_part_dieu"),
                          ("lille europe", "lille_europe"), ("nantes", "nantes"), ("eiffel", "tour_eiffel"),
                          ("lyon", "lyon"), ("lille", "lille"), ("london", "london"), ("londres", "london")):  # fmt: skip
            if key in text:
                return _load(f"nominatim_{name}.json")
        return []
    if host == "api.met.no":
        try:
            lat, lon = float(q.get("lat", "")), float(q.get("lon", ""))
        except ValueError:
            return {}
        near = min(_MET, key=lambda k: (k[0] - lat) ** 2 + (k[1] - lon) ** 2)
        if abs(near[0] - lat) < 0.05 and abs(near[1] - lon) < 0.05:
            return _load(f"met_{_MET[near]}.json")
        return {"type": "Feature", "properties": {"timeseries": []}}
    return {}


def map_file(c, z: int) -> str:
    return hashlib.sha256(json.dumps([round(c[0], 6), round(c[1], 6), int(z)]).encode()).hexdigest()[:16] + ".webp"


def localise_maps(widgets: list[dict]) -> list[dict]:
    """Point each map at its pre-rendered image (zoom buttons are then hidden: the demo has one image per map)."""
    for w in widgets:
        m = w.get("map")
        if m:
            f = map_file(m["c"], m["z"])
            if (STATIC_DEMO / f).is_file():
                m["src"], m["static"] = f"/static/demo/{f}", True
    return widgets


def run_tool(tool: str, args: dict, lang: str, charts: list | None = None):
    """(result text, step info) of a widget tool on recorded data; ``charts`` receives the charts it drew
    (get_statistics)."""
    import tempfile

    from birds.harness import Config, Context
    from birds.harness.tools import TOOLS

    ctx = Context(config=Config(workspace=Path(tempfile.gettempdir()), audit_file=None), http=None, lang=lang)
    ctx.recorded = recorded
    if tool == "get_weather":
        from datetime import datetime

        ctx.now = datetime.fromisoformat(MET_RECORDED)  # the instant the forecasts were recorded
    text = TOOLS[tool](args, ctx)
    if charts is not None:
        charts.extend(ctx.charts)
    return text, dict(ctx.step_info or {}), list(ctx.sources)
