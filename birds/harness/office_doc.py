"""The document engine (.docx): a cover page (title, subtitle, date, the cover picture or the logo), a table of
contents, headings, callouts, tables, figures with numbered captions (pictures, maps and charts drawn from the
document's own tables of figures), a sources section with live links and the picture credits, page numbers.
Same three themes as the decks.
"""

from __future__ import annotations

import datetime as dt
import io
import re

from birds.harness import office as o
from birds.harness.office import C
from birds.harness.office_media import Media, chart_png, cropped
from birds.harness.office_plan import SOURCES_TITLE, expand_doc, number

_TEXT_CM = 16.2
MAX_TABLE_CHARTS = 3


def table_series(rows: list[list[str]], title: str = "") -> dict | None:
    """A chart spec for a Markdown table that is a series: a label column and one to three columns of figures in
    one unit, 3 to 12 rows (total rows left out)."""
    if len(rows) < 4 or len(rows) > 13 or not 2 <= len(rows[0]) <= 4:
        return None
    head, body = rows[0], [r for r in rows[1:] if r and not o._TOTAL_CELL.match(o.plain(r[0]).strip())]
    if len(body) < 3 or len({o.plain(r[0]) for r in body}) != len(body):
        return None
    cols, units = [], []
    for j in range(1, len(head)):
        vals, unit = [], ""
        for r in body:
            cell = o.plain(r[j]) if j < len(r) else ""
            m = re.match(r"^\s*([+\-−]?[\d\s  .,]*\d)\s*(%|€|k€|M€|Md€|\$|£|h)?\s*$", cell)
            if not m:
                return None
            v = number(m.group(1))
            if v is None:
                return None
            vals.append(v)
            unit = unit or (m.group(2) or "")
        cols.append(vals)
        units.append(unit)
    if len(set(units)) != 1 or re.search(r"ann[ée]e|year|code|id\b|n°", o.plain(head[1]), re.I):
        return None
    labels = [o.plain(r[0])[:30] for r in body]
    timeish = all(re.fullmatch(r"(?:19|20)\d{2}|[TQS][1-4](?:\s?(?:19|20)\d{2})?|[A-Za-zéû]{3,9}\.?(?:\s\d{4})?", lb)
                  for lb in labels)  # fmt: skip
    kind = "line" if timeish and len(body) >= 4 else "bar"
    return {
        "title": title,
        "type": kind,
        "columns": [o.plain(head[0])] + [o.plain(h) for h in head[1:]],
        "rows": [[labels[i]] + [c[i] for c in cols] for i in range(len(body))],
        "unit": units[0],
    }


def _picture(doc, m: Media, width_cm: float, data: bytes | None = None):
    """An inline picture, centred, named bird-media:<id> with its alt text (the editor finds it in the file)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    par = doc.add_paragraph()
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = par.paragraph_format
    pf.space_before, pf.space_after, pf.keep_with_next = Pt(6), Pt(2), True
    run = par.add_run()
    shape = run.add_picture(io.BytesIO(data or m.data), width=Cm(width_cm))
    pr = shape._inline.find(qn("wp:docPr"))
    if pr is not None:
        pr.set("name", f"bird-media:{m.id}")
        pr.set("descr", (m.alt or m.title or "")[:250])
    return par


def _caption(doc, n: int, text: str, credit: str = "", url: str = "", lang: str = "fr") -> None:
    """'Figure 3 – text. Source : credit' in the Caption style, numbered by a SEQ field (Word renumbers)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    par = doc.add_paragraph(style="Caption")
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    par.paragraph_format.space_after = Pt(12)
    r = par.add_run("Figure ")
    r.bold = True
    o._field(par, "SEQ Figure \\* ARABIC", str(n))
    for el in par._p.iter():
        if el.tag.endswith("}r") and el.getparent().tag.endswith("fldSimple"):
            rp = o._w("w:rPr")
            rp.append(o._w("w:b"))
            el.insert(0, rp)
    par.add_run(" – " if text else "").bold = True
    if text:
        text = o._cut(text, 160)
        par.add_run(text[:1].upper() + text[1:])
    if credit:
        label = "Source: " if lang == "en" else "Source : "
        par.add_run(("  ·  " if text else "  ") + label + credit)
        if url:
            par.add_run(" — ")
            link(par, url, re.sub(r"^https?://(www\.)?", "", url)[:70], RGBColor.from_string(C.MUTED))


