"""Pictures of the canvas: ``::: image query="…"`` is resolved by the harness, never by a URL the model wrote.

Server mode: an Openverse search (``search_openverse``: CC0, public-domain mark, CC BY, CC BY-SA only, asked of the
API AND checked again on every result; the result must match the query's words), then Wikimedia Commons (bitmap
files only, licence read on Commons and checked as free: ``office_media.commons_licence``; NC/ND refused). The
credit line (author — licence — source) is kept with the picture, which is fetched through the egress guard and
re-encoded on the server. Results are cached in memory (``CACHE``) so « une autre image » and a second deck on the
same subject do not search again. Demo mode (no network): an abstract illustration drawn here,
labelled as such, never passed off as a photo.

The browser receives the picture as base64 (the app's CSP has no ``data:``; canvas.js turns it into a ``blob:``).
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import time
from urllib.parse import quote

from birds.harness import office_media as om

SHOW_BYTES = 240_000  # a canvas picture: sharp at 1280 px, light enough to travel in the event stream
SEARCH_LIMIT = 10
GEN_CREDIT = {
    "fr": "Illustration générée par Bird (mode démo : aucune image du web)",
    "en": "Illustration drawn by Bird (demo mode: no web picture)",
}


def to_entry(m: om.Media, query: str = "") -> dict:
    """What the browser keeps of one picture: the bytes (base64) and everything the credit needs."""
    return {"id": m.id, "kind": m.kind, "data": base64.b64encode(m.data).decode("ascii"), "fmt": m.fmt,
            "w": m.w, "h": m.h, "alt": m.alt[:160], "title": m.title[:120], "credit": m.credit[:300],
            "licence": m.licence[:120], "source": m.source[:300], "query": query[:120]}  # fmt: skip


OPENVERSE_API = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENCES = {"cc0": "CC0", "pdm": "Domaine public", "by": "CC BY", "by-sa": "CC BY-SA"}
CACHE_SIZE, CACHE_SECONDS = 96, 3600.0


class _Cache:
    """A small in-memory LRU of found pictures: (source, query, excluded) -> Media (or None: nothing found)."""

    def __init__(self, size: int = CACHE_SIZE, ttl: float = CACHE_SECONDS):
        import threading
        from collections import OrderedDict

        self.size, self.ttl, self.lock, self.d = size, ttl, threading.Lock(), OrderedDict()
        self.hits = self.misses = 0

    def get(self, key):
        with self.lock:
            hit = self.d.get(key)
            if hit is None or time.monotonic() - hit[0] > self.ttl:
                self.d.pop(key, None)
                self.misses += 1
                return False, None
            self.d.move_to_end(key)
            self.hits += 1
            return True, hit[1]

    def put(self, key, value) -> None:
        with self.lock:
            self.d[key] = (time.monotonic(), value)
            self.d.move_to_end(key)
            while len(self.d) > self.size:
                self.d.popitem(last=False)

    def clear(self) -> None:
        with self.lock:
            self.d.clear()
            self.hits = self.misses = 0


CACHE = _Cache()


def _renamed(m: om.Media | None, mid: str) -> om.Media | None:
    if m is None:
        return None
    import copy

    out = copy.copy(m)
    out.id = mid
    return out


def relevant(query: str, title: str, tags: list[str] | None = None) -> bool:
    """Does a result speak of the query? At least one of the query's words (or its first 5 letters: « tramways »
    ~ « tramway ») is in the title or the tags. A picture that matches nothing is not shown: no image rather than
    a wrong one."""
    want = om.words(query)
    if not want:
        return False
    have = om.words(title + " " + " ".join(tags or []))
    stems = {w[:5] for w in have}
    return any(w in have or w[:5] in stems for w in want)


def openverse_licence(r: dict) -> str | None:
    """'CC BY-SA 4.0' for a result whose licence allows reuse with a credit, else None (NC, ND, unknown)."""
    lic = str(r.get("license") or "").lower()
    if lic not in OPENVERSE_LICENCES:
        return None
    ver = str(r.get("license_version") or "").strip()
    name = OPENVERSE_LICENCES[lic]
    return f"{name} {ver}".strip() if lic != "pdm" and re.fullmatch(r"\d(?:\.\d)?", ver or "x") else name


def _big_url(r: dict) -> str:
    """The picture to fetch: a 1280 px Commons thumbnail for a Commons file, the original when small enough, else
    Openverse's own thumbnail."""
    url = str(r.get("url") or "")
    name = om.commons_file(url)
    if name and "/thumb/" not in url:
        m = re.match(r"^(https://upload\.wikimedia\.org/wikipedia/commons)/([0-9a-f]/[0-9a-f]{2})/([^/]+)$", url)
        if m and (r.get("width") or 0) > 1280:
            return f"{m.group(1)}/thumb/{m.group(2)}/{m.group(3)}/1280px-{m.group(3)}"
    if url.startswith("https://") and (r.get("filesize") or 0) <= 3_500_000:
        return url
    return str(r.get("thumbnail") or "")


