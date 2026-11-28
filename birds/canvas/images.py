"""Pictures of the canvas: ``::: image query="…"`` is resolved by the harness, never by a URL the model wrote.

Server mode: a Wikimedia Commons search (bitmap files only), licence read on Commons and checked as free
(``office_media.commons_licence``: CC0, public domain, CC BY, CC BY-SA; NC/ND refused), credit line kept, picture
fetched through the egress guard and re-encoded. Demo mode (no network): an abstract illustration drawn here,
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


def search_commons(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
                   deadline: float | None = None) -> om.Media | None:  # fmt: skip
    """The first free-licence Commons photograph for ``query`` (files in ``exclude``, by source URL, skipped)."""
    q = re.sub(r"\s+", " ", str(query or "")).strip()[:120]
    if not q or fetch is None:
        return None
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
        return m
    return None


_PALETTES = {
    "corporate": ((11, 27, 63), (30, 91, 216), (127, 164, 238), (226, 233, 248)),
    "modern": ((17, 24, 39), (13, 148, 136), (99, 102, 241), (204, 251, 241)),
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
    for b in doc.get("blocks") or []:
        for p in b.get("parts") or []:
            if p.get("t") != "image" or p.get("media"):
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
    return lambda q, exclude, mid: search_commons(q, fetch, exclude, mid)
