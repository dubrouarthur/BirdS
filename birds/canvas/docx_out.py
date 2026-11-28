"""A canvas document (kind « doc ») as a .docx that follows the preview of the canvas, element for element.

Same rules as the page drawn by canvas-doc.js: the template's look (cover page with the template's name, title,
subtitle, date and author; a table of contents; numbered headings « 1. », « 1.1 »; or a letter), heading levels 1-3,
callouts by tone (« À retenir », « Attention », « Info »), tables with their header row, figures numbered with their
caption and credit (« Figure 2 – … · Source : … »), the footnotes as numbered notes at the end, page numbers.
``outline(doc)`` is that shared plan (pure, no Word): the tests compare the .docx with it, and the preview draws the
same numbers.
"""

from __future__ import annotations

import re

from birds.harness import office as o
from birds.harness import office_doc as od
from birds.harness.office import C
from birds.harness.office_media import Media, chart_png, chart_spec_ok

from . import dsl, templates

_TEXT_CM = 16.2
LABELS = {
    "fr": {"key": "À retenir", "ok": "À retenir", "warn": "Attention", "info": "Info", "notes": "Notes",
           "toc": "Sommaire", "figure": "Figure", "source": "Source", "object": "Objet"},
    "en": {"key": "Key point", "ok": "Key point", "warn": "Warning", "info": "Note", "notes": "Notes",
           "toc": "Contents", "figure": "Figure", "source": "Source", "object": "Subject"},
}  # fmt: skip
_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def look(doc: dict) -> dict:
    """The page look of a document: its template's flags (cover, table of contents, numbering, letter)."""
    tpl = templates.TEMPLATES.get(doc.get("template") or "") or templates.TEMPLATES[templates.DEFAULT]
    n = len(doc.get("blocks") or [])
    return {"template": tpl.id, "name": tpl.en if doc.get("lang") == "en" else tpl.fr, "cover": tpl.cover,
            "toc": tpl.toc and n >= 3 and not tpl.letter, "numbered": tpl.numbered, "letter": tpl.letter}  # fmt: skip


def outline(doc: dict) -> list[dict]:
    """The document as the page shows it, in order: headings with their numbers, callouts, tables, figures with
    their numbers, the notes. [{'k': 'h1'|'h2'|'h3'|'text'|'list'|'callout'|'table'|'figure'|'quote'|'kpi'|
    'timeline'|'code'|'notes', …}]."""
    lk = look(doc)
    out: list[dict] = []
    fig = 0
    media = doc.get("media") or {}
    for i, b in enumerate(doc.get("blocks") or [], 1):
        if not lk["letter"]:
            out.append(
                {"k": "h1", "text": (f"{i}. " if lk["numbered"] else "") + (b.get("title") or ""), "id": b["id"]}
            )
        sub = 0
        for p in b.get("parts") or []:
            t = p.get("t")
            if t == "heading":
                level = 2 if int(p.get("level") or 2) <= 2 else 3
                if level == 2:
                    sub += 1
                num = f"{i}.{sub} " if lk["numbered"] and level == 2 and not lk["letter"] else ""
                out.append({"k": f"h{level}", "text": num + (p.get("text") or "")})
            elif t == "image":
                if not p.get("media"):
                    continue  # a picture still being searched is not in the file (nor printed)
                fig += 1
                m = media.get(p["media"]) or {}
                out.append({"k": "figure", "n": fig, "media": p["media"], "caption": p.get("caption") or (
                    m.get("alt") if m.get("kind") == "web" else "") or "", "credit": m.get("credit") or "",
                    "licence": m.get("licence") or "", "source": m.get("source") or ""})  # fmt: skip
            elif t == "chart":
                fig += 1
                out.append({"k": "figure", "n": fig, "chart": p, "caption": p.get("title") or b.get("title") or "",
                            "credit": p.get("source") or "", "licence": "", "source": ""})  # fmt: skip
            else:
                out.append({"k": t, "part": p})
    notes = dsl.footnote_order(doc)
    if notes:
        out.append({"k": "notes", "items": notes})
    return out


def _marks(doc: dict) -> dict[str, int]:
    return {x["key"]: x["n"] for x in dsl.footnote_order(doc)}


def _runs(par, text: str, marks: dict[str, int]) -> None:
    """Inline Markdown (bold, code) with the footnote calls as superscript numbers."""
    pos = 0
    for m in dsl.FOOTNOTE_REF.finditer(text or ""):
        if m.start() > pos:
            o._add_runs(par, text[pos : m.start()])
        n = marks.get(m.group(1))
        if n is not None:
            r = par.add_run(str(n))
            r.font.superscript = True
        pos = m.end()
    if pos < len(text or ""):
        o._add_runs(par, text[pos:])


def _plain_marks(text: str, marks: dict[str, int]) -> str:
    """In a list item or a table cell: « [^1] » as « ¹ »."""
    return dsl.FOOTNOTE_REF.sub(lambda m: str(marks.get(m.group(1), "")).translate(_SUP), text or "")


