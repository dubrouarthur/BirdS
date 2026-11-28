"""The deck engine: a 16:9 grid, three themes, and one drawer per layout (title, agenda, section divider, the text
layouts of office.py, picture beside the text, full picture, picture grid, chart with its key takeaway, table,
timeline, quotation, two-sided comparison, sources, closing slide). Text is measured before it is placed: a slide
that would overflow is split (office.plan_slides) or set smaller (list_fit), never left to spill.
"""

from __future__ import annotations

import io
import re

from birds.harness import office as o
from birds.harness.office import _BOT, _CW, _GUT, _H, _IN, _M, _TOP, _W, _ZONE, C, col_x, span
from birds.harness.office_media import Media, cropped, fmt_num

_PT = 12700  # EMU per point


# ------------------------------------------------------------------ small drawing helpers


def _alpha(shape, opacity: float) -> None:
    from pptx.oxml.ns import qn

    clr = shape._element.spPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
    clr.append(clr.makeelement(qn("a:alpha"), {"val": str(int(opacity * 100000))}))


def _gradient(shape, stops: list[tuple[float, str, float]], angle: int = 90) -> None:
    """A linear gradient fill: stops (position 0-1, colour, opacity 0-1), angle in degrees (90 = top to bottom)."""
    from pptx.oxml.ns import qn

    shape.fill.gradient()
    grad = shape._element.spPr.find(qn("a:gradFill"))
    lst = grad.find(qn("a:gsLst"))
    for el in list(lst):
        lst.remove(el)
    for pos, color, opacity in stops:
        gs = lst.makeelement(qn("a:gs"), {"pos": str(int(pos * 100000))})
        clr = gs.makeelement(qn("a:srgbClr"), {"val": color})
        clr.append(clr.makeelement(qn("a:alpha"), {"val": str(int(opacity * 100000))}))
        gs.append(clr)
        lst.append(gs)
    lin = grad.find(qn("a:lin"))
    if lin is None:
        lin = grad.makeelement(qn("a:lin"), {})
        grad.append(lin)
    lin.set("ang", str(angle * 60000))
    lin.set("scaled", "0")


def _picture(slide, m: Media, x, y, w, h, *, fit: str = "cover", focus: float = 0.4):
    """The picture in the frame: 'cover' cuts it to the frame, 'contain' keeps it whole (centred). Named
    bird-media:<id> with its alt text, so the editor finds it again in the file."""
    x, y, w, h = int(x), int(y), int(w), int(h)
    if fit == "contain" or m.logo or m.kind == "chart":
        r = m.ratio
        if w / h > r:
            nw = int(h * r)
            x, w = x + (w - nw) // 2, nw
        else:
            nh = int(w / r)
            y, h = y + (h - nh) // 2, nh
        data = m.data
    else:
        data = cropped(m, w / h, focus)
    pic = slide.shapes.add_picture(io.BytesIO(data), x, y, w, h)
    pic.name = f"bird-media:{m.id}"
    pic._element.nvPicPr.cNvPr.set("descr", (m.alt or m.title or "")[:250])
    return pic


def _credit_line(m: Media, lang: str) -> str:
    if not m.credit:
        return ""
    head = {"map": "Carte" if lang != "en" else "Map", "web": "Photo"}.get(m.kind, "")
    return f"{head} : {m.credit}" if head and lang != "en" else f"{head}: {m.credit}" if head else m.credit


def _credit(slide, m: Media, x, y, w, lang: str) -> None:
    """The picture's credit on the picture itself: small light text on a dark translucent band at its foot."""
    text = _credit_line(m, lang)
    if not text:
        return
    h = int(0.26 * _IN)
    band = o._box(slide, x, y - h, w, h, "000000")
    _alpha(band, 0.45)
    tb = o._tb(slide, x + int(0.12 * _IN), y - h, w - int(0.24 * _IN), h, _anchor("m"))
    o._par(tb.text_frame, o._cut(text, 150), 8, "FFFFFF")


def _anchor(a: str):
    from pptx.enum.text import MSO_ANCHOR

    return {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[a]


def _logo(slide, m: Media, x, y, max_w, max_h, plate: bool = False) -> int:
    """The user's logo, whole, at most max_w x max_h; on a white plate on a dark background. Returns its width."""
    r = m.ratio
    w, h = (int(max_h * r), int(max_h)) if max_h * r <= max_w else (int(max_w), int(max_w / r))
    if plate:
        pad = int(0.1 * _IN)
        from pptx.enum.shapes import MSO_SHAPE

        p = o._shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x - pad, y - pad, w + 2 * pad, h + 2 * pad, "FFFFFF")
        p.adjustments[0] = 0.12
    _picture(slide, m, x, y, w, h, fit="contain")
    return w


def _fit_size(text: str, width: int, height: int, start: float, floor: float = 12, spacing: float = 1.1,
              avg: float = 0.5) -> float:  # fmt: skip
    size = start
    while size > floor and o._height(o._lines(o.plain(text), size, width, avg), size, spacing) > height:
        size -= 1
    return size


# ------------------------------------------------------------------ layouts


