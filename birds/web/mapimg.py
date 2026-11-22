"""Same-origin images for the widgets: ``/api/map`` (static map stitched from raster tiles) and ``/api/icon``
(site favicons for the source cards). The browser never contacts a tile server or a third-party site.

Security rules (the same as the charts team's ``/api/img``): GET only, same-origin check, its own rate limiter,
no request header forwarded upstream, every upstream hop through the egress guard (``guard.fetch_bytes``), images
re-encoded with Pillow, LRU caches, JSON errors that never echo an upstream URL, logs with no coordinates.
**No URL ever comes from the client**: tile URLs are built from a fixed template and a signed token; favicon URLs
are ``https://{signed domain}/favicon.ico``.

OSM tile usage policy (https://operations.osmfoundation.org/policies/tiles/): generic identifying User-Agent, at
most 2 concurrent downloads, upstream cache headers honoured (min 1 day, max 7 days, stale served on error), no
prefetching, « © OpenStreetMap contributors » burnt into every image (and shown as text by the client).
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from birds.harness import geo, guard

from . import tokens

MAP_W, MAP_H = 640, 360
MAP_TTL = 30 * 86400
OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
IGN_TILES = (
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2"
    "&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
)
ATTRIBUTION = {"osm": "© OpenStreetMap contributors", "ign": "© IGN – Géoplateforme"}
BACKGROUND = (229, 227, 223)
ICON_TYPES = ("image/x-icon", "image/vnd.microsoft.icon", "image/png", "image/jpeg", "image/gif", "image/webp")
_HOST = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class LRU:
    def __init__(self, size: int):
        self.size, self.data, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        return None

    def put(self, key, value) -> None:
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)

    def clear(self) -> None:
        with self.lock:
            self.data.clear()


def map_token(secret: bytes, center: tuple[float, float], z: int, layer: str = "osm", now: float | None = None) -> str:
    c = [round(float(center[0]), 6), round(float(center[1]), 6)]
    return tokens.sign({"k": "map", "c": c, "z": int(z), "w": MAP_W, "h": MAP_H, "l": layer}, secret, MAP_TTL, now)


def map_src(secret: bytes, center, z: int, layer: str = "osm") -> dict:
    return {"src": "/api/map?t=" + map_token(secret, center, z, layer), "w": MAP_W, "h": MAP_H,
            "c": [round(center[0], 6), round(center[1], 6)], "z": int(z)}  # fmt: skip


def icon_sig(secret: bytes, domain: str) -> str:
    return hmac.new(secret, f"icon|{domain}".encode(), hashlib.sha256).hexdigest()[:24]


def icon_src(secret: bytes, domain: str) -> str:
    return f"/api/icon?d={domain}&s={icon_sig(secret, domain)}"


def _registrable(host: str) -> str:
    parts = host.lower().rstrip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("gouv", "co", "com", "org", "ac", "gov", "net"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


class Tiles:
    """Decoded-tile cache (PNG bytes) with upstream freshness, stale-if-error and ETag revalidation."""

    def __init__(self, fetch, disk: str | None = None, size: int = 256, per_minute: int = 120):
        self.fetch, self.disk, self.mem = fetch, disk, LRU(size)
        self.sem = threading.BoundedSemaphore(2)  # OSM policy: at most 2 concurrent downloads
        self.wall = time.time
        # a process-wide cap on uncached tile downloads, whoever asks (the per-IP limiters can be shared by a NAT)
        self.per_minute, self.recent, self.budget_lock = per_minute, [], threading.Lock()

    def _spend(self) -> bool:
        now = time.monotonic()
        with self.budget_lock:
            self.recent = [t for t in self.recent if now - t < 60]
            if len(self.recent) >= self.per_minute:
                return False
            self.recent.append(now)
            return True

    def _disk_path(self, key: str) -> Path | None:
        return Path(self.disk) / (hashlib.sha256(key.encode()).hexdigest() + ".tile") if self.disk else None

    def _load(self, key: str):
        hit = self.mem.get(key)
        if hit is None and self.disk:
            p = self._disk_path(key)
            try:
                meta = json.loads(p.with_suffix(".json").read_text())
                hit = (p.read_bytes(), meta["fresh_until"], meta.get("etag", ""))
                self.mem.put(key, hit)
            except (OSError, ValueError, KeyError):
                hit = None
        return hit

    def _store(self, key: str, value) -> None:
        self.mem.put(key, value)
        if self.disk:
            try:
                p = self._disk_path(key)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(value[0])
                p.with_suffix(".json").write_text(json.dumps({"fresh_until": value[1], "etag": value[2]}))
            except OSError:
                pass

    def get(self, url: str) -> tuple[bytes | None, bool]:
        """(PNG/JPEG bytes or None, served from cache)."""
        now = self.wall()
        hit = self._load(url)
        if hit and hit[1] > now:
            return hit[0], True
        headers = {"If-None-Match": hit[2]} if hit and hit[2] else None
        try:
            if not self._spend():
                raise guard.ToolError("tile download budget spent for this minute")
            with self.sem:
                status, _, body, rh = self.fetch(url, headers)
        except (guard.Blocked, guard.ToolError):
            if hit and now - hit[1] < 7 * 86400:  # stale-if-error, up to 7 days
                return hit[0], True
            raise
        lower = {k.lower(): v for k, v in rh.items()}
        m = re.search(r"max-age=(\d+)", lower.get("cache-control", ""))
        ttl = min(7 * 86400, max(86400, int(m.group(1)) if m else 86400))
        if status == 304 and hit:
            self._store(url, (hit[0], now + ttl, hit[2]))
            return hit[0], True
        if not (body.startswith(b"\x89PNG\r\n\x1a\n") or body.startswith(b"\xff\xd8\xff")):
            raise guard.Blocked("not a PNG or JPEG tile")
        self._store(url, (body, now + ttl, lower.get("etag", "")))
        return body, False


def render_map(center, z: int, tiles: Tiles, template: str, attribution: str, w: int = MAP_W, h: int = MAP_H):
    """(WebP bytes, partial, tiles used, from cache). Pillow stitches the tiles that cover the w x h window."""
    from PIL import Image, ImageDraw, ImageFont

    Image.MAX_IMAGE_PIXELS = 4_000_000
    cx, cy = geo.world_xy(center[0], center[1], z)
    left, top = cx - w / 2, cy - h / 2
    n = 2**z
    x0, x1 = int(left // 256), int((left + w - 1) // 256)
    y0, y1 = int(top // 256), int((top + h - 1) // 256)
    img = Image.new("RGB", (w, h), BACKGROUND)
    count = cached = failed = 0
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            if ty < 0 or ty >= n:
                continue
            count += 1
            url = template.format(z=z, x=tx % n, y=ty)
            try:
                data, was_cached = tiles.get(url)
                tile = Image.open(io.BytesIO(data))
                tile.load()
                if tile.size != (256, 256):
                    raise ValueError("tile size")
                img.paste(tile.convert("RGB"), (int(round(tx * 256 - left)), int(round(ty * 256 - top))))
                cached += was_cached
            except (guard.Blocked, guard.ToolError, OSError, ValueError, Image.DecompressionBombError):
                failed += 1
    if count and failed == count:
        raise guard.ToolError("every tile failed")
    draw = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.load_default(size=11)
    box = draw.textbbox((0, 0), attribution, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.rectangle((w - tw - 10, h - th - 8, w, h), fill=(255, 255, 255, 204))
    draw.text((w - tw - 5, h - th - 5 - box[1]), attribution, fill=(34, 34, 34, 255), font=font)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=78, method=4)
    return out.getvalue(), failed > 0, count, cached


def make_router(settings, harness_cfg) -> APIRouter:
    """``harness_cfg()`` returns a fresh ``birds.harness.Config`` (egress policy, user agent, provider URLs)."""
    import httpx

    router = APIRouter()
    secret = settings.signing_secret
    from .server import RateLimiter, peer_ip  # noqa: PLC0415 - avoids an import cycle at module load

    map_limit, icon_limit = RateLimiter(getattr(settings, "map_rate_limit", 30)), RateLimiter(120)
    client = httpx.Client(trust_env=not settings.pin_dns, follow_redirects=False, timeout=10.0)
    finals, icons = LRU(32), LRU(512)

    def upstream(url: str, headers: dict | None, accept: str = "image/png,image/jpeg", types=("image/png", "image/jpeg"),
                 max_bytes: int = 200_000, redirect_ok=None):  # fmt: skip
        cfg = harness_cfg()
        return guard.fetch_bytes(
            client, cfg, url, accept=accept, types=types, max_bytes=max_bytes, user_agent=cfg.geo_user_agent,
            headers=headers, max_redirects=2, redirect_ok=redirect_ok,
        )  # fmt: skip

    tiles = Tiles(
        lambda url, headers: upstream(url, headers),
        getattr(settings, "tile_cache_dir", None),
        per_minute=getattr(settings, "tile_fetch_per_min", 120),
    )
    router.tiles = tiles  # tests

    def err(status: int, code: str, message: str):
        return HTTPException(status, {"code": code, "message": message})

    def check(request: Request, limiter) -> None:
        if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            raise err(403, "cross_origin", "cross-origin requests are not accepted")
        origin = request.headers.get("origin")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        if origin and origin.split("://", 1)[-1].rstrip("/").lower() != host.lower():
            raise err(403, "cross_origin", "cross-origin requests are not accepted")
        if not limiter.allow(peer_ip(request, getattr(settings, "trusted_proxies", 0))):
            raise err(429, "rate_limited", "too many requests, wait a minute")

    def image(body: bytes, ctype: str, extra: dict | None = None) -> Response:
        return Response(body, media_type=ctype, headers={"Cache-Control": "private, max-age=86400", **(extra or {})})

    @router.get("/api/map", include_in_schema=False)
    def get_map(request: Request, t: str = "", dz: int = 0):
        check(request, map_limit)
        if not getattr(settings, "geo", True):
            raise err(503, "geo_disabled", "maps are switched off on this deployment")
        if not -2 <= dz <= 3:
            raise err(400, "bad_params", "dz must be between -2 and 3")
        try:
            p = tokens.verify(t, secret)
        except tokens.TokenError as e:
            code = "expired" if "expired" in str(e) else "bad_signature"
            raise err(410 if code == "expired" else 403, code, str(e)) from None
        try:
            if p.get("k") != "map":
                raise ValueError
            lat, lon = float(p["c"][0]), float(p["c"][1])
            z = max(3, min(18, int(p["z"]) + dz))
            layer = "ign" if p.get("l") == "ign" and getattr(settings, "tile_layer", "osm") == "ign" else "osm"
            if not (-85.06 <= lat <= 85.06 and -180 <= lon <= 180):
                raise ValueError
        except (KeyError, TypeError, ValueError, IndexError):
            raise err(400, "bad_params", "invalid map token") from None
        key = (lat, lon, z, layer)
        hit = finals.get(key)
        if hit:
            return image(hit, "image/webp")
        template = IGN_TILES if layer == "ign" else (getattr(settings, "tile_url", None) or OSM_TILES)
        t0 = time.monotonic()
        try:
            body, partial, n, cached = render_map((lat, lon), z, tiles, template, ATTRIBUTION[layer])
        except guard.Blocked:
            raise err(403, "blocked", "the tile server is not allowed by the egress policy") from None
        except guard.ToolError:
            raise err(502, "upstream", "the map tiles could not be loaded") from None
        print(json.dumps({"event": "map", "tiles": n, "cached": cached, "partial": partial,
                          "ms": int((time.monotonic() - t0) * 1000)}), file=sys.stderr)  # fmt: skip
        if partial:
            # a tile failed (503, timeout): never kept as final, nor by the browser; the tiles that did load are in
            # the tile cache, so the next request only asks upstream for the missing ones
            return Response(body, media_type="image/webp", headers={"Cache-Control": "no-store", "X-Bird-Partial": "1"})
        finals.put(key, body)
        return image(body, "image/webp")

    @router.get("/api/icon", include_in_schema=False)
    def get_icon(request: Request, d: str = "", s: str = ""):
        check(request, icon_limit)
        if not _HOST.match(d or "") or not re.fullmatch(r"[0-9a-f]{24}", s or ""):
            raise err(400, "bad_params", "invalid icon request")
        if not hmac.compare_digest(s, icon_sig(secret, d)):
            raise err(403, "bad_signature", "invalid signature")
        now = time.time()
        hit = icons.get(d)
        if hit and hit[1] > now:
            if hit[0] is None:
                raise err(404, "no_icon", "no icon")
            return image(hit[0], "image/png")
        reg = _registrable(d)

        def same_site(url: str) -> bool:
            m = re.match(r"https://([^/:?#]+)", url)
            return bool(m) and _registrable(m.group(1)) == reg

        png = None
        try:
            _, _, body, _ = upstream(
                f"https://{d}/favicon.ico", None, accept="image/*", types=ICON_TYPES, max_bytes=100_000,
                redirect_ok=same_site,
            )  # fmt: skip
            png = to_icon_png(body)
        except (guard.Blocked, guard.ToolError):
            png = None
        icons.put(d, (png, now + (7 * 86400 if png else 86400)))
        if png is None:
            raise err(404, "no_icon", "no icon")
        return image(png, "image/png")

    router.caches = (finals, icons)
    return router


def to_icon_png(body: bytes) -> bytes | None:
    """A 32x32 RGBA PNG from an ICO/PNG/JPEG/GIF/WebP favicon (largest ICO frame up to 64 px). SVG is refused."""
    from PIL import Image

    if body[:5].lower().startswith(b"<?xml") or b"<svg" in body[:512].lower():
        return None
    try:
        im = Image.open(io.BytesIO(body))
        if im.format == "ICO":
            sizes = sorted((s for s in im.info.get("sizes", ()) if s[0] <= 64), reverse=True)
            if sizes:
                im.size = sizes[0]
        im.load()
        if max(im.size) > 1024:
            return None
        im = im.convert("RGBA").resize((32, 32), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "PNG")
        return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError, SyntaxError):
        return None
