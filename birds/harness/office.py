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
    indent = 274320  # 0.30 in
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


def _runs(p, text: str, size: float, color: str, bold: bool = False, font: str = FONT) -> None:
    from pptx.util import Pt

    for style, chunk in inline_runs(text):
        r = p.add_run()
        r.text = nbsp(chunk)
        r.font.size, r.font.name, r.font.bold = Pt(size), font, bold or style == "b"
        r.font.color.rgb = _rgb(color)


# French typography: no line break inside '3 200', before '%', '€', ':', '?', '!' or after '«'
_NBSP = re.compile(r"(?<=\d) (?=\d{3}(?!\d))|(?<=\S) (?=(?:%|€|k€|K€|M€|Md€|Mds€|:|\?|!|»|;)(?!\w))|(?<=«) ")


def nbsp(text: str) -> str:
    return _NBSP.sub("\xa0", text)


def _box(slide, x, y, w, h, fill: str | None = None):
    from pptx.enum.shapes import MSO_SHAPE

    return _shape(slide, MSO_SHAPE.RECTANGLE, x, y, w, h, fill)


def _level(bullet: str) -> tuple[int, str]:
    """Bullet hierarchy from the text itself: '  - x', '-- x', '> x' or '◦ x' is a sub-point."""
    m = re.match(r"^(\s{2,}|\t+|-{1,2}\s|>\s?|◦\s?|–\s)(.*)$", bullet)
    return (1, m.group(2).strip()) if m and m.group(2).strip() else (0, bullet.strip())


# ------------------------------------------------------------------ figures the user gave must reach the deck

KEY_FIGURES = {"fr": "Chiffres clés", "en": "Key figures"}

_FIG = re.compile(
    r"(?<![\w,.])[+\-−]?\d{1,3}(?:[   ]\d{3})*(?!\d)(?:[.,]\d+)?|(?<![\w,.])[+\-−]?\d+(?:[.,]\d+)?"
)
_FIG_UNIT = re.compile(
    r"\s?(?:%|M€|K€|k€|Md€|Mds€|€|M\b|Md\b|k\b|pts?\b|points?\b|heures?\b|hours?\b|jours?\b|days?\b|h\b)", re.I
)
# a span of values ('21 à 26', 'de 3 à 5 jours', 'from 2 to 4'): no single headline figure, so no kpi card
_RANGE = re.compile(r"\d\s*(?:à|a|to|-|–)\s*[+\-−]?\d|\bde\s+\S+\s+à\s|\bfrom\s+\S+\s+to\s", re.I)
_YEAR = re.compile(r"(?:19|20)\d{2}")
_COUNT_WORDS = re.compile(
    r"\s*(?:slides?|diapo\w*|pages?|parties|sections?|points?|minutes?|min\b|mots|lignes|colonnes|bullets?)", re.I
)


def _core(fig: str) -> str:
    """'1 250,00' -> '1250', '+8' -> '8', '1,2' -> '1.2': the value, whatever the spacing and decimal mark."""
    f = re.sub(r"[   ]", "", fig).lstrip("+-−")
    f = f.replace(",", ".")
    if "." in f:
        f = f.rstrip("0").rstrip(".") if re.fullmatch(r"\d+\.\d+", f) else f
    return f


def figures(text: str) -> list[str]:
    """The figures of a request, with their unit ('1,2 M€', '+8 %', '14'), leaving out counts of the deck itself
    ('6 slides') and small list numbers. Years are figures too."""
    out = []
    for m in _FIG.finditer(text or ""):
        after = text[m.end() : m.end() + 20]
        if _COUNT_WORDS.match(after):
            continue
        unit = _FIG_UNIT.match(after)
        fig = m.group(0) + (unit.group(0) if unit else "")
        if not unit and _core(m.group(0)) in {str(i) for i in range(10)} and not re.match(r"\s*[a-zà-ÿ]{3,}", after):
            continue  # a lone digit with nothing after it is a list number, not a figure
        out.append(fig.strip())
    return out


def missing_figures(request: str, slides: list[dict], title: str = "") -> list[str]:
    """Figures of the request that appear nowhere in the deck (title, slide titles, bullets, notes)."""
    deck = " ".join(
        [title]
        + [str(s.get("title") or "") for s in slides]
        + [str(b) for s in slides for b in (s.get("bullets") or [])]
        + [str(s.get("notes") or "") for s in slides]
    )
    have = {_core(m.group(0)) for m in _FIG.finditer(deck)}
    seen, out = set(), []
    for f in figures(request):
        core = _core(re.sub(_FIG_UNIT.pattern + "$", "", f, flags=re.I).strip())
        if core and core not in have and core not in seen:
            seen.add(core)
            out.append(f)
    return out


def figure_bullets(request: str, missing: list[str]) -> list[str]:
    """The passages of the request that carry the missing figures, as bullets ('CA 1,2 M€ (+8 %)')."""
    body = request.split(":", 1)[1] if ":" in request else request
    parts = [p.strip(" .;\n") for p in re.split(r"[;\n]|,(?!\d)|\s+et\s+|\s+and\s+", body) if p.strip(" .;\n")]
    out = []
    for f in missing:
        core = _core(re.sub(_FIG_UNIT.pattern + "$", "", f, flags=re.I).strip())
        part = next((p for p in parts if core in {_core(m.group(0)) for m in _FIG.finditer(p)}), f)
        part = part[:1].upper() + part[1:]
        if part not in out:
            out.append(part[:90])
    return out


# ------------------------------------------------------------------ layouts chosen from the content

_STEP = re.compile(r"^(?:(?:phase|étape|etape|step|stage|jalon)\s*\d+|\d{1,2}[.)])\s*[:.\-–—]?\s*", re.I)


def layout_of(bullets: list[str]) -> str:
    """'kpi' (1-4 short lines, each with a figure), 'steps' (3-5 numbered phases), 'columns' (6+ short points)
    or 'bullets'."""
    if any(_level(b)[0] for b in bullets):
        return "bullets"
    if 3 <= len(bullets) <= 5 and all(_STEP.match(b) and len(_STEP.sub("", b)) <= 70 for b in bullets):
        return "steps"  # before kpi: "Phase 1 : ..." carries a digit but is not a figure
    if 1 <= len(bullets) <= 4 and all(
        len(b) <= 60 and _FIG.search(b) and not _STEP.match(b) and not _RANGE.search(b) for b in bullets
    ):
        return "kpi"
    if len(bullets) >= 6 and all(len(b) <= 60 for b in bullets):
        return "columns"
    return "bullets"


def kpi_parts(bullet: str) -> tuple[str, str]:
    """'CA : 1,2 M€ (+8 %)' -> ('1,2 M€', 'CA (+8 %)'): the first figure, big, and what it measures."""
    text = plain(bullet)
    found = list(_FIG.finditer(text))
    # a year ('CA 2026 : 3,4 M€') says when, not how much: the headline is the next figure, if there is one
    m = next(
        (f for f in found if not (_YEAR.fullmatch(f.group(0)) and not _FIG_UNIT.match(text[f.end() :]))),
        found[0],
    )
    unit = _FIG_UNIT.match(text[m.end() :])
    end = m.end() + (len(unit.group(0)) if unit else 0)
    big = text[m.start() : end].strip()
    label = (text[: m.start()] + " " + text[end:]).replace(":", " ").strip()
    label = re.sub(r"\s{2,}", " ", re.sub(r"^\W+|[\s:–—-]+$", "", label)).strip(" :–—-")
    label = re.sub(r"\(\s*\)", "", label).strip()
    return big, label[:1].upper() + label[1:] if label else ""