def link(par, url: str, text: str, color=None) -> None:
    """A real hyperlink (w:hyperlink to an external relationship), underlined."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.ns import qn

    rid = par.part.relate_to(url, RT.HYPERLINK, is_external=True)
    h = o._w("w:hyperlink")
    h.set(qn("r:id"), rid)
    r, rpr, t = o._w("w:r"), o._w("w:rPr"), o._w("w:t")
    u = o._w("w:u")
    o._set(u, val="single")
    clr = o._w("w:color")
    o._set(clr, val=str(color) if color is not None else C.BLUE)
    rpr.append(clr)
    rpr.append(u)
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r.append(rpr)
    r.append(t)
    h.append(r)
    par._p.append(h)


def _styles(doc) -> None:
    """Caption, TOC and source styles on top of office._docx_styles."""
    from docx.enum.style import WD_STYLE_TYPE
    from docx.shared import Cm, Pt, RGBColor

    have = {s.name for s in doc.styles}

    def style(name, size, color, bold=False, before=0, after=4):
        st = doc.styles[name] if name in have else doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = doc.styles["Normal"]
        st.font.name, st.font.size, st.font.bold, st.font.italic = o.FONT, Pt(size), bold, False
        st.font.color.rgb = RGBColor.from_string(color)
        st.paragraph_format.space_before, st.paragraph_format.space_after = Pt(before), Pt(after)
        return st

    style("Caption", 8.5, C.MUTED, after=12)
    style("TOC Heading", 15, C.NAVY, bold=True, before=0, after=14)
    t1 = style("TOC 1", 11, C.INK, after=5)
    t2 = style("TOC 2", 10, C.MUTED, after=3)
    t2.paragraph_format.left_indent = Cm(0.6)
    del t1
    style("Bird Source", 9.5, C.INK, after=5)
    style("Bird Cover Date", 10.5, C.MUTED, before=6, after=0)


def _page_break(doc) -> None:
    from docx.enum.text import WD_BREAK

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _bookmark(par, name: str, ident: int) -> None:
    from docx.oxml.ns import qn

    start, end = o._w("w:bookmarkStart"), o._w("w:bookmarkEnd")
    start.set(qn("w:id"), str(ident))
    start.set(qn("w:name"), name)
    end.set(qn("w:id"), str(ident))
    par._p.insert(1 if par._p.pPr is not None else 0, start)
    par._p.append(end)


def _toc(doc, headings: list[tuple[int, str, str]], lang: str) -> None:
    """A real Word table of contents (TOC field: Word fills the page numbers on 'Update field'), shown at once with
    the headings as links (the cached result), so it reads right before any update and in other viewers."""
    from docx.oxml.ns import qn

    doc.add_paragraph("Sommaire" if lang != "en" else "Contents", style="TOC Heading")
    first = True
    for level, text, anchor in headings:
        par = doc.add_paragraph(style=f"TOC {level}")
        if first:  # the field begins with the first entry and ends after the last one
            r = o._w("w:r")
            fc = o._w("w:fldChar")
            fc.set(qn("w:fldCharType"), "begin")
            r.append(fc)
            par._p.append(r)
            r = o._w("w:r")
            it = o._w("w:instrText")
            it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            it.text = ' TOC \\o "1-2" \\h \\z \\u '
            r.append(it)
            par._p.append(r)
            r = o._w("w:r")
            fc = o._w("w:fldChar")
            fc.set(qn("w:fldCharType"), "separate")
            r.append(fc)
            par._p.append(r)
            first = False
        h = o._w("w:hyperlink")
        h.set(qn("w:anchor"), anchor)
        r, t = o._w("w:r"), o._w("w:t")
        t.text = text
        r.append(t)
        h.append(r)
        par._p.append(h)
    if not first:
        r = o._w("w:r")
        fc = o._w("w:fldChar")
        fc.set(qn("w:fldCharType"), "end")
        r.append(fc)
        par._p.append(r)


def _cover_page(doc, title: str, subtitle: str, cover: Media | None, logo: Media | None, lang: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    if logo is not None:
        par = _picture(doc, logo, min(4.5, 1.6 * logo.ratio))
        par.alignment = WD_ALIGN_PARAGRAPH.LEFT
        par.paragraph_format.space_after = Pt(30)
    else:
        doc.add_paragraph().paragraph_format.space_after = Pt(60)
    if cover is not None:
        data = cropped(cover, 16 / 9)
        _picture(doc, cover, _TEXT_CM, data).paragraph_format.space_after = Pt(4)
        if cover.credit:
            par = doc.add_paragraph(style="Caption")
            par.add_run(("Photo : " if lang != "en" else "Photo: ") + cover.credit)
            par.paragraph_format.space_after = Pt(30)
    else:
        doc.add_paragraph().paragraph_format.space_after = Pt(120)
    par = doc.add_paragraph(title, style="Title")
    for run in par.runs:
        run.font.size = Pt(32 if len(title) <= 50 else 26)
    date = o._long_date(lang)
    if subtitle:
        doc.add_paragraph(subtitle, style="Subtitle").paragraph_format.space_after = Pt(6)
        doc.add_paragraph(date, style="Bird Cover Date")
    else:
        doc.add_paragraph(date, style="Subtitle")
    _page_break(doc)


def _sources(doc, content: str, lang: str) -> None:
    """'[n] title — url' lines as numbered references with live links; '### x' sub-headings; '- x' credits."""
    from docx.shared import RGBColor

    for line in str(content or "").split("\n"):
        text = line.strip()
        if not text:
            continue
        if text.startswith("#"):
            doc.add_heading(o.plain(text.lstrip("# ")), level=2)
            continue
        par = doc.add_paragraph(style="Bird Source")
        m = re.match(r"^\s*(?:[-*•]\s*)?(\[\d{1,2}\])?\s*(.*?)(?:\s+[—–-]\s+(https?://\S+))?\s*$", o.plain(text))
        if m and m.group(1):
            r = par.add_run(m.group(1) + "  ")
            r.bold, r.font.color.rgb = True, RGBColor.from_string(C.BLUE)
        body = m.group(2) if m else text
        par.add_run(body)
        if m and m.group(3):
            par.add_run("  ")
            link(par, m.group(3), re.sub(r"^https?://(www\.)?", "", m.group(3))[:90], C.MUTED)


def build(path, title: str, sections: list[dict], subtitle: str = "", preview: dict | None = None, *,
          media: list[Media] | None = None, theme: str | None = None, sources: list | None = None, lang: str = "fr",
          request: str = "", options: dict | None = None) -> dict:  # fmt: skip
    name = o.pick_theme(request + " " + title, theme)
    token = o._THEME.set(o.THEMES[name])
    try:
        return _build(path, title, sections, subtitle, preview, media or [], name, sources, lang, options or {})
    finally:
        o._THEME.reset(token)


def _build(path, title, sections, subtitle, preview, media, theme, sources, lang, options) -> dict:
    from docx import Document

    secs, meta = expand_doc(title, sections, media, lang, sources, options)
    doc = Document()
    o._docx_styles(doc)
    _styles(doc)
    doc.core_properties.title = title[:200]
    o._furniture(doc, title)
    cover, logo = meta["cover"], meta["logo"]
    full = meta["toc"] or cover is not None
    if full:
        _cover_page(doc, title, subtitle, cover, logo, lang)
        if meta["toc"]:
            heads = []
            for i, s in enumerate(secs):
                heads.append((1, o.plain(s["heading"]), f"_bird_s{i}"))
            _toc(doc, heads, lang)
            _page_break(doc)
    else:
        if logo is not None:
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            _picture(doc, logo, min(3.5, 1.2 * logo.ratio)).alignment = WD_ALIGN_PARAGRAPH.LEFT
        o._cover(doc, title, subtitle or dt.date.today().strftime("%d/%m/%Y"))
    stats = {"sections": len(secs), "tables": 0, "items": 0, "figures": 0, "added": list(meta["added"])}
    fig = 0
    charts = 0
    colors = o.chart_colors()
    placed: dict[int, list[str]] = {}
    for i, s in enumerate(secs):
        heading = o.plain(str(s.get("heading") or ""))
        h = doc.add_heading(heading, level=1)
        _bookmark(h, f"_bird_s{i}", 100 + i)
        content = str(s.get("content") or "")
        if SOURCES_TITLE.match(heading):
            _sources(doc, content, lang)
        else:
            blocks = o.parse_markdown(content)
            stats["tables"] += sum(b.kind == "table" for b in blocks)
            stats["items"] += sum(b.kind in ("bullet", "number") for b in blocks)
            # a table of figures is followed by its chart
            chunk: list = []
            for b in blocks:
                chunk.append(b)
                if b.kind == "table" and charts < MAX_TABLE_CHARTS and (spec := table_series(b.rows, heading)):
                    o._blocks_to_docx(doc, chunk, base_level=2, context=heading)
                    chunk = []
                    png = chart_png(spec, colors, C.INK, C.MUTED, C.HAIR, lang)
                    m = Media(id=f"t{charts + 1}", kind="chart", data=png, fmt="png", w=1600, h=820,
                              alt=heading, title=heading)  # fmt: skip
                    fig += 1
                    charts += 1
                    _picture(doc, m, 15.0)
                    _caption(doc, fig, heading, lang=lang)
            if chunk:
                o._blocks_to_docx(doc, chunk, base_level=2, context=heading)
        for m in s.get("figures") or []:
            if m.kind == "chart":
                data = chart_png(m.spec, colors, C.INK, C.MUTED, C.HAIR, lang)
                width = 15.0
            else:
                data = None
                width = _TEXT_CM if m.ratio >= 1.25 else min(_TEXT_CM, 9.5 * m.ratio)
            fig += 1
            _picture(doc, m, width, data)
            src = m.spec.get("source") if m.kind == "chart" else None
            credit = m.credit or (src.get("label", "") if isinstance(src, dict) else "")
            caption = m.alt if m.kind != "user" or len(m.alt.split()) >= 2 else ""
            _caption(doc, fig, caption, credit, m.source if m.kind in ("web", "map") else "", lang)
            placed.setdefault(i, []).append(m.id)
    stats["figures"] = fig
    o._finish(doc)
    doc.save(str(path))
    plan = {
        "tool": "make_document",
        "args": {
            "title": title,
            "subtitle": subtitle,
            "sections": [
                {
                    "heading": str(s.get("heading") or ""),
                    "content": str(sections[i].get("content") or ""),
                    **({"figures": placed[i]} if i in placed else {}),
                }
                for i, s in enumerate(secs)
                if i < len(sections)
            ],
        },  # fmt: skip
        "theme": theme,
        "cover": cover.id if cover is not None else "none",
        "media": [m.meta() for m in media],
        "sources": [s for s in (sources or []) if isinstance(s, dict)][:20],
    }
    if preview is not None:
        preview.update(o.doc_preview(doc, title))
        preview["theme"] = theme
        preview["plan"] = plan
    stats["plan"] = plan
    return stats
