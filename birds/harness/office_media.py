"""Pictures for the office files: the user's attached images, free-licence web images (Wikimedia Commons), charts
drawn with Pillow (documents; decks use native charts) and maps stitched from map tiles.

Every picture is re-encoded here (never the bytes as received): EXIF/GPS and anything hidden in the file are
dropped, the long side is bounded, the format is the one Office reads best (JPEG for photos, PNG when there is
transparency), and the size is capped so a deck or a document stays well under the 4.5 MB response limit of the
serverless deployment. A web image goes in only when its licence allows reuse (CC0, public domain, CC BY,
CC BY-SA) and its author and licence are known: the credit is written into the file next to it. No network call is
made from here except through a ``Fetcher`` (guard-checked, injectable in tests).
"""

from __future__ import annotations

import base64
import html
import io
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

USER_DIR = ".bird_images"  # where the web backend leaves the images attached to the message (re-encoded copies)
MAX_SIDE = 1600  # long side of a placed picture, px (13.3 in slide at ~120 dpi: sharp on screen and projector)
MAX_IMAGE_BYTES = 420_000
MAX_TOTAL_BYTES = 2_200_000  # all the pictures of one file
MAX_MEDIA = 10
MAX_PIXELS = 40_000_000  # refuse to decode bigger (decompression bombs)
THUMB_SIDE = 360  # preview thumbnails (the chat), JPEG
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


@dataclass
class Media:
    """One picture ready to be placed. ``data`` is JPEG or PNG; ``kind`` user | web | map | chart."""

    id: str
    kind: str
    data: bytes = b""
    fmt: str = "jpeg"
    w: int = 0
    h: int = 0
    alt: str = ""
    title: str = ""
    credit: str = ""  # one line written next to the picture ('Photo : X — CC BY-SA 4.0 — Wikimedia Commons')
    licence: str = ""
    source: str = ""  # the page the picture comes from (web, map)
    logo: bool = False
    spec: dict = field(default_factory=dict)  # kind chart: the chart's columns/rows/type/unit/title

    @property
    def ratio(self) -> float:
        return self.w / self.h if self.w and self.h else 1.5

    def meta(self) -> dict:
        """What the editor needs to know of it (no bytes)."""
        out = {"id": self.id, "kind": self.kind, "alt": self.alt[:160], "w": self.w, "h": self.h}
        for k in ("title", "credit", "licence", "source"):
            if getattr(self, k):
                out[k] = getattr(self, k)[:300]
        if self.logo:
            out["logo"] = 1
        if self.spec:
            out["spec"] = self.spec
        return out


class ImageError(ValueError):
    pass


def _sniff(raw: bytes) -> str:
    for magic, fmt in _MAGIC:
        if raw.startswith(magic):
            return fmt
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return ""


def _open(raw: bytes):
    """A decoded first frame (RGB or RGBA), oriented, or ImageError. Bounded before decoding."""
    import warnings

    from PIL import Image, ImageOps

    if not _sniff(raw):
        raise ImageError("not a PNG, JPEG, GIF or WebP image")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(raw))
        w, h = im.size
        if w * h > MAX_PIXELS or min(w, h) < 16:
            raise ImageError("image too large or too small")
        im.seek(0)
        if im.format == "JPEG":
            im.draft("RGB", (2 * MAX_SIDE, 2 * MAX_SIDE))
        im.load()
        im = ImageOps.exif_transpose(im)
        alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        im = im.convert("RGBA" if alpha else "RGB")
        if alpha and im.getextrema()[3][0] >= 250:  # an alpha channel that hides nothing
            im = im.convert("RGB")
        return im
    except ImageError:
        raise
    except Exception as e:  # noqa: BLE001 - truncated, corrupt, bomb
        raise ImageError("this image cannot be read") from e