def _callout(d, text: str, tone: str, lang: str, marks: dict[str, int]):
    from docx.shared import Cm, Pt, RGBColor

    par = d.add_paragraph()
    pf = par.paragraph_format
    pf.left_indent, pf.space_before, pf.space_after = Cm(0.5), Pt(4), Pt(10)
    ppr = par._p.get_or_add_pPr()
    fill, bar = {"warn": (o._WARN_T, o._WARN_BAR), "key": (C.POS_T, C.POS), "ok": (C.POS_T, C.POS)}.get(
        tone, (C.TINT, C.BLUE)
    )
    o._p_border(ppr, left=(24, bar, 8), **o._pad(fill))
    o._p_shade(ppr, fill)
    label = LABELS[lang].get(tone, LABELS[lang]["info"])
    body = text or ""
    if not re.match(rf"^\W{{0,3}}{re.escape(label)}\b", body, re.I):
        r = par.add_run(label + (" : " if lang != "en" else ": "))
        r.bold, r.font.color.rgb = True, RGBColor.from_string(C.NAVY)
    _runs(par, body, marks)
    return par


def _list(d, p: dict, marks: dict[str, int]) -> None:
    from docx.shared import Pt

    base = "List Number" if p.get("ordered") else "List Bullet"
    num_id = o._new_list(d, base) if p.get("ordered") else None
    last = None
    for it in p.get("items") or []:
        sub = str(it).startswith("  ")
        style = base + (" 2" if sub else "")
        par = d.add_paragraph(style=style)
        if num_id and not sub:
            num_pr = o._w("w:numPr")
            ilvl, nid = o._w("w:ilvl"), o._w("w:numId")
            o._set(ilvl, val=0)
            o._set(nid, val=num_id)
            num_pr.append(ilvl)
            num_pr.append(nid)
            o._put(par._p.get_or_add_pPr(), num_pr, o._PPR)
        _runs(par, str(it).strip(), marks)
        last = par
    if last is not None:
        last.paragraph_format.space_after = Pt(8)


def _figure(d, item: dict, media: dict[str, Media], lang: str) -> bool:
    if "chart" in item:
        p = item["chart"]
        spec = {k: p[k] for k in ("type", "columns", "rows", "unit", "title") if p.get(k)}
        spec.setdefault("title", item["caption"])
        if not chart_spec_ok(spec):
            return False
        data = chart_png(spec, o.chart_colors(), C.INK, C.MUTED, C.HAIR, lang)
        m = Media(id=f"c{item['n']}", kind="chart", data=data, fmt="png", w=1600, h=820, alt=item["caption"])
        od._picture(d, m, 15.0)
    else:
        m = media.get(item["media"])
        if m is None:
            return False
        width = _TEXT_CM if m.ratio >= 1.25 else min(_TEXT_CM, 9.5 * m.ratio)
        od._picture(d, m, width)
    credit = " · ".join(x for x in (item.get("credit"), item.get("licence")) if x)
    od._caption(d, item["n"], item.get("caption") or "", credit, item.get("source") or "", lang)
    return True


def _cover(d, doc: dict, lk: dict, lang: str) -> None:
    from docx.shared import Pt

    d.add_paragraph().paragraph_format.space_after = Pt(150)
    kicker = d.add_paragraph(lk["name"].upper(), style="Bird Cover Date")
    kicker.paragraph_format.space_after = Pt(10)
    for r in kicker.runs:
        r.bold = True
    title = doc.get("title") or ""
    par = d.add_paragraph(title, style="Title")
    for run in par.runs:
        run.font.size = Pt(32 if len(title) <= 50 else 26)
    if doc.get("subtitle"):
        d.add_paragraph(doc["subtitle"], style="Subtitle").paragraph_format.space_after = Pt(6)
    line = " · ".join(x for x in (doc.get("date") or o._long_date(lang), doc.get("author") or "") if x)
    d.add_paragraph(line, style="Bird Cover Date")
    od._page_break(d)


def _head(d, doc: dict, lk: dict, lang: str) -> None:
    """The compact head of a document without a cover page (minutes, procedure)."""
    from docx.shared import Pt

    kicker = d.add_paragraph(lk["name"].upper(), style="Bird Cover Date")
    for r in kicker.runs:
        r.bold = True
    o._cover(d, doc.get("title") or "", doc.get("subtitle") or None)
    line = " · ".join(x for x in (doc.get("date") or o._long_date(lang), doc.get("author") or "") if x)
    d.add_paragraph(line, style="Bird Cover Date").paragraph_format.space_after = Pt(18)


