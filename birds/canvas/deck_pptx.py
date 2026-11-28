"""A canvas deck as a .pptx that looks like the canvas: the same layout per slide (``layouts.pick``), the same
palettes (``PALETTES``, mirrored by the ``.cvt-*`` classes of canvas.css: a test compares them), the same type scale
and grid (1 in = 7.5 % of the slide width = 7.5 cqi in the CSS), the same pictures and credits.

Each theme has its own slide master (background colour of the theme). Charts are native PowerPoint charts (the
office engine's ``native_chart``), so the figures stay editable. Text that would not fit is set smaller, never
left to spill; nothing is added that the canvas does not show (no agenda, no closing slide of its own).
"""

from __future__ import annotations

import datetime as dt
import io
import re

from birds.harness import office as o
from birds.harness import office_deck as od
from birds.harness.office_media import Media, fmt_num

from . import layouts

IN = 914400
W, H = 12192000, 6858000  # 13.333 x 7.5 in
M = int(0.75 * IN)
CW = W - 2 * M

# one palette per theme: canvas.css (.cvt-<theme>) carries the same values (tests/test_canvas_decks.py)
PALETTES: dict[str, dict[str, str]] = {
    "corporate": {"bg": "FFFFFF", "ink": "121A2E", "head": "0B1B3F", "accent": "1E5BD8", "muted": "586078",
                  "soft": "E2E9F8", "tint": "F4F6FB", "hair": "D9DEE8", "dark": "0B1B3F", "on-dark": "C9D3EA",
                  "accent2": "5BD69B"},
    "forest": {"bg": "FBFCF8", "ink": "14231B", "head": "12301F", "accent": "2E7D52", "muted": "5C6B61",
               "soft": "DDEED6", "tint": "F2F7EF", "hair": "DCE5DA", "dark": "12301F", "on-dark": "D3E6D5",
               "accent2": "C9A227"},
    "warm": {"bg": "FFFCF8", "ink": "2B1D16", "head": "3B1F14", "accent": "C2410C", "muted": "7C6A5E",
             "soft": "FDE7D7", "tint": "F8EEE4", "hair": "EADFD3", "dark": "3B1F14", "on-dark": "F3E5D8",
             "accent2": "E8A26B"},
    "night": {"bg": "0F1424", "ink": "E8ECF5", "head": "FFFFFF", "accent": "7FA4FF", "muted": "9AA4BC",
              "soft": "232B42", "tint": "161C2E", "hair": "2A3350", "dark": "070A14", "on-dark": "C9D3EA",
              "accent2": "A78BFA"},
    "modern": {"bg": "FFFFFF", "ink": "0F172A", "head": "111827", "accent": "0D9488", "muted": "64748B",
               "soft": "CCFBF1", "tint": "F1F5F9", "hair": "E2E8F0", "dark": "111827", "on-dark": "CBD5E1",
               "accent2": "6366F1"},
}  # fmt: skip
HEAD_FONT = {"warm": "Georgia"}  # the others: Calibri (Carlito in the canvas, its metric twin)
FONT = "Calibri"
MONO = "Consolas"


def _i(x: float) -> int:
    return int(x * IN)


class _Ctx:
    def __init__(self, prs, doc: dict, media: dict[str, Media], theme: str, lang: str):
        self.prs, self.doc, self.media, self.theme, self.lang = prs, doc, media, theme, lang
        self.p = PALETTES.get(theme, PALETTES["corporate"])
        self.head_font = HEAD_FONT.get(theme, FONT)
        self.total = len(doc.get("blocks") or []) + 1
        self.sections = 0
        self.layout = prs.slide_layouts[5]  # « Title Only »: real slide titles (outline view, screen readers)


# ------------------------------------------------------------------ drawing helpers


def text(slide, x, y, w, h, value: str, size: float, color: str, *, bold=False, align=None, anchor=None,
         spacing=None, font=FONT, italic=False, track=0):  # fmt: skip
    tb = o._tb(slide, x, y, w, h, anchor)
    par(tb.text_frame, value, size, color, bold=bold, align=align, spacing=spacing, font=font, italic=italic,
        track=track)  # fmt: skip
    return tb


def par(tf, value: str, size: float, color: str, *, bold=False, first=True, align=None, spacing=None, font=FONT,
        italic=False, after=0, track=0):  # fmt: skip
    p = o._par(tf, value, size, color, bold=bold, first=first, align=align, spacing=spacing, after=after, track=track)
    for r in p.runs:
        r.font.name = font
        if italic:
            r.font.italic = True
    return p


def fit(value: str, width: int, height: int, start: float, floor: float = 12, spacing: float = 1.15,
        avg: float = 0.5) -> float:  # fmt: skip
    size = start
    while size > floor and o._height(o._lines(o.plain(value), size, width, avg), size, spacing) > height:
        size -= 1
    return size


def box(slide, x, y, w, h, color: str | None, rounded: float | None = None):
    from pptx.enum.shapes import MSO_SHAPE

    if rounded is None:
        return o._box(slide, x, y, w, h, color)
    s = o._shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, color)
    s.adjustments[0] = rounded
    return s