def search_openverse(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
                     deadline: float | None = None) -> om.Media | None:  # fmt: skip
    """The first relevant, free-licence Openverse picture for ``query`` (sources in ``exclude`` skipped)."""
    q = re.sub(r"\s+", " ", str(query or "")).strip()[:120]
    if not q or fetch is None:
        return None
    key = ("openverse", q.lower(), tuple(sorted(exclude or [])))
    hit, m = CACHE.get(key)
    if hit:
        return _renamed(m, mid)
    url = (f"{OPENVERSE_API}?q={quote(q)}&license={','.join(OPENVERSE_LICENCES)}&page_size={SEARCH_LIMIT}"
           "&mature=false")  # fmt: skip
    try:
        results = fetch.json(url).get("results") or []
    except Exception:  # noqa: BLE001 - no picture rather than a failed turn
        return None
    skip = set(exclude or [])
    found = None
    for r in results:
        if deadline is not None and time.monotonic() > deadline:
            break
        if not isinstance(r, dict) or r.get("mature") or r.get("unstable__sensitivity"):
            continue
        lic = openverse_licence(r)
        title = str(r.get("title") or "")
        tags = [str(t.get("name") or "") for t in r.get("tags") or [] if isinstance(t, dict)]
        source = str(r.get("foreign_landing_url") or r.get("url") or "")
        if not lic or source in skip or str(r.get("url") or "") in skip:
            continue
        if str(r.get("filetype") or "").lower() in ("svg", "gif", "tif", "tiff", "pdf"):
            continue
        if not relevant(q, title, tags):
            continue
        creator = re.sub(r"\s+", " ", str(r.get("creator") or "")).strip()[:100]
        if not creator and not lic.startswith(("CC0", "Domaine")):
            continue  # a CC BY licence needs its author
        big = _big_url(r)
        if not big.startswith("https://"):
            continue
        try:
            raw = fetch.image(big)
            m = om.prepare(raw, mid, "web", max_bytes=SHOW_BYTES, alt=q, title=title[:120], licence=lic,
                           source=source[:300])  # fmt: skip
        except Exception:  # noqa: BLE001 - this file fails, the next one may not
            continue
        if m.w < 400 or m.h < 260:
            continue
        provider = str(r.get("provider") or r.get("source") or "").replace("_", " ").title()[:40]
        m.credit = f"{creator or 'Domaine public'} — {lic} — {provider + ' via ' if provider else ''}Openverse"
        found = m
        break
    CACHE.put(key, found)
    return _renamed(found, mid)


def search_commons(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
                   deadline: float | None = None) -> om.Media | None:  # fmt: skip
    """The first free-licence Commons photograph for ``query`` (files in ``exclude``, by source URL, skipped)."""
    q = re.sub(r"\s+", " ", str(query or "")).strip()[:120]
    if not q or fetch is None:
        return None
    key = ("commons", q.lower(), tuple(sorted(exclude or [])))
    hit, cached = CACHE.get(key)
    if hit:
        return _renamed(cached, mid)
    url = (f"{om.COMMONS_API}?action=query&format=json&formatversion=2&generator=search&gsrnamespace=6"
           f"&gsrlimit={SEARCH_LIMIT}&gsrsearch={quote(q + ' filetype:bitmap')}&prop=imageinfo"
           f"&iiprop=url|extmetadata|size|mime&iiurlwidth=1280")  # fmt: skip
    try:
        pages = (fetch.json(url).get("query") or {}).get("pages") or []
    except Exception:  # noqa: BLE001 - no picture rather than a failed turn
        return None
    pages = sorted((p for p in pages if isinstance(p, dict)), key=lambda p: p.get("index", 99))
    skip = set(exclude or [])
    for p in pages:
        if deadline is not None and time.monotonic() > deadline:
            break
        title = str(p.get("title") or "")
        if re.search(r"\.(svg|tiff?|pdf|djvu|gif)$", title, re.I):
            continue
        info = (p.get("imageinfo") or [{}])[0]
        lic = om.commons_licence(info)
        if not lic or not str(lic.get("thumb") or "").startswith("https://upload.wikimedia.org/"):
            continue
        if lic.get("url") in skip or title in skip:
            continue
        try:
            raw = fetch.image(lic["thumb"])
            name = re.sub(r"^File:", "", title)
            label = re.sub(r"\.[a-z]{3,4}$", "", name, flags=re.I).replace("_", " ")[:120]
            m = om.prepare(raw, mid, "web", max_bytes=SHOW_BYTES, alt=q, title=label, licence=lic["licence"],
                           source=lic["url"] or f"https://commons.wikimedia.org/wiki/{quote(title)}")  # fmt: skip
        except Exception:  # noqa: BLE001 - this file fails, the next one may not
            continue
        m.credit = f"{lic['author']} — {lic['licence']} — Wikimedia Commons"
        if m.w < 400 or m.h < 260:
            continue
        CACHE.put(key, m)
        return _renamed(m, mid)
    CACHE.put(key, None)
    return None