def draw_image_side(s, bullets, ctx):
    """Text on one side, the picture bleeding off the other edge, full height."""
    m: Media = ctx["image"]
    right = ctx.get("side", "right") != "left"
    img_w = _W - (col_x(7) - _GUT)
    ix = _W - img_w if right else 0
    _picture(s, m, ix, 0, img_w, _H)
    if m.kind in ("web", "map"):
        _credit(s, m, ix, _H, img_w, ctx["lang"])
    tx = _M if right else img_w + int(0.6 * _IN)
    tw = (ix - int(0.55 * _IN) - _M) if right else (_W - _M - tx)
    ctx["text_x"], ctx["text_w"] = tx, tw
    if bullets:
        n = len(bullets)
        short = n <= 3 and all(len(o.plain(b)) <= 90 for b in bullets)
        start = 24 if short else 20
        h = _BOT - _TOP
        size = o.list_fit(bullets, tw, h, start, 13)
        block = sum(
            o._height(o._lines(o.plain(o._level(b)[1]), size, tw - int(0.3 * _IN)), size, 1.15) for b in bullets
        )
        block += int(n * (12 if n <= 4 else 8) / 72 * _IN)
        y = _TOP + max(0, (h - block) // 3)
        o._draw_list(s, bullets, {**ctx, "box": (tx, y, tw, _BOT - y), "size": size})


def draw_image(s, bullets, ctx):
    """One picture across the content zone (a map, a photo with nothing to say beside it), its credit under it."""
    m: Media = ctx["image"]
    h = _BOT - _TOP - int(0.3 * _IN)
    fit = "contain" if m.kind == "map" or m.ratio < 1.2 else "cover"
    _picture(s, m, _M, _TOP, _CW, h, fit=fit)
    line = _credit_line(m, ctx["lang"]) or ""
    caption = m.alt if m.kind == "user" and len(m.alt.split()) >= 2 and not re.match(r"(?i)img|dsc|photo\s?\d", m.alt) \
        else ""  # fmt: skip
    text = " — ".join(t for t in (caption, line) if t)
    if text:
        tb = o._tb(s, _M, _TOP + h + int(0.08 * _IN), _CW, int(0.25 * _IN))
        o._par(tb.text_frame, o._cut(text, 180), 10, C.MUTED)


def draw_grid(s, bullets, ctx):
    pics: list[Media] = ctx["grid"]
    k = len(pics)
    cap_h = int(0.32 * _IN)
    if k == 4:
        cells = [(col_x(6 * (i % 2)), _TOP + (i // 2) * ((_ZONE - _GUT) // 2 + _GUT), span(6), (_ZONE - _GUT) // 2 - cap_h)
                 for i in range(4)]  # fmt: skip
    else:
        n = 6 if k == 2 else 4
        cells = [(col_x(n * i), _TOP, span(n), _ZONE - cap_h - int(0.4 * _IN)) for i in range(k)]
    for m, (x, y, w, h) in zip(pics, cells, strict=False):
        _picture(s, m, x, y, w, h)
        caption = m.alt if len(m.alt.split()) >= 2 and not re.match(r"(?i)img|dsc", m.alt) else ""
        text = " — ".join(t for t in (caption, _credit_line(m, ctx["lang"])) if t)
        if text:
            tb = o._tb(s, x, y + h + int(0.06 * _IN), w, cap_h)
            o._par(tb.text_frame, o._cut(text, 90), 10, C.MUTED)


def _number_format(unit: str, values: list[float]) -> str:
    dec = any(abs(v - round(v)) > 1e-9 for v in values if v is not None)
    base = "#,##0.0" if dec else "#,##0"
    u = (unit or "").replace('"', "")
    return f'{base}" {u}"' if u else base


def _labels(plot, rows, unit: str, lang: str, color: str, size: float, position=None) -> None:
    """Each value written out as the reader expects it ('1,4\u00a0M€' in French): a number format would follow the
    viewer's locale settings, not the language of the deck."""
    from pptx.util import Pt

    plot.has_data_labels = True
    dl = plot.data_labels
    dl.font.size, dl.font.bold = Pt(size), True
    dl.font.color.rgb = o._rgb(color)
    dl.show_value = True
    if position is not None:
        dl.position = position
    for j, ser in enumerate(plot.series, start=1):
        for i, point in enumerate(ser.points):
            v = rows[i][j] if i < len(rows) and j < len(rows[i]) else None
            if not isinstance(v, int | float):
                continue
            tf = point.data_label.text_frame
            tf.text = fmt_num(v, lang) + (("\u00a0" + unit) if unit else "")
            for r in tf.paragraphs[0].runs:
                r.font.size, r.font.bold = Pt(size), True
                r.font.color.rgb = o._rgb(color)
            if position is not None:
                point.data_label.position = position


def native_chart(s, spec: dict, x, y, w, h, meta: dict, name: str, lang: str = "fr"):
    """A real PowerPoint chart (editable, data inside): columns (or bars for long labels), a line for a time
    series, a doughnut for shares. Theme colours, labelled values, no chart junk."""
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
    from pptx.util import Pt

    cols = [str(c) for c in spec.get("columns") or []]
    rows = [r for r in spec.get("rows") or [] if isinstance(r, list) and r]
    kind = spec.get("type") or "bar"
    labels = [str(r[0])[:40] for r in rows]
    series = cols[1:] or [""]
    unit = str(spec.get("unit") or "")
    data = CategoryChartData()
    data.categories = labels
    values_all = []
    for j, name_s in enumerate(series, start=1):
        vals = [(float(r[j]) if j < len(r) and isinstance(r[j], int | float) else None) for r in rows]
        values_all += [v for v in vals if v is not None]
        data.add_series(name_s or unit or " ", vals, _number_format(unit, vals))
    long_labels = max((len(lb) for lb in labels), default=0) > 14 or len(labels) > 8
    if kind == "line":
        ctype = XL_CHART_TYPE.LINE_MARKERS
    elif kind == "pie":
        ctype = XL_CHART_TYPE.DOUGHNUT
    else:
        ctype = XL_CHART_TYPE.BAR_CLUSTERED if long_labels else XL_CHART_TYPE.COLUMN_CLUSTERED
    gf = s.shapes.add_chart(ctype, int(x), int(y), int(w), int(h), data)
    gf.name = name
    chart = gf.chart
    chart.has_title = False
    chart.font.name, chart.font.size = o.FONT, Pt(13)
    chart.font.color.rgb = o._rgb(C.MUTED)
    colors = o.chart_colors()
    multi = len(series) > 1
    chart.has_legend = multi or kind == "pie"
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(13)
        chart.legend.font.color.rgb = o._rgb(C.INK)
    plot = chart.plots[0]
    if kind == "pie":
        from pptx.oxml.ns import qn

        hole = plot._element.find(qn("c:holeSize"))
        if hole is not None:
            hole.set("val", "58")
        for i, point in enumerate(plot.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = o._rgb(colors[i % len(colors)])
            point.format.line.color.rgb = o._rgb(C.BG)
        _labels(plot, rows, unit, lang, "FFFFFF", 14)
    else:
        if ctype != XL_CHART_TYPE.LINE_MARKERS:
            plot.gap_width = 55 if not multi else 80
            plot.overlap = 0 if not multi else -10
        for j, ser in enumerate(plot.series):
            col = o._rgb(colors[j % len(colors)])
            if kind == "line":
                ser.format.line.color.rgb = col
                ser.format.line.width = Pt(3)
                ser.smooth = False
                from pptx.enum.chart import XL_MARKER_STYLE

                ser.marker.style = XL_MARKER_STYLE.CIRCLE
                ser.marker.size = 9
                ser.marker.format.fill.solid()
                ser.marker.format.fill.fore_color.rgb = o._rgb("FFFFFF")
                ser.marker.format.line.color.rgb = col
                ser.marker.format.line.width = Pt(2.25)
            else:
                ser.format.fill.solid()
                ser.format.fill.fore_color.rgb = col
        if len(labels) * len(series) <= 16:
            _labels(plot, rows, unit, lang, C.INK, 13,
                    XL_LABEL_POSITION.ABOVE if kind == "line" else XL_LABEL_POSITION.OUTSIDE_END)
        va, ca = chart.value_axis, chart.category_axis
        va.has_major_gridlines = not plot.has_data_labels
        if va.has_major_gridlines:
            va.major_gridlines.format.line.color.rgb = o._rgb(C.HAIR)
        va.visible = not plot.has_data_labels
        va.format.line.fill.background()
        va.tick_labels.font.size = Pt(12)
        if min(values_all, default=0) >= 0 and kind != "line":
            va.minimum_scale = 0
        ca.format.line.color.rgb = o._rgb(C.HAIR)
        ca.tick_labels.font.size = Pt(13)
        ca.tick_labels.font.color.rgb = o._rgb(C.INK)
        from pptx.enum.chart import XL_TICK_MARK

        ca.major_tick_mark = XL_TICK_MARK.NONE
        va.major_tick_mark = XL_TICK_MARK.NONE
    meta[name] = {
        "t": "barh" if ctype == XL_CHART_TYPE.BAR_CLUSTERED else kind,
        "cats": labels,
        "ser": [
            {
                "n": series[j - 1],
                "v": [(r[j] if j < len(r) and isinstance(r[j], int | float) else None) for r in rows],
                "c": colors[(j - 1) % len(colors)],
            }
            for j in range(1, len(series) + 1)
        ],  # fmt: skip
        "u": unit,
        "pal": colors,
    }
    return gf


def _headline(spec: dict, lang: str) -> tuple[str, str, str]:
    """(value, what it is, change) for the panel beside a chart: the last point of a time series and its change
    since the first; else the largest value. Arithmetic on the chart's own figures only."""
    rows = [r for r in spec.get("rows") or [] if len(r) > 1 and isinstance(r[1], int | float)]
    if not rows:
        return "", "", ""
    unit = str(spec.get("unit") or "")
    fmt = lambda v: fmt_num(v, lang) + ((" " + unit) if unit else "")  # noqa: E731
    if spec.get("type") == "line":
        first, last = rows[0], rows[-1]
        change = ""
        if first[1] and first[1] > 0 and unit != "%":
            pct = (last[1] - first[1]) / first[1] * 100
            change = f"{'+' if pct >= 0 else '−'}{fmt_num(abs(round(pct)), lang)} % " + (
                f"since {first[0]}" if lang == "en" else f"depuis {first[0]}"
            )
        elif unit == "%":
            d = last[1] - first[1]
            change = f"{'+' if d >= 0 else '−'}{fmt_num(abs(d), lang)} pt " + (
                f"since {first[0]}" if lang == "en" else f"depuis {first[0]}"
            )
        return fmt(last[1]), str(last[0]), change
    top = max(rows, key=lambda r: r[1])
    return fmt(top[1]), str(top[0]), ""


def draw_chart(s, bullets, ctx):
    spec = ctx["chart"]
    takeaway = [str(t) for t in spec.get("takeaway") or [] if str(t).strip()]
    panel = bool(takeaway) or bool(spec.get("rows"))
    w = span(8) if panel else _CW
    native_chart(s, spec, _M - int(0.1 * _IN), _TOP - int(0.05 * _IN), w + int(0.1 * _IN), _ZONE, ctx["meta"],
                 f"bird-chart-{ctx['n']}", ctx["lang"])  # fmt: skip
    src = spec.get("source")
    if isinstance(src, dict) and src.get("label"):
        tb = o._tb(s, _M, _BOT + int(0.02 * _IN), w, int(0.25 * _IN))
        o._par(tb.text_frame, o._cut(f"Source : {src['label']}" if ctx["lang"] != "en" else f"Source: {src['label']}",
                                     120), 10, C.MUTED)  # fmt: skip
    if not panel:
        return
    x, pw = col_x(8) + int(0.1 * _IN), span(4) - int(0.1 * _IN)
    o._box(s, x, _TOP, pw, _ZONE, C.TINT)
    pad = int(0.3 * _IN)
    iw = pw - 2 * pad
    y = _TOP + pad
    o._accent(s, x + pad, y)
    y += int(0.3 * _IN)
    value, label, change = _headline(spec, ctx["lang"])
    if value:
        size = o._fit(54, value, iw)
        tb = o._tb(s, x + pad, y, iw, o._height(1, size, 0.95))
        o._par(tb.text_frame, value, size, C.NAVY, bold=True, spacing=0.9)
        y += o._height(1, size, 0.95) + int(0.08 * _IN)
        if label:
            tb = o._tb(s, x + pad, y, iw, int(0.35 * _IN))
            o._par(tb.text_frame, o._cut(label, 40), 16, C.MUTED)
            y += int(0.4 * _IN)
        if change:
            o._chip(s, x + pad, y, change)
            y += int(0.5 * _IN)
    if takeaway:
        y += int(0.1 * _IN)
        o._box(s, x + pad, y, iw, 9525, C.HAIR)
        y += int(0.18 * _IN)
        room = _TOP + _ZONE - pad - y
        text = "\n".join(o.plain(t) for t in takeaway[:2])
        size = _fit_size(text, iw, room, 18, 12, 1.15)
        tb = o._tb(s, x + pad, y, iw, room)
        for i, t in enumerate(takeaway[:2]):
            o._par(tb.text_frame, t, size, C.INK, first=i == 0, spacing=1.15, after=6)


def _numeric_cell(v: str) -> bool:
    return bool(re.fullmatch(r"[<>≤≥~]?\s?[+\-−]?[\d\s  .,]+\s?(?:%|€|k€|M€|\$|£|h|j|pts?|/\w+|[^\s\d]{0,6})?",
                             o.plain(v).strip())) and bool(re.search(r"\d", v))  # fmt: skip


def draw_table(s, bullets, ctx):
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Pt

    rows = [[o.plain(c) for c in r] for r in ctx["table"]]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    n = len(rows)
    top = _TOP
    longest = [max(len(r[j]) for r in rows) for j in range(width)]
    size = 18 if n <= 5 and width <= 4 and max(longest) <= 30 else 16 if n <= 7 else 14
    if width >= 6:
        size = min(size, 13)
    shares = [max(6, min(36, x)) for x in longest]
    widths = [int(_CW * x / sum(shares)) for x in shares]
    numeric = [all(_numeric_cell(r[j]) for r in rows[1:] if r[j].strip()) and any(r[j].strip() for r in rows[1:])
               for j in range(width)]  # fmt: skip
    rh = [o._height(max(o._lines(r[j], size, widths[j] - int(0.2 * _IN), 0.52) for j in range(width)), size, 1.0)
          + int(0.22 * _IN) for r in rows]  # fmt: skip
    total_h = min(sum(rh), _BOT - top)
    gf = s.shapes.add_table(n, width, _M, top, _CW, total_h)
    gf.name = f"bird-table-{ctx['n']}"
    tbl = gf.table
    tbl.first_row, tbl.horz_banding = True, False
    for j, w in enumerate(widths):
        tbl.columns[j].width = w
    for i, h in enumerate(rh):
        tbl.rows[i].height = h
    meta_rows = []
    for i, r in enumerate(rows):
        mrow = []
        for j, v in enumerate(r):
            cell = tbl.cell(i, j)
            cell.margin_left = cell.margin_right = int(0.1 * _IN)
            cell.margin_top = cell.margin_bottom = int(0.06 * _IN)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            fill = C.NAVY if i == 0 else (C.TINT if i % 2 == 0 else C.BG)
            cell.fill.solid()
            cell.fill.fore_color.rgb = o._rgb(fill)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = ""
            right = numeric[j]
            p.alignment = PP_ALIGN.RIGHT if right else PP_ALIGN.LEFT
            color = "FFFFFF" if i == 0 else (C.NAVY if j == 0 else C.INK)
            bold = i == 0 or j == 0
            run = p.add_run()
            run.text = o.nbsp(v)
            run.font.size, run.font.bold, run.font.name = Pt(size), bold, o.FONT
            run.font.color.rgb = o._rgb(color)
            mrow.append(
                {"t": v[:120], "f": fill, "c": color, **({"b": 1} if bold else {}), **({"al": "r"} if right else {})}
            )
        meta_rows.append(mrow)
    ctx["meta"][gf.name] = {"rows": meta_rows, "s": size, "cw": [round(w / 9525, 1) for w in widths],
                            "rh": [round(h / 9525, 1) for h in rh]}  # fmt: skip


def draw_timeline(s, bullets, ctx):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN

    items = ctx["timeline"]
    k = len(items)
    sw = _CW // k
    tw = sw - int(0.25 * _IN)
    date_size = 24 if k <= 4 else 20
    text_size = min(_fit_size(t, tw, int(2.0 * _IN), 20 if k <= 4 else 17, 12, 1.15) for _, t in items)
    items = [(d, _cap(t)) for d, t in items]
    th = max(o._height(o._lines(o.plain(t), text_size, tw), text_size, 1.15) for _, t in items)
    block = int(0.5 * _IN) + int(0.35 * _IN) + th + int(0.6 * _IN)
    y0 = _TOP + max(0, (_ZONE - block) // 2 - int(0.2 * _IN))
    line_y = y0 + int(0.62 * _IN)
    o._box(s, _M, line_y - 9525, _CW, 19050, C.HAIR)
    d = int(0.26 * _IN)
    for j, (date, text) in enumerate(items):
        x = _M + j * sw
        tb = o._tb(s, x, y0, tw, int(0.45 * _IN))
        o._par(tb.text_frame, date, date_size, C.BLUE, bold=True)
        dot = o._shape(s, MSO_SHAPE.OVAL, x, line_y - d // 2, d, d, C.BLUE if j < k - 1 else C.NAVY)
        del dot
        tb = o._tb(s, x, line_y + int(0.35 * _IN), tw, _BOT - line_y - int(0.35 * _IN))
        o._par(tb.text_frame, text, text_size, C.INK, spacing=1.15, align=PP_ALIGN.LEFT)


def draw_quote(s, bullets, ctx):
    text, author = ctx["quote"]
    w = span(10)
    size = _fit_size(text, w - int(0.6 * _IN), int(2.6 * _IN), 32, 20, 1.15)
    th = o._height(o._lines(text, size, w - int(0.6 * _IN)), size, 1.15)
    block = int(1.0 * _IN) + th + (int(0.6 * _IN) if author else 0)
    y = o._place(block)
    tb = o._tb(s, _M, y - int(0.2 * _IN), int(1.2 * _IN), int(1.2 * _IN))
    o._par(tb.text_frame, "“", 110, C.BLUE, bold=True, spacing=0.8)
    tb = o._tb(s, _M + int(0.6 * _IN), y + int(0.9 * _IN), w - int(0.6 * _IN), th + int(0.2 * _IN))
    o._par(tb.text_frame, text, size, C.NAVY, spacing=1.15)
    if author:
        y2 = y + int(0.9 * _IN) + th + int(0.25 * _IN)
        o._accent(s, _M + int(0.6 * _IN), y2 + int(0.14 * _IN))
        tb = o._tb(s, _M + int(1.35 * _IN), y2, w, int(0.4 * _IN))
        o._par(tb.text_frame, author, 18, C.MUTED)


def draw_compare(s, bullets, ctx):
    a, pa, b, pb = ctx["compare"]
    pa, pb = [_cap(p) for p in pa], [_cap(p) for p in pb]
    w = span(6)
    head_h = int(0.66 * _IN)
    pad = int(0.3 * _IN)
    room = _ZONE - head_h - 2 * pad
    size = min(o.list_fit(pa, w - 2 * pad, room, 22, 13), o.list_fit(pb, w - 2 * pad, room, 22, 13))
    need = max(_list_height(pa, size, w - 2 * pad), _list_height(pb, size, w - 2 * pad))
    panel = min(_ZONE, head_h + 2 * pad + need + int(0.1 * _IN))
    y = o._place(panel)
    for j, (head, points) in enumerate(((a, pa), (b, pb))):
        x = col_x(6 * j)
        o._box(s, x, y, w, panel, C.TINT)
        o._box(s, x, y, w, head_h, C.NAVY if j else C.BLUE)
        tb = o._tb(s, x + pad, y, w - 2 * pad, head_h, _anchor("m"))
        o._par(tb.text_frame, o._cut(_cap(head), 40), 20, "FFFFFF", bold=True)
        o._draw_list(s, points, {"box": (x + pad, y + head_h + pad, w - 2 * pad, panel - head_h - 2 * pad),
                                 "size": size})  # fmt: skip


def _cap(text: str) -> str:
    text = str(text).strip()
    return text[:1].upper() + text[1:]


def _list_height(bullets, size: float, width: int) -> int:
    n = len(bullets)
    total = 0
    for raw in bullets:
        level, text = o._level(raw)
        z = size - 2 * level
        total += o._height(o._lines(o.plain(text), z, width - int(0.30 * _IN) * (level + 1)), z, 1.15)
        total += int((4 if level else (12 if n <= 4 else 8)) / 72 * _IN)
    return total


def draw_agenda(s, bullets, ctx):
    items = [o._cut(o.plain(t), 70) for t in ctx["agenda"]]
    k = len(items)
    cols = 2 if k > 6 else 1
    per = -(-k // cols)
    rh = min(int(0.72 * _IN), _ZONE // per)
    size = 22 if cols == 1 else 18
    y0 = o._place(per * rh)
    w = span(10) if cols == 1 else span(6) - _GUT
    for i, text in enumerate(items):
        c, r = divmod(i, per)
        x = col_x(6 * c)
        y = y0 + r * rh
        tb = o._tb(s, x, y, int(0.8 * _IN), rh, _anchor("m"))
        o._par(tb.text_frame, f"{i + 1:02d}", size, C.BLUE, bold=True)
        tb = o._tb(s, x + int(0.85 * _IN), y, w - int(0.85 * _IN), rh, _anchor("m"))
        o._par(tb.text_frame, text, _fit_size(text, w - int(0.85 * _IN), rh, size, 14), C.NAVY)
        o._box(s, x, y + rh - 4762, w, 9525, C.HAIR)


def draw_sources(s, bullets, ctx):
    from pptx.util import Pt

    credits = ctx.get("credits") or []
    tb = o._tb(s, _M, _TOP - int(0.1 * _IN), _CW, _ZONE + int(0.2 * _IN))
    tf = tb.text_frame
    first = True
    for line in bullets:
        text = o.plain(line)
        m = re.match(r"^\s*(\[\d{1,2}\])\s*(.*?)(?:\s+[—–-]\s+(https?://\S+))?\s*$", text)
        p = o._par(tf, "", 14, C.INK, first=first, after=7, spacing=1.05)
        first = False
        parts = [(m.group(1) + "  ", C.BLUE, True), (m.group(2), C.INK, False)] if m else [(text, C.INK, False)]
        if m and m.group(3):
            parts.append(("  ", C.INK, False))
            parts.append((re.sub(r"^https?://(www\.)?", "", m.group(3))[:90], C.MUTED, False))
        for t, col, bold in parts:
            r = p.add_run()
            r.text = t
            r.font.size, r.font.bold, r.font.name = Pt(14 if col != C.MUTED else 12), bold, o.FONT
            r.font.color.rgb = o._rgb(col)
            if col == C.MUTED and m and m.group(3):
                r.hyperlink.address = m.group(3)
    if credits:
        from birds.harness.office_plan import tr

        o._par(tf, tr("credits", ctx["lang"]).upper(), 11, C.BLUE,
               bold=True, first=first, before=0 if first else 14, after=6, track=100)  # fmt: skip
        for c in credits:
            o._par(tf, o._cut(c, 220), 11, C.MUTED, first=False, after=4, spacing=1.05)


LAYOUTS = {
    "image_side": draw_image_side,
    "image": draw_image,
    "grid": draw_grid,
    "chart": draw_chart,
    "table": draw_table,
    "timeline": draw_timeline,
    "quote": draw_quote,
    "compare": draw_compare,
    "agenda": draw_agenda,
    "sources": draw_sources,
}


# ------------------------------------------------------------------ speaker notes with the details


def auto_notes(item: dict, kind: str, sources: dict, lang: str) -> str:
    """What the slide condenses, for the speaker: the full points behind a chart, a table, a timeline or KPI
    tiles, the picture's credit and the sources cited on the slide."""
    out = []
    en = lang == "en"
    if kind == "chart":
        spec = item.get("chart") or {}
        unit = str(spec.get("unit") or "")
        out.append(("Data: " if en else "Données : ") + "; ".join(
            f"{r[0]} : {fmt_num(r[1], lang) if isinstance(r[1], int | float) else r[1]}{(' ' + unit) if unit else ''}"
            for r in spec.get("rows") or [] if len(r) > 1))  # fmt: skip
        out += [o.plain(t) for t in spec.get("takeaway") or []]
    elif kind in ("kpi", "timeline", "steps", "compare", "quote") and item.get("bullets"):
        out += [o.plain(b) for b in item["bullets"]]
    elif kind == "table":
        out += [" | ".join(r) for r in item.get("table") or []]
    img = item.get("image")
    if isinstance(img, Media) and img.credit:
        out.append(_credit_line(img, lang) + (f" ({img.source})" if img.source else ""))
    text = " ".join(str(b) for b in item.get("bullets") or [])
    cited = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", text)})
    for n in cited:
        if n in sources:
            out.append(sources[n])
    return "\n".join(x for x in out if x)


# ------------------------------------------------------------------ the deck


def build(path, title: str, slides: list[dict], subtitle: str = "", lang: str = "fr", preview: dict | None = None,
          *, media: list[Media] | None = None, theme: str | None = None, sources: list | None = None,
          request: str = "", options: dict | None = None) -> dict:  # fmt: skip
    """Write the deck. Returns {'total', 'theme', 'added', 'plan'} — 'plan' is what the editor edits (the slides
    with the harness's choices made explicit: picture per slide, cover, theme)."""
    name = o.pick_theme(request + " " + title, theme)
    token = o._THEME.set(o.THEMES[name])
    try:
        return _build(path, title, slides, subtitle, lang, preview, media or [], name, sources, options or {})
    finally:
        o._THEME.reset(token)


def _build(path, title, slides, subtitle, lang, preview, media, theme, sources, options) -> dict:
    from pptx import Presentation
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Pt

    from birds.harness.office_plan import expand_deck

    expanded, deck = expand_deck(title, slides, media, lang, sources, options)
    cover, logo = deck["cover"], deck["logo"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = _W, _H
    prs.core_properties.title = title[:200]
    prs.core_properties.author = prs.core_properties.last_modified_by = ""
    blank = prs.slide_layouts[5]  # "Title Only": real slide titles (outline view, screen readers, read_file)

    def title_box(slide, x, y, w, h, text, size, color, anchor):
        t = slide.shapes.title
        t.left, t.top, t.width, t.height = int(x), int(y), int(w), int(h)
        sp = t._element  # drawn last, above the decorative shapes added after it
        tree = sp.getparent()
        tree.remove(sp)
        tree.append(sp)
        o._plain_frame(t.text_frame, anchor)
        o._par(t.text_frame, text, size, color, bold=True, spacing=0.95)
        return t

    plan = o.plan_slides(expanded)
    kinds = o._deck_kinds(plan)
    contexts = o._group_context(plan, kinds)
    total = len(plan) + 1
    meta: dict = {}
    src_map = {}
    for src in sources or []:
        if isinstance(src, dict) and src.get("n"):
            src_map[int(src["n"])] = f"[{src['n']}] {src.get('title') or ''} — {src.get('url') or ''}".strip()
    for item in expanded:
        if item.get("layout") == "sources":
            for b in item["bullets"]:
                m = re.match(r"^\s*\[(\d{1,2})\]", o.plain(b))
                if m:
                    src_map.setdefault(int(m.group(1)), o.plain(b))

    def background(slide):
        if C.BG.upper() != "FFFFFF":
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = o._rgb(C.BG)

    def number(slide, n, color=None, x=None, w=None):
        x = (_W - _M) if x is None else x
        tb = o._tb(slide, x - int(1.2 * _IN), int(6.92 * _IN), int(1.2 * _IN), int(0.28 * _IN))
        o._par(tb.text_frame, f"{n} / {total}", 10, color or C.MUTED, align=PP_ALIGN.RIGHT)

    def footer(slide, x0=_M, x1=_W - _M):
        x = x0
        if logo is not None:
            x += _logo(slide, logo, x, int(6.88 * _IN), int(1.1 * _IN), int(0.3 * _IN)) + int(0.18 * _IN)
        tb = o._tb(slide, x, int(6.92 * _IN), max(int(1.0 * _IN), x1 - x - int(1.4 * _IN)), int(0.28 * _IN))
        o._par(tb.text_frame, o._cut(o.plain(title), 80), 10, C.MUTED)

    def dark(slide, text, picture: Media | None = None, sub: str = ""):
        """Full-bleed dark slide, or the cover picture under a dark gradient: the title bottom-left on the grid."""
        text = o._cut(text, 200)
        size = 44 if len(text) <= 40 else 40 if len(text) <= 70 else 34 if len(text) <= 120 else 28
        if picture is not None:
            _picture(slide, picture, 0, 0, _W, _H, focus=0.35)
            veil = o._box(slide, 0, 0, _W, _H, C.NAVY)
            _gradient(veil, [(0, C.NAVY, 0.15), (0.45, C.NAVY, 0.45), (1, C.NAVY, 0.92)], 90)
            if picture.credit:
                tb = o._tb(slide, col_x(6), int(0.3 * _IN), span(6), int(0.25 * _IN))
                o._par(tb.text_frame, o._cut(_credit_line(picture, lang), 120), 8, C.ON_DARK, align=PP_ALIGN.RIGHT)
        else:
            o._box(slide, 0, 0, _W, _H, C.NAVY)
            if theme == "modern":  # a quiet accent block on the right
                o._box(slide, _W - int(2.2 * _IN), 0, int(2.2 * _IN), _H, C.DARK_LINE)
                o._box(slide, _W - int(2.2 * _IN), 0, int(0.08 * _IN), _H, C.BLUE)
            elif theme == "warm":
                from pptx.enum.shapes import MSO_SHAPE

                o._shape(slide, MSO_SHAPE.OVAL, _W - int(4.2 * _IN), -int(1.6 * _IN), int(5.6 * _IN), int(5.6 * _IN),
                         C.DARK_LINE)  # fmt: skip
        o._box(slide, _M, int(4.78 * _IN), int(0.6 * _IN), 50800, C.BLUE)
        o._box(slide, _M, int(6.45 * _IN), _CW, 9525, C.DARK_LINE if picture is None else C.ON_DARK2)
        title_box(slide, _M, int(1.05 * _IN), span(10), int(3.45 * _IN), text, size, "FFFFFF", MSO_ANCHOR.BOTTOM)
        if sub:
            sub = o._cut(sub, 180)
            tb = o._tb(slide, _M, int(5.0 * _IN), span(10), int(1.3 * _IN))
            o._par(tb.text_frame, sub, 18 if len(sub) <= 90 else 16, C.ON_DARK, spacing=1.1)
        if logo is not None:
            _logo(slide, logo, _M + int(0.1 * _IN), int(0.55 * _IN), int(2.0 * _IN), int(0.6 * _IN), plate=True)

    # title slide
    s = prs.slides.add_slide(blank)
    dark(s, title, cover, subtitle)
    dated = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|\b(?:19|20)\d{2}\b", subtitle or "")
    if not dated:
        tb = o._tb(s, _M, int(6.62 * _IN), span(6), int(0.3 * _IN))
        o._par(tb.text_frame, o._long_date(lang), 12, C.ON_DARK2 if cover is None else C.ON_DARK)
    tb = o._tb(s, col_x(6), int(6.62 * _IN), span(6), int(0.3 * _IN))
    count = f"{total} slides" if lang == "en" else f"{total} diapositives"
    o._par(tb.text_frame, count, 12, C.ON_DARK2 if cover is None else C.ON_DARK, align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = ""
    if cover is not None and cover.credit:
        s.notes_slide.notes_text_frame.text = _credit_line(cover, lang) + (f" ({cover.source})" if cover.source else "")

    sections, eyebrow = 0, ""
    notes_count = 0
    for n, item in enumerate(plan, start=2):
        s = prs.slides.add_slide(blank)
        kind = kinds[n - 2]
        base, suffix = item.get("base", item["title"]), item.get("suffix", "")
        heading = o._cut(base, 160) + suffix
        notes = item["notes"]
        if len(re.sub(r"\s+", " ", base).strip()) > 160 and item["offset"] == 0:  # a cut title stays whole in notes
            notes = (base + "\n\n" + notes).strip()
        auto = auto_notes(item, kind, src_map, lang)
        if auto and auto not in notes:
            notes = (notes + "\n\n" + auto).strip()
        if kind == "closing" or (item["section"] and n == total):
            dark(s, heading, cover, item.get("subtitle") or "")
            number(s, n, C.ON_DARK2)
            kind = "closing"
        elif item["section"]:  # a slide without bullets is a section divider
            sections += 1
            eyebrow = heading
            heading = o._cut(heading, 120)
            background(s)
            o._box(s, 0, 0, int(4.25 * _IN), _H, C.NAVY)
            tb = o._tb(s, _M, int(2.85 * _IN), int(3.0 * _IN), int(1.3 * _IN))
            o._par(tb.text_frame, f"{sections:02d}", 72, C.POS, bold=True, spacing=0.9)
            o._accent(s, int(5.0 * _IN), int(2.85 * _IN))
            title_box(s, int(5.0 * _IN), int(3.15 * _IN), _W - int(5.0 * _IN) - _M, int(2.9 * _IN), heading,
                      40 if len(heading) <= 40 else 32 if len(heading) <= 80 else 26, C.NAVY, MSO_ANCHOR.TOP)  # fmt: skip
            number(s, n)
        else:
            background(s)
            ctx = {**contexts[n - 2], **{k: item[k] for k in o._EXTRA if k in item}, "lang": lang, "meta": meta, "n": n}
            if kind == "image_side":
                img_w = _W - (col_x(7) - _GUT)
                right = item.get("side", "right") != "left"
                tx = _M if right else img_w + int(0.6 * _IN)
                tw = ((_W - img_w) - int(0.55 * _IN) - _M) if right else (_W - _M - tx)
                if eyebrow:
                    tb = o._tb(s, tx, int(0.42 * _IN), tw, int(0.28 * _IN))
                    o._par(tb.text_frame, o._cut(eyebrow, 40).upper(), 11, C.BLUE, bold=True, track=100)
                size = _fit_size(heading, tw, int(0.96 * _IN), 30 if len(heading) <= 45 else 26, 18, 0.95, 0.55)
                title_box(s, tx, int(0.74 * _IN), tw, int(0.96 * _IN), heading, size, C.NAVY, MSO_ANCHOR.BOTTOM)
                o._rule(s, tx, int(1.84 * _IN), tw)
                LAYOUTS[kind](s, item["bullets"], ctx)
                footer(s, tx, tx + tw)
                number(s, n, x=tx + tw)
            else:
                if eyebrow:
                    tb = o._tb(s, _M, int(0.42 * _IN), _CW, int(0.28 * _IN))
                    o._par(tb.text_frame, o._cut(eyebrow, 60).upper(), 11, C.BLUE, bold=True, track=100)
                size = 30 if len(heading) <= 45 else 26 if len(heading) <= 70 else 22 if len(heading) <= 110 else 18
                title_box(s, _M, int(0.74 * _IN), _CW, int(0.96 * _IN), heading, size, C.NAVY, MSO_ANCHOR.BOTTOM)
                o._rule(s, _M, int(1.84 * _IN), _CW)
                (LAYOUTS.get(kind) or o._DRAW[kind])(s, item["bullets"], ctx)
                footer(s)
                number(s, n)
        kinds[n - 2] = kind
        if notes:
            notes_count += 1
            tf = s.notes_slide.notes_text_frame
            tf.text = notes[:4000]
            for p in tf.paragraphs:
                for r in p.runs:
                    r.font.name, r.font.size, r.font.color.rgb = o.FONT, Pt(12), o._rgb(o.INK)
    prs.save(str(path))
    plan_out = editable_plan(title, subtitle, slides, expanded, deck, theme, media, sources)
    if preview is not None:
        preview.update(deck_preview(prs, title, subtitle, plan, kinds, meta, theme, notes_count))
        preview["plan"] = plan_out
    return {"total": total, "theme": theme, "added": deck["added"], "plan": plan_out}


def editable_plan(title, subtitle, slides, expanded, deck, theme, media, sources) -> dict:
    """The deck as the editor edits it: the model's slides (the harness's own additions are made again on each
    build), each with the picture the harness gave it, the cover, the theme and the pictures available."""
    placed = {}
    for s in expanded:
        img = s.get("image")
        if isinstance(img, Media):
            placed[o.plain(s.get("title") or "")] = img.id
    out = []
    for s in slides:
        entry = {"title": str(s.get("title") or ""), "bullets": [str(b) for b in s.get("bullets") or []]}
        if s.get("notes"):
            entry["notes"] = str(s["notes"])
        img = s.get("image") if isinstance(s.get("image"), str) else placed.get(o.plain(entry["title"]))
        if img:
            entry["image"] = img
        if s.get("layout"):
            entry["layout"] = s["layout"]
        out.append(entry)
    return {
        "tool": "make_slides",
        "args": {"title": title, "subtitle": subtitle, "slides": out},
        "theme": theme,
        "cover": deck["cover"].id if deck.get("cover") else "none",
        "media": [m.meta() for m in media],
        "sources": [s for s in (sources or []) if isinstance(s, dict)][:20],
    }


# ------------------------------------------------------------------ what the chat shows of a deck


def deck_preview(prs, title, subtitle, plan, kinds, meta, theme, notes) -> dict:
    """office.deck_preview, plus the pictures (small JPEG thumbnails, by key), charts and tables as data, the
    theme and each slide's background."""

    base = o.deck_preview(prs, title, subtitle, plan, kinds)
    thumbs: dict[str, str] = {}
    for entry, slide in zip(base["slides"], prs.slides, strict=False):
        entry["shapes"] = scene(slide, meta, thumbs)
        if C.BG.upper() != "FFFFFF" and entry.get("kind") not in ("title", "closing"):
            entry["bg"] = C.BG
        if entry.get("kind") == "closing":
            entry["kind"] = "closing"
    base.update(theme=theme, media=thumbs, notes=notes)
    return base


def scene(slide, meta: dict, thumbs: dict) -> list[dict]:
    """office._scene for every kind of shape, in z-order: text shapes (with opacity and gradients), pictures (a key
    into the thumbnails), native charts and tables (their data, drawn by the chat)."""
    import hashlib

    from pptx.oxml.ns import qn

    from birds.harness.office_media import thumb

    out = []
    text_shapes = iter(o._scene(slide))
    for el in slide.shapes._spTree.iterchildren():
        tag = el.tag.split("}")[1]
        if tag == "sp":
            sp_pr = el.find(qn("p:spPr"))
            has_geom = sp_pr is not None and sp_pr.find(qn("a:xfrm")) is not None
            fill = sp_pr.find(qn("a:solidFill") + "/" + qn("a:srgbClr")) if sp_pr is not None else None
            body = el.find(qn("p:txBody"))
            texty = body is not None and any((t.text or "") for t in body.iter(qn("a:t")))
            if not has_geom or (fill is None and not texty and sp_pr.find(qn("a:gradFill")) is None):
                continue
            if fill is None and not texty:  # a gradient veil
                item = _geom(el)
            else:
                item = next(text_shapes, None)
                if item is None:
                    continue
            if fill is not None and (a := fill.find(qn("a:alpha"))) is not None:
                item["o"] = round(int(a.get("val")) / 100000, 2)
            grad = sp_pr.find(qn("a:gradFill"))
            if grad is not None:
                stops = []
                for gs in grad.iter(qn("a:gs")):
                    clr = gs.find(qn("a:srgbClr"))
                    al = clr.find(qn("a:alpha")) if clr is not None else None
                    stops.append([int(gs.get("pos")) / 100000, clr.get("val") if clr is not None else "000000",
                                  round(int(al.get("val")) / 100000, 2) if al is not None else 1])  # fmt: skip
                lin = grad.find(qn("a:lin"))
                item["gr"] = {"a": int(lin.get("ang", "5400000")) // 60000 if lin is not None else 90, "s": stops}
            out.append(item)
        elif tag == "pic":
            item = _geom(el)
            blip = el.find(".//" + qn("a:blip"))
            rid = blip.get(qn("r:embed")) if blip is not None else None
            if not rid:
                continue
            blob = slide.part.related_part(rid).blob
            key = hashlib.sha1(blob).hexdigest()[:12]
            if key not in thumbs:
                try:
                    thumbs[key] = thumb(blob, 640)
                except Exception:  # noqa: BLE001 - a preview without this picture, never a failed file
                    continue
            item["img"] = key
            name = el.find(qn("p:nvPicPr") + "/" + qn("p:cNvPr"))
            if name is not None and name.get("descr"):
                item["alt"] = name.get("descr")[:160]
            out.append(item)
        elif tag == "graphicFrame":
            name = el.find(qn("p:nvGraphicFramePr") + "/" + qn("p:cNvPr"))
            key = name.get("name") if name is not None else ""
            if key in meta:
                item = _frame_geom(el)
                item["ch" if key.startswith("bird-chart") else "tb"] = meta[key]
                out.append(item)
    return out


def _geom(el) -> dict:
    from pptx.oxml.ns import qn

    xfrm = el.find(".//" + qn("a:xfrm"))
    off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    return {"x": o._px(off.get("x")), "y": o._px(off.get("y")), "w": o._px(ext.get("cx")), "h": o._px(ext.get("cy"))}


def _frame_geom(el) -> dict:
    from pptx.oxml.ns import qn

    xfrm = el.find(qn("p:xfrm"))
    off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    return {"x": o._px(off.get("x")), "y": o._px(off.get("y")), "w": o._px(ext.get("cx")), "h": o._px(ext.get("cy"))}


def media_in(path) -> dict[str, bytes]:
    """The pictures of a deck or document Bird made, by media id (bird-media:<id>): what the editor reuses."""
    import zipfile

    out: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        for xml in [n for n in names if re.match(r"(ppt/slides/slide\d+|word/document)\.xml$", n)]:
            body = zf.read(xml).decode("utf-8", "replace")
            rels_name = re.sub(r"([^/]+)$", r"_rels/\1.rels", xml)
            rels = zf.read(rels_name).decode("utf-8", "replace") if rels_name in names else ""
            targets = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))
            targets.update({k: v for v, k in re.findall(r'Target="([^"]+)"[^>]*Id="(rId\d+)"', rels)})
            for mid, rid in re.findall(r'name="bird-media:([\w-]{1,12})".*?r:embed="(rId\d+)"', body, re.S):
                target = targets.get(rid)
                if not target or mid in out:
                    continue
                folder = xml.rsplit("/", 1)[0]
                full = re.sub(r"[^/]+/\.\./", "", f"{folder}/{target}")
                if full in names:
                    out[mid] = zf.read(full)
    return out