def _letter_head(d, doc: dict, lang: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    if doc.get("author"):
        par = d.add_paragraph()
        par.add_run(doc["author"]).bold = True
    date = d.add_paragraph(("Le " if lang != "en" else "") + (doc.get("date") or o._long_date(lang)))
    date.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date.paragraph_format.space_after = Pt(18)
    if doc.get("recipient"):
        for line in re.split(r"\s*(?:\n|,|;)\s*", doc["recipient"])[:5]:
            par = d.add_paragraph(line)
            par.paragraph_format.left_indent = Cm(9.5)
            par.paragraph_format.space_after = Pt(0)
        d.add_paragraph().paragraph_format.space_after = Pt(12)
    obj = d.add_paragraph()
    r = obj.add_run(LABELS[lang]["object"] + (" : " if lang != "en" else ": "))
    r.bold = True
    obj.add_run(doc.get("title") or "").bold = True
    obj.paragraph_format.space_after = Pt(16)


def build(path, doc: dict, media: list[Media]) -> dict:
    """Write ``doc`` (validated, kind « doc ») to ``path``. Returns what was placed (for the tests)."""
    name = o.pick_theme("", doc.get("theme"))
    token = o._THEME.set(o.THEMES[name])
    try:
        return _build(path, doc, {m.id: m for m in media})
    finally:
        o._THEME.reset(token)


def _build(path, doc: dict, media: dict[str, Media]) -> dict:
    from docx import Document
    from docx.shared import Cm, Pt

    lang = "en" if doc.get("lang") == "en" else "fr"
    lk = look(doc)
    plan = outline(doc)
    marks = _marks(doc)
    d = Document()
    o._docx_styles(d)
    od._styles(d)
    d.core_properties.title = (doc.get("title") or "")[:200]
    if doc.get("author"):
        d.core_properties.author = doc["author"][:120]
    if lk["letter"]:
        _letter_head(d, doc, lang)
    else:
        o._furniture(d, doc.get("title") or "")
        if lk["cover"]:
            _cover(d, doc, lk, lang)
        else:
            _head(d, doc, lk, lang)
        if lk["toc"]:
            heads = [(1 if x["k"] == "h1" else 2, x["text"], f"_bird_h{j}") for j, x in enumerate(plan)
                     if x["k"] in ("h1", "h2")]  # fmt: skip
            od._toc(d, heads, lang)
            if lk["cover"]:
                od._page_break(d)
            else:
                d.add_paragraph().paragraph_format.space_after = Pt(6)
    stats = {"headings": [], "tables": 0, "figures": 0, "callouts": 0, "notes": 0, "look": lk}
    for j, x in enumerate(plan):
        k = x["k"]
        if k in ("h1", "h2", "h3"):
            level = int(k[1])
            h = d.add_heading(x["text"], level=level)
            if level <= 2:
                od._bookmark(h, f"_bird_h{j}", 200 + j)
            stats["headings"].append((level, x["text"]))
        elif k == "figure":
            stats["figures"] += _figure(d, x, media, lang)
        elif k == "notes":
            par = d.add_paragraph(LABELS[lang]["notes"], style="Heading 3" if lk["letter"] else "Heading 2")
            del par
            for it in x["items"]:
                par = d.add_paragraph(style="Bird Source")
                r = par.add_run(str(it["n"]))
                r.font.superscript = True
                par.add_run(" " + it["text"])
                stats["notes"] += 1
        else:
            p = x["part"]
            if k == "text":
                par = d.add_paragraph()
                _runs(par, p.get("text") or "", marks)
                if lk["letter"]:
                    par.paragraph_format.space_after = Pt(10)
            elif k == "list":
                _list(d, p, marks)
            elif k == "callout":
                _callout(d, p.get("text") or "", p.get("tone") or "info", lang, marks)
                stats["callouts"] += 1
            elif k == "table":
                rows = [[_plain_marks(c, marks) for c in r] for r in p.get("rows") or [] if r]
                if rows:
                    o._table(d, rows)
                    stats["tables"] += 1
            elif k == "quote":
                par = d.add_paragraph(style="Quote")
                _runs(par, p.get("text") or "", marks)
                if p.get("by"):
                    par.add_run(" — " + p["by"]).italic = True
            elif k == "kpi":
                rows = [["Indicateur" if lang != "en" else "Indicator", "Valeur" if lang != "en" else "Value"]]
                rows += [[x2.get("label") or "", " ".join(v for v in (x2.get("value"), x2.get("delta")) if v)]
                         for x2 in p.get("items") or []]  # fmt: skip
                o._table(d, rows)
                stats["tables"] += 1
            elif k == "timeline":
                _list(d, {"items": [f"**{i.get('when')}** : {i.get('what')}" if i.get("when") else i.get("what", "")
                                    for i in p.get("items") or []]}, marks)  # fmt: skip
            elif k == "code":
                par = d.add_paragraph()
                par.paragraph_format.left_indent = Cm(0.5)
                r = par.add_run(p.get("text") or "")
                r.font.name, r.font.size = "Consolas", Pt(9)
    o._finish(d)
    d.save(str(path))
    return stats
