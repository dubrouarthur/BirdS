"""Geocoding and Web-Mercator maths for the places and company widgets. No web framework import.

Providers (all keyless, all through the egress guard, see docs/WEB.md "Widgets"):

- French postal addresses -> Base Adresse Nationale (Géoplateforme geocoder), accepted when its score >= 0.6;
- places and points of interest -> Nominatim (OpenStreetMap), with a bounded viewbox for "near X";
- Photon (komoot) as the fallback when Nominatim fails or finds nothing.

Usage policies are enforced here, in code, for the whole process: at most one request every 1.1 s to Nominatim and
to Photon (OSMF policy: 1 req/s for the whole application), results cached 7 days (1 day for "nothing found"), at
most MAX_LOOKUPS_PER_RUN upstream requests per answer, a generic User-Agent (never a person's name or e-mail), no
cookie, no Referer. Nothing here ever geocodes the text of an attachment: callers pass the user's own words only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode

from birds.harness import guard
from birds.harness.guard import ToolError

MAX_LOOKUPS_PER_RUN = 4
TTL_HIT = 7 * 86400
TTL_MISS = 86400
MAX_WAIT = 3.0
INTERVALS = {  # seconds between two requests to the same host, process-wide
    "nominatim.openstreetmap.org": 1.1,
    "photon.komoot.io": 1.1,
    "data.geopf.fr": 0.05,
    "api-adresse.data.gouv.fr": 0.05,
    "recherche-entreprises.api.gouv.fr": 0.2,
}
DEFAULT_INTERVAL = 1.1  # an operator's own instance gets the conservative default unless listed


# ---------------------------------------------------------------- policy: rate and cache


class Policy:
    """Process-wide request spacing per host and a small TTL cache (optionally mirrored on disk)."""

    def __init__(self, max_entries: int = 1000):
        self.lock = threading.Lock()
        self.next_at: dict[str, float] = {}
        self.cache: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self.max_entries = max_entries
        self.clock, self.sleep = time.monotonic, time.sleep
        self.wall = time.time

    def wait_turn(self, host: str) -> None:
        interval = INTERVALS.get(host, DEFAULT_INTERVAL)
        with self.lock:
            now = self.clock()
            at = max(now, self.next_at.get(host, 0.0))
            if at - now > MAX_WAIT:
                raise ToolError("the map service is busy, try again in a moment")
            self.next_at[host] = at + interval
        if at > now:
            self.sleep(at - now)

    @staticmethod
    def key(*parts) -> str:
        return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()

    def get(self, key: str, disk: str | None = None):
        now = self.wall()
        with self.lock:
            hit = self.cache.get(key)
            if hit and hit[0] > now:
                self.cache.move_to_end(key)
                return hit[1]
        if disk:
            f = Path(disk) / f"{key}.json"
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                if rec["exp"] > now:
                    self.put(key, rec["v"], rec["exp"] - now)
                    return rec["v"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return None

    def put(self, key: str, value, ttl: float, disk: str | None = None) -> None:
        exp = self.wall() + ttl
        with self.lock:
            self.cache[key] = (exp, value)
            self.cache.move_to_end(key)
            while len(self.cache) > self.max_entries:
                self.cache.popitem(last=False)
        if disk:
            try:
                Path(disk).mkdir(parents=True, exist_ok=True)
                (Path(disk) / f"{key}.json").write_text(json.dumps({"exp": exp, "v": value}), encoding="utf-8")
            except OSError:
                pass

    def reset(self) -> None:
        with self.lock:
            self.next_at.clear()
            self.cache.clear()


POLICY = Policy()


def get_json(ctx, url: str, *, xml: bool = False, cache_ttl: float = TTL_HIT, miss=lambda v: not v, count=True):
    """Cached, rate-limited GET of a fixed service URL. Upstream requests count against the per-run cap."""
    cfg = ctx.config
    key = Policy.key("get", url)
    cached = POLICY.get(key, getattr(cfg, "geo_cache_dir", None))
    if cached is not None:
        return cached
    if count:
        if ctx.geo_calls >= MAX_LOOKUPS_PER_RUN:
            raise ToolError("lookup limit of this answer reached")
        ctx.geo_calls += 1
    host = (httpx_host(url) or "").lower()
    POLICY.wait_turn(host)
    ua = getattr(cfg, "geo_user_agent", None) or "BirdHarness/0.1 (+geo)"
    data, size = guard.fetch_json(ctx.http, cfg, url, user_agent=ua, xml=xml)
    ctx.bytes_fetched += size
    POLICY.put(key, data, TTL_MISS if miss(data) else cache_ttl, getattr(cfg, "geo_cache_dir", None))
    return data


def httpx_host(url: str) -> str:
    m = re.match(r"https?://([^/:?#]+)", url)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- places


@dataclass
class Place:
    name: str
    lat: float
    lon: float
    kind: str = ""
    address: str = ""
    detail: str = ""
    hours: str = ""
    website: str = ""
    phone: str = ""
    wiki: str = ""
    source_url: str = ""
    provider: str = ""
    importance: float = 0.0
    distance_m: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


_ADDRESS = re.compile(
    r"\b\d{1,4}\s*(?:bis|ter)?,?\s+(?:rue|avenue|av\.?|bd|boulevard|place|pl\.|chemin|all[ée]e|impasse|quai|route|"
    r"cours|square|passage|rond-point)\s+[^\n,;?!]{2,60}(?:,?\s*\d{5}\s+[A-Za-zÀ-ÿ' -]{2,40})?",
    re.I,
)
_POSTCODE_STREET = re.compile(
    r"\b\d{5}\b.*\b(?:rue|avenue|boulevard|place|chemin|quai|route|allée|impasse)\b|"
    r"\b(?:rue|avenue|boulevard|place|chemin|quai|route|allée|impasse)\b.*\b\d{5}\b",
    re.I,
)
_TOWNS = {"city", "town", "village", "administrative", "municipality", "hamlet", "suburb", "county", "state"}


def find_address(text: str) -> str:
    """The French postal address written in ``text``, or ''."""
    m = _ADDRESS.search(text or "")
    return " ".join(m.group(0).split()).strip(" ,.") if m else ""


def looks_like_address(q: str) -> bool:
    return bool(_ADDRESS.search(q or "") or _POSTCODE_STREET.search(q or ""))


def short_address(a: dict) -> str:
    """'26 boulevard Diderot, 75012 Paris' from a Nominatim address object (French order, no display_name)."""
    a = a or {}
    road = a.get("road") or a.get("pedestrian") or a.get("square") or a.get("place") or ""
    street = " ".join(x for x in (a.get("house_number", ""), road) if x).strip()
    city = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or ""
    tail = " ".join(x for x in (a.get("postcode", ""), city) if x).strip()
    return ", ".join(x for x in (street, tail) if x)


_WIKI = re.compile(r"^([a-z]{2,3}):([^\n]{1,200})$")


def _wiki(tag: str) -> str:
    m = _WIKI.match(tag or "")
    if not m:
        return ""
    from urllib.parse import quote

    return f"https://{m.group(1)}.wikipedia.org/wiki/{quote(m.group(2).replace(' ', '_'))}"


def _osm_url(osm_type: str, osm_id) -> str:
    kind = {"N": "node", "W": "way", "R": "relation"}.get(str(osm_type), str(osm_type))
    if kind not in ("node", "way", "relation") or not str(osm_id).isdigit():
        return ""
    return f"https://www.openstreetmap.org/{kind}/{osm_id}"


def _clean(text, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def from_nominatim(item: dict) -> Place | None:
    try:
        lat, lon = float(item["lat"]), float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    tags = item.get("extratags") or {}
    addr = item.get("address") or {}
    name = _clean(item.get("name") or item.get("namedetails", {}).get("name"), 120)
    kind = str(item.get("type") or item.get("category") or "")
    if not name and kind in ("house", "building", "yes") and addr:
        name = short_address(addr)
    if not name:
        return None
    detail = tags.get("cuisine") or ""
    if tags.get("description"):
        detail = (detail + " · " if detail else "") + _clean(tags["description"], 140)
    website = tags.get("website") or tags.get("contact:website") or ""
    return Place(
        name=name,
        lat=lat,
        lon=lon,
        kind=kind,
        address=short_address(addr),
        detail=_clean(detail, 160),
        hours=_clean(tags.get("opening_hours"), 200),
        website=website if re.match(r"^https?://[^\s<>\"']+$", website) else "",
        phone=_clean(tags.get("phone") or tags.get("contact:phone"), 30),
        wiki=_wiki(tags.get("wikipedia", "")),
        source_url=_osm_url(item.get("osm_type", ""), item.get("osm_id", "")),
        provider="nominatim",
        importance=float(item.get("importance") or 0.0),
    )


def from_photon(feature: dict) -> Place | None:
    try:
        lon, lat = feature["geometry"]["coordinates"][:2]
        lat, lon = float(lat), float(lon)
    except (KeyError, TypeError, ValueError):
        return None
    p = feature.get("properties") or {}
    name = _clean(p.get("name"), 120)
    if not name:
        return None
    street = " ".join(x for x in (p.get("housenumber", ""), p.get("street", "")) if x)
    tail = " ".join(x for x in (p.get("postcode", ""), p.get("city", "")) if x)
    return Place(
        name=name,
        lat=lat,
        lon=lon,
        kind=str(p.get("osm_value") or p.get("type") or ""),
        address=", ".join(x for x in (street, tail) if x),
        source_url=_osm_url(p.get("osm_type", ""), p.get("osm_id", "")),
        provider="photon",
    )


def from_ban(feature: dict) -> Place | None:
    try:
        lon, lat = feature["geometry"]["coordinates"][:2]
        lat, lon = float(lat), float(lon)
    except (KeyError, TypeError, ValueError):
        return None
    p = feature.get("properties") or {}
    label = _clean(p.get("label"), 160)
    if not label:
        return None
    return Place(
        name=_clean(p.get("name"), 120) or label,
        lat=lat,
        lon=lon,
        kind="address" if p.get("type") == "housenumber" else str(p.get("type") or "address"),
        address=label,
        source_url="https://adresse.data.gouv.fr/carte-base-adresse-nationale?"
        + urlencode({"lat": f"{lat:.6f}", "lng": f"{lon:.6f}", "zoom": 18}),
        provider="ban",
        importance=float(p.get("score") or 0.0),
    )


def distance_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> int:
    r = 6_371_000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.asin(math.sqrt(h))))


def _norm(q: str) -> str:
    return " ".join(unicodedata.normalize("NFC", q or "").lower().split())


class Geocoder:
    """Search places for one run (``ctx``: http client, config, per-run counter, bytes meter)."""

    def __init__(self, ctx):
        self.ctx, self.cfg = ctx, ctx.config

    def _url(self, base: str, params: dict) -> str:
        return base + ("&" if "?" in base else "?") + urlencode(params)

    def nominatim(self, q: str, limit: int = 3, viewbox: tuple | None = None, lang: str = "fr") -> list[Place]:
        params = {
            "q": q,
            "format": "jsonv2",
            "addressdetails": 1,
            "extratags": 1,
            "limit": limit,
            "accept-language": lang,
        }
        if viewbox:
            params.update(viewbox=",".join(f"{v:.5f}" for v in viewbox), bounded=1)
        data = get_json(self.ctx, self._url(self.cfg.nominatim_url, params))
        return [p for p in (from_nominatim(x) for x in (data if isinstance(data, list) else [])) if p]

    def photon(self, q: str, limit: int = 3, lang: str = "fr", near: Place | None = None) -> list[Place]:
        params = {"q": q, "limit": limit, "lang": lang if lang in ("fr", "en", "de", "it") else "default"}
        if near:
            params.update(lat=f"{near.lat:.5f}", lon=f"{near.lon:.5f}")
        data = get_json(self.ctx, self._url(self.cfg.photon_url, params))
        feats = data.get("features", []) if isinstance(data, dict) else []
        return [p for p in (from_photon(f) for f in feats) if p]

    def ban(self, q: str, limit: int = 1) -> list[Place]:
        base = self.cfg.ban_url
        params = {"q": q, "limit": limit}
        if "geopf" in base and "index=" not in base:
            params["index"] = "address"
        data = get_json(self.ctx, self._url(base, params))
        feats = data.get("features", []) if isinstance(data, dict) else []
        return [p for p in (from_ban(f) for f in feats) if p]

    def search(self, q: str, *, near: Place | None = None, limit: int = 3, lang: str = "fr") -> list[Place]:
        """Places for ``q``: BAN for a postal address (score >= 0.6), Nominatim otherwise, Photon as fallback.
        With ``near``: a bounded box of about 500 m around it (x3 when fewer than 3 results), nearest first."""
        q = " ".join(str(q or "").split())[:160]
        if not q:
            return []
        if near is None and looks_like_address(q):
            try:
                found = [p for p in self.ban(q) if p.importance >= 0.6]
            except (ToolError, guard.Blocked):
                found = []
            if found:
                return found[:1]
        if near is not None:
            out: list[Place] = []
            for factor in (1, 3):
                d = 0.0045 * factor
                dl = d / max(0.2, math.cos(math.radians(near.lat)))
                box = (near.lon - dl, near.lat + d, near.lon + dl, near.lat - d)
                try:
                    out = self.nominatim(q, limit=max(limit, 8), viewbox=box, lang=lang)
                except ToolError:
                    out = []
                if len(out) >= 3:
                    break
            for p in out:
                p.distance_m = distance_m(near.lat, near.lon, p.lat, p.lon)
            out.sort(key=lambda p: p.distance_m or 0)
            return out[:limit]
        try:
            found = self.nominatim(q, limit=limit, lang=lang)
        except ToolError:
            found = []
        if not found:
            try:
                found = self.photon(q, limit=limit, lang=lang)
            except ToolError:
                found = []
        return found[:limit]


# ---------------------------------------------------------------- Web-Mercator (mirrored in static/widgets.js)

TILE = 256


def world_xy(lat: float, lon: float, z: float) -> tuple[float, float]:
    """Pixel coordinates in the world map at zoom z."""
    lat = max(-85.05112878, min(85.05112878, lat))
    scale = TILE * 2**z
    x = (lon + 180.0) / 360.0 * scale
    phi = math.radians(lat)
    y = (1 - math.log(math.tan(phi) + 1 / math.cos(phi)) / math.pi) / 2 * scale
    return x, y


def fit(
    points: list[tuple[float, float]],
    w: int = 640,
    h: int = 360,
    pad: int = 48,
    zmin: int = 3,
    zmax: int = 17,
    single: int = 16,
) -> tuple[tuple[float, float], int]:
    """(centre (lat, lon), zoom) of a map of w x h pixels that shows every point with ``pad`` pixels of margin."""
    if not points:
        return (46.6, 2.4), 5
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    if len(points) == 1 or (max(lats) - min(lats) < 1e-6 and max(lons) - min(lons) < 1e-6):
        return (points[0][0], points[0][1]), single
    z = zmax
    while z > zmin:
        xs, ys = zip(*(world_xy(la, lo, z) for la, lo in points), strict=True)
        if max(xs) - min(xs) <= w - 2 * pad and max(ys) - min(ys) <= h - 2 * pad:
            break
        z -= 1
    xs, ys = zip(*(world_xy(la, lo, z) for la, lo in points), strict=True)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return unproject(cx, cy, z), z


def unproject(x: float, y: float, z: float) -> tuple[float, float]:
    scale = TILE * 2**z
    lon = x / scale * 360.0 - 180.0
    n = math.pi - 2 * math.pi * y / scale
    lat = math.degrees(math.atan(math.sinh(n)))
    return lat, lon


def single_zoom(kind: str) -> int:
    return 13 if kind in _TOWNS else 16