def encode(im, max_bytes: int = MAX_IMAGE_BYTES, max_side: int = MAX_SIDE) -> tuple[bytes, str, int, int]:
    """(bytes, 'jpeg'|'png', w, h): JPEG for opaque pictures, PNG for transparent ones (logos), reduced until it
    fits ``max_bytes`` (quality first, then size)."""
    from PIL import Image

    im = im.copy()
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    for _ in range(8):
        buf = io.BytesIO()
        if im.mode == "RGBA":
            im.save(buf, "PNG", optimize=True)
            fmt = "png"
        else:
            fmt = "jpeg"
            for q in (86, 78, 70, 62):
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
                if buf.tell() <= max_bytes:
                    break
        if buf.tell() <= max_bytes or max(im.size) <= 320:
            return buf.getvalue(), fmt, im.size[0], im.size[1]
        im.thumbnail((int(im.size[0] * 0.8), int(im.size[1] * 0.8)), Image.LANCZOS)
    return buf.getvalue(), fmt, im.size[0], im.size[1]


def prepare(raw: bytes, mid: str, kind: str, max_bytes: int = MAX_IMAGE_BYTES, **meta) -> Media:
    im = _open(raw)
    data, fmt, w, h = encode(im, max_bytes)
    return Media(id=mid, kind=kind, data=data, fmt=fmt, w=w, h=h, **meta)


