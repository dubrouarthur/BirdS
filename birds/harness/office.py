"""Office files with a sober, consistent Bird look: .pptx, .docx, .xlsx (python-pptx, python-docx, openpyxl).

Inputs are what the model gave to make_slides / make_document / make_sheet (already validated), or an answer in
Markdown (export of any answer as .docx). No network, no template file, no font download: the files use
Calibri, which Office has and LibreOffice replaces by the metric-compatible Carlito.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

NAVY, BLUE, INK, MUTED, LINE, SOFT = "0B1B3F", "1E5BD8", "121A2E", "586078", "DDDBD1", "E2E9F8"
FONT = "Calibri"

# ------------------------------------------------------------------ a small Markdown reader (blocks + inline bold)


@dataclass
class Block:
    kind: str  # heading | para | bullet | number | table | quote | code
    text: str = ""
    level: int = 0
    rows: list[list[str]] = field(default_factory=list)


_BUL = re.compile(r"^(\s*)(?:[-*+•·▪◦]|–)\s+(.*)$")
_NUM = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _cells(line: str, sep: str) -> list[str]:
    s = line.strip()
    if sep == "|":
        s = s.strip("|")
    return [c.strip() for c in s.split(sep)]


def _table_sep(lines: list[str]) -> str | None:
    """The separator of a block of lines that forms a table: '|' (Markdown), tab, or ';' (CSV-like)."""
    if len(lines) < 2:
        return None
    for sep in ("|", "\t", ";"):
        counts = [len(_cells(ln, sep)) for ln in lines if not _SEP.match(ln)]
        if sep in lines[0] and counts and min(counts) >= 2 and len(set(counts)) == 1:
            return sep
    return None


def parse_markdown(text: str) -> list[Block]:
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    out: list[Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.strip().startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append(Block("code", "\n".join(lines[i + 1 : j])))
            i = j + 1
            continue
        # a run of consecutive non-empty lines that all look like table rows
        j = i
        while j < len(lines) and lines[j].strip() and not _BUL.match(lines[j]) and not _HEAD.match(lines[j]):
            j += 1
        sep = _table_sep(lines[i:j])
        if sep:
            rows = [_cells(ln, sep) for ln in lines[i:j] if not _SEP.match(ln)]
            out.append(Block("table", rows=rows))
            i = j
            continue
        if m := _HEAD.match(line):
            out.append(Block("heading", m.group(2).strip(), len(m.group(1))))
        elif m := _BUL.match(line):
            out.append(Block("bullet", m.group(2).strip(), min(len(m.group(1).expandtabs(4)) // 2, 2)))
        elif m := _NUM.match(line):
            out.append(Block("number", m.group(3).strip(), min(len(m.group(1).expandtabs(4)) // 2, 2)))
        elif line.lstrip().startswith(">"):
            out.append(Block("quote", line.lstrip()[1:].strip()))
        else:
            out.append(Block("para", line.strip()))
        i += 1
    return out


_INLINE = re.compile(r"(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\))")


def inline_runs(text: str) -> list[tuple[str, str]]:
    """[(style, text)] with style in '', 'b', 'code'. Links keep their label; italics markers are dropped."""
    runs = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith(("**", "__")) and len(part) > 4:
            runs.append(("b", part[2:-2]))
        elif part.startswith("`"):
            runs.append(("code", part[1:-1]))
        elif part.startswith("[") and "](" in part:
            runs.append(("", part[1 : part.index("](")]))
        else:
            runs.append(("", re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])", r"\1", part)))
    return runs


def plain(text: str) -> str:
    return "".join(t for _, t in inline_runs(text))


# ------------------------------------------------------------------ .pptx


def _rgb(hexstr: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(hexstr)


def _bullet(paragraph, level: int, char: str = "•") -> None:
    """Real bullets (a:buChar) with a hanging indent, so wrapped lines align under the text."""
    from pptx.oxml.ns import qn

    p_pr = paragraph._p.get_or_add_pPr()
    indent = 342900  # 0.375 in
    p_pr.set("marL", str(indent * (level + 1)))
    p_pr.set("indent", str(-indent))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum", "a:buClr", "a:buFont"):
        for el in p_pr.findall(qn(tag)):
            p_pr.remove(el)
    clr = p_pr.makeelement(qn("a:buClr"), {})
    srgb = clr.makeelement(qn("a:srgbClr"), {"val": BLUE if level == 0 else MUTED})
    clr.append(srgb)
    p_pr.append(clr)
    p_pr.append(p_pr.makeelement(qn("a:buFont"), {"typeface": "Arial"}))
    p_pr.append(p_pr.makeelement(qn("a:buChar"), {"char": char}))


def _text(frame, text: str, size: float, color: str = INK, bold: bool = False, font: str = FONT):
    from pptx.enum.text import PP_ALIGN

    p = frame.paragraphs[0]
    p.text = ""
    p.alignment = PP_ALIGN.LEFT
    _runs(p, text, size, color, bold, font)
    return p


def _runs(p, text: str, size: float, color: str, bold: bool = False, font: str = FONT) -> None:
    from pptx.util import Pt

    for style, chunk in inline_runs(text):
        r = p.add_run()
        r.text = chunk
        r.font.size, r.font.name, r.font.bold = Pt(size), font, bold or style == "b"
        r.font.color.rgb = _rgb(color)


def _box(slide, x, y, w, h, fill: str | None = None):
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shape.line.fill.background()
    if fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(fill)
    else:
        shape.fill.background()
    shape.shadow.inherit = False
    return shape


def _level(bullet: str) -> tuple[int, str]:
    """Bullet hierarchy from the text itself: '  - x', '-- x', '> x' or '◦ x' is a sub-point."""
    m = re.match(r"^(\s{2,}|\t+|-{1,2}\s|>\s?|◦\s?|–\s)(.*)$", bullet)
    return (1, m.group(2).strip()) if m and m.group(2).strip() else (0, bullet.strip())


def plan_slides(slides: list[dict], max_lines: int = 6, max_chars: int = 520) -> list[dict]:
    """Split long slides into balanced continuation slides so nothing overflows; each part keeps the title."""
    out = []
    for s in slides:
        bullets = [str(b) for b in (s.get("bullets") or []) if str(b).strip()]
        chars = sum(len(b) for b in bullets)
        n_parts = max(1, -(-len(bullets) // max_lines), -(-chars // max_chars))
        n_parts = min(n_parts, max(1, len(bullets)))
        size = -(-len(bullets) // n_parts) if bullets else 0
        parts = [bullets[i : i + size] for i in range(0, len(bullets), size)] if bullets else [[]]
        for k, part in enumerate(parts):
            title = str(s.get("title") or "")
            out.append(
                {
                    "title": title + (f" ({k + 1}/{len(parts)})" if len(parts) > 1 else ""),
                    "bullets": part,
                    "notes": str(s.get("notes") or "") if k == 0 else "",
                    "section": not bullets,
                }
            )
    return out


def _font_size(bullets: list[str]) -> float:
    n, chars = len(bullets), sum(len(b) for b in bullets)
    if n <= 4 and chars <= 300:
        return 28
    if n <= 6 and chars <= 420:
        return 24
    return 21


def build_pptx(path, title: str, slides: list[dict], subtitle: str = "") -> int:
    """Write the deck; return the number of slides written (title slide included)."""
    from pptx import Presentation
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    W, H = prs.slide_width, prs.slide_height
    blank = prs.slide_layouts[5]  # "Title Only": real slide titles (outline view, screen readers, read_file)

    def title_box(slide, x, y, w, h):
        t = slide.shapes.title
        t.left, t.top, t.width, t.height = x, y, w, h
        sp = t._element  # drawn last, above the decorative shapes added after it
        tree = sp.getparent()
        tree.remove(sp)
        tree.append(sp)
        t.text_frame.word_wrap = True
        return t

    plan = plan_slides(slides)
    total = len(plan) + 1

    def footer(slide, n: int, dark: bool = False):
        tb = slide.shapes.add_textbox(W - Inches(1.9), H - Inches(0.6), Inches(1.2), Inches(0.35))
        tb.text_frame.word_wrap = True
        p = _text(tb.text_frame, f"{n} / {total}", 12, "C9D3EA" if dark else MUTED)
        p.alignment = PP_ALIGN.RIGHT
        if not dark:
            tb = slide.shapes.add_textbox(Inches(0.7), H - Inches(0.6), Inches(9), Inches(0.35))
            tb.text_frame.word_wrap = True
            _text(tb.text_frame, title[:90], 12, MUTED).alignment = PP_ALIGN.LEFT

    # title slide
    s = prs.slides.add_slide(blank)
    _box(s, 0, 0, W, H, NAVY)
    _box(s, Inches(0.9), Inches(3.05), Inches(0.9), Emu(54000), BLUE)
    tb = title_box(s, Inches(0.9), Inches(1.2), W - Inches(1.8), Inches(1.75))
    tf = tb.text_frame
    tf.word_wrap, tf.vertical_anchor = True, MSO_ANCHOR.BOTTOM
    _text(tf, title, 48 if len(title) < 50 else 36, "FFFFFF", bold=True)
    sub = subtitle or dt.date.today().strftime("%d/%m/%Y")
    tb = s.shapes.add_textbox(Inches(0.9), Inches(3.3), W - Inches(1.8), Inches(1.0))
    tb.text_frame.word_wrap = True
    _text(tb.text_frame, sub, 22, "C9D3EA")
    footer(s, 1, dark=True)

    for n, item in enumerate(plan, start=2):
        s = prs.slides.add_slide(blank)
        if item["section"]:  # a slide without bullets is a section divider
            _box(s, 0, 0, Inches(0.35), H, BLUE)
            _box(s, Inches(0.35), 0, W - Inches(0.35), H, SOFT)
            tb = title_box(s, Inches(1.2), Inches(2.6), W - Inches(2.4), Inches(2.0))
            tb.text_frame.word_wrap, tb.text_frame.vertical_anchor = True, MSO_ANCHOR.MIDDLE
            _text(tb.text_frame, item["title"], 44, NAVY, bold=True)
            footer(s, n)
        else:
            _box(s, 0, 0, W, Inches(0.12), NAVY)
            tb = title_box(s, Inches(0.7), Inches(0.45), W - Inches(1.4), Inches(1.0))
            tb.text_frame.word_wrap, tb.text_frame.vertical_anchor = True, MSO_ANCHOR.BOTTOM
            _text(tb.text_frame, item["title"], 36 if len(item["title"]) < 50 else 28, NAVY, bold=True)
            _box(s, Inches(0.7), Inches(1.6), Inches(0.9), Emu(45000), BLUE)
            body = s.shapes.add_textbox(Inches(0.7), Inches(2.0), W - Inches(1.4), H - Inches(2.8))
            tf = body.text_frame
            tf.word_wrap = True
            size = _font_size(item["bullets"])
            for i, raw in enumerate(item["bullets"]):
                level, text = _level(raw)
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                _runs(p, text, size - 3 * level, INK if level == 0 else "39435C")
                _bullet(p, level, "•" if level == 0 else "–")
                p.space_after = Pt(14 if level == 0 else 6)
                p.line_spacing = 1.08
            footer(s, n)
        if item["notes"]:
            s.notes_slide.notes_text_frame.text = item["notes"][:4000]
    prs.save(str(path))
    return total


# ------------------------------------------------------------------ .docx


def _docx_styles(doc) -> None:
    from docx.shared import Pt, RGBColor

    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = FONT, Pt(11)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for name, size, color in (
        ("Title", 26, NAVY),
        ("Subtitle", 13, MUTED),
        ("Heading 1", 16, NAVY),
        ("Heading 2", 13, NAVY),
        ("Heading 3", 11.5, "39435C"),
    ):
        st = doc.styles[name]
        st.font.name, st.font.size, st.font.bold = FONT, Pt(size), name != "Subtitle"
        st.font.italic = False
        st.font.color.rgb = RGBColor.from_string(color)
        # the theme fonts of the default template would override the name in East Asian / complex scripts
        rpr = st.element.get_or_add_rPr()
        fonts = rpr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts")
        if fonts is not None:
            for k in list(fonts.attrib):
                if "Theme" in k:
                    del fonts.attrib[k]
    title = doc.styles["Title"]
    title.paragraph_format.space_after = Pt(4)
    ppr = title.element.get_or_add_pPr()  # drop the default blue bottom border of "Title"
    for el in ppr.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr"):
        ppr.remove(el)
    doc.styles["Heading 1"].paragraph_format.space_before = Pt(16)
    for sec in doc.sections:
        from docx.shared import Cm

        sec.left_margin = sec.right_margin = Cm(2.2)
        sec.top_margin = sec.bottom_margin = Cm(2.0)


def _add_runs(par, text: str) -> None:
    from docx.shared import Pt

    for style, chunk in inline_runs(text):
        r = par.add_run(chunk)
        if style == "b":
            r.bold = True
        elif style == "code":
            r.font.name, r.font.size = "Consolas", Pt(10)


def _shade(cell, fill: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _table(doc, rows: list[list[str]]) -> None:
    from docx.shared import Pt, RGBColor

    width = max(len(r) for r in rows)
    table = doc.add_table(rows=0, cols=width)
    table.style = doc.styles["Table Grid"]
    for i, row in enumerate(rows[:200]):
        cells = table.add_row().cells
        for j in range(width):
            value = row[j] if j < len(row) else ""
            par = cells[j].paragraphs[0]
            par.paragraph_format.space_after = Pt(0)
            _add_runs(par, value)
            if i == 0:
                _shade(cells[j], NAVY)
                for r in par.runs:
                    r.bold, r.font.color.rgb = True, RGBColor(0xFF, 0xFF, 0xFF)
            elif i % 2 == 0:
                _shade(cells[j], "F3F5FA")
            if i and re.fullmatch(r"[-+]?[\d\s.,]+\s?[%€$£]?", value.strip() or "x"):
                from docx.enum.text import WD_ALIGN_PARAGRAPH

                par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph()


def _blocks_to_docx(doc, blocks: list[Block], base_level: int = 1) -> None:
    for b in blocks:
        if b.kind == "heading":
            doc.add_heading(plain(b.text), level=min(3, base_level + max(0, b.level - 1)))
        elif b.kind in ("bullet", "number"):
            style = ("List Bullet" if b.kind == "bullet" else "List Number") + (f" {b.level + 1}" if b.level else "")
            _add_runs(doc.add_paragraph(style=style), b.text)
        elif b.kind == "table":
            _table(doc, b.rows)
        elif b.kind == "quote":
            par = doc.add_paragraph(style="Quote")
            _add_runs(par, b.text)
        elif b.kind == "code":
            from docx.shared import Pt

            par = doc.add_paragraph()
            r = par.add_run(b.text)
            r.font.name, r.font.size = "Consolas", Pt(9.5)
        else:
            _add_runs(doc.add_paragraph(), b.text)


def build_docx(path, title: str, sections: list[dict], subtitle: str = "") -> dict:
    """Write the document; return counts for the summary (sections, tables, list items)."""
    from docx import Document

    doc = Document()
    _docx_styles(doc)
    doc.core_properties.title = title[:200]
    doc.add_paragraph(title, style="Title")
    doc.add_paragraph(subtitle or dt.date.today().strftime("%d/%m/%Y"), style="Subtitle")
    stats = {"sections": len(sections), "tables": 0, "items": 0}
    for s in sections:
        doc.add_heading(plain(str(s.get("heading") or "")), level=1)
        blocks = parse_markdown(str(s.get("content") or ""))
        stats["tables"] += sum(b.kind == "table" for b in blocks)
        stats["items"] += sum(b.kind in ("bullet", "number") for b in blocks)
        _blocks_to_docx(doc, blocks, base_level=2)
    doc.save(str(path))
    return stats


def docx_from_markdown(path, title: str, markdown: str) -> None:
    """Export of an answer: '# x' headings become document headings, lists and tables are kept."""
    from docx import Document

    doc = Document()
    _docx_styles(doc)
    doc.core_properties.title = title[:200]
    blocks = parse_markdown(markdown)
    if not (blocks and blocks[0].kind == "heading" and blocks[0].level == 1):
        doc.add_paragraph(title, style="Title")
    else:
        doc.add_paragraph(plain(blocks.pop(0).text), style="Title")
    _blocks_to_docx(doc, blocks, base_level=1)
    doc.save(str(path))


# ------------------------------------------------------------------ .xlsx

# Formulas are kept (a spreadsheet without formulas is a dead table), except those that reach outside the file.
_UNSAFE_FORMULA = re.compile(
    r"WEBSERVICE|FILTERXML|HYPERLINK|IMPORT\w*|CALL\s*\(|REGISTER|EXEC|RTD\s*\(|DDE|INFO\s*\(|"
    r"://|\\\\|\[[^\]]*\]|\||!\s*'?[A-Za-z]:",
    re.I,
)


def safe_formula(value: str) -> bool:
    return value.startswith("=") and len(value) <= 2000 and not _UNSAFE_FORMULA.search(value)


_PCT = re.compile(r"^([-+]?\d+(?:[.,]\d+)?)\s?%$")
_CUR = re.compile(r"^([-+]?[\d\s \xa0.,]*\d)\s?(€|\$|£|EUR|USD)$|^(€|\$|£)\s?([-+]?[\d\s \xa0.,]*\d)$")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$|^(\d{2})/(\d{2})/(\d{4})$")


def _to_number(s: str) -> float | int | None:
    t = s.replace(" ", "").replace("\xa0", "").replace(" ", "")
    if re.fullmatch(r"0\d+", t) or len(t.replace(".", "").replace(",", "")) > 15:
        return None  # phone numbers, postcodes, identifiers: keep as text
    if re.fullmatch(r"[-+]?\d+", t):
        return int(t)
    if re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+,\d+", t):  # 1.234,5
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):  # 1,234.5
        t = t.replace(",", "")
    elif re.fullmatch(r"[-+]?\d+,\d+", t):  # 12,5
        t = t.replace(",", ".")
    try:
        return float(t) if re.fullmatch(r"[-+]?\d*\.\d+|[-+]?\d+\.?\d*", t) else None
    except ValueError:
        return None


def typed_cell(value):
    """(value, number_format or None) for one cell written by the model."""
    if isinstance(value, bool) or value is None:
        return value, None
    if isinstance(value, int):
        return value, "#,##0"
    if isinstance(value, float):
        return value, "#,##0.00"
    s = str(value).strip()
    if s.startswith("="):
        return (s, None) if safe_formula(s) else (s, "@")
    if m := _PCT.match(s):
        n = _to_number(m.group(1))
        if n is not None:
            return n / 100, "0.0 %" if "." in str(n) or "," in m.group(1) else "0 %"
    if m := _CUR.match(s):
        num, sym = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        n = _to_number(num)
        if n is not None:
            sym = {"EUR": "€", "USD": "$"}.get(sym, sym)
            return n, f'#,##0.00 "{sym}"' if isinstance(n, float) and not n.is_integer() else f'#,##0 "{sym}"'
    if m := _DATE.match(s):
        try:
            y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(6), m.group(5), m.group(4))
            return dt.date(int(y), int(mo), int(d)), "dd/mm/yyyy"
        except ValueError:
            pass
    n = _to_number(s)
    if n is not None:
        return n, "#,##0" if isinstance(n, int) else "#,##0.00"
    return s, None


def build_xlsx(path, title: str, columns: list, rows: list[list]) -> dict:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", " ", title)[:31].strip() or "Feuille"
    wb.properties.title = title[:200]
    head_font = Font(name=FONT, bold=True, color="FFFFFF", size=11)
    head_fill = PatternFill("solid", fgColor=NAVY)
    thin = Side(style="thin", color=LINE)
    ws.append([str(c) for c in columns])
    for cell in ws[1]:
        cell.font, cell.fill = head_font, head_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(bottom=thin)
    ws.row_dimensions[1].height = 22
    formulas = blocked = 0
    widths = [len(str(c)) for c in columns]
    body_font = Font(name=FONT, size=11)
    for r, row in enumerate(rows, start=2):
        for c, raw in enumerate(list(row)[: max(len(columns), len(row))], start=1):
            value, fmt = typed_cell(raw)
            cell = ws.cell(row=r, column=c)
            if fmt == "@":  # an unsafe formula: written as text, never evaluated
                cell.value = value
                cell.data_type = "s"
                blocked += 1
            else:
                cell.value = value
                if isinstance(value, str) and value.startswith("="):
                    formulas += 1
                elif isinstance(value, str) and value[:1] in "+-@" and len(value) > 1:
                    cell.data_type = "s"  # CSV-style injection markers stay text
                if fmt:
                    cell.number_format = fmt
            cell.font = body_font
            cell.border = Border(bottom=thin)
            if isinstance(value, int | float) and not isinstance(value, bool):
                cell.alignment = Alignment(horizontal="right")
            if c <= len(widths):
                shown = (
                    12 if isinstance(value, str) and value.startswith("=") else len(str(raw if raw is not None else ""))
                )
                widths[c - 1] = max(widths[c - 1], min(shown, 60))
            else:
                widths.append(min(len(str(raw)), 60))
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(9, min(w + 3, 62))
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(max(1, len(columns)))}{len(rows) + 1}"
    ws.sheet_view.showGridLines = True
    wb.save(str(path))
    return {"formulas": formulas, "blocked_formulas": blocked}
