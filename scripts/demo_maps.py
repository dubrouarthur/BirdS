"""Pre-render the static maps of the scripted demo (birds/web/static/demo/*.webp) from OpenStreetMap tiles.

Run once, by hand, when the demo data change: .venv/bin/python scripts/demo_maps.py
It fetches each tile once (at most 2 at a time, generic User-Agent, through the egress guard) and burns the
attribution « © OpenStreetMap contributors » into each image. The demo itself never fetches a tile.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from birds.harness import Config, guard  # noqa: E402
from birds.web import mapimg  # noqa: E402
from birds.web.demo_widgets import STATIC_DEMO, map_file, run_tool  # noqa: E402
from birds.web.widgets import build_widgets  # noqa: E402

DEMOS = [
    ("find_places", {"query": "restaurant", "near": "gare de Lyon"}),
    ("find_places", {"query": "tour Eiffel"}),
    ("find_places", {"query": "20 avenue de Ségur Paris"}),
    ("find_places", {"query": "Lyon Part-Dieu ; Lille Europe ; Nantes"}),
    ("find_places", {"query": "10 rue de Rivoli Paris ; 5 place Bellecour Lyon ; 1 La Canebière Marseille"}),
    ("find_places", {"query": "Lyon ; Grenoble ; Annecy ; Chambéry"}),
    ("find_places", {"query": "Paris ; Lyon ; Marseille ; Bordeaux ; Nantes ; Lille ; Strasbourg ; Toulouse ; Nice ; Rennes"}),
    ("find_company", {"name": "Airbus"}),
]


def main() -> None:
    pin = os.environ.get("BIRD_PIN_DNS", "1") not in ("0", "false")
    cfg = Config(workspace=Path(tempfile.gettempdir()), audit_file=None, pin_dns=pin)
    client = httpx.Client(trust_env=not pin, follow_redirects=False, timeout=15.0)
    tiles = mapimg.Tiles(
        lambda url, headers: guard.fetch_bytes(
            client,
            cfg,
            url,
            accept="image/png",
            types=("image/png",),
            max_bytes=200_000,
            user_agent=cfg.geo_user_agent,
            headers=headers,
        ),  # fmt: skip
        disk=os.environ.get("BIRD_TILE_CACHE") or None,  # a re-run asks OSM only for the tiles it has not got
    )
    STATIC_DEMO.mkdir(parents=True, exist_ok=True)
    for lang in ("fr",):
        for tool, args in DEMOS:
            _, info, _ = run_tool(tool, args, lang)
            for w in build_widgets([SimpleNamespace(tool=tool, info=info, error=None)], "", lang, None, b"demo"):
                m = w.get("map")
                if not m:
                    continue
                out = STATIC_DEMO / map_file(m["c"], m["z"])
                if out.exists():
                    continue
                body, partial, n, _ = mapimg.render_map(
                    m["c"], m["z"], tiles, mapimg.OSM_TILES, mapimg.ATTRIBUTION["osm"]
                )
                if partial:  # a tile failed: never kept, run again later
                    print(out.name, "PARTIAL, not written")
                    continue
                out.write_bytes(body)
                print(out.name, len(body), "bytes", n, "tiles")


if __name__ == "__main__":
    main()