def oval(slide, x, y, d, color: str):
    from pptx.enum.shapes import MSO_SHAPE

    return o._shape(slide, MSO_SHAPE.OVAL, x, y, d, d, color)


def title_box(c: _Ctx, slide, value: str, x, y, w, h, size, color, anchor="b", align=None, caps=False):
    """The slide's title in its title placeholder (moved to the frame, drawn above the decoration)."""
    t = slide.shapes.title
    t.left, t.top, t.width, t.height = int(x), int(y), int(w), int(h)
    sp = t._element
    tree = sp.getparent()
    tree.remove(sp)
    tree.append(sp)
    o._plain_frame(t.text_frame, od._anchor(anchor))
    p = par(t.text_frame, value, size, color, bold=True, spacing=0.95, font=c.head_font if not caps else FONT,
            align=align)
    if caps:  # an eyebrow: small capitals drawn by PowerPoint, the title text kept as written
        for r in p.runs:
            r._r.get_or_add_rPr().set("cap", "all")
            r._r.get_or_add_rPr().set("spc", "120")
    return t


def head(c: _Ctx, slide, title: str, x=M, w=CW, color=None):
    """Title (bottom-aligned at 1.55 in) and the short accent bar under it: the frame of an ordinary slide."""
    value = o._cut(title or "", 160)
    size = fit(value, w, _i(0.95), 30, 20, 0.95, 0.52)
    title_box(c, slide, value, x, _i(0.55), w, _i(0.98), size, color or c.p["head"])
    box(slide, x, _i(1.66), _i(0.7), _i(0.06), c.p["accent"])


def footer(c: _Ctx, slide, n: int, dark=False, x0=M, x1=W - M):
    color = c.p["on-dark"] if dark else c.p["muted"]
    text(slide, x0, _i(6.93), (x1 - x0) - _i(1.3), _i(0.26), o._cut(c.doc.get("title") or "", 80), 10, color)
    from pptx.enum.text import PP_ALIGN

    text(slide, x1 - _i(1.2), _i(6.93), _i(1.2), _i(0.26), f"{n} / {c.total}", 10, color, align=PP_ALIGN.RIGHT)


def bg(slide, color: str):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = o._rgb(color)


def picture(c: _Ctx, slide, mid: str | None, x, y, w, h, credit=True):
    m = c.media.get(mid or "")
    if m is None:
        return None
    od._picture(slide, m, x, y, w, h, focus=0.4)
    if credit and m.credit:
        od._credit(slide, m, x, y + h, w, c.lang)
    return m


