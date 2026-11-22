"""Scripted demo of the widget tools: the REAL tool functions run on provider answers recorded on 2026-11-22
(``demo_data/``), so the demo shows exactly what a live run shows, with no network request. Maps are pre-rendered
images in ``static/demo/`` (made by ``scripts/demo_maps.py`` from OSM tiles, attribution burnt in)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DATA = Path(__file__).parent / "demo_data"
STATIC_DEMO = Path(__file__).parent / "static" / "demo"


def _load(name: str):
    p = DATA / name
    return p.read_text(encoding="utf-8") if name.endswith(".xml") else json.loads(p.read_text(encoding="utf-8"))


def recorded(url: str):
    """The recorded answer for a provider URL built by the tools (unknown queries: nothing found)."""
    u = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    host, text = u.hostname or "", (q.get("q") or "").lower()
    if host.endswith("ecb.europa.eu"):
        return _load("ecb_daily.xml")
    if host == "calendrier.api.gouv.fr":
        return _load("feries_metropole_2026.json") if "2026" in u.path else {}
    if host == "recherche-entreprises.api.gouv.fr":
        return _load("entreprises_siren.json") if text.isdigit() else _load("entreprises_airbus.json")
    if host == "data.geopf.fr" or host == "api-adresse.data.gouv.fr":
        return _load("geopf_segur.json") if "ségur" in text or "segur" in text else {"features": []}
    if host == "photon.komoot.io":
        return _load("photon_tour_eiffel.json") if "eiffel" in text else {"features": []}
    if host == "nominatim.openstreetmap.org":
        if "viewbox" in q and "restaurant" in text:
            return _load("nominatim_restaurants_viewbox.json")
        for key, name in (("gare de lyon", "gare_de_lyon"), ("part-dieu", "lyon_part_dieu"),
                          ("lille europe", "lille_europe"), ("nantes", "nantes"), ("eiffel", "tour_eiffel")):  # fmt: skip
            if key in text:
                return _load(f"nominatim_{name}.json")
        return []
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


def run_tool(tool: str, args: dict, lang: str):
    """(result text, step info) of a widget tool on recorded data."""
    import tempfile

    from birds.harness import Config, Context
    from birds.harness.tools import TOOLS

    ctx = Context(config=Config(workspace=Path(tempfile.gettempdir()), audit_file=None), http=None, lang=lang)
    ctx.recorded = recorded
    text = TOOLS[tool](args, ctx)
    return text, dict(ctx.step_info or {}), list(ctx.sources)