def search_web(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
               deadline: float | None = None) -> om.Media | None:  # fmt: skip
    """Openverse first (wider: Flickr, museums, Commons), then Commons directly."""
    return search_openverse(query, fetch, exclude, mid, deadline) or search_commons(query, fetch, exclude, mid,
                                                                                    deadline)


_PALETTES = {
    "corporate": ((11, 27, 63), (30, 91, 216), (127, 164, 238), (226, 233, 248)),
    "modern": ((17, 24, 39), (13, 148, 136), (99, 102, 241), (204, 251, 241)),
    "forest": ((16, 42, 30), (46, 125, 82), (143, 196, 132), (221, 238, 214)),
    "night": ((10, 14, 26), (91, 141, 239), (167, 139, 250), (40, 48, 72)),
    "warm": ((59, 31, 20), (194, 65, 12), (232, 162, 107), (253, 231, 215)),
}


def generated(query: str, mid: str = "g1", theme: str | None = None, lang: str = "fr") -> om.Media:
    """An abstract, theme-coloured illustration for ``query`` (demo mode): soft shapes, no text, deterministic."""
    from PIL import Image, ImageDraw, ImageFilter

    seed = int(hashlib.sha256(str(query).encode("utf-8")).hexdigest()[:12], 16)
    pal = _PALETTES.get(theme or "corporate", _PALETTES["corporate"])
    w, h = 1280, 800
    small = Image.new("RGB", (16, 10))
    a, b = pal[0], pal[1]
    for y in range(10):  # a diagonal gradient, drawn small then smoothed up
        for x in range(16):
            t = min(1.0, max(0.0, (x / 15) * 0.6 + (y / 9) * 0.4))
            small.putpixel((x, y), tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3)))
    im = small.resize((w, h), Image.BICUBIC)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rnd = seed
    for k in range(7):
        rnd = (rnd * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        cx, cy = (rnd >> 8) % w, (rnd >> 24) % h
        r = 90 + (rnd >> 40) % 260
        col = pal[2] if k % 2 else pal[3]
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*col, 70 + (rnd >> 50) % 70))
    layer = layer.filter(ImageFilter.GaussianBlur(28))
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    m = om.prepare(buf.getvalue(), mid, "user", max_bytes=SHOW_BYTES, alt=str(query)[:160], title=str(query)[:120])
    m.kind = "gen"
    m.credit = GEN_CREDIT["en" if lang == "en" else "fr"]
    return m


def next_media_id(doc: dict, prefix: str = "w") -> str:
    used = set((doc.get("media") or {}).keys())
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def resolve(doc: dict, find, limit: int = 4, deadline: float | None = None) -> list[dict]:
    """Give a picture to the image parts that have none (at most ``limit`` searches). ``find(query, exclude, mid)``
    returns a Media or None. Returns the browser entries of the pictures found; ``doc['media']`` gets their
    metadata and each part its ``media`` id. A part with no picture found keeps its query (the canvas shows a
    placeholder with « Chercher une image »), nothing is made up."""
    found = []
    tries = 0
    cache: dict[str, str] = {}
    cover = doc.get("cover") if doc.get("kind") == "deck" else None
    targets = [cover] if isinstance(cover, dict) and not cover.get("off") else []
    for b in doc.get("blocks") or []:
        targets += [p for p in b.get("parts") or [] if p.get("t") == "image"]
    for b in [{"parts": targets}]:
        for p in b.get("parts") or []:
            if p.get("media"):
                continue
            q = str(p.get("query") or "").strip()
            if not q:
                continue
            if q.lower() in cache and not p.get("exclude"):
                p["media"] = cache[q.lower()]
                continue
            if tries >= limit or (deadline is not None and time.monotonic() > deadline):
                p["pending"] = True
                continue
            tries += 1
            exclude = []
            for mid in p.get("exclude") or []:
                src = ((doc.get("media") or {}).get(mid) or {}).get("source")
                exclude.append(src or mid)  # a drawn illustration has no source: its id is enough
            m = find(q, exclude, next_media_id(doc, "w"))
            p.pop("exclude", None)
            p.pop("pending", None)
            if m is None:
                p["missing"] = True
                continue
            entry = to_entry(m, q)
            doc.setdefault("media", {})[m.id] = {k: entry[k] for k in ("kind", "alt", "credit", "licence", "source",
                                                                        "w", "h", "query", "title")}  # fmt: skip
            p["media"] = m.id
            p.pop("missing", None)
            cache[q.lower()] = m.id
            found.append(entry)
    return found


def finder(mode: str, fetch=None, theme: str | None = None, lang: str = "fr"):
    """The ``find`` function for ``resolve``: Commons in server mode, the drawn illustration in demo mode."""
    if mode == "demo":
        return lambda q, exclude, mid: generated(q + "|" + "|".join(exclude), mid.replace("w", "g", 1), theme, lang)
    return lambda q, exclude, mid: search_web(q, fetch, exclude, mid)