def items_list(c: _Ctx, slide, parts: list[dict], x, y, w, h, size: float = 20, color=None, center=False):
    """Lists, paragraphs, sub-headings and callouts of a slide, top to bottom, set smaller until they fit."""
    color = color or c.p["ink"]
    rows: list[tuple[str, str]] = []  # (kind, text)
    for p in parts:
        t = p.get("t")
        if t == "list":
            for k, it in enumerate(p.get("items") or []):
                if it.strip():
                    rows.append(("sub" if it.startswith("  ") else ("num" if p.get("ordered") else "dot"),
                                 it.strip() if not p.get("ordered") else f"{k + 1}|{it.strip()}"))  # fmt: skip
        elif t == "heading":
            rows.append(("head", p.get("text") or ""))
        elif t == "callout":
            rows.append(("callout", p.get("text") or ""))
        elif t == "text":
            rows.append(("text", p.get("text") or ""))
    if not rows:
        return
    pad = _i(0.42)

    def height(sz: float) -> int:
        total = 0
        for kind, val in rows:
            s = sz * (0.85 if kind == "sub" else 1)
            ww = w - (pad if kind in ("dot", "num", "sub") else 0) - (_i(0.5) if kind == "callout" else 0)
            total += o._height(o._lines(o.plain(val.split("|", 1)[-1]), s, ww), s, 1.2) + _i(0.16)
            total += _i(0.3) if kind == "callout" else 0
        return total

    while size > 13 and height(size) > h:
        size -= 1
    cy = y + max(0, (h - height(size)) // 2) if center and height(size) < h * 0.6 else y
    for kind, val in rows:
        s = size * (0.85 if kind == "sub" else 1)
        if kind in ("dot", "sub", "num"):
            indent = _i(0.35) if kind == "sub" else 0
            if kind == "num":
                n, val = val.split("|", 1)
                d = _i(0.3)
                oval(slide, x + indent, cy + _i(0.02), d, c.p["accent"])
                from pptx.enum.text import PP_ALIGN

                text(slide, x + indent, cy + _i(0.02), d, d, n, 11, "FFFFFF", bold=True, align=PP_ALIGN.CENTER,
                     anchor=od._anchor("m"))  # fmt: skip
            else:
                d = _i(0.1)
                dot = oval(slide, x + indent + _i(0.04), cy + int(s * 0.62 / 72 * IN) - d // 2, d,
                           c.p["accent"] if kind == "dot" else None)  # fmt: skip
                if kind == "sub":
                    dot.line.color.rgb = o._rgb(c.p["accent"])
            hh = o._height(o._lines(o.plain(val), s, w - pad - indent), s, 1.2)
            text(slide, x + pad + indent, cy, w - pad - indent, hh + _i(0.05), val, s,
                 c.p["muted"] if kind == "sub" else color, spacing=1.08)  # fmt: skip
            cy += hh + _i(0.16)
        elif kind == "callout":
            hh = o._height(o._lines(o.plain(val), s, w - _i(0.5)), s, 1.2)
            box(slide, x, cy, w, hh + _i(0.3), c.p["tint"])
            box(slide, x, cy, _i(0.07), hh + _i(0.3), c.p["accent"])
            text(slide, x + _i(0.3), cy + _i(0.15), w - _i(0.5), hh + _i(0.05), val, s, color, spacing=1.08)
            cy += hh + _i(0.46)
        else:
            bold = kind == "head"
            hh = o._height(o._lines(o.plain(val), s, w), s, 1.2)
            text(slide, x, cy, w, hh + _i(0.05), val, s, c.p["head"] if bold else color, bold=bold, spacing=1.08,
                 font=c.head_font if bold else FONT)  # fmt: skip
            cy += hh + _i(0.16)


def _text_parts(b: dict) -> list[dict]:
    return [p for p in b.get("parts") or [] if p.get("t") in layouts.TEXT]


def _images(b: dict) -> list[dict]:
    return [p for p in b.get("parts") or [] if p.get("t") == "image"]


# ------------------------------------------------------------------ the layouts


def draw_bullets(c, s, b, n):
    head(c, s, b.get("title"))
    n_items = sum(len(p.get("items") or [1]) for p in _text_parts(b))
    items_list(c, s, _text_parts(b), M, _i(2.05), _i(10.4), _i(4.55), 24 if n_items <= 4 else 21, center=True)


def draw_columns(c, s, b, n):
    head(c, s, b.get("title"))
    items = [x for p in _text_parts(b) if p.get("t") == "list" for x in p.get("items") or [] if x.strip()]
    half = (len(items) + 1) // 2
    gw = (CW - _i(0.6)) // 2
    for k, chunk in enumerate((items[:half], items[half:])):
        items_list(c, s, [{"t": "list", "items": chunk}], M + k * (gw + _i(0.6)), _i(2.05), gw, _i(4.55), 18)


def draw_statement(c, s, b, n):
    from pptx.enum.text import PP_ALIGN

    p = _text_parts(b)[0]
    value = p.get("text") if p.get("t") != "list" else (p.get("items") or [""])[0].strip()
    box(s, M, _i(1.45), _i(0.7), _i(0.06), c.p["accent"])
    t = o._cut(b.get("title") or "", 80)
    title_box(c, s, t, M, _i(0.9), CW, _i(0.45), 13, c.p["accent"], caps=True)
    size = fit(value, _i(10.6), _i(4.2), 40, 22, 1.15, 0.5)
    text(s, M, _i(1.85), _i(10.6), _i(4.4), value, size, c.p["head"], bold=True, anchor=od._anchor("m"),
         spacing=1.12, font=c.head_font, align=PP_ALIGN.LEFT)  # fmt: skip


def draw_section(c, s, b, n):
    c.sections += 1
    bg(s, c.p["dark"])
    img = next(iter(_images(b)), None)
    if not (img and picture(c, s, img.get("media"), _i(7.6), 0, W - _i(7.6), H, credit=True)):
        img = None
        od._alpha(oval(s, W - _i(4.6), -_i(1.9), _i(6.2), c.p["accent"]), 0.18)  # a soft disc of the accent colour
    text(s, M, _i(2.2), _i(3), _i(1.1), f"{c.sections:02d}", 66, c.p["accent2"], bold=True, font=c.head_font)
    box(s, M, _i(3.45), _i(0.7), _i(0.06), c.p["accent"])
    t = o._cut(b.get("title") or "", 120)
    title_box(c, s, t, M, _i(3.7), _i(6.6), _i(2.2), fit(t, _i(6.6), _i(2.2), 44, 26, 0.95), "FFFFFF", anchor="t")
    sub = " ".join(p.get("text") or " ".join(p.get("items") or []) for p in _text_parts(b))
    if sub:
        text(s, M, _i(5.9), _i(6.6), _i(0.8), o._cut(sub, 160), 16, c.p["on-dark"])
    footer(c, s, n, dark=True, x1=_i(7.2) if img else W - M)


def draw_closing(c, s, b, n):
    bg(s, c.p["dark"])
    img = next(iter(_images(b)), None)
    m = c.media.get((img or {}).get("media") or "")
    if m is not None:
        od._picture(s, m, 0, 0, W, H, focus=0.4)
        veil = box(s, 0, 0, W, H, c.p["dark"])
        od._gradient(veil, [(0, c.p["dark"], 0.35), (1, c.p["dark"], 0.92)], 0)
        if m.credit:
            from pptx.enum.text import PP_ALIGN

            text(s, _i(6.5), _i(0.3), W - _i(6.5) - M, _i(0.25), o._cut(od._credit_line(m, c.lang), 120), 8,
                 c.p["on-dark"], align=PP_ALIGN.RIGHT)  # fmt: skip
    else:
        od._alpha(oval(s, -_i(2.2), _i(3.4), _i(6.4), c.p["accent"]), 0.22)
    box(s, M, _i(2.25), _i(0.9), _i(0.08), c.p["accent2"])
    t = o._cut(b.get("title") or "", 120)
    title_box(c, s, t, M, _i(2.5), _i(10.5), _i(1.7), fit(t, _i(10.5), _i(1.7), 54, 30, 0.95), "FFFFFF", anchor="t")
    parts = _text_parts(b)
    if parts:
        items_list(c, s, parts, M, _i(4.35), _i(9.5), _i(2.2), 20, c.p["on-dark"])
    footer(c, s, n, dark=True)


def draw_agenda(c, s, b, n):
    head(c, s, b.get("title"))
    items = [x.strip() for p in _text_parts(b) if p.get("t") == "list" for x in p.get("items") or []
             if x.strip() and not x.startswith("  ")][:8]  # fmt: skip
    cols = 2 if len(items) > 4 else 1
    per = (len(items) + cols - 1) // cols
    gw = (CW - _i(0.8)) // cols
    rh = min(_i(1.05), _i(4.5) // max(1, per))
    for k, it in enumerate(items):
        col, row = divmod(k, per)
        x, y = M + col * (gw + _i(0.8)), _i(2.1) + row * rh
        text(s, x, y, _i(0.9), rh, f"{k + 1:02d}", 30, c.p["accent"], bold=True, font=c.head_font,
             anchor=od._anchor("m"))  # fmt: skip
        text(s, x + _i(1.0), y, gw - _i(1.0), rh, o._cut(it, 90), fit(it, gw - _i(1.0), rh, 22, 14), c.p["ink"],
             anchor=od._anchor("m"))  # fmt: skip
        box(s, x + _i(1.0), y + rh - _i(0.04), gw - _i(1.0), 9525, c.p["hair"])


def draw_figure(c, s, b, n):
    from pptx.enum.text import PP_ALIGN

    head(c, s, b.get("title"))
    main = layouts.main_part(b) or {}
    k = (main.get("items") or [{}])[0]
    img = next(iter(_images(b)), None)
    m = c.media.get((img or {}).get("media") or "")
    w = _i(6.4) if m else CW
    if m is not None:
        picture(c, s, img.get("media"), _i(7.6), 0, W - _i(7.6), H)
    value = k.get("value") or ""
    size = fit(value, w, _i(2.2), 120, 60, 0.9, 0.55)
    text(s, M, _i(2.0), w, _i(2.4), value, size, c.p["accent"], bold=True, font=c.head_font,
         anchor=od._anchor("b"), spacing=0.9)  # fmt: skip
    text(s, M, _i(4.55), w, _i(1.1), k.get("label") or "", 24, c.p["ink"], spacing=1.1)
    if k.get("delta"):
        down = bool(re.match(r"^[-−]", k["delta"]))
        pill = box(s, M, _i(5.75), _i(1.6), _i(0.45), "FBE9E6" if down else "E6F5EC", 0.5)
        pill.name = "delta"
        text(s, M, _i(5.75), _i(1.6), _i(0.45), k["delta"], 14, "B23B2A" if down else "1A8A5A", bold=True,
             align=PP_ALIGN.CENTER, anchor=od._anchor("m"))  # fmt: skip
    rest = [p for p in _text_parts(b)]
    if rest and m is None:
        items_list(c, s, rest, _i(7.4), _i(2.3), W - _i(7.4) - M, _i(3.6), 18)
    footer(c, s, n, x1=_i(7.2) if m else W - M)


def draw_kpis(c, s, b, n):
    from pptx.enum.text import PP_ALIGN

    head(c, s, b.get("title"))
    items = ((layouts.main_part(b) or {}).get("items") or [])[:4]
    k = max(1, len(items))
    gap = _i(0.35)
    tw = (CW - gap * (k - 1)) // k
    y, th = _i(2.25), _i(2.6)
    for j, it in enumerate(items):
        x = M + j * (tw + gap)
        box(s, x, y, tw, th, c.p["tint"], 0.06)
        box(s, x, y, tw, _i(0.07), c.p["accent"])
        v = it.get("value") or ""
        text(s, x + _i(0.3), y + _i(0.35), tw - _i(0.6), _i(1.1), v, fit(v, tw - _i(0.6), _i(1.0), 48, 24, 0.9, 0.55),
             c.p["accent"], bold=True, font=c.head_font)  # fmt: skip
        text(s, x + _i(0.3), y + _i(1.5), tw - _i(0.6), _i(0.9), it.get("label") or "", 16, c.p["muted"], spacing=1.1)
        if it.get("delta"):
            down = bool(re.match(r"^[-−]", it["delta"]))
            box(s, x + _i(0.3), y + th - _i(0.6), _i(1.2), _i(0.36), "FBE9E6" if down else "E6F5EC", 0.5)
            text(s, x + _i(0.3), y + th - _i(0.6), _i(1.2), _i(0.36), it["delta"], 12, "B23B2A" if down else "1A8A5A",
                 bold=True, align=PP_ALIGN.CENTER, anchor=od._anchor("m"))  # fmt: skip
    rest = _text_parts(b)
    if rest:
        items_list(c, s, rest, M, y + th + _i(0.35), CW, _i(1.4), 16)


def draw_versus(c, s, b, n):
    from pptx.enum.text import PP_ALIGN

    head(c, s, b.get("title"))
    cols = layouts.columns_of(b)[:2]
    gap = _i(0.9)
    cw = (CW - gap) // 2
    y, ch = _i(2.1), _i(4.45)
    for j, col in enumerate(cols):
        x = M + j * (cw + gap)
        box(s, x, y, cw, ch, c.p["tint"] if j == 0 else c.p["soft"], 0.05)
        text(s, x + _i(0.4), y + _i(0.35), cw - _i(0.8), _i(0.6), col.get("title") or "", 24,
             c.p["accent"] if j else c.p["head"], bold=True, font=c.head_font)  # fmt: skip
        items_list(c, s, [{"t": "list", "items": col.get("items") or []}], x + _i(0.4), y + _i(1.15), cw - _i(0.8),
                   ch - _i(1.4), 20)  # fmt: skip
    d = _i(0.85)
    cx = M + cw + gap // 2 - d // 2
    oval(s, cx, y + ch // 2 - d // 2, d, c.p["accent"])
    text(s, cx, y + ch // 2 - d // 2, d, d, "VS", 18, "FFFFFF", bold=True, align=PP_ALIGN.CENTER,
         anchor=od._anchor("m"))  # fmt: skip


def draw_compare(c, s, b, n):
    head(c, s, b.get("title"))
    cols = layouts.columns_of(b)[:3]
    k = max(1, len(cols))
    gap = _i(0.3)
    cw = (CW - gap * (k - 1)) // k
    y = _i(2.1)
    for j, col in enumerate(cols):
        x = M + j * (cw + gap)
        box(s, x, y, cw, _i(0.7), c.p["head"] if c.theme != "night" else c.p["soft"], 0.12)
        text(s, x + _i(0.25), y, cw - _i(0.5), _i(0.7), col.get("title") or "", 18, "FFFFFF", bold=True,
             anchor=od._anchor("m"), font=c.head_font)  # fmt: skip
        items_list(c, s, [{"t": "list", "items": col.get("items") or []}], x + _i(0.15), y + _i(0.95), cw - _i(0.3),
                   _i(3.6), 17)  # fmt: skip


def draw_timeline(c, s, b, n):
    head(c, s, b.get("title"))
    items = ((layouts.main_part(b) or {}).get("items") or [])[:6]
    k = max(1, len(items))
    gw = CW // k
    ly = _i(2.75)
    box(s, M, ly, CW, _i(0.05), c.p["soft"])
    for j, it in enumerate(items):
        x = M + j * gw
        d = _i(0.26)
        oval(s, x, ly - d // 2 + _i(0.025), d, c.p["accent"])
        text(s, x, ly + _i(0.35), gw - _i(0.25), _i(0.5), it.get("when") or "", 20, c.p["accent"], bold=True,
             font=c.head_font)  # fmt: skip
        what = it.get("what") or ""
        text(s, x, ly + _i(0.9), gw - _i(0.25), _i(2.8), what, fit(what, gw - _i(0.25), _i(2.8), 17, 12), c.p["ink"],
             spacing=1.1)  # fmt: skip


def draw_steps(c, s, b, n):
    from pptx.enum.text import PP_ALIGN

    head(c, s, b.get("title"))
    items = layouts.items_of(b)[:6]
    k = max(1, len(items))
    gw = CW // k
    d = _i(0.7)
    y = _i(2.25)
    box(s, M + d // 2, y + d // 2 - _i(0.02), CW - gw + 0, _i(0.04), c.p["hair"])
    for j, it in enumerate(items):
        x = M + j * gw
        oval(s, x, y, d, c.p["accent"])
        text(s, x, y, d, d, str(j + 1), 22, "FFFFFF", bold=True, align=PP_ALIGN.CENTER, anchor=od._anchor("m"),
             font=c.head_font)  # fmt: skip
        t = it.get("title") or ""
        text(s, x, y + d + _i(0.3), gw - _i(0.3), _i(0.8), t, fit(t, gw - _i(0.3), _i(0.8), 20, 13), c.p["head"],
             bold=True, font=c.head_font)  # fmt: skip
        if it.get("text"):
            text(s, x, y + d + _i(1.15), gw - _i(0.3), _i(2.2), it["text"], fit(it["text"], gw - _i(0.3), _i(2.2), 16, 11),
                 c.p["muted"], spacing=1.1)  # fmt: skip


def draw_cards(c, s, b, n):
    from pptx.enum.text import PP_ALIGN

    head(c, s, b.get("title"))
    items = layouts.items_of(b)[:6]
    k = len(items)
    per = 3 if k in (3, 5, 6) else 2 if k in (2, 4) else 3
    rows = (k + per - 1) // per
    gap = _i(0.3)
    cw = (CW - gap * (per - 1)) // per
    ch = (_i(4.5) - gap * (rows - 1)) // max(1, rows)
    for j, it in enumerate(items):
        r, col = divmod(j, per)
        x, y = M + col * (cw + gap), _i(2.1) + r * (ch + gap)
        box(s, x, y, cw, ch, c.p["tint"], 0.06)
        d = _i(0.55)
        oval(s, x + _i(0.3), y + _i(0.3), d, c.p["accent"])
        initial = (it.get("title") or "?").strip()[:1].upper()
        text(s, x + _i(0.3), y + _i(0.3), d, d, initial, 18, "FFFFFF", bold=True, align=PP_ALIGN.CENTER,
             anchor=od._anchor("m"), font=c.head_font)  # fmt: skip
        t = it.get("title") or ""
        text(s, x + _i(0.3), y + _i(1.0), cw - _i(0.6), _i(0.5), t, fit(t, cw - _i(0.6), _i(0.5), 19, 13), c.p["head"],
             bold=True, font=c.head_font)  # fmt: skip
        if it.get("text"):
            hh = max(_i(0.3), ch - _i(1.6))
            text(s, x + _i(0.3), y + _i(1.5), cw - _i(0.6), hh, it["text"], fit(it["text"], cw - _i(0.6), hh, 15, 10),
                 c.p["muted"], spacing=1.1)  # fmt: skip


def draw_quote(c, s, b, n):
    main = layouts.main_part(b) or {}
    img = next(iter(_images(b)), None)
    m = c.media.get((img or {}).get("media") or "")
    w = _i(6.6) if m else _i(10.8)
    if m is not None:
        picture(c, s, img.get("media"), _i(7.9), 0, W - _i(7.9), H)
    t = o._cut(b.get("title") or "", 80)
    title_box(c, s, t, M, _i(0.7), w, _i(0.4), 13, c.p["accent"], caps=True)
    text(s, M - _i(0.1), _i(1.1), _i(1.4), _i(1.4), "“", 120, c.p["accent"], bold=True, font="Georgia")
    q = main.get("text") or ""
    text(s, M + _i(0.2), _i(2.35), w - _i(0.2), _i(3.0), q, fit(q, w - _i(0.2), _i(3.0), 32, 18, 1.2), c.p["head"],
         italic=True, font="Georgia", spacing=1.18)  # fmt: skip
    if main.get("by"):
        box(s, M + _i(0.2), _i(5.65), _i(0.5), _i(0.04), c.p["accent"])
        text(s, M + _i(0.85), _i(5.45), w - _i(0.9), _i(0.45), main["by"], 18, c.p["muted"], anchor=od._anchor("m"))
    footer(c, s, n, x1=_i(7.6) if m else W - M)


def draw_image_side(c, s, b, n, left: bool):
    img = _images(b)[0]
    iw = _i(5.9)
    ix = 0 if left else W - iw
    picture(c, s, img.get("media"), ix, 0, iw, H)
    if not c.media.get(img.get("media") or ""):
        box(s, ix, 0, iw, H, c.p["soft"])
    tx = iw + _i(0.65) if left else M
    tw = (W - M - tx) if left else (W - iw - _i(0.65) - M)
    head(c, s, b.get("title"), tx, tw)
    items_list(c, s, _text_parts(b), tx, _i(2.05), tw, _i(4.55), 19)
    footer(c, s, n, x0=tx, x1=tx + tw)


def draw_image_full(c, s, b, n):
    img = _images(b)[0]
    m = c.media.get(img.get("media") or "")
    bg(s, c.p["dark"])
    if m is not None:
        od._picture(s, m, 0, 0, W, H, focus=0.4)
    veil = box(s, 0, 0, W, H, "000000")
    od._gradient(veil, [(0, "000000", 0.0), (0.5, "000000", 0.15), (1, "000000", 0.78)], 90)
    if m is not None and m.credit:
        from pptx.enum.text import PP_ALIGN

        text(s, _i(5.5), _i(0.3), W - _i(5.5) - M, _i(0.25), o._cut(od._credit_line(m, c.lang), 140), 8, "FFFFFF",
             align=PP_ALIGN.RIGHT)  # fmt: skip
    t = o._cut(b.get("title") or "", 120)
    box(s, M, _i(4.35), _i(0.7), _i(0.06), c.p["accent2"])
    title_box(c, s, t, M, _i(4.55), _i(10.5), _i(1.2), fit(t, _i(10.5), _i(1.2), 40, 24, 0.95), "FFFFFF", anchor="t")
    parts = _text_parts(b)
    if parts:
        p = parts[0]
        v = p.get("text") if p.get("t") != "list" else " ".join(p.get("items") or [])
        text(s, M, _i(5.8), _i(10.5), _i(0.8), o._cut(v, 200), 18, "FFFFFF", spacing=1.1)
    footer(c, s, n, dark=True)


def draw_image_grid(c, s, b, n):
    head(c, s, b.get("title"))
    imgs = _images(b)[:4]
    k = len(imgs)
    gap = _i(0.25)
    gw = (CW - gap * (k - 1)) // k
    gh = _i(4.1)
    for j, img in enumerate(imgs):
        x = M + j * (gw + gap)
        m = picture(c, s, img.get("media"), x, _i(2.05), gw, gh)
        if m is None:
            box(s, x, _i(2.05), gw, gh, c.p["soft"], 0.04)
        cap = img.get("caption") or img.get("alt") or ""
        if cap:
            text(s, x, _i(2.05) + gh + _i(0.1), gw, _i(0.4), o._cut(cap, 80), 12, c.p["muted"])


def draw_chart(c, s, b, n):
    head(c, s, b.get("title"))
    main = layouts.main_part(b) or {}
    rest = _text_parts(b)
    spec = {key: main[key] for key in ("type", "columns", "rows", "unit", "title", "source") if main.get(key)}
    cw = _i(7.7) if rest else CW
    token = o._THEME.set(o.THEMES.get(c.theme) or o.THEMES["corporate"])
    try:
        od.native_chart(s, spec, M, _i(2.0), cw, _i(4.6), {}, b.get("id") or "c", c.lang)
    finally:
        o._THEME.reset(token)
    if rest:
        x = M + cw + _i(0.4)
        w = W - M - x
        box(s, x, _i(2.1), w, _i(4.4), c.p["tint"], 0.05)
        box(s, x, _i(2.1), _i(0.07), _i(4.4), c.p["accent"])
        items_list(c, s, rest, x + _i(0.35), _i(2.4), w - _i(0.6), _i(3.8), 18)


def draw_table(c, s, b, n):
    from pptx.util import Pt

    head(c, s, b.get("title"))
    rows = [r for r in ((layouts.main_part(b) or {}).get("rows") or []) if r][:12]
    if not rows:
        return
    ncol = max(len(r) for r in rows)
    h = min(_i(4.6), _i(0.62) * len(rows))
    shape = s.shapes.add_table(len(rows), ncol, M, _i(2.05), CW, h)
    tbl = shape.table
    size = 18 if len(rows) <= 6 else 15 if len(rows) <= 9 else 12
    for r, row in enumerate(rows):
        for k in range(ncol):
            cell = tbl.cell(r, k)
            val = row[k] if k < len(row) else ""
            cell.fill.solid()
            cell.fill.fore_color.rgb = o._rgb(c.p["head"] if r == 0 and c.theme != "night" else
                                              c.p["soft"] if r == 0 else
                                              (c.p["tint"] if r % 2 == 0 else c.p["bg"]))  # fmt: skip
            tf = cell.text_frame
            tf.margin_left = tf.margin_right = _i(0.12)
            num = r > 0 and bool(re.fullmatch(r"[+\-−]?[\d\s  .,]+\s?(?:%|€|k€|M€|\$|pts?)?", val.strip() or "x"))
            from pptx.enum.text import PP_ALIGN

            par(tf, val, size, "FFFFFF" if r == 0 else c.p["ink"], bold=r == 0,
                align=PP_ALIGN.RIGHT if num else PP_ALIGN.LEFT)  # fmt: skip
            for p in tf.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(size)


def draw_code(c, s, b, n):
    head(c, s, b.get("title"))
    main = layouts.main_part(b) or {}
    box(s, M, _i(2.0), CW, _i(4.6), "0F1424", 0.03)
    code = "\n".join((main.get("text") or "").split("\n")[:18])
    tb = o._tb(s, M + _i(0.3), _i(2.2), CW - _i(0.6), _i(4.2))
    for k, ln in enumerate(code.split("\n")):
        par(tb.text_frame, ln or " ", 13, "E8ECF5", first=k == 0, font=MONO)


DRAW = {
    "bullets": draw_bullets, "columns": draw_columns, "statement": draw_statement, "section": draw_section,
    "closing": draw_closing, "agenda": draw_agenda, "figure": draw_figure, "kpis": draw_kpis, "versus": draw_versus,
    "compare": draw_compare, "timeline": draw_timeline, "steps": draw_steps, "cards": draw_cards,
    "quote": draw_quote, "image-left": lambda c, s, b, n: draw_image_side(c, s, b, n, True),
    "image-right": lambda c, s, b, n: draw_image_side(c, s, b, n, False), "image-full": draw_image_full,
    "image-grid": draw_image_grid, "chart": draw_chart, "table": draw_table, "code": draw_code,
}  # fmt: skip
assert set(DRAW) == set(layouts.CATALOGUE)
OWN_FOOTER = {"section", "closing", "figure", "quote", "image-left", "image-right", "image-full"}


def draw_cover(c: _Ctx, s) -> None:
    doc = c.doc
    cover = doc.get("cover") or {}
    m = None if cover.get("off") else c.media.get(cover.get("media") or "")
    bg(s, c.p["dark"])
    if m is not None:
        od._picture(s, m, 0, 0, W, H, focus=0.4)
        veil = box(s, 0, 0, W, H, c.p["dark"])
        od._gradient(veil, [(0, c.p["dark"], 0.1), (0.45, c.p["dark"], 0.45), (1, c.p["dark"], 0.94)], 90)
        if m.credit:
            from pptx.enum.text import PP_ALIGN

            text(s, _i(5.5), _i(0.3), W - _i(5.5) - M, _i(0.25), o._cut(od._credit_line(m, c.lang), 140), 8,
                 c.p["on-dark"], align=PP_ALIGN.RIGHT)  # fmt: skip
    else:
        disc = oval(s, W - _i(5.4), -_i(2.4), _i(7.6), c.p["accent"])
        od._alpha(disc, 0.35)
        disc2 = oval(s, W - _i(2.6), _i(3.6), _i(4.2), c.p["accent2"])
        od._alpha(disc2, 0.16)
    box(s, M, _i(3.0), _i(1.0), _i(0.08), c.p["accent2"] if m is None else c.p["accent"])
    t = o._cut(doc.get("title") or "", 160)
    title_box(c, s, t, M, _i(3.25), _i(10.8), _i(2.0), fit(t, _i(10.8), _i(2.0), 54, 30, 0.95), "FFFFFF", anchor="t")
    if doc.get("subtitle"):
        text(s, M, _i(5.35), _i(10.5), _i(0.8), o._cut(doc["subtitle"], 160), 22, c.p["on-dark"], spacing=1.1)
    text(s, M, _i(6.6), _i(6), _i(0.35), _date(c.lang), 13, c.p["on-dark"])


def _date(lang: str) -> str:
    d = dt.date.today()
    months = o._MONTHS_EN if lang == "en" else o._MONTHS_FR
    return f"{d.day} {months[d.month - 1]} {d.year}"


def notes_for(c: _Ctx, b: dict) -> str:
    """The speaker notes: the block's own notes, then each picture's credit and source (and a chart's figures)."""
    out = [b.get("notes") or ""]
    main = layouts.main_part(b)
    if main and main.get("t") == "chart":
        unit = main.get("unit") or ""
        out.append(("Data: " if c.lang == "en" else "Données : ") + "; ".join(
            f"{r[0]} : {fmt_num(r[1], c.lang) if isinstance(r[1], int | float) else r[1]}{(' ' + unit) if unit else ''}"
            for r in main.get("rows") or [] if len(r) > 1))  # fmt: skip
    for p in _images(b):
        m = c.media.get(p.get("media") or "")
        if m is not None and m.credit:
            out.append(od._credit_line(m, c.lang) + (f" ({m.source})" if m.source else ""))
    return "\n".join(x for x in out if x).strip()


def build(path, doc: dict, media: list[Media]) -> dict:
    """Write the deck; returns {'layouts': [...], 'theme'} (what was drawn, for tests and the measure)."""
    from pptx import Presentation
    from pptx.util import Pt

    theme = doc.get("theme") if doc.get("theme") in PALETTES else "corporate"
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    prs.core_properties.title = (doc.get("title") or "")[:200]
    prs.core_properties.author = prs.core_properties.last_modified_by = ""
    master = prs.slide_master  # the theme's master: its background colour, for every slide
    master.background.fill.solid()
    master.background.fill.fore_color.rgb = o._rgb(PALETTES[theme]["bg"])
    c = _Ctx(prs, doc, {m.id: m for m in media}, theme, doc.get("lang") or "fr")
    drawn = ["cover"]
    s = prs.slides.add_slide(c.layout)
    draw_cover(c, s)
    cover = doc.get("cover") or {}
    m = c.media.get(cover.get("media") or "")
    if m is not None and m.credit and not cover.get("off"):
        s.notes_slide.notes_text_frame.text = od._credit_line(m, c.lang) + (f" ({m.source})" if m.source else "")
    blocks = doc.get("blocks") or []
    for k, b in enumerate(blocks):
        name = layouts.pick(b, k, len(blocks))
        s = prs.slides.add_slide(c.layout)
        n = k + 2
        DRAW[name](c, s, b, n)
        if name not in OWN_FOOTER and name != "image-grid":
            footer(c, s, n)
        elif name == "image-grid":
            footer(c, s, n)
        notes = notes_for(c, b)
        if notes:
            tf = s.notes_slide.notes_text_frame
            tf.text = notes[:4000]
            for p in tf.paragraphs:
                for r in p.runs:
                    r.font.name, r.font.size = FONT, Pt(12)
        drawn.append(name)
    for slide in prs.slides:  # an empty title placeholder would show « Click to add title »
        t = slide.shapes.title
        if t is not None and not t.text_frame.text.strip():
            t._element.getparent().remove(t._element)
    prs.save(path if hasattr(path, "write") else str(path))
    return {"layouts": drawn, "theme": theme}


def to_bytes(doc: dict, media: list[Media]) -> bytes:
    buf = io.BytesIO()
    build(buf, doc, media)
    return buf.getvalue()