def cropped(m: Media, ratio: float, focus: float = 0.4) -> bytes:
    """The picture cut to ``ratio`` (w/h), centred across, ``focus`` of the way down (faces sit high in photos).
    A logo or a chart is never cut: the picture is returned as is."""
    if m.logo or m.kind == "chart" or not m.data or abs(m.ratio - ratio) < 0.02:
        return m.data
    im = _open(m.data)
    w, h = im.size
    if w / h > ratio:  # too wide: cut the sides
        nw = int(h * ratio)
        box = ((w - nw) // 2, 0, (w - nw) // 2 + nw, h)
    else:
        nh = int(w / ratio)
        top = int((h - nh) * focus)
        box = (0, top, w, top + nh)
    out, _, _, _ = encode(im.crop(box), MAX_IMAGE_BYTES)
    return out


def thumb(data: bytes, side: int = THUMB_SIDE) -> str:
    """A small JPEG of a picture, base64 (the chat preview turns it into a blob: URL; the CSP has no data:)."""
    from PIL import Image

    im = _open(data)
    if im.mode == "RGBA":  # a logo on white, as it sits on the slide or page
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    im.thumbnail((side, side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=68, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def budget(media: list[Media], total: int = MAX_TOTAL_BYTES) -> list[Media]:
    """At most MAX_MEDIA pictures and ``total`` bytes: the biggest are re-encoded smaller, the rest kept in order."""
    media = media[:MAX_MEDIA]
    for _ in range(4):
        size = sum(len(m.data) for m in media)
        if size <= total:
            break
        share = total // max(1, len(media))
        for m in media:
            if len(m.data) > share and m.data:
                m.data, m.fmt, m.w, m.h = encode(_open(m.data), max(60_000, share))
    while media and sum(len(m.data) for m in media) > total:
        media.pop()
    return media


# ------------------------------------------------------------------ words (relevance of a picture to a slide)

_STOP = set(
    "le la les un une des de du d l et en au aux pour par sur dans avec sans the a an of and in on for to by with "
    "est sont qui que quoi vos nos notre votre leur leurs ce cet cette ces se sa son ses il elle ils elles nous vous "
    "plus moins tres très entre comme mais ou où".split()
)


def words(text: str) -> set[str]:
    flat = unicodedata.normalize("NFKD", str(text or "").lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]{3,}", flat) if w not in _STOP}


# ------------------------------------------------------------------ the user's own pictures

_LOGO = re.compile(r"logo|brand|marque|embl[eè]me|charte", re.I)


def user_images(workspace: Path, request: str = "") -> list[Media]:
    """The images attached to the message, as the web backend left them in <workspace>/.bird_images."""
    d = Path(workspace) / USER_DIR
    if not d.is_dir():
        return []
    out = []
    for i, p in enumerate(sorted(d.iterdir(), key=lambda p: p.name)[:MAX_MEDIA], 1):
        try:
            raw = p.read_bytes()[:20_000_000]
            name = re.sub(r"^\d+-", "", p.name)
            stem = Path(name).stem
            m = prepare(raw, f"u{i}", "user", alt=re.sub(r"[_-]+", " ", stem)[:120], title=name[:120])
        except (ImageError, OSError):
            continue
        m.logo = bool(_LOGO.search(name)) or (bool(_LOGO.search(request)) and m.fmt == "png" and len(out) == 0)
        out.append(m)
    return out


def from_data_url(url: str, mid: str, alt: str = "") -> Media:
    m = re.match(r"^data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=\s]+)$", str(url or ""))
    if not m:
        raise ImageError("images must be PNG, JPEG, GIF or WebP data URLs")
    raw = base64.b64decode(m.group(2))
    return prepare(raw, mid, "user", alt=alt[:160])


# ------------------------------------------------------------------ web pictures (Wikimedia Commons only)

_FREE = re.compile(r"^(?:cc0|cc[ -]?zero|public domain|pd\b|pd-|cc[ -]by(?:-sa)?(?:[ -]\d(?:\.\d)?)?\b)", re.I)
_NOT_FREE = re.compile(r"\bnc\b|\bnd\b|non[- ]?commercial|no ?deriv|fair use|non-free|copyrighted", re.I)


def commons_file(src: str) -> str | None:
    """'Name.jpg' for a Wikimedia Commons upload URL (thumbnail or original), else None. Pictures stored on a
    single Wikipedia (non-free files, fair use) are not Commons files and are refused."""
    u = urlsplit(str(src or ""))
    if (u.hostname or "").lower() != "upload.wikimedia.org":
        return None
    m = re.match(r"^/wikipedia/commons/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/]+)", u.path)
    return unquote(m.group(1)) if m else None


def _clean_html(value) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(text).split())


def commons_licence(info: dict) -> dict | None:
    """{licence, author, url, thumb, w, h} when the Commons file's licence allows reuse with a credit, else None."""
    meta = info.get("extmetadata") or {}

    def v(key):
        return _clean_html((meta.get(key) or {}).get("value"))

    lic = v("LicenseShortName") or v("UsageTerms")
    if not lic or not _FREE.search(lic) or _NOT_FREE.search(lic) or v("NonFree").lower() in ("true", "1", "yes"):
        return None
    author = v("Artist") or v("Credit")
    public = re.search(r"public domain|^pd|cc0|zero", lic, re.I)
    if not author and not public:
        return None  # a CC BY licence needs its author: no credit line, no picture
    return {
        "licence": lic[:60],
        "author": author[:100] or ("Domaine public" if public else ""),
        "url": info.get("descriptionurl") or "",
        "thumb": info.get("thumburl") or info.get("url") or "",
    }


class Fetcher:
    """Network access for pictures, through the harness egress guard (check_url on every hop, DNS pinning, size
    caps, no cookie). Tests pass a fake with the same two methods."""

    def __init__(self, http, cfg):
        self.http, self.cfg = http, cfg

    def image(self, url: str) -> bytes:
        from birds.harness import guard

        _, raw = guard.fetch_image(self.http, self.cfg, url, max_bytes=4_000_000, timeout=8.0)
        return raw

    def json(self, url: str) -> dict:
        import json

        from birds.harness import guard

        status, _, body, _ = guard.fetch_bytes(
            self.http, self.cfg, url, accept="application/json", types=("application/json",), max_bytes=400_000,
            user_agent=guard.IMAGE_USER_AGENT, timeout=8.0,
        )  # fmt: skip
        if status != 200:
            raise ValueError(f"HTTP {status}")
        return json.loads(body.decode("utf-8", "replace"))

    def tile(self, url: str, headers=None):
        from birds.harness import guard

        return guard.fetch_bytes(
            self.http, self.cfg, url, accept="image/png,image/jpeg", types=("image/png", "image/jpeg"),
            max_bytes=400_000, user_agent="BirdHarness/0.1 (+office map; OSM tile policy)", headers=headers,
        )  # fmt: skip


COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def web_images(candidates: list[dict], fetch, topic: str, limit: int = 4, start: int = 1,
               deadline: float | None = None) -> list[Media]:  # fmt: skip
    """Free-licence pictures among the research step's candidates: Commons files only (Wikipedia thumbnails),
    relevant to ``topic`` (a content word in common), licence checked on Commons, credit captured. Page images
    (og:image) carry no licence: they are skipped."""
    if fetch is None:
        return []
    topic_w = words(topic)
    out, seen = [], set()
    for c in candidates or []:
        if len(out) >= limit or not isinstance(c, dict) or (deadline is not None and time.monotonic() > deadline):
            break
        name = commons_file(str(c.get("src") or ""))
        if not name or name in seen or re.search(r"\.(svg|tiff?|pdf|djvu)$", name, re.I):
            continue  # logos, maps and scans are SVG/TIFF/PDF: not photographs to illustrate a slide
        seen.add(name)
        label = " ".join(str(c.get(k) or "") for k in ("title", "alt"))
        if topic_w and not (words(label + " " + name.replace("_", " ")) & topic_w):
            continue
        try:
            q = (f"{COMMONS_API}?action=query&format=json&formatversion=2&prop=imageinfo"
                 f"&iiprop=url|extmetadata|size&iiurlwidth=1280&titles={quote('File:' + name)}")  # fmt: skip
            pages = (fetch.json(q).get("query") or {}).get("pages") or []
            info = ((pages[0] if pages else {}).get("imageinfo") or [{}])[0]
            lic = commons_licence(info)
            if not lic or not lic["thumb"].startswith("https://upload.wikimedia.org/"):
                continue
            raw = fetch.image(lic["thumb"])
            title = str(c.get("title") or "").strip() or Path(name).stem.replace("_", " ")
            m = prepare(raw, f"w{start + len(out)}", "web", alt=(str(c.get("alt") or "") or title)[:160],
                        title=title[:120], licence=lic["licence"], source=lic["url"] or str(c.get("page") or ""))  # fmt: skip
            m.credit = f"{lic['author']} — {lic['licence']} — Wikimedia Commons"
        except Exception:  # noqa: BLE001 - one picture that fails is left out, never the whole file
            continue
        if m.w < 400 or m.h < 260:
            continue  # too small to fill half a slide decently
        out.append(m)
    return out


# ------------------------------------------------------------------ maps (OpenStreetMap tiles, pins drawn here)

OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_CREDIT = "© OpenStreetMap contributors"


def map_image(places: list[dict], fetch, mid: str = "m1", title: str = "", w: int = 1280, h: int = 720) -> Media | None:
    """A map of the places found in the run (numbered pins), or None. Tiles go through the same tile cache class as
    /api/map (2 concurrent downloads, per-minute budget)."""
    if fetch is None:
        return None
    pts = [(float(p["lat"]), float(p["lon"])) for p in places if p.get("lat") is not None and p.get("lon") is not None]
    if not pts:
        return None
    try:
        from PIL import Image, ImageDraw

        from birds.harness import geo
        from birds.web.mapimg import Tiles, render_map

        center, z = geo.fit(pts, w // 2, h // 2, pad=40, single=15)
        tiles = Tiles(fetch.tile)
        body, partial, _, _ = render_map(center, z, tiles, OSM_TILES, OSM_CREDIT, w // 2, h // 2, scale=2)
        if partial:
            return None
        im = Image.open(io.BytesIO(body)).convert("RGB")
        draw = ImageDraw.Draw(im)
        font = _font(22, bold=True)
        cx, cy = geo.world_xy(center[0], center[1], z + 1)
        for i, (la, lo) in enumerate(pts[:12], 1):
            x, y = geo.world_xy(la, lo, z + 1)
            x, y = x - cx + w / 2, y - cy + h / 2
            r = 17
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(30, 91, 216), outline=(255, 255, 255), width=4)
            label = str(i) if len(pts) > 1 else "•"
            box = draw.textbbox((0, 0), label, font=font)
            draw.text((x - (box[2] - box[0]) / 2 - box[0], y - (box[3] - box[1]) / 2 - box[1]), label,
                      fill=(255, 255, 255), font=font)  # fmt: skip
        data, fmt, mw, mh = encode(im, 380_000)
    except Exception:  # noqa: BLE001 - no map rather than a broken file
        return None
    names = ", ".join(str(p.get("name") or "") for p in places[:4] if p.get("name"))
    return Media(id=mid, kind="map", data=data, fmt=fmt, w=mw, h=mh, alt=(title or names)[:160], title=title[:120],
                 credit=OSM_CREDIT, licence="ODbL", source="https://www.openstreetmap.org/copyright")  # fmt: skip


# ------------------------------------------------------------------ charts drawn with Pillow (documents)

_FONTS = Path(__file__).resolve().parent.parent / "web" / "static" / "fonts"


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(str(_FONTS / f"carlito-{'bold' if bold else 'regular'}.woff2"), size)
    except OSError:
        return ImageFont.load_default(size=size)


def _hex(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def fmt_num(v: float, lang: str = "fr") -> str:
    if v is None:
        return ""
    s = f"{v:,.1f}" if abs(v) < 100 and not float(v).is_integer() else f"{v:,.0f}"
    if lang == "fr":
        s = s.replace(",", " ").replace(".", ",")
    return s


def chart_png(spec: dict, colors: list[str], ink: str = "121A2E", muted: str = "586078", hair: str = "D9DEE8",
              lang: str = "fr", w: int = 1600, h: int = 820) -> bytes:  # fmt: skip
    """A clean chart image (bar, line or pie as a doughnut) at print resolution, PNG. Values labelled, light grid."""
    from PIL import Image, ImageDraw

    cols = [str(c) for c in spec.get("columns") or []]
    rows = [r for r in spec.get("rows") or [] if isinstance(r, list) and r]
    kind = spec.get("type") or "bar"
    unit = str(spec.get("unit") or "")
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f_lab, f_val, f_leg = _font(26), _font(26, bold=True), _font(26)
    series = cols[1:] or [""]
    labels = [str(r[0]) for r in rows]
    values = [[(float(r[j]) if j < len(r) and isinstance(r[j], int | float) else None) for j in range(1, len(series) + 1)]
              for r in rows]  # fmt: skip
    pal = [_hex(c) for c in colors] or [(30, 91, 216)]
    top = 40
    if len(series) > 1 or kind == "pie":  # legend
        x = 60
        items = series if kind != "pie" else labels
        for i, name in enumerate(items[:8]):
            d.rectangle((x, top + 6, x + 22, top + 28), fill=pal[i % len(pal)])
            d.text((x + 32, top), name[:28], fill=_hex(ink), font=f_leg)
            x += 32 + int(d.textlength(name[:28], font=f_leg)) + 40
        top += 60
    if kind == "pie":
        vals = [max(0.0, v[0] or 0.0) for v in values]
        total = sum(vals) or 1
        r = min(w, h - top) // 2 - 40
        cx, cy = w // 2, top + (h - top) // 2
        a = -90.0
        for i, v in enumerate(vals):
            sweep = 360 * v / total
            d.pieslice((cx - r, cy - r, cx + r, cy + r), a, a + sweep, fill=pal[i % len(pal)], outline=(255, 255, 255),
                       width=4)  # fmt: skip
            import math

            mid = math.radians(a + sweep / 2)
            if sweep > 14:
                lx, ly = cx + math.cos(mid) * r * 0.78, cy + math.sin(mid) * r * 0.78
                t = f"{round(100 * v / total)} %"
                d.text((lx - d.textlength(t, font=f_val) / 2, ly - 14), t, fill=(255, 255, 255), font=f_val)
            a += sweep
        d.ellipse((cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5), fill=(255, 255, 255))
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
        return out.getvalue()
    flat = [v for row in values for v in row if v is not None]
    vmax = max(flat + [0.0]) or 1.0
    vmin = min(flat + [0.0])
    left, right, bottom = 110, w - 40, h - 90
    span_v = (vmax - vmin) or 1.0
    # grid: 4 steps on a round scale
    import math

    step = 10 ** math.floor(math.log10(span_v / 4)) if span_v > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if span_v / (step * m) <= 5:
            step *= m
            break
    lo = math.floor(vmin / step) * step
    hi = math.ceil(vmax / step) * step
    hi = hi if hi > lo else lo + step

    def y_of(v):
        return bottom - (v - lo) / (hi - lo) * (bottom - top - 30)

    g = lo
    while g <= hi + 1e-9:
        y = y_of(g)
        d.line((left, y, right, y), fill=_hex(hair), width=2)
        t = fmt_num(g, lang)
        d.text((left - 16 - d.textlength(t, font=f_lab), y - 14), t, fill=_hex(muted), font=f_lab)
        g += step
    n, k = len(rows), len(series)
    slot = (right - left) / max(1, n)
    for i, lab in enumerate(labels):
        t = (
            lab
            if d.textlength(lab, font=f_lab) <= slot - 8
            else lab[: max(3, int(len(lab) * (slot - 8) / max(1, d.textlength(lab, font=f_lab))) - 1)] + "…"
        )  # noqa: E501
        d.text((left + slot * (i + 0.5) - d.textlength(t, font=f_lab) / 2, bottom + 18), t, fill=_hex(ink), font=f_lab)
    if kind == "line":
        for j in range(k):
            pts = [(left + slot * (i + 0.5), y_of(values[i][j])) for i in range(n) if values[i][j] is not None]
            if len(pts) > 1:
                d.line(pts, fill=pal[j % len(pal)], width=6, joint="curve")
            for i, (x, y) in enumerate(pts):
                d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(255, 255, 255), outline=pal[j % len(pal)], width=5)
                if k == 1 and (n <= 12):
                    t = fmt_num(values[i][j], lang)
                    d.text((x - d.textlength(t, font=f_val) / 2, y - 46), t, fill=_hex(ink), font=f_val)
    else:
        bw = slot * 0.64 / k
        for i in range(n):
            for j in range(k):
                v = values[i][j]
                if v is None:
                    continue
                x0 = left + slot * i + slot * 0.18 + j * bw
                y0, y1 = sorted((y_of(v), y_of(max(lo, 0.0))))
                d.rectangle((x0, y0, x0 + bw - 4, y1), fill=pal[j % len(pal)])
                if n * k <= 16:
                    t = fmt_num(v, lang)
                    d.text(
                        (x0 + (bw - 4) / 2 - d.textlength(t, font=f_val) / 2, y0 - 38), t, fill=_hex(ink), font=f_val
                    )
    d.line((left, y_of(max(lo, 0.0)), right, y_of(max(lo, 0.0))), fill=_hex(muted), width=2)
    if unit:
        d.text((left - 90, top - 6 if top > 40 else 4), unit[:12], fill=_hex(muted), font=f_lab)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


def chart_media(spec: dict, mid: str) -> Media:
    """A chart from make_chart (or a table of figures): kept as data, drawn natively in decks and as a picture in
    documents."""
    keep = {k: spec[k] for k in ("title", "type", "columns", "rows", "unit", "source") if k in spec}
    return Media(id=mid, kind="chart", alt=str(spec.get("title") or "")[:160], title=str(spec.get("title") or "")[:120],
                 spec=keep, w=16, h=9)  # fmt: skip


def chart_spec_ok(spec) -> bool:
    """A chart spec that came back from the browser (editor): small, flat, numeric."""
    if not isinstance(spec, dict):
        return False
    cols, rows = spec.get("columns"), spec.get("rows")
    if not isinstance(cols, list) or not 2 <= len(cols) <= 7 or not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        return False
    if spec.get("type") not in ("bar", "line", "pie"):
        return False
    for r in rows:
        if not isinstance(r, list) or len(r) != len(cols) or not isinstance(r[0], str | int | float):
            return False
        if not all(v is None or (isinstance(v, int | float) and not isinstance(v, bool)) for v in r[1:]):
            return False
    return all(isinstance(c, str) and len(c) <= 80 for c in cols)


def keep_user_images(workspace: Path, images: list[dict], texts: dict[str, str] | None = None) -> int:
    """Leave the pictures attached to the message in <workspace>/.bird_images (re-encoded), for a deck or a
    document of this run. A picture whose transcription is long (a scanned invoice, a page of text) is a document
    already read as text, not an illustration: it is not kept. Returns the number kept."""
    d = Path(workspace) / USER_DIR
    kept = 0
    for k, img in enumerate(images or [], 1):
        name = re.sub(r"[^\w.-]+", "-", str(img.get("name") or f"image-{k}"))[:80] or f"image-{k}"
        if len((texts or {}).get(str(img.get("name") or ""), "")) > 400:
            continue
        try:
            m = from_data_url(str(img.get("url") or ""), f"u{k}")
        except (ImageError, ValueError):
            continue
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{k:02d}-{Path(name).stem}.{'png' if m.fmt == 'png' else 'jpg'}").write_bytes(m.data)
        kept += 1
    return kept
