"""Server-side finishing of the open-data cards (birds/harness/tools/opendata) before they reach the browser.

The browser never contacts a third party (strict CSP): the entity card's Wikimedia picture becomes a signed
same-origin ``/api/img`` URL, and the commune card gets a signed static map (``/api/map``). Everything else in a
card comes from the tool's result as it is. A picture without a known licence was already dropped by the tool.
"""

from __future__ import annotations

from urllib.parse import urlsplit

TYPES = ("calendar", "entity", "tenders", "papers", "commune")
IMAGE_TTL = 7 * 86400.0
_IMAGE_HOSTS = {"upload.wikimedia.org"}


def prepare(w: dict, secret: bytes, layer: str = "osm", geo_on: bool = True) -> dict:
    from . import tokens
    from .widgets import _map_for

    if w.get("type") == "entity":
        img = w.get("image") or None
        src = str((img or {}).get("src") or "")
        try:
            host = (urlsplit(src).hostname or "").lower()
        except ValueError:
            host = ""
        if img and src.startswith("https://") and host in _IMAGE_HOSTS and img.get("license"):
            img["src"] = tokens.sign_image_url(src, secret, IMAGE_TTL)
        else:
            w["image"] = None
    elif w.get("type") == "commune":
        pts = []
        a = w.get("address") or {}
        if a.get("lat") is not None and a.get("lon") is not None:
            pts = [(a["lat"], a["lon"])]
        else:
            c = (w.get("communes") or [{}])[0] or {}
            if w.get("mode") == "commune" and c.get("lat") is not None and c.get("lon") is not None:
                pts = [(c["lat"], c["lon"])]
        kind = "address" if w.get("mode") == "address" else "city"
        w["map"] = _map_for(pts, secret, kind, layer) if (pts and geo_on) else None
    return w