def plan_slides(slides: list[dict], max_lines: int = 6, max_chars: int = 680) -> list[dict]:
    """Split long slides into balanced continuation slides so nothing overflows; each part keeps the title."""
    out = []
    for g, s in enumerate(slides):
        bullets = [str(b) for b in (s.get("bullets") or []) if str(b).strip()]
        chars = sum(len(b) for b in bullets)
        short = all(len(b) <= 60 for b in bullets) and not any(_level(b)[0] for b in bullets)
        lines, limit = (10, 640) if short else (max_lines, max_chars)  # short points fit on two columns
        n_parts = max(1, -(-len(bullets) // lines), -(-chars // limit))
        n_parts = min(n_parts, max(1, len(bullets)))
        size = -(-len(bullets) // n_parts) if bullets else 0
        parts = [bullets[i : i + size] for i in range(0, len(bullets), size)] if bullets else [[]]
        for k, part in enumerate(parts):
            title = str(s.get("title") or "")
            out.append(
                {
                    "title": title + (f" ({k + 1}/{len(parts)})" if len(parts) > 1 else ""),
                    "base": title,
                    "suffix": f" ({k + 1}/{len(parts)})" if len(parts) > 1 else "",
                    "offset": k * size,  # bullets of the same slide on the parts before: numbering continues
                    "bullets": part,
                    "notes": str(s.get("notes") or "") if k == 0 else "",
                    "section": not bullets,
                    "group": g,
                }
            )
    return out


# ------------------------------------------------------------------ deck rendering (design system v2)

# Grid of the 16:9 canvas, in EMU: 0.75 in margins, 12 columns with 0.25 in gutters.
_IN = 914400
_W, _H = 12192000, 6858000
_M, _COL, _GUT = 685800, 692150, 228600
_CW = _W - 2 * _M
_TOP, _BOT = int(2.20 * _IN), int(6.55 * _IN)  # content zone
_TINT, _GREEN = "F4F6FB", "5BD69B"
_ON_NAVY, _ON_NAVY_2, _HAIR, _SUB, _NAVY_LINE = "C9D3EA", "8FA0C8", "D9DEE8", "39435C", "24366B"
_MONTHS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTH = re.compile(
    r"\s*(?:janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[ée]c|jan|feb|mar|apr|may|jun|jul|aug|sep)",
    re.I,
)
_FUNCTION_END = re.compile(
    r"(?:^|\s)(?:au|aux|à|a|le|la|les|l'|de|du|des|d'|en|pour|par|sur|n°|no|poste|numéro|the|at|on|of|in|to|by)$",
    re.I,
)
_DELTA = re.compile(r"\(\s*([+\-−]\s?\d[^()]*)\)")


def col_x(i: int) -> int:
    return _M + i * (_COL + _GUT)


def span(n: int) -> int:
    return n * _COL + (n - 1) * _GUT


def kpi_ok(bullet: str) -> bool:
    """A figure that is a date ('le 15 janvier'), a time ('à 14h30') or an extension ('poste 214') is no KPI."""
    text = plain(bullet)
    big, label = kpi_parts(text)
    at = text.find(big)
    after = text[at + len(big) :] if at >= 0 else ""
    if _MONTH.match(after) or re.match(r"\s?h\d", after) or re.match(r"\s?(?:h|heures?)\b", after):
        return False
    rest = re.sub(_DELTA, "", label).strip(" .;:!?,–—-")
    before = text[:at].strip(" .;:,–—-") if at >= 0 else ""
    return not (_FUNCTION_END.search(rest) or _FUNCTION_END.search(before))


def _rows_ok(bullets: list[str]) -> bool:
    n, longest = len(bullets), max((len(plain(b)) for b in bullets), default=0)
    if any(_level(b)[0] for b in bullets):
        return False
    return 2 <= n <= 3 and longest <= 220 or 2 <= n <= 5 and longest <= 160 or n == 6 and longest <= 130


def _deck_kinds(plan: list[dict]) -> list[str]:
    """One render kind per planned slide; the parts of a split slide share one look (rows, else a list)."""
    kinds = [render_kind(item["bullets"]) if item["bullets"] else "" for item in plan]
    for g in {item["group"] for item in plan}:
        idx = [i for i, item in enumerate(plan) if item["group"] == g]
        if len({kinds[i] for i in idx}) > 1:
            shared = "rows" if all(_rows_ok(plan[i]["bullets"]) for i in idx) else "list"
            for i in idx:
                kinds[i] = shared
    return kinds


def render_kind(bullets: list[str]) -> str:
    """The way a slide is drawn: layout_of() refined (statement, cards, rows, list) and guarded (kpi_ok)."""
    kind = layout_of(bullets)
    if kind == "kpi" and not all(kpi_ok(b) for b in bullets):
        kind = "bullets"
    if kind != "bullets":
        return kind
    if any(_level(b)[0] for b in bullets):
        return "list"
    n, lens = len(bullets), [len(plain(b)) for b in bullets]
    if n == 1 and lens[0] <= 140:
        return "statement"
    if n in (2, 3) and max(lens) <= 90:
        return "cards"
    if _rows_ok(bullets):
        return "rows"
    return "list"


def _lines(text: str, size: float, width: int, avg: float = 0.5) -> int:
    """Estimated wrapped line count of a Calibri text at `size` pt in a box `width` EMU wide."""
    per_line = max(1, int(width / _IN * 72 / (size * avg)))
    n, cur = 0, 0
    for para in str(text).split("\n"):
        n += 1
        cur = 0
        for word in para.split():
            if cur and cur + 1 + len(word) > per_line:
                n += 1
                cur = len(word)
            else:
                cur += (1 if cur else 0) + len(word)
    return max(1, n)


def _height(lines: int, size: float, spacing: float = 1.0) -> int:
    return int(lines * size * 1.2 * spacing / 72 * _IN)


def _cut(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(" ,;:–—-") + "…"


def _long_date(lang: str) -> str:
    d = dt.date.today()
    months = _MONTHS_EN if lang == "en" else _MONTHS_FR
    return f"{d.day} {months[d.month - 1]} {d.year}"


def _plain_frame(tf, anchor=None) -> None:
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE

    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor if anchor is not None else MSO_ANCHOR.TOP


def _tb(slide, x, y, w, h, anchor=None):
    tb = slide.shapes.add_textbox(int(x), int(y), int(w), int(h))
    _plain_frame(tb.text_frame, anchor)
    return tb


def _par(
    tf,
    text: str,
    size: float,
    color: str = INK,
    bold: bool = False,
    first: bool = True,
    align=None,
    spacing: float | None = None,
    after: float = 0,
    before: float = 0,
    track: int = 0,
):
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Pt

    p = tf.paragraphs[0] if first else tf.add_paragraph()
    if first:
        p.text = ""
    p.alignment = align if align is not None else PP_ALIGN.LEFT
    _runs(p, text, size, color, bold)
    if track:
        for r in p.runs:
            r._r.get_or_add_rPr().set("spc", str(track))
    if spacing:
        p.line_spacing = spacing
    p.space_after, p.space_before = Pt(after), Pt(before)
    return p


def _nostyle(shape):
    """No theme style: no shadow, outline or white theme font from <p:style>."""
    from pptx.oxml.ns import qn

    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    shape.line.fill.background()
    return shape


def _shape(slide, kind, x, y, w, h, fill: str | None):
    shape = _nostyle(slide.shapes.add_shape(kind, int(x), int(y), int(w), int(h)))
    if fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(fill)
    else:
        shape.fill.background()
    return shape


def _rule(slide, x, y, w, accent: int = int(0.6 * _IN)):
    """A hairline with a short blue accent segment at its left: the one piece of furniture of the deck."""
    _box(slide, x, y, w, 9525, _HAIR)
    _box(slide, x, y - 9525, accent, 28575, BLUE)


def _accent(slide, x, y, h: int = 28575):
    _box(slide, x, y, int(0.6 * _IN), h, BLUE)


def _split_label(label: str) -> tuple[str, str]:
    """'Formation : deux jours' -> ('Formation', 'deux jours'): a bold head and a lighter remainder."""
    for sep in (" : ", " – ", " — ", ": ", ". "):
        if sep in label:
            head, rest = label.split(sep, 1)
            if head.strip() and rest.strip():
                return head.strip(), rest.strip()
    return label, ""


_ZONE = _BOT - _TOP


def _place(block: int) -> int:
    """Top of a block in the content zone: optical centre (2/5 of the leftover), 1/3 for a tall block."""
    left = max(0, _ZONE - block)
    return _TOP + (left // 3 if block > _ZONE // 2 else left * 2 // 5)


def _fold(text: str) -> list[str]:
    import unicodedata

    flat = unicodedata.normalize("NFKD", plain(text).lower())
    return re.findall(r"[a-z0-9]+", "".join(c for c in flat if not unicodedata.combining(c)))


def _redundant(label: str, title: str) -> bool:
    """A label that only repeats the slide title ('Nouveaux clients' under 'Nouveaux clients')."""
    words = _fold(label)
    return bool(words) and set(words) <= set(_fold(title))


def _draw_statement(s, bullets, ctx):
    text = plain(bullets[0])
    size = 32 if len(text) <= 80 else 28
    w = span(10)
    th = _height(_lines(text, size, w), size, 1.1)
    block = int(0.35 * _IN) + th
    y = _place(block)
    _accent(s, _M, y)
    tb = _tb(s, _M, y + int(0.35 * _IN), w, _BOT - y - int(0.35 * _IN))
    _par(tb.text_frame, bullets[0], size, NAVY, spacing=1.1)


def _cards_size(bullets) -> float:
    k = len(bullets)
    w = span(6 if k == 2 else 4)
    if all(len(plain(b)) <= 60 for b in bullets) and all(_lines(plain(b), 28, w, 0.5) <= 4 for b in bullets):
        return 28
    return 24 if all(len(plain(b)) <= 60 for b in bullets) else 20


def _draw_cards(s, bullets, ctx):
    k = len(bullets)
    n_cols = 6 if k == 2 else 4
    size = ctx.get("size") or _cards_size(bullets)
    w = span(n_cols)
    th = max(_height(_lines(plain(b), size, w, 0.5), size, 1.15) for b in bullets)
    head = int(1.2 * _IN)
    block = head + th
    y = _place(block)
    for j, raw in enumerate(bullets):
        x = col_x(j * n_cols)
        _rule(s, x, y, w)
        tb = _tb(s, x, y + int(0.32 * _IN), w, int(0.55 * _IN))
        _par(tb.text_frame, f"{ctx.get('offset', 0) + j + 1:02d}", 32, BLUE, bold=True)
        tb = _tb(s, x, y + head, w, _BOT - y - head)
        _par(tb.text_frame, raw, size, INK, spacing=1.15)


def _rows_metrics(bullets) -> tuple[float, int]:
    n = len(bullets)
    longest = max(len(plain(b)) for b in bullets)
    size = 24 if longest <= 60 and n <= 5 else 20 if longest <= 90 or n <= 3 else 18 if n <= 5 else 16
    rh = min(int((1.05 if n > 3 or longest <= 160 else 1.4) * _IN), _ZONE // n)
    return size, rh


def _draw_rows(s, bullets, ctx):
    n = len(bullets)
    size, rh = _rows_metrics(bullets)
    size, rh = ctx.get("size") or size, ctx.get("rh") or rh
    y0 = ctx.get("y0") or _place(n * rh)
    for j, raw in enumerate(bullets):
        y = y0 + j * rh
        th = _height(_lines(plain(raw), size, span(11), 0.46), size, 1.1)
        ty = y + max(0, (rh - th) // 2)
        # the index sits on the first line of its text (same baseline), not centred on the row
        tb = _tb(s, col_x(0), ty + int((size - 16) * 0.8 / 72 * _IN), _COL, int(0.3 * _IN))
        _par(tb.text_frame, f"{ctx.get('offset', 0) + j + 1:02d}", 16, BLUE, bold=True)
        tb = _tb(s, col_x(1), ty, span(11), y + rh - ty)
        _par(tb.text_frame, raw, size, INK, spacing=1.1)
        _box(s, _M, y + rh - 4762, _CW, 9525, _HAIR)


def _columns_size(bullets) -> float:
    w, pad = span(6), int(0.28 * _IN)
    return next((z for z in (22, 20, 18) if all(_lines(plain(b), z, w - pad) == 1 for b in bullets)), 16)


def _draw_columns(s, bullets, ctx):
    from pptx.enum.text import MSO_ANCHOR

    half = (len(bullets) + 1) // 2
    groups = [bullets[:half], bullets[half:]]
    w = span(6)
    marker, pad = int(0.08 * _IN), int(0.28 * _IN)
    size = ctx.get("size") or _columns_size(bullets)
    rows = ctx.get("half") or half
    rh = min(int(0.8 * _IN), _ZONE // rows)
    y0 = ctx.get("y0") or _place(rows * rh)
    for g, group in enumerate(groups):
        x = col_x(6 * g)
        for j, raw in enumerate(group):
            y = y0 + j * rh
            _box(s, x, y + (rh - marker) // 2, marker, marker, BLUE)
            tb = _tb(s, x + pad, y, w - pad, rh, MSO_ANCHOR.MIDDLE)
            _par(tb.text_frame, raw, size, INK, spacing=1.0)
            _box(s, x, y + rh - 4762, w, 9525, _HAIR)


def _fit(size: float, text: str, width: int) -> float:
    """The largest size <= `size` at which a one-line bold figure fits in `width` (Calibri digits ~0.53 em)."""
    while size > 28 and len(text) * size * 0.55 / 72 * _IN > width:
        size -= 4
    return size


def _chip(s, x, y, delta: str):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

    w, h = int((0.11 * len(delta) + 0.3) * _IN), int(0.32 * _IN)
    chip = _shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, _GREEN if delta.lstrip()[:1] == "+" else SOFT)
    chip.adjustments[0] = 0.5
    _plain_frame(chip.text_frame, MSO_ANCHOR.MIDDLE)
    _par(chip.text_frame, delta, 14, NAVY, bold=True, align=PP_ALIGN.CENTER)


# a figure read as a bound ('Churn below 3%'): the comparator goes into the value ('< 3%'), not the label
_COMPARATORS = (
    (r"less than|below|under|moins de|sous|inf[ée]rieure? [àa]", "<"),
    (r"more than|above|over|plus de|au-del[àa] de|sup[ée]rieure? [àa]", ">"),
    (r"at least|au moins|minimum|min\.?", "≥"),
    (r"at most|up to|maximum|max\.?|au plus|jusqu'[àa]|jusqu’[àa]", "≤"),
)


def _kpi_split(raw: str) -> tuple[str, str, str]:
    big, label = kpi_parts(raw)
    text = plain(raw)
    at = text.find(big)
    before = re.sub(r"[\s:–—-]+$", "", text[:at]) if at > 0 else ""
    for words, sign in _COMPARATORS:
        if m := re.search(rf"(?:^|\s)(?:{words})$", before, re.I):
            big = f"{sign}\xa0{big}"
            head = before[: m.start()].strip()
            label = re.sub(r"\s{2,}", " ", head + " " + text[at + len(kpi_parts(raw)[0]) :]).strip(" :–—-")
            label = label[:1].upper() + label[1:]
            break
    delta = ""
    if m := _DELTA.search(label):
        delta = m.group(1).strip()
        label = re.sub(r"\s{2,}", " ", (label[: m.start()] + label[m.end() :])).strip(" ,;:–—-")
    return big, label, delta


_KPI_LABEL = 18  # one label style for every kpi layout (muted)


def _draw_kpi(s, bullets, ctx):
    from pptx.enum.text import MSO_ANCHOR

    parts = [_kpi_split(b) for b in bullets]
    k = len(parts)
    pad = int(0.34 * _IN)
    tile_h = int(0.66 * _ZONE)
    if k == 1:
        # one figure: a tinted panel across the grid, the number on columns 0-6, what it measures on 7-11
        big, label, delta = parts[0]
        if _redundant(label, ctx.get("title", "")):
            label = ""
        y = _place(tile_h)
        _box(s, _M, y, _CW, tile_h, _TINT)
        _accent(s, _M + pad, y + pad)
        w = span(7) - pad
        size = _fit(120 if len(big) <= 7 else 96, big, w)
        vh = _height(1, size, 0.95)
        tb = _tb(s, _M + pad, y + (tile_h - vh) // 2 + int(0.1 * _IN), w, vh, MSO_ANCHOR.MIDDLE)
        _par(tb.text_frame, big, size, NAVY, bold=True, spacing=0.9)
        if label or delta:
            x, lw = col_x(7) + pad // 2, span(5) - pad
            _box(s, col_x(7) - _GUT // 2, y + pad, 9525, tile_h - 2 * pad, _HAIR)
            lh = _height(_lines(label, 20, lw), 20, 1.15) if label else 0
            block = lh + (int(0.32 * _IN) + (int(0.2 * _IN) if label else 0) if delta else 0)
            ly = y + (tile_h - block) // 2
            if label:
                tb = _tb(s, x, ly, lw, lh + int(0.1 * _IN))
                _par(tb.text_frame, label, 20, MUTED, spacing=1.15)
            if delta:
                _chip(s, x, ly + lh + (int(0.2 * _IN) if label else 0), delta)
        return
    n_cols = {2: 6, 3: 4, 4: 3}[k]
    w = span(n_cols)
    inner = w - 2 * pad
    longest = max(len(p[0]) for p in parts)
    base = {2: (72, 60), 3: (60, 48), 4: (48, 40)}[k]
    size = min(_fit(base[0] if longest <= 7 else base[1], p[0], inner) for p in parts)
    vh = _height(1, size, 0.95)
    lines = max((_lines(p[1], _KPI_LABEL, inner) for p in parts if p[1]), default=0)
    need = 2 * pad + int(0.22 * _IN) + vh + int(0.14 * _IN) + _height(lines, _KPI_LABEL, 1.15)
    need += int(0.5 * _IN) if any(p[2] for p in parts) else 0
    tile_h = max(tile_h, need)
    y = _place(tile_h)
    for j, (big, label, delta) in enumerate(parts):
        x = col_x(j * n_cols)
        _box(s, x, y, w, tile_h, _TINT)
        _accent(s, x + pad, y + pad)
        vy = y + pad + int(0.22 * _IN)
        tb = _tb(s, x + pad, vy, inner, vh, MSO_ANCHOR.BOTTOM)
        _par(tb.text_frame, big, size, NAVY, bold=True, spacing=0.9)
        ly = vy + vh + int(0.14 * _IN)
        if label:
            lh = _height(_lines(label, _KPI_LABEL, inner), _KPI_LABEL, 1.15)
            tb = _tb(s, x + pad, ly, inner, min(int(1.1 * _IN), lh + int(0.1 * _IN)))
            _par(tb.text_frame, label, _KPI_LABEL, MUTED, spacing=1.15)
        if delta:
            _chip(s, x + pad, y + tile_h - pad - int(0.32 * _IN), delta)


def _draw_steps(s, bullets, ctx):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

    k = len(bullets)
    sw = _CW // k
    d = int(0.62 * _IN)
    lw = sw - int(0.3 * _IN)
    labels = [_split_label(_STEP.sub("", plain(b)).strip()) for b in bullets]
    described = any(r for _, r in labels)
    head_size = (20 if described else 24) if k <= 4 else (18 if described else 20)
    rest_size = 16 if k <= 4 else 14
    lh = max(
        _height(_lines(h, head_size, lw, 0.55), head_size, 1.05)
        + (_height(_lines(r, rest_size, lw), rest_size, 1.15) + int(0.08 * _IN) if r else 0)
        for h, r in labels
    )
    gap = int(0.42 * _IN)
    block = d + gap + lh
    y = _place(block)
    _box(s, _M + d // 2, y + d // 2 - 9525, (k - 1) * sw, 19050, _HAIR)  # from the first dot to the last one
    for j, raw in enumerate(bullets):
        x = _M + j * sw
        num = re.search(r"\d+", raw)
        dot = _shape(s, MSO_SHAPE.OVAL, x, y, d, d, BLUE if j < k - 1 else NAVY)
        _plain_frame(dot.text_frame, MSO_ANCHOR.MIDDLE)
        _par(dot.text_frame, num.group(0) if num else str(j + 1), 18, "FFFFFF", bold=True, align=PP_ALIGN.CENTER)
        head, rest = labels[j]
        tb = _tb(s, x, y + d + gap, lw, _BOT - y - d - gap)
        _par(tb.text_frame, head, head_size, NAVY, bold=True, spacing=1.05)
        if rest:
            _par(tb.text_frame, rest, rest_size, INK, first=False, spacing=1.15, before=6)


def _list_size(bullets) -> float:
    n = len(bullets)
    chars = sum(len(plain(b)) for b in bullets)
    return 22 if n <= 6 and chars <= 220 else 20 if n <= 4 and chars <= 360 else 18 if n <= 6 and chars <= 600 else 16


def _draw_list(s, bullets, ctx):
    n = len(bullets)
    size = ctx.get("size") or _list_size(bullets)
    w = span(10) if all(len(plain(b)) <= 110 for b in bullets) else _CW
    tb = _tb(s, _M, _TOP, w, _BOT - _TOP)
    tf = tb.text_frame
    prev = 0
    for i, raw in enumerate(bullets):
        level, text = _level(raw)
        p = _par(
            tf,
            text,
            size - 2 * level,
            INK if level == 0 else _SUB,
            first=i == 0,
            spacing=1.15,
            after=4 if level else (12 if n <= 4 else 8),
            before=4 if (prev and not level) else 0,
        )
        _bullet(p, level, "•" if level == 0 else "–")
        prev = level


_DRAW = {
    "statement": _draw_statement,
    "cards": _draw_cards,
    "rows": _draw_rows,
    "columns": _draw_columns,
    "kpi": _draw_kpi,
    "steps": _draw_steps,
    "list": _draw_list,
}


def _group_context(plan: list[dict], kinds: list[str]) -> list[dict]:
    """Drawing context of each planned slide. The parts of a split slide share one type size, one row height and
    one top edge (chosen for the densest part), and their numbering continues (05 after 04)."""
    ctx = [{"offset": item.get("offset", 0), "title": item.get("base", item["title"])} for item in plan]
    for g in {item["group"] for item in plan}:
        idx = [i for i, item in enumerate(plan) if item["group"] == g and item["bullets"]]
        if len(idx) < 2:
            continue
        kind, parts = kinds[idx[0]], [plan[i]["bullets"] for i in idx]
        shared: dict = {}
        if kind == "rows":
            metrics = [_rows_metrics(b) for b in parts]
            size, rh = min(m[0] for m in metrics), min(m[1] for m in metrics)
            shared = {"size": size, "rh": rh, "y0": _place(max(len(b) for b in parts) * rh)}
        elif kind == "list":
            shared = {"size": min(_list_size(b) for b in parts)}
        elif kind == "columns":
            half = max((len(b) + 1) // 2 for b in parts)
            rh = min(int(0.8 * _IN), _ZONE // half)
            shared = {"size": min(_columns_size(b) for b in parts), "half": half, "y0": _place(half * rh)}
        elif kind == "cards":
            shared = {"size": min(_cards_size(b) for b in parts)}
        for i in idx:
            ctx[i].update(shared)
    return ctx


def build_pptx(path, title: str, slides: list[dict], subtitle: str = "", lang: str = "fr") -> int:
    """Write the deck; return the number of slides written (title slide included)."""
    from pptx import Presentation
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Pt

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
        _plain_frame(t.text_frame, anchor)
        _par(t.text_frame, text, size, color, bold=True, spacing=0.95)
        return t

    plan = plan_slides(slides)
    kinds = _deck_kinds(plan)
    contexts = _group_context(plan, kinds)
    total = len(plan) + 1

    def number(slide, n, color=MUTED):
        tb = _tb(slide, _W - _M - int(1.2 * _IN), int(6.92 * _IN), int(1.2 * _IN), int(0.28 * _IN))
        _par(tb.text_frame, f"{n} / {total}", 10, color, align=PP_ALIGN.RIGHT)

    def dark(slide, text):
        """Full-bleed navy: the title on the grid (columns 0-9) over a short blue tab, a hairline above the foot."""
        text = _cut(text, 200)
        size = 44 if len(text) <= 40 else 40 if len(text) <= 70 else 34 if len(text) <= 120 else 28
        _box(slide, 0, 0, _W, _H, NAVY)
        _box(slide, _M, int(4.78 * _IN), int(0.6 * _IN), 50800, BLUE)
        _box(slide, _M, int(6.45 * _IN), _CW, 9525, _NAVY_LINE)
        title_box(slide, _M, int(1.05 * _IN), span(10), int(3.45 * _IN), text, size, "FFFFFF", MSO_ANCHOR.BOTTOM)

    # title slide
    s = prs.slides.add_slide(blank)
    dark(s, title)
    if subtitle:
        sub = _cut(subtitle, 180)
        tb = _tb(s, _M, int(5.0 * _IN), span(10), int(1.3 * _IN))
        _par(tb.text_frame, sub, 18 if len(sub) <= 90 else 16, _ON_NAVY, spacing=1.1)
    dated = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|\b(?:19|20)\d{2}\b", subtitle or "")
    if not dated:
        tb = _tb(s, _M, int(6.62 * _IN), span(6), int(0.3 * _IN))
        _par(tb.text_frame, _long_date(lang), 12, _ON_NAVY_2)
    tb = _tb(s, col_x(6), int(6.62 * _IN), span(6), int(0.3 * _IN))
    count = f"{total} slides" if lang == "en" else f"{total} diapositives"
    _par(tb.text_frame, count, 12, _ON_NAVY_2, align=PP_ALIGN.RIGHT)

    sections, eyebrow = 0, ""
    for n, item in enumerate(plan, start=2):
        s = prs.slides.add_slide(blank)
        base, suffix = item.get("base", item["title"]), item.get("suffix", "")
        heading = _cut(base, 160) + suffix
        notes = item["notes"]
        if len(re.sub(r"\s+", " ", base).strip()) > 160 and item["offset"] == 0:  # a cut title stays whole in notes
            notes = (base + "\n\n" + notes).strip()
        if item["section"] and n == total:  # the model's closing slide ("Merci", "Questions ?")
            dark(s, heading)
            number(s, n, _ON_NAVY_2)
        elif item["section"]:  # a slide without bullets is a section divider
            sections += 1
            eyebrow = heading
            heading = _cut(heading, 120)
            _box(s, 0, 0, int(4.25 * _IN), _H, NAVY)
            tb = _tb(s, _M, int(2.85 * _IN), int(3.0 * _IN), int(1.3 * _IN))
            _par(tb.text_frame, f"{sections:02d}", 72, _GREEN, bold=True, spacing=0.9)
            _accent(s, int(5.0 * _IN), int(2.85 * _IN))
            title_box(
                s,
                int(5.0 * _IN),
                int(3.15 * _IN),
                _W - int(5.0 * _IN) - _M,
                int(2.9 * _IN),
                heading,
                40 if len(heading) <= 40 else 32 if len(heading) <= 80 else 26,
                NAVY,
                MSO_ANCHOR.TOP,
            )
            number(s, n)
        else:
            if eyebrow:
                tb = _tb(s, _M, int(0.42 * _IN), _CW, int(0.28 * _IN))
                _par(tb.text_frame, _cut(eyebrow, 60).upper(), 11, BLUE, bold=True, track=100)
            size = 30 if len(heading) <= 45 else 26 if len(heading) <= 70 else 22 if len(heading) <= 110 else 18
            title_box(s, _M, int(0.74 * _IN), _CW, int(0.96 * _IN), heading, size, NAVY, MSO_ANCHOR.BOTTOM)
            _rule(s, _M, int(1.84 * _IN), _CW)
            _DRAW[kinds[n - 2]](s, item["bullets"], contexts[n - 2])
            tb = _tb(s, col_x(0), int(6.92 * _IN), span(9), int(0.28 * _IN))
            _par(tb.text_frame, _cut(plain(title), 80), 10, MUTED)
            number(s, n)
        if notes:
            tf = s.notes_slide.notes_text_frame
            tf.text = notes[:4000]
            for p in tf.paragraphs:
                for r in p.runs:
                    r.font.name, r.font.size, r.font.color.rgb = FONT, Pt(12), _rgb(INK)
    prs.save(str(path))
    return total
# ------------------------------------------------------------------ .docx

# A4 page, 2.4 cm side margins: 16.2 cm of text width (in twips, 567 per cm).
_TEXT_TW = 9185
_GREEN_T, _CODE = "EEFAF3", "F3F4F6"
_PPR = (
    "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs "
    "suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd "
    "snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment "
    "textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange"
).split()
_TCPR = "cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection tcFitText vAlign hideMark".split()
_DECISION = re.compile(r"^\W{0,3}(?:d[ée]cision|d[ée]cid[ée]e?s?|valid[ée]e?s?|decided)\b[^:]{0,30}:", re.I)
_ACTION = re.compile(r"^\W{0,3}(?:actions?|[àa] faire|to ?do|next steps?|prochaine [ée]tape)\b[^:]{0,30}:", re.I)
_DECISION_HEAD = re.compile(r"d[ée]cision|decision", re.I)
_ACTION_HEAD = re.compile(r"\bactions?\b|[àa] faire|next steps|prochaines? [ée]tapes|to ?do", re.I)
_NUM_CELL = re.compile(r"[-+−]?\s?(?:[\d\xa0  .,]*\d)\s?(?:%|€|k€|M€|\$|£|pts?|h)?")
_TOTAL_CELL = re.compile(r"(?:sous-?total|total|totaux|grand total)\b", re.I)
_RULE = re.compile(r"[-*_](?:\s*[-*_]){2,}")


def _w(tag: str):
    from docx.oxml import OxmlElement

    return OxmlElement(tag)


def _set(el, **attrs) -> None:
    from docx.oxml.ns import qn

    for k, v in attrs.items():
        el.set(qn(f"w:{k}"), str(v))


def _put(parent, el, order: list[str]):
    """Replace the child of the same tag, inserted at its schema position (Word refuses out-of-order XML)."""
    from docx.oxml.ns import qn

    tag = el.tag.split("}")[1]
    for old in parent.findall(qn(f"w:{tag}")):
        parent.remove(old)
    parent.insert_element_before(el, *[f"w:{t}" for t in order[order.index(tag) + 1 :]])
    return el


def _border(parent_tag: str, sides: dict) -> object:
    """sides: {'left': (size_eighths, colour, space_pt)} -> <w:pBdr>/<w:tcBorders>/<w:tblBorders>."""
    box = _w(parent_tag)
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        if side in sides:
            el = _w(f"w:{side}")
            if sides[side] is None:
                _set(el, val="nil")
            else:
                sz, color, space = sides[side]
                _set(el, val="single", sz=sz, space=space, color=color)
            box.append(el)
    return box


def _shd(fill: str):
    el = _w("w:shd")
    _set(el, val="clear", color="auto", fill=fill)
    return el


def _p_border(ppr, **sides) -> None:
    _put(ppr, _border("w:pBdr", sides), _PPR)


def _pad(fill: str) -> dict:
    """Top and bottom borders in the fill colour: vertical padding for a tinted paragraph."""
    return {"top": (4, fill, 4), "bottom": (4, fill, 4)}


def _p_shade(ppr, fill: str) -> None:
    _put(ppr, _shd(fill), _PPR)


def _strip_theme_fonts(rpr) -> None:
    from docx.oxml.ns import qn

    fonts = rpr.find(qn("w:rFonts"))
    if fonts is not None:
        for k in list(fonts.attrib):
            if "theme" in k.lower():
                del fonts.attrib[k]


def _style_numbering(doc) -> None:
    """Bullet glyphs in blue (dashes in grey below), numbers in bold navy, indents of the design system."""
    from docx.oxml.ns import qn

    try:
        numbering = doc.part.numbering_part.element
        abstract = {a.get(qn("w:abstractNumId")): a for a in numbering.findall(qn("w:abstractNum"))}
        nums = {n.get(qn("w:numId")): n for n in numbering.findall(qn("w:num"))}
        for name in ("List Bullet", "List Number"):
            for level in range(3):
                style = doc.styles[name + (f" {level + 1}" if level else "")]
                num_id = style.element.pPr.find(qn("w:numPr")).find(qn("w:numId")).get(qn("w:val"))
                a = abstract[nums[num_id].find(qn("w:abstractNumId")).get(qn("w:val"))]
                lvl = a.find(qn("w:lvl"))
                left = int((0.63 + 0.635 * level) * 567)
                ppr = lvl.find(qn("w:pPr"))
                for tag in ("w:tabs", "w:ind"):
                    for el in ppr.findall(qn(tag)):
                        ppr.remove(el)
                tabs, tab, ind = _w("w:tabs"), _w("w:tab"), _w("w:ind")
                _set(tab, val="num", pos=left)
                tabs.append(tab)
                _set(ind, left=left, hanging=284)
                ppr.append(tabs)
                ppr.append(ind)
                rpr = lvl.find(qn("w:rPr"))
                if rpr is None:
                    rpr = _w("w:rPr")
                    lvl.append(rpr)
                for el in list(rpr):
                    rpr.remove(el)
                if name == "List Bullet":
                    lvl.find(qn("w:lvlText")).set(qn("w:val"), "•" if level == 0 else "–")
                    fonts = _w("w:rFonts")
                    _set(fonts, ascii="Arial", hAnsi="Arial", cs="Arial", hint="default")
                    rpr.append(fonts)
                    color = _w("w:color")
                    _set(color, val=BLUE if level == 0 else MUTED)
                    rpr.append(color)
                else:
                    fonts = _w("w:rFonts")
                    _set(fonts, ascii=FONT, hAnsi=FONT, cs=FONT)
                    rpr.append(fonts)
                    rpr.append(_w("w:b"))
                    color = _w("w:color")
                    _set(color, val=NAVY)
                    rpr.append(color)
    except (AttributeError, KeyError, TypeError, ValueError):
        return  # an unexpected template: keep Word's default glyphs, never fail the document


def _docx_styles(doc) -> None:
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.4)
    sec.top_margin, sec.bottom_margin = Cm(2.6), Cm(2.4)
    sec.header_distance = sec.footer_distance = Cm(1.2)
    defaults = doc.styles.element.find(qn("w:docDefaults"))
    if defaults is not None:
        for fonts in defaults.iter(qn("w:rFonts")):
            for k in list(fonts.attrib):
                del fonts.attrib[k]
            _set(fonts, ascii=FONT, hAnsi=FONT, eastAsia=FONT, cs=FONT)
    cp = doc.core_properties
    cp.author = cp.last_modified_by = cp.comments = ""

    def style(name, size, color, bold=False, before=0, after=6, line=1.2, keep=False):
        st = doc.styles[name]
        st.font.name, st.font.size, st.font.bold, st.font.italic = FONT, Pt(size), bold, False
        st.font.color.rgb = RGBColor.from_string(color)
        rpr = st.element.get_or_add_rPr()
        _strip_theme_fonts(rpr)
        for tag in ("w:spacing", "w:iCs", "w:bCs"):
            for el in rpr.findall(qn(tag)):
                rpr.remove(el)
        pf = st.paragraph_format
        pf.space_before, pf.space_after, pf.line_spacing = Pt(before), Pt(after), line
        pf.widow_control = True
        if keep:
            pf.keep_with_next = True
        ppr = st.element.get_or_add_pPr()
        for tag in ("w:pBdr", "w:contextualSpacing"):
            for el in ppr.findall(qn(tag)):
                ppr.remove(el)
        return st

    style("Normal", 10.5, INK)
    title = style("Title", 26, NAVY, bold=True, after=4, line=1.0, keep=True)
    sub = style("Subtitle", 11, MUTED, after=28)
    for el in sub.element.pPr.findall(qn("w:numPr")):
        sub.element.pPr.remove(el)
    bar = (36, BLUE, 10)  # 4.5 pt bar in the left margin, shared by title and subtitle (Word merges them)
    _p_border(title.element.pPr, left=bar)
    _p_border(sub.element.pPr, left=bar)
    # sections are set apart by space and colour, not by a rule: a rule above an H1 that opens a page would sit
    # right under the running-header hairline (two stacked grey lines)
    style("Heading 1", 15, NAVY, bold=True, before=26, after=8, line=1.0, keep=True)
    style("Heading 2", 12, BLUE, bold=True, before=16, after=4, line=1.0, keep=True)
    style("Heading 3", 10.5, INK, bold=True, before=12, after=2, line=1.0, keep=True)
    for name in ("List Bullet", "List Number"):
        for level in range(3):
            st = style(name + (f" {level + 1}" if level else ""), 10.5, INK, after=3)
            st.paragraph_format.left_indent = Cm(0.63 + 0.635 * level)
            st.paragraph_format.first_line_indent = Cm(-0.5)
    quote = style("Quote", 10.5, INK, before=6, after=10)
    quote.paragraph_format.left_indent = Cm(0.5)
    quote.paragraph_format.right_indent = Cm(0)  # every tinted block ends on the text column, like tables
    _p_border(quote.element.pPr, left=(24, BLUE, 8), **_pad(_TINT))
    _p_shade(quote.element.pPr, _TINT)
    for name, size, color, bold in (
        ("Bird Table", 9.5, INK, False),
        ("Bird Table Header", 9.5, "FFFFFF", True),
        ("Bird Table Small", 7.5, INK, False),  # tables of more than 8 columns
        ("Bird Table Header Small", 7.5, "FFFFFF", True),
    ):
        if name not in [s.name for s in doc.styles]:
            doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH).base_style = doc.styles["Normal"]
        style(name, size, color, bold=bold, after=0, line=1.0)
    _style_numbering(doc)


def _field(par, instr: str, cached: str = "1") -> None:
    fld = _w("w:fldSimple")
    _set(fld, instr=instr)
    r, t = _w("w:r"), _w("w:t")
    t.text = cached
    r.append(t)
    fld.append(r)
    par._p.append(fld)


def _furniture(doc, title: str) -> None:
    """Running header (pages 2+) with the title over a hairline; footer 'n / total' on every page."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    sec = doc.sections[0]
    sec.different_first_page_header_footer = True
    sec.first_page_header.is_linked_to_previous = False
    head = sec.header.paragraphs[0]
    r = head.add_run(_cut(title, 80))
    r.font.size, r.font.color.rgb = Pt(8.5), RGBColor.from_string(MUTED)
    _p_border(head._p.get_or_add_pPr(), bottom=(4, _HAIR, 4))
    for footer in (sec.footer, sec.first_page_footer):
        par = footer.paragraphs[0]
        par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _field(par, "PAGE")
        par.add_run(" / ")
        _field(par, "NUMPAGES")
        for el in par._p.iter():
            if el.tag.endswith("}r"):
                rp = _w("w:rPr")
                sz, color = _w("w:sz"), _w("w:color")
                _set(sz, val=17)
                _set(color, val=MUTED)
                rp.append(color)
                rp.append(sz)
                for old in el.findall(rp.tag):
                    el.remove(old)
                el.insert(0, rp)


def _add_runs(par, text: str, code_size: float = 9.5) -> None:
    from docx.shared import Pt

    for style, chunk in inline_runs(text):
        r = par.add_run(chunk)
        if style == "b":
            r.bold = True
        elif style == "code":
            r.font.name, r.font.size = "Consolas", Pt(code_size)
            r._r.get_or_add_rPr().append(_shd(_TINT))


def _shade(cell, fill: str) -> None:
    _put(cell._tc.get_or_add_tcPr(), _shd(fill), _TCPR)


def _numeric(value: str) -> bool:
    v = plain(value).strip()
    return bool(v) and bool(re.search(r"\d", v)) and bool(_NUM_CELL.fullmatch(v))


def _col_widths(rows: list[list[str]], width: int, numeric: list[bool], text_tw: int = _TEXT_TW, pt: float = 9.5,
                pad: int = 220) -> list[int]:
    """Column widths in twips, proportional to the longest text of each column (bounded), and never narrower than
    the longest word of the column (or the whole figure of a numeric column): no word is cut in the middle."""
    def cell(r, j):
        return plain(r[j]) if j < len(r) else ""

    need = [max(4, min(40, max(len(cell(r, j)) for r in rows))) for j in range(width)]
    char = pt * 0.52 * 20  # twips per character of Calibri (average, bold headers included)
    words = []
    for j in range(width):
        longest = max((len(w) for r in rows for w in (cell(r, j).split() if not numeric[j] else [cell(r, j)])), default=1)
        words.append(min(longest, 16) * char + pad)
    floors = [w / text_tw for w in words]
    if sum(floors) > 1:  # too many columns for the page even at one word: scale the floors down evenly
        floors = [f / sum(floors) for f in floors]
    share = [n / sum(need) for n in need]
    for _ in range(4):  # clamp then give the rest back to the free columns, a few rounds are enough
        fixed = [max(floors[j], min(s, 0.22)) if numeric[j] else max(floors[j], s) for j, s in enumerate(share)]
        free = [j for j in range(width) if fixed[j] == share[j] and not numeric[j]] or list(range(width))
        excess = sum(fixed) - 1
        total_free = sum(fixed[j] - floors[j] for j in free) or 1
        share = [f - (excess * (f - floors[j]) / total_free if j in free else 0) for j, f in enumerate(fixed)]
    return [int(text_tw * s) for s in share]


_WIDE_TABLE, _LANDSCAPE_TABLE = 8, 10  # columns: smaller type above the first, own landscape pages above the second
_LANDSCAPE_TW = 14117  # 29.7 cm - 2 x 2.4 cm


def _table(doc, rows: list[list[str]]) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    rows = rows[:200]
    width = max(len(r) for r in rows)
    body = rows[1:]
    numeric = []
    for j in range(width):
        cells = [r[j] for r in body if j < len(r) and plain(r[j]).strip() and not _TOTAL_CELL.match(plain(r[j]))]
        numeric.append(bool(cells) and sum(map(_numeric, cells)) >= 0.6 * len(cells))
    small, wide = width > _WIDE_TABLE, width > _LANDSCAPE_TABLE
    if wide:  # its own landscape pages; the headings just above it go along so they stay with it
        tail = []
        for el in reversed([el for el in doc.element.body if el.tag != qn("w:sectPr")]):
            style = el.find(qn("w:pPr") + "/" + qn("w:pStyle")) if el.tag == qn("w:p") else None
            if style is None or not style.get(qn("w:val"), "").startswith("Heading"):
                break
            tail.insert(0, el)
        for el in tail:
            el.getparent().remove(el)
        _orient(doc, landscape=True)
        final = doc.element.body.find(qn("w:sectPr"))
        for el in tail:
            final.addprevious(el)
    pad = 60 if small else 110
    widths = _col_widths(
        rows, width, numeric, _LANDSCAPE_TW if wide else _TEXT_TW, 7.5 if small else 9.5, 2 * pad + 20
    )
    sid = {
        name: doc.styles[name + (" Small" if small else "")].style_id for name in ("Bird Table", "Bird Table Header")
    }
    table = doc.add_table(rows=0, cols=width)
    table.style = doc.styles["Normal Table"]
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    order = "tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing "
    order += "tblInd tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription"
    order = order.split()
    tbl_w = _w("w:tblW")
    _set(tbl_w, type="pct", w=5000)
    _put(tbl_pr, tbl_w, order)
    rules = {"top": None, "left": None, "right": None, "insideV": None, "bottom": (8, NAVY, 0), "insideH": (4, _HAIR, 0)}
    _put(tbl_pr, _border("w:tblBorders", rules), order)
    ind = _w("w:tblInd")  # cell edges, not cell text, on the margin (the padding goes inside)
    _set(ind, w=pad, type="dxa")
    _put(tbl_pr, ind, order)
    layout = _w("w:tblLayout")
    _set(layout, type="fixed")
    _put(tbl_pr, layout, order)
    mar = _w("w:tblCellMar")
    for side, v in (("top", 50 if small else 70), ("left", pad), ("bottom", 50 if small else 70), ("right", pad)):
        el = _w(f"w:{side}")
        _set(el, w=v, type="dxa")
        mar.append(el)
    _put(tbl_pr, mar, order)
    for col, w in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths, strict=False):
        col.set(qn("w:w"), str(w))
    first_total = True
    for i, row in enumerate(rows):
        r = table.add_row()
        tr_pr = r._tr.get_or_add_trPr()
        tr_pr.append(_w("w:cantSplit"))
        if i == 0:
            tr_pr.append(_w("w:tblHeader"))
        total = i > 0 and bool(row) and bool(_TOTAL_CELL.match(plain(row[0]).strip()))
        for j, cell in enumerate(r.cells):
            value = row[j] if j < len(row) else ""
            tc_pr = cell._tc.get_or_add_tcPr()  # tcW already comes from the grid (add_row)
            if j and numeric[j - 1] and not numeric[j]:  # air between right-aligned figures and the next text
                mar, left = _w("w:tcMar"), _w("w:left")
                _set(left, w=3 * pad, type="dxa")
                mar.append(left)
                _put(tc_pr, mar, _TCPR)
            figure = (numeric[j] or (i and _numeric(value))) and not (total and j == 0)
            if figure and i:
                _put(tc_pr, _w("w:noWrap"), _TCPR)  # '1 250,50 €' never breaks over two lines
            v_align = _w("w:vAlign")
            _set(v_align, val="center")
            _put(tc_pr, v_align, _TCPR)
            par = cell.paragraphs[0]
            par._p.style = sid["Bird Table Header" if i == 0 else "Bird Table"]  # the id: no style lookup per cell
            _add_runs(par, value, code_size=7 if small else 8.5)
            if figure:
                par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            if i == 0:
                _shade(cell, NAVY)
            elif total:
                _shade(cell, SOFT)
                for run in par.runs:
                    run.bold = True
                if first_total:
                    _put(tc_pr, _border("w:tcBorders", {"top": (6, NAVY, 0)}), _TCPR)
            elif i % 2 == 0:
                _shade(cell, _TINT)
        first_total = first_total and not total
    _spacer(doc)
    if wide:
        _orient(doc, landscape=False)


def _spacer(doc) -> None:
    """A small unshaded paragraph: white space after a table or a shaded block that no shading can swallow."""
    from docx.shared import Pt

    spacer = doc.add_paragraph()
    pf = spacer.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(8), 1.0
    mark, sz = _w("w:rPr"), _w("w:sz")
    _set(sz, val=8)
    mark.append(sz)
    _put(spacer._p.get_or_add_pPr(), mark, _PPR)


def _orient(doc, landscape: bool) -> None:
    """Start a new section (new page) in landscape or back in portrait; header and footer follow."""
    from docx.enum.section import WD_ORIENT, WD_SECTION
    from docx.shared import Cm

    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    sec.different_first_page_header_footer = False
    sec.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = (Cm(29.7), Cm(21)) if landscape else (Cm(21), Cm(29.7))


def _finish(doc) -> None:
    """A document that ends on a landscape table ends there: no empty portrait section (blank last page)."""
    from docx.oxml.ns import qn

    body = doc.element.body
    last = [el for el in body if el.tag != qn("w:sectPr")]
    if not last or last[-1].tag != qn("w:p"):
        return
    ppr = last[-1].find(qn("w:pPr"))
    inner = ppr.find(qn("w:sectPr")) if ppr is not None else None
    if inner is None or "".join(last[-1].itertext()).strip():
        return
    final = body.find(qn("w:sectPr"))
    for tag in ("w:pgSz", "w:pgMar"):
        new, old = inner.find(qn(tag)), final.find(qn(tag))
        if new is not None and old is not None:
            old.getparent().replace(old, new)
    body.remove(last[-1])


def _callout(doc, text: str, kind: str):
    """A decision (green) or an action (blue) as a tinted paragraph with a bar; the label before ':' in bold navy."""
    from docx.shared import Cm, Pt, RGBColor

    par = doc.add_paragraph()
    pf = par.paragraph_format
    pf.left_indent, pf.space_after = Cm(0.5), Pt(4)
    ppr = par._p.get_or_add_pPr()
    fill = _GREEN_T if kind == "decision" else _TINT
    _p_border(ppr, left=(24, _GREEN if kind == "decision" else BLUE, 8), **_pad(fill))
    _p_shade(ppr, fill)
    m = re.match(r"^\s*(?:\*\*|__)?([^:*_\n]{1,40}?)\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*", text)
    if m and (_DECISION.match(text) or _ACTION.match(text)):
        r = par.add_run(m.group(1).strip() + " : ")
        r.bold, r.font.color.rgb = True, RGBColor.from_string(NAVY)
        rest = text[m.end() :]
        if rest.count("**") % 2:
            rest = rest.replace("**", "", 1)
        _add_runs(par, rest)
    else:
        _add_runs(par, text)
    return par


def _new_list(doc, style_name: str) -> str | None:
    """A fresh numbering instance (restarts at 1) for a numbered list; None keeps the style's own numbering."""
    from docx.oxml.ns import qn

    try:
        numbering = doc.part.numbering_part.element
        num_id = doc.styles[style_name].element.pPr.find(qn("w:numPr")).find(qn("w:numId")).get(qn("w:val"))
        base = next(n for n in numbering.findall(qn("w:num")) if n.get(qn("w:numId")) == num_id)
        num = numbering.add_num(int(base.find(qn("w:abstractNumId")).get(qn("w:val"))))
        num.add_lvlOverride(ilvl=0).add_startOverride(1)
        return str(num.numId)
    except (AttributeError, KeyError, StopIteration, TypeError, ValueError):
        return None


def _blocks_to_docx(doc, blocks: list[Block], base_level: int = 1, context: str = "") -> None:
    """base_level is the Word level of the shallowest Markdown heading of the blocks ('##' and '###' of a section
    become Heading 2 and 3, '#' and '##' of an answer Heading 1 and 2). context: the heading above (callouts)."""
    from docx.shared import Cm, Pt

    top = min((b.level for b in blocks if b.kind == "heading"), default=1)
    mode = "decision" if _DECISION_HEAD.search(context) else "action" if _ACTION_HEAD.search(context) else ""
    flat = not any(b.kind in ("bullet", "number") and b.level for b in blocks)  # nested lists stay lists
    lists: dict[int, str | None] = {}
    last_item = None
    for b in blocks:
        is_item = b.kind in ("bullet", "number")
        if not is_item:
            if last_item is not None:
                last_item.paragraph_format.space_after = Pt(8)
            last_item, lists = None, {}
        if b.kind == "heading":
            doc.add_heading(plain(b.text), level=min(3, base_level + max(0, b.level - top)))
            if _DECISION_HEAD.search(b.text):
                mode = "decision"
            elif _ACTION_HEAD.search(b.text):
                mode = "action"
        elif is_item:
            text = plain(b.text)
            kind = "decision" if _DECISION.match(text) else "action" if _ACTION.match(text) else ""
            if b.kind == "bullet" and (kind or (mode and flat)):
                last_item = _callout(doc, b.text, kind or mode)
                continue
            style = ("List Bullet" if b.kind == "bullet" else "List Number") + (f" {b.level + 1}" if b.level else "")
            lists = {k: v for k, v in lists.items() if k <= b.level}
            par = doc.add_paragraph(style=style)
            if b.kind == "number":
                if b.level not in lists:
                    lists[b.level] = _new_list(doc, style)
                if lists[b.level]:
                    num_pr = _w("w:numPr")
                    ilvl, num_id = _w("w:ilvl"), _w("w:numId")
                    _set(ilvl, val=0)
                    _set(num_id, val=lists[b.level])
                    num_pr.append(ilvl)
                    num_pr.append(num_id)
                    _put(par._p.get_or_add_pPr(), num_pr, _PPR)
            else:
                lists.pop(b.level, None)
            _add_runs(par, b.text)
            last_item = par
        elif b.kind == "table":
            _table(doc, b.rows)
        elif b.kind == "quote":
            _add_runs(doc.add_paragraph(style="Quote"), b.text)
        elif b.kind == "code":
            par = doc.add_paragraph()
            pf = par.paragraph_format
            pf.space_before, pf.space_after, pf.line_spacing, pf.left_indent = Pt(4), Pt(0), 1.0, Cm(0.5)
            pf.right_indent = Cm(0)
            # a neutral grey, not the quote tint, and real white space after it (shading covers space_after)
            _p_border(par._p.get_or_add_pPr(), left=(24, _CODE, 8), **_pad(_CODE))
            _p_shade(par._p.get_or_add_pPr(), _CODE)
            r = par.add_run(b.text)
            r.font.name, r.font.size = "Consolas", Pt(9)
            _spacer(doc)
        elif b.kind == "para" and _RULE.fullmatch(b.text.strip()):
            par = doc.add_paragraph()
            par.paragraph_format.space_after = Pt(12)
            _p_border(par._p.get_or_add_pPr(), bottom=(4, _HAIR, 1))
        else:
            text = plain(b.text)
            kind = "decision" if _DECISION.match(text) else "action" if _ACTION.match(text) else ""
            if kind:
                last_item = _callout(doc, b.text, kind)
            else:
                _add_runs(doc.add_paragraph(), b.text)
    if last_item is not None:
        last_item.paragraph_format.space_after = Pt(8)


def _cover(doc, title: str, subtitle: str | None) -> None:
    from docx.shared import Pt

    par = doc.add_paragraph(title, style="Title")
    for run in par.runs:
        run.font.size = Pt(26 if len(title) <= 60 else 22)
    if subtitle is None:
        par.paragraph_format.space_after = Pt(24)
    else:
        doc.add_paragraph(subtitle, style="Subtitle")


def build_docx(path, title: str, sections: list[dict], subtitle: str = "") -> dict:
    """Write the document; return counts for the summary (sections, tables, list items)."""
    from docx import Document

    doc = Document()
    _docx_styles(doc)
    doc.core_properties.title = title[:200]
    _furniture(doc, title)
    _cover(doc, title, subtitle or dt.date.today().strftime("%d/%m/%Y"))
    stats = {"sections": len(sections), "tables": 0, "items": 0}
    for s in sections:
        heading = plain(str(s.get("heading") or ""))
        doc.add_heading(heading, level=1)
        blocks = parse_markdown(str(s.get("content") or ""))
        stats["tables"] += sum(b.kind == "table" for b in blocks)
        stats["items"] += sum(b.kind in ("bullet", "number") for b in blocks)
        _blocks_to_docx(doc, blocks, base_level=2, context=heading)
    _finish(doc)
    doc.save(str(path))
    return stats


def docx_from_markdown(path, title: str, markdown: str) -> None:
    """Export of an answer: '# x' headings become document headings, lists and tables are kept."""
    from docx import Document

    doc = Document()
    _docx_styles(doc)
    blocks = parse_markdown(markdown)
    if blocks and blocks[0].kind == "heading" and blocks[0].level == 1:
        title = plain(blocks.pop(0).text)
    doc.core_properties.title = title[:200]
    _furniture(doc, title)
    _cover(doc, title, None)
    _blocks_to_docx(doc, blocks, base_level=1)
    _finish(doc)
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


# identifiers that look like numbers: never grouped ('75 001', '2 026'), codes and phones kept as written
_CODE_HEAD = re.compile(
    r"\b(?:code|cp|postal|zip|t[ée]l[ée]?\w*|phone|mobile|portable|siren|siret|tva intra|iban|r[ée]f\w*)(?!\w)",
    re.I,
)
_ID_HEAD = re.compile(r"\b(?:ann[ée]es?|years?|exercice|id|identifiant|n°|no\.?|num[ée]ro)(?!\w)", re.I)


def typed_cell(value, header: str = ""):
    """(value, number_format or None) for one cell written by the model, under the column `header`."""
    if isinstance(value, bool) or value is None:
        return value, None
    head = str(header or "")
    if isinstance(value, int) and _CODE_HEAD.search(head):
        return str(value), None
    if isinstance(value, int) and _ID_HEAD.search(head):
        return value, "0"
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
            cents = bool(re.search(r"[.,]\d{1,2}$", num.strip())) or (isinstance(n, float) and not n.is_integer())
            return n, f'#,##0.00 "{sym}"' if cents else f'#,##0 "{sym}"'
    if re.fullmatch(r"\+\d[\d .]*\d", s) and " " in s:
        return s, None  # an international phone number ('+33 6 12 34 56 78'), not a sum
    if re.fullmatch(r"[\d\s\xa0.]+", s) and _CODE_HEAD.search(head):
        return s, None
    if m := _DATE.match(s):
        try:
            y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(6), m.group(5), m.group(4))
            return dt.date(int(y), int(mo), int(d)), "dd/mm/yyyy"
        except ValueError:
            pass
    n = _to_number(s)
    if n is not None and isinstance(n, int) and _ID_HEAD.search(head):
        return n, "0"
    if n is not None:
        return n, "#,##0" if isinstance(n, int) else "#,##0.00"
    return s, None


# right inset of figures, as two digit-wide spaces in the number format: an alignment indent would do the same in
# Excel, but LibreOffice drops it on regular-weight figures and keeps it on bold totals, so columns went ragged
_NUM_PAD = "_0_0"
_TOTAL_ROW = re.compile(
    r"^(?:sous-?total|total|totaux|grand total|tva|vat|ttc|ht|net [àa] payer|montant total|reste [àa] payer)\b", re.I
)
_PCT_HEAD = re.compile(r"%|part|taux|marge|remise|share|rate|ratio", re.I)
_REF = re.compile(r"(?<![A-Za-z_\d])\$?([A-Z]{1,3})\$?(\d{1,7})(?![\d(])")


def _shown(value, fmt: str | None) -> int:
    """Approximate number of characters a cell shows once formatted (for column widths)."""
    if value is None:
        return 0
    if isinstance(value, dt.date):
        return 10
    if isinstance(value, int | float) and not isinstance(value, bool):
        fmt = fmt or ""
        if "%" in fmt:
            return len(f"{value * 100:.1f}") + 2
        text = f"{value:,.2f}" if ".00" in fmt else f"{value:,.0f}"
        return len(text) + (2 if '"' in fmt else 0)
    return len(str(value))


def _formula_format(formula: str, header: str, col: int, typed: list[list], fmts: dict) -> str:
    """Number format of a formula cell: a ratio column, else its column, else the cells it refers to."""
    from openpyxl.utils import column_index_from_string

    if _PCT_HEAD.search(header) and "/" in formula:
        return "0.0 %"
    seen = [f for r in typed if col < len(r) and (f := r[col][1]) and f != "@" and not str(r[col][0]).startswith("=")]
    if seen:
        return max(set(seen), key=seen.count)
    refs = []
    for letters, row in _REF.findall(formula.upper()):
        refs.append(fmts.get((int(row), column_index_from_string(letters))))
    refs = [f for f in refs if f]
    return next((f for f in refs if '"' in f), refs[0] if refs else "#,##0.00")


def build_xlsx(path, title: str, columns: list, rows: list[list]) -> dict:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.properties import PageSetupProperties

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", " ", title)[:31].strip() or "Feuille"
    wb.properties.title = title[:200]
    wb.properties.creator = ""
    columns = [str(c) for c in columns]
    typed = [[typed_cell(raw, columns[c] if c < len(columns) else "") for c, raw in enumerate(row)] for row in rows]
    width = max([len(columns)] + [len(r) for r in typed])
    # formats of every typed cell, then of the formulas (a few passes so formulas over formulas resolve)
    fmts: dict = {}
    for r, row in enumerate(typed, start=2):
        for c, (_value, fmt) in enumerate(row, start=1):
            if fmt and fmt != "@":
                fmts[(r, c)] = fmt
    for _ in range(3):
        for r, row in enumerate(typed, start=2):
            for c, (value, fmt) in enumerate(row, start=1):
                if fmt is None and isinstance(value, str) and value.startswith("="):
                    head = columns[c - 1] if c <= len(columns) else ""
                    fmts[(r, c)] = _formula_format(value, head, c - 1, typed, fmts)
    totals = [
        i
        for i, row in enumerate(typed)
        if (first := next((v for v, _ in row if v not in (None, "")), None)) is not None
        and isinstance(first, str)
        and _TOTAL_ROW.match(first.strip())
        and not first.startswith("=")
    ]
    # column kinds over the data rows: numeric (numbers and formulas), date, or text
    kinds = []
    for c in range(width):
        vals = [row[c][0] for i, row in enumerate(typed) if c < len(row) and row[c][0] not in (None, "")]
        vals = [v for v in vals if not (isinstance(v, str) and _TOTAL_ROW.match(v))]
        num = sum(
            (isinstance(v, int | float) and not isinstance(v, bool)) or (isinstance(v, str) and v.startswith("="))
            for v in vals
        )
        date = sum(isinstance(v, dt.date) for v in vals)
        kinds.append("date" if vals and date >= 0.6 * len(vals) else "num" if vals and num >= 0.6 * len(vals) else "text")

    thin, hair = Side(style="thin", color=NAVY), Side(style="thin", color=_HAIR)
    # family=2 (swiss): without it LibreOffice measures regular figures with another font and drops their right
    # indent, so body values touch the cell edge while bold totals keep their inset
    font = Font(name=FONT, family=2, size=10, color=INK)
    bold = Font(name=FONT, family=2, size=10, color=INK, bold=True)
    grand_font = Font(name=FONT, family=2, size=10, color=NAVY, bold=True)
    head_font = Font(name=FONT, family=2, size=10, color="FFFFFF", bold=True)
    head_fill, zebra, grand_fill = (PatternFill("solid", fgColor=x) for x in (NAVY, _TINT, SOFT))
    row_border = Border(bottom=hair)
    first_total_border = Border(top=thin, bottom=hair)
    grand_border = Border(top=Side(style="medium", color=NAVY), bottom=thin)
    align = {
        "num": Alignment(horizontal="right", vertical="center"),  # the right inset is in the format (_NUM_PAD)
        "date": Alignment(horizontal="center", vertical="center"),
        "text": Alignment(horizontal="left", vertical="center", indent=1),
        "text2": Alignment(horizontal="left", vertical="center", indent=2),
        "wrap": Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True),
    }
    head_align = {
        k: Alignment(horizontal=a.horizontal, vertical="center", indent=a.indent, wrap_text=True)
        for k, a in align.items()
    }

    widths = [len(c) for c in columns] + [0] * (width - len(columns))
    for r, row in enumerate(typed, start=2):
        for c, (value, fmt) in enumerate(row):
            shown = _shown(value, fmt)
            if isinstance(value, str) and value.startswith("=") and fmt != "@":
                shown = 8 if "%" in (fmts.get((r, c + 1)) or "") else 12
            widths[c] = max(widths[c], min(shown, 60))
    first_text = next((c for c in range(width) if kinds[c] == "text"), None)
    # + indent and padding: the right inset of figures survives LibreOffice, which drops the indent of a tight cell
    widths = [max(10, min(w + 5, 50)) for w in widths]
    if first_text is not None:
        widths[first_text] = max(widths[first_text], 16)

    ws.append(columns)
    for c in range(len(columns)):
        cell = ws.cell(row=1, column=c + 1)
        after_num = kinds[c] == "text" and c and kinds[c - 1] == "num"
        cell.font, cell.fill, cell.alignment = head_font, head_fill, head_align["text2" if after_num else kinds[c]]
        if kinds[c] == "num":
            cell.number_format = "@" + _NUM_PAD  # the header ends where the figures under it end
    ws.row_dimensions[1].height = 28
    formulas = blocked = 0
    grand = totals[-1] if totals else None
    for i, row in enumerate(typed):
        r = i + 2
        is_total = i in totals
        lines = 1
        for c in range(1, width + 1):
            value, fmt = row[c - 1] if c <= len(row) else (None, None)
            cell = ws.cell(row=r, column=c)
            if fmt == "@":  # an unsafe formula: written as text, never evaluated
                cell.value = value
                cell.data_type = "s"
                blocked += 1
            elif value is not None:
                cell.value = value
                if isinstance(value, str) and value.startswith("="):
                    formulas += 1
                    fmt = fmts.get((r, c))
                elif isinstance(value, str) and value[:1] in "+-@" and len(value) > 1:
                    cell.data_type = "s"  # CSV-style injection markers stay text
                if fmt:
                    cell.number_format = fmt
            kind = kinds[c - 1]
            if isinstance(value, int | float) and not isinstance(value, bool) or (
                isinstance(value, str) and value.startswith("=") and fmt != "@"
            ):
                kind = "num" if kind != "date" else kind
            elif isinstance(value, str) and kind == "num":
                kind = "text"
            per_line = max(1, int((widths[c - 1] - 2) * 1.25))  # Calibri 10 fits ~1.25 characters per unit
            if kind == "text" and isinstance(value, str) and len(value) > per_line:
                kind = "wrap"
                lines = max(lines, -(-len(value) // per_line))
            if kind == "text" and c > 1 and kinds[c - 2] == "num":
                kind = "text2"  # air between right-aligned figures and the text that follows
            cell.alignment = align[kind]
            if kind == "num" and fmt and fmt != "@":
                cell.number_format = fmt + _NUM_PAD
            if i == grand:
                cell.font, cell.fill, cell.border = grand_font, grand_fill, grand_border
            elif is_total:
                cell.font = bold
                cell.border = first_total_border if (i - 1) not in totals else row_border
            else:
                cell.font, cell.border = font, row_border
                if i % 2 == 1:
                    cell.fill = zebra
        ws.row_dimensions[r].height = 22 if i == grand else max(20, 14 * lines + 6)

    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"
    data_rows = totals[0] if totals else len(typed)
    if data_rows >= 2:
        ws.auto_filter.ref = f"A1:{get_column_letter(max(1, len(columns)))}{data_rows + 1}"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = NAVY
    # print: A4, one page wide, header row repeated, title and page numbers in the margins
    ws.page_setup.paperSize = 9
    ws.page_setup.orientation = "landscape" if sum(widths) > 120 else "portrait"
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.print_title_rows = "1:1"
    ws.print_options.gridLines = False
    m = ws.page_margins
    m.left = m.right = 0.5
    m.top, m.bottom, m.header, m.footer = 0.75, 0.6, 0.3, 0.3
    ws.oddHeader.left.text = _cut(title, 80).replace("&", "&&")
    ws.oddHeader.left.font, ws.oddHeader.left.size, ws.oddHeader.left.color = f"{FONT},Bold", 10, NAVY
    for part, text in ((ws.oddFooter.left, dt.date.today().strftime("%d/%m/%Y")), (ws.oddFooter.right, "&P / &N")):
        part.text, part.font, part.size, part.color = text, FONT, 9, MUTED
    wb.save(str(path))
    return {"formulas": formulas, "blocked_formulas": blocked}
