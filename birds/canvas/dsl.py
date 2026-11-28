"""The canvas content format: a tiny, forgiving, Markdown-like text the small model writes, and the document model
the harness keeps (one JSON shape for decks, documents, code and sheets).

The model writes content only, never a layout::

    ---
    title: Plan mobilité 2027
    subtitle: Comité de direction
    theme: moderne
    ---
    # Contexte
    - 40 % des trajets font moins de 5 km
    ::: image query="vélo en ville"
    :::
    # Chiffres clés
    ::: kpi
    1,2 M€ | Budget | +8 %
    31 % | Part modale visée
    :::

``parse`` NEVER fails: garbage in gives a valid document (possibly empty), and every repair it made is listed. A
small model forgets to close a block, numbers its headings (« Diapositive 3 : »), puts the deck title in a first
``#`` heading and the slides in ``##``, writes « Titre : … » instead of front matter, uses ``---`` between slides
(Marp), or a Markdown image ``![vélo](…)``: all of these are read as meant. A picture is a SEARCH QUERY, never a
URL the model chose (a URL is not fetched; its alt text becomes the query).

Document model (``v`` 1)::

    {"v": 1, "kind": "deck"|"doc"|"code"|"sheet", "title", "subtitle", "theme", "lang",
     "blocks": [{"id": "b1", "title": str, "parts": [part, ...], "notes": str}],   # deck, doc
     "code": {"lang", "text", "entry", "files": [{"name", "lang", "text"}]},       # code (see code.py)
     "sheet": {"columns": [str], "rows": [[str]]},                                # sheet
     "media": {"<id>": {"kind": "web"|"user"|"gen", "alt", "credit", "licence", "source", "w", "h"}}}

Parts: text, list, kpi, image, chart, table, timeline, quote, code, callout, heading (see ``PART_TYPES``).
"""

from __future__ import annotations

import copy
import re

KINDS = ("deck", "doc", "code", "sheet")
THEMES = ("corporate", "modern", "warm", "forest", "night")
DECK_THEMES = ("corporate", "forest", "warm", "night")  # the four branded deck themes (Bird blue, forest, terracotta, night)
THEME_ALIASES = {
    "corporate": "corporate", "sobre": "corporate", "classique": "corporate", "classic": "corporate",
    "institutionnel": "corporate", "bleu": "corporate", "blue": "corporate", "pro": "corporate", "bird": "corporate",
    "modern": "modern", "moderne": "modern", "tech": "modern", "startup": "modern",
    "warm": "warm", "chaleureux": "warm", "chaud": "warm", "chaleureuse": "warm", "orange": "warm",
    "terracotta": "warm", "terre": "warm", "terrecuite": "warm",
    "forest": "forest", "foret": "forest", "forêt": "forest", "vert": "forest", "green": "forest", "nature": "forest",
    "night": "night", "nuit": "night", "sombre": "night", "dark": "night", "noir": "night",
}  # fmt: skip
PART_TYPES = ("text", "list", "kpi", "image", "chart", "table", "timeline", "quote", "code", "callout", "heading",
              "compare", "steps", "cards")  # fmt: skip
CHART_TYPES = ("bar", "line", "pie")
# the slide layouts a block may ask for (birds/canvas/layouts.py picks and validates them; the cover is the deck's own)
LAYOUT_NAMES = ("section", "agenda", "statement", "bullets", "columns", "figure", "kpis", "versus", "compare",
                "timeline", "steps", "quote", "image-left", "image-right", "image-full", "image-grid", "chart",
                "table", "cards", "closing", "code")  # fmt: skip
LAYOUT_ALIASES = {
    "section": "section", "intercalaire": "section", "divider": "section", "chapitre": "section",
    "agenda": "agenda", "sommaire": "agenda", "programme": "agenda", "plan": "agenda",
    "statement": "statement", "message": "statement", "phrase": "statement", "idee": "statement",
    "bullets": "bullets", "liste": "bullets", "list": "bullets", "points": "bullets",
    "columns": "columns", "deux-colonnes": "columns", "two-columns": "columns",
    "figure": "figure", "chiffre": "figure", "chiffre-cle": "figure", "big-number": "figure", "bignumber": "figure",
    "kpis": "kpis", "kpi": "kpis", "chiffres": "kpis", "indicateurs": "kpis",
    "versus": "versus", "vs": "versus", "avant-apres": "versus", "compare": "compare", "comparaison": "compare",
    "comparison": "compare", "timeline": "timeline", "frise": "timeline", "steps": "steps", "etapes": "steps",
    "processus": "steps", "process": "steps", "quote": "quote", "citation": "quote",
    "image-left": "image-left", "image-gauche": "image-left", "image-right": "image-right",
    "image-droite": "image-right", "image": "image-full", "image-full": "image-full", "plein-cadre": "image-full",
    "photo": "image-full", "image-grid": "image-grid", "grille": "image-grid", "galerie": "image-grid",
    "gallery": "image-grid", "chart": "chart", "graphique": "chart", "table": "table", "tableau": "table",
    "cards": "cards", "cartes": "cards", "equipe": "cards", "team": "cards", "closing": "closing",
    "conclusion": "closing", "fin": "closing", "cta": "closing", "merci": "closing", "code": "code",
}  # fmt: skip
_LAYOUT_TAG = re.compile(r"\s*\{\s*(?:\.|layout\s*[=:]\s*|mise en page\s*[=:]\s*)?([\w\- éèà]{2,30})\s*\}\s*$", re.I)
_LAYOUT_LINE = re.compile(r"^\s*(?:layout|mise en page|disposition)\s*[:=]\s*([\w\- éèà]{2,30})\s*$", re.I)


def layout_of(word: object) -> str | None:
    """A layout name the model wrote (« image-droite », « Chiffre clé ») -> its id, or None."""
    w = re.sub(r"[\s_]+", "-", str(word or "").strip().lower())
    w = w.translate(str.maketrans("éèêàâîôûç", "eeeaaiouc"))
    return LAYOUT_ALIASES.get(w)


TONES = ("info", "warn", "ok", "key")  # key: « à retenir »
CODE_LANGS = ("html", "svg", "css", "js", "python", "mermaid", "markdown", "json", "text", "ts", "sql", "bash", "yaml")

MAX_BLOCKS = 40
MAX_PARTS = 14
MAX_ITEMS = 14
MAX_TEXT = 4000
MAX_TITLE = 200
MAX_CODE = 60_000
MAX_SHEET_ROWS, MAX_SHEET_COLS = 200, 26
MAX_ROWS = 40  # chart / table rows

_DIRECTIVE = re.compile(r"^\s*:{3,}\s*([A-Za-zÀ-ÿ][\w-]*)?\s*(.*?)\s*:*\s*$")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s*(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)(?:[-*+•▪◦·]|–)\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d{1,2})[.)]\s+(.*)$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)")
_SEP_ROW = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_ID_TAG = re.compile(r"^\s*\[\s*(b\d{1,3})\s*\]\s*")
_NUMBERED_HEAD = re.compile(
    r"^\s*(?:(?:slide|diapositive|diapo|section|partie|part|page|chapitre|chapter)\s*n?°?\s*\d{1,2}\s*[:.\-–—)]?\s*|"
    r"\d{1,2}\s*[.)\-–—:]\s+)",
    re.I,
)
_MD_IMAGE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)]*)\)\s*$")
_NOTES = re.compile(
    r"^\s*(?:\*\*)?(?:notes?(?: de l['’]orateur| du pr[ée]sentateur| orateur)?|speaker notes?|presenter notes?)"
    r"(?:\*\*)?\s*:\s*(.*)$",
    re.I,
)
_KV = re.compile(r"^\s*([A-Za-zÀ-ÿ][\wÀ-ÿ -]{0,20}?)\s*:\s*(.+?)\s*$")
_FRONT_KEYS = {
    "title": "title", "titre": "title", "subtitle": "subtitle", "sous-titre": "subtitle", "sous titre": "subtitle",
    "soustitre": "subtitle", "theme": "theme", "thème": "theme", "style": "theme", "kind": "kind", "type": "kind",
    "lang": "lang", "langue": "lang",
    "template": "template", "modèle": "template", "modele": "template", "gabarit": "template",
    "author": "author", "auteur": "author", "autrice": "author", "rédacteur": "author", "redacteur": "author",
    "to": "recipient", "destinataire": "recipient", "recipient": "recipient",
    "image": "image", "cover": "image", "couverture": "image",
    "photo": "image",
}  # fmt: skip
_ATTR = re.compile(r"""([A-Za-zÀ-ÿ_][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|«\s*([^»]*?)\s*»|(\S+))""")
_TYPE_ALIASES = {
    "kpi": "kpi", "kpis": "kpi", "stats": "kpi", "stat": "kpi", "chiffres": "kpi", "chiffres-cles": "kpi",
    "figures": "kpi", "metrics": "kpi", "indicateurs": "kpi",
    "image": "image", "img": "image", "photo": "image", "picture": "image", "illustration": "image",
    "figure": "image",
    "chart": "chart", "graph": "chart", "graphique": "chart", "graphe": "chart", "diagramme": "chart",
    "bar": "chart", "line": "chart", "pie": "chart", "courbe": "chart", "barres": "chart", "camembert": "chart",
    "table": "table", "tableau": "table", "grid": "table",
    "timeline": "timeline", "frise": "timeline", "calendrier": "timeline", "planning": "timeline",
    "roadmap": "timeline", "etapes": "steps", "étapes": "steps", "steps": "steps", "process": "steps",
    "processus": "steps", "methode": "steps", "méthode": "steps",
    "compare": "compare", "comparaison": "compare", "comparison": "compare", "versus": "compare", "vs": "compare",
    "colonnes": "compare", "columns": "compare", "avant-apres": "compare", "avant-après": "compare",
    "cards": "cards", "cartes": "cards", "equipe": "cards", "équipe": "cards", "team": "cards", "piliers": "cards",
    "pillars": "cards", "offres": "cards", "features": "cards",
    "quote": "quote", "citation": "quote", "cite": "quote",
    "code": "code",
    "callout": "callout", "note": "callout", "info": "callout", "important": "callout", "warning": "callout",
    "attention": "callout", "alerte": "callout", "tip": "callout", "astuce": "callout", "ok": "callout",
    "success": "callout", "succes": "callout", "succès": "callout", "danger": "callout", "risque": "callout",
    "cle": "callout", "clé": "callout", "key": "callout", "retenir": "callout", "a-retenir": "callout",
    "à-retenir": "callout", "essentiel": "callout", "key-point": "callout", "takeaway": "callout",
    "notes": "notes", "speaker": "notes", "orateur": "notes",
    "list": "list", "liste": "list", "points": "list",
    "text": "text", "texte": "text", "paragraph": "text",
}  # fmt: skip
_CHART_WORDS = {"bar": "bar", "barres": "bar", "bars": "bar", "histogramme": "bar", "colonnes": "bar",
                "line": "line", "courbe": "line", "ligne": "line", "lines": "line",
                "pie": "pie", "camembert": "pie", "donut": "pie", "secteurs": "pie"}  # fmt: skip
_WARN = re.compile(r"^\W{0,3}(?:attention|avertissement|vigilance|risques?|warning|caution|alerte|danger)\b", re.I)
_INFO = re.compile(r"^\W{0,3}(?:à retenir|a retenir|important|note|nb|n\.b\.|conseil|astuce|en bref|key takeaway|tip)\b",
                   re.I)  # fmt: skip
_KEY = re.compile(r"^\W{0,3}(?:à retenir|a retenir|important|essentiel|en bref|key takeaway|key point)\b", re.I)
# Footnotes: « … 40 % des trajets[^1] » in the text, « [^1]: Source, 2024 » on its own line anywhere.
FOOTNOTE_DEF = re.compile(r"^\s*\[\^([\w-]{1,8})\]\s*:\s*(.+?)\s*$")
FOOTNOTE_REF = re.compile(r"\[\^([\w-]{1,8})\]")
MAX_FOOTNOTES = 30
_NUM = re.compile(r"[+\-−]?\d{1,3}(?:[\s  ]\d{3})+(?:[.,]\d+)?|[+\-−]?\d+(?:[.,]\d+)?")
_DELTA = re.compile(r"^[+\-−]\s?\d")


# ------------------------------------------------------------------ small helpers


def _cut(text: object, n: int) -> str:
    s = str(text if text is not None else "")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _clean_inline(text: str) -> str:
    """One line of model text: control characters out, surrounding spaces and stray ``**`` wrappers trimmed."""
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text or ""))
    s = s.strip()
    if re.fullmatch(r"\*\*[^*]+\*\*", s) or re.fullmatch(r"__[^_]+__", s):
        s = s[2:-2].strip()
    return s


def number(text: str) -> float | None:
    """'1 234,5' / '1,234.5' / '-3' -> float (French and English writing); None when it is not one number."""
    t = re.sub(r"[\s  ]", "", str(text)).replace("−", "-")
    if re.fullmatch(r"[+-]?\d+,\d+", t):
        t = t.replace(",", ".")
    elif re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        t = t.replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v == v and abs(v) < 1e15 else None  # no NaN, no absurd magnitudes


def value_unit(text: str) -> tuple[float | None, str]:
    """'1,1 M€' -> (1.1, 'M€'); '31 %' -> (31.0, '%'); 'n/a' -> (None, '')."""
    s = _clean_inline(text).replace("\xa0", " ").replace(" ", " ")
    m = _NUM.search(s)
    if not m:
        return None, ""
    v = number(m.group(0))
    unit = s[m.end() :].strip(" .;")
    unit = unit if len(unit) <= 8 and not re.search(r"\d", unit) else ""
    return v, unit


def theme_of(value: object) -> str | None:
    key = re.sub(r"[^a-zà-ÿ]", "", str(value or "").lower())
    return THEME_ALIASES.get(key)


def attrs_of(rest: str) -> tuple[dict[str, str], str]:
    """``query="vélo" type=bar`` -> ({'query': 'vélo', 'type': 'bar'}, '') ; the words left over are returned."""
    out: dict[str, str] = {}
    for m in _ATTR.finditer(rest or ""):
        val = next(g for g in m.groups()[1:] if g is not None)
        out[m.group(1).lower()] = _cut(_clean_inline(val), 300)
    left = _ATTR.sub(" ", rest or "").strip().strip("\"'«» ")
    return out, _cut(_clean_inline(left), 300)


def new_id(doc: dict) -> str:
    """The next free block id of a document (b1, b2…): ids are never reused within one artifact."""
    used = [int(b["id"][1:]) for b in doc.get("blocks") or [] if re.fullmatch(r"b\d{1,4}", str(b.get("id")))]
    nxt = doc.get("_next") if isinstance(doc.get("_next"), int) else 1
    n = max([nxt, *[u + 1 for u in used], 1])
    doc["_next"] = n + 1
    return f"b{n}"


def empty(kind: str = "deck", lang: str = "fr") -> dict:
    return {"v": 1, "kind": kind if kind in KINDS else "deck", "title": "", "subtitle": "", "theme": None,
            "lang": "en" if lang == "en" else "fr", "blocks": [], "media": {}}  # fmt: skip


# ------------------------------------------------------------------ directive bodies


def _strip_marker(line: str) -> str:
    m = _BULLET.match(line) or _ORDERED.match(line)
    return _clean_inline(m.groups()[-1] if m else line)


def kpi_item(line: str) -> dict | None:
    """'1,2 M€ | Chiffre d'affaires | +8 %', 'CA : 1,2 M€ (+8 %)', '31 % de marge' -> {value, label, delta}."""
    s = _strip_marker(line)
    if not s:
        return None
    cells = [c.strip() for c in s.strip("|").split("|")] if "|" in s else []
    value, label, delta = "", "", ""
    if len(cells) >= 2:
        nums = [c for c in cells if _NUM.search(c)]
        value = next((c for c in cells if _NUM.search(c) and not _DELTA.match(c)), nums[0] if nums else cells[0])
        rest = [c for c in cells if c is not value]
        delta = next((c for c in rest if _DELTA.match(c)), "")
        label = " ".join(c for c in rest if c is not delta and c)
    else:
        m = re.match(r"^(?P<label>[^:]{1,80}?)\s*[:=–—]\s*(?P<value>.+)$", s)
        if m and _NUM.search(m.group("value")):
            label, value = m.group("label"), m.group("value")
        else:
            n = _NUM.search(s)
            if not n:
                return {"value": "", "label": _cut(s, 120), "delta": ""}
            # the figure and its unit, then what it measures
            um = re.match(r"\s?(%|[kKM]?€|Md€|Mds€|M\$|\$|£|pts?|h\b|k\b|M\b|Md\b|ans?\b|jours?\b|x\b)?", s[n.end() :])
            end = n.end() + (len(um.group(0)) if um and um.group(1) else 0)
            value, label = s[n.start() : end], (s[: n.start()] + " " + s[end:]).strip(" :–—-")
        d = re.search(r"\(\s*([+\-−]\s?\d[^()]*)\)", value + " " + label)
        if d:
            delta = d.group(1).strip()
            value = value.replace(d.group(0), "").strip()
            label = label.replace(d.group(0), "").strip()
    label = re.sub(r"\s{2,}", " ", label).strip(" :–—-")
    return {"value": _cut(value.strip(), 40), "label": _cut(label[:1].upper() + label[1:], 120),
            "delta": _cut(delta, 24)}  # fmt: skip


def chart_part(lines: list[str], attrs: dict, words: str = "", title: str = "") -> dict | None:
    """Rows of a chart: 'label: 12', 'label | 12 | 15' (a header row first may name the series). None when fewer
    than two numeric rows survive (the caller keeps the lines as a table or a list instead)."""
    kind = _CHART_WORDS.get(str(attrs.get("type") or attrs.get("kind") or "").lower()) or next(
        (v for k, v in _CHART_WORDS.items() if re.search(rf"\b{k}\b", words, re.I)), None
    )
    unit = str(attrs.get("unit") or attrs.get("unite") or attrs.get("unité") or "")[:8]
    header: list[str] | None = None
    rows: list[list] = []
    for raw in lines:
        s = _strip_marker(raw)
        if not s or _SEP_ROW.match(s):
            continue
        if "|" in s or "\t" in s or ";" in s:
            sep = "|" if "|" in s else ("\t" if "\t" in s else ";")
            cells = [c.strip() for c in s.strip("|").split(sep)]
        else:
            m = re.match(r"^(?P<label>.{1,60}?)\s*(?::|=|–|—|\s-\s)\s*(?P<vals>.+)$", s)
            if not m:
                continue
            cells = [m.group("label")] + [c.strip() for c in re.split(r"[,/](?!\d)|\s{2,}", m.group("vals"))]
        values = [value_unit(c) for c in cells[1:]]
        if header is None and not rows and len(cells) >= 2 and all(v is None for v, _ in values):
            header = [_cut(c, 80) for c in cells]
            continue
        if not values or all(v is None for v, _ in values):
            continue
        if not unit:
            unit = next((u for _, u in values if u), "")
        rows.append([_cut(_clean_inline(cells[0]), 80)] + [v for v, _ in values])
    if len(rows) < 2 and not (rows and kind == "pie"):
        return None
    width = max(len(r) for r in rows)
    width = min(width, 7)
    rows = [(r + [None] * width)[:width] for r in rows][:MAX_ROWS]
    cols = header[:width] if header and len(header) >= width else None
    if cols is None:
        cols = [""] + (
            [unit or (attrs.get("series") or "Valeur")] if width == 2 else [f"S{i}" for i in range(1, width)]
        )
    cols = [_cut(c, 80) for c in (cols + [""] * width)[:width]]
    if not kind:
        first = [str(r[0]) for r in rows]
        timeish = all(re.match(r"^(?:(?:19|20)\d{2}|[TQS][1-4]|janv|f[ée]v|mars|avr|mai|juin|juil|ao|sep|oct|nov|"
                               r"d[ée]c|jan|feb|mar|apr|may|jun|jul|aug|dec|s\d|semaine|week|mois)", f, re.I)
                      for f in first)  # fmt: skip
        kind = "line" if timeish and len(rows) >= 4 else "bar"
    return {"t": "chart", "type": kind, "unit": unit, "title": _cut(attrs.get("title") or title, 120),
            "columns": cols, "rows": rows, "source": _cut(attrs.get("source") or "", 200)}  # fmt: skip


def table_rows(lines: list[str]) -> list[list[str]]:
    rows = []
    for raw in lines:
        s = raw.strip()
        if not s or _SEP_ROW.match(s):
            continue
        sep = "|" if "|" in s else ("\t" if "\t" in s else (";" if ";" in s else None))
        if sep is None:
            rows.append([_cut(_strip_marker(s), 300)])
            continue
        rows.append([_cut(_clean_inline(c), 300) for c in s.strip().strip("|").split(sep)])
    if not rows:
        return []
    width = min(max(len(r) for r in rows), 8)
    return [(r + [""] * width)[:width] for r in rows][:MAX_ROWS]


def timeline_items(lines: list[str]) -> list[dict]:
    out = []
    for raw in lines:
        s = _strip_marker(raw)
        if not s:
            continue
        m = re.match(r"^(?P<when>.{1,40}?)\s*(?::|–|—|\s-\s|\|)\s*(?P<what>.+)$", s)
        out.append({"when": _cut(m.group("when"), 40), "what": _cut(m.group("what"), 300)} if m
                   else {"when": "", "what": _cut(s, 300)})  # fmt: skip
    return out[:MAX_ITEMS]


def quote_part(lines: list[str], attrs: dict) -> dict | None:
    texts = [_clean_inline(re.sub(r"^\s*>\s?", "", ln)) for ln in lines]
    texts = [t for t in texts if t]
    if not texts:
        return None
    by = str(attrs.get("by") or attrs.get("author") or attrs.get("auteur") or "")
    if not by and len(texts) > 1 and re.match(r"^[—–-]\s*\S", texts[-1]):
        by = texts.pop().lstrip("—–- ")
    text = " ".join(texts)
    m = re.match(r"^(.*?[»”\"])\s*[—–-]\s*(.{2,80})$", text)
    if m and not by:
        text, by = m.group(1), m.group(2)
    text = text.strip().strip('«»“”"').strip()
    return {"t": "quote", "text": _cut(text, 600), "by": _cut(by, 120)}


def _tone(kind_word: str, text: str) -> str:
    w = kind_word.lower()
    if w in ("warning", "attention", "alerte", "danger", "risque") or _WARN.match(text):
        return "warn"
    if w in ("ok", "success", "succes", "succès"):
        return "ok"
    if w in ("cle", "clé", "key", "retenir", "a-retenir", "à-retenir", "essentiel", "key-point", "takeaway",
             "important") or _KEY.match(text):
        return "key"
    return "info"


def directive_part(word: str, rest: str, body: list[str], title: str, repairs: list[str]) -> list[dict] | str:
    """The part(s) of one ``::: type`` block; for ``notes`` the notes text is returned (a str)."""
    kind = _TYPE_ALIASES.get(word.lower(), "")
    attrs, left = attrs_of(rest)
    text_lines = [ln for ln in body if ln.strip()]
    if kind == "notes":
        return " ".join(_clean_inline(ln) for ln in text_lines)[:MAX_TEXT]
    if kind == "kpi":
        items = [k for k in (kpi_item(ln) for ln in text_lines) if k]
        return [{"t": "kpi", "items": items[:6]}] if items else []
    if kind == "image":
        query = attrs.get("query") or attrs.get("q") or attrs.get("recherche") or attrs.get("search") or left
        if not query and text_lines:
            query = _clean_inline(" ".join(text_lines))
        src = attrs.get("src") or attrs.get("url") or ""
        if not query and src:
            query = re.sub(r"[_\-./]+", " ", re.sub(r"^https?://[^/]+/?", "", src)).strip()
            repairs.append("image URL ignored: its words became the search query")
        query = _cut(query, 120)
        if not query:
            repairs.append("image block without a query dropped")
            return []
        return [
            {
                "t": "image",
                "query": query,
                "alt": _cut(attrs.get("alt") or query, 160),
                "caption": _cut(attrs.get("caption") or attrs.get("legende") or attrs.get("légende") or "", 200),
            }
        ]
    if kind == "chart":
        words = f"{word} {left}"
        part = chart_part(text_lines, attrs, words, title)
        if part:
            return [part]
        repairs.append("chart without two numeric rows kept as a table")
        rows = table_rows(text_lines)
        return [{"t": "table", "rows": rows}] if rows else []
    if kind == "table":
        rows = table_rows(text_lines)
        return [{"t": "table", "rows": rows}] if rows else []
    if kind == "timeline":
        items = timeline_items(text_lines)
        return [{"t": "timeline", "items": items}] if items else []
    if kind == "quote":
        q = quote_part(text_lines, attrs)
        return [q] if q else []
    if kind == "code":
        lang = code_lang(attrs.get("lang") or attrs.get("language") or left)
        code = "\n".join(body).strip("\n")
        return [{"t": "code", "lang": lang, "text": code[:MAX_CODE]}] if code.strip() else []
    if kind == "callout":
        text = " ".join(_clean_inline(ln) for ln in text_lines) or left
        return [{"t": "callout", "tone": _tone(word, text), "text": _cut(text, MAX_TEXT)}] if text else []
    if kind == "compare":
        part = compare_part(text_lines, left)
        if part:
            return [part]
        repairs.append("comparison without two columns kept as a list")
        return [{"t": "list", "items": [_list_item(ln) for ln in text_lines][:MAX_ITEMS], "ordered": False}]
    if kind in ("steps", "cards"):
        items = card_items(text_lines)
        if kind == "steps" and items and all(_DATEISH.match(x["title"]) for x in items):
            return [{"t": "timeline", "items": [{"when": x["title"][:40], "what": x["text"] or x["title"]}
                                                for x in items]}]  # fmt: skip
        return [{"t": kind, "items": items}] if items else []
    if kind == "list":
        items = [_list_item(ln) for ln in text_lines]
        return [{"t": "list", "items": [i for i in items if i.strip()][:MAX_ITEMS], "ordered": False}]
    # unknown type, or « text »: its lines are ordinary content
    if kind != "text" and word:
        repairs.append(f"unknown block type '{word[:20]}' read as text")
    return _content_parts(body, repairs)


_DATEISH = re.compile(r"^(?:\d{4}|[TSQH]\d\b|semaine|week|jour|day|mois|month|janv|f[ée]v|mars|avr|mai|juin|juil|"
                      r"ao[uû]t|sept|oct|nov|d[ée]c|jan|feb|mar|apr|may|jun|jul|aug|sep|dec|printemps|[ée]t[ée]|"
                      r"automne|hiver|spring|summer|autumn|winter)", re.I)  # fmt: skip
_CARD = re.compile(r"^(?P<title>[^:|—–]{1,80}?)\s*(?::|\||—|–|\s-\s)\s*(?P<text>.+)$")
_GROUP = re.compile(r"^\s*(?:#{1,6}\s*)?(?P<t>[^:|]{1,60}?)\s*:\s*$")


def card_items(lines: list[str]) -> list[dict]:
    """'Titre : texte' (or 'Titre | texte', 'Titre — texte') lines -> [{title, text}] (steps, cards)."""
    out = []
    for raw in lines:
        s = _strip_marker(raw)
        if not s:
            continue
        m = _CARD.match(s)
        out.append({"title": _cut(m.group("title"), 80), "text": _cut(m.group("text"), 300)} if m
                   else {"title": _cut(s, 80) if len(s) <= 80 else "", "text": "" if len(s) <= 80 else _cut(s, 300)})
    return out[:8]


def compare_part(lines: list[str], words: str = "") -> dict | None:
    """Two or three columns: a header row 'Avant | Après' then 'x | y' rows, or groups ('Avant :' then bullets).
    None when fewer than two columns come out."""
    rows = [ln for ln in lines if ln.strip() and not _SEP_ROW.match(ln)]
    cols: list[dict] = []
    if rows and "|" in rows[0]:
        head = [_clean_inline(c) for c in rows[0].strip().strip("|").split("|")][:3]
        cols = [{"title": _cut(h, 80), "items": []} for h in head]
        for r in rows[1:]:
            cells = [_clean_inline(c) for c in r.strip().strip("|").split("|")]
            for k, c in enumerate(cells[: len(cols)]):
                if c.strip(" -"):
                    cols[k]["items"].append(_cut(c, 300))
    else:
        for r in rows:
            g = _GROUP.match(r)
            if g and not _BULLET.match(r):
                cols.append({"title": _cut(_clean_inline(g.group("t")), 80), "items": []})
            elif cols:
                cols[-1]["items"].append(_cut(_strip_marker(r), 300))
        if not cols and re.search(r"\bvs\.?\b|\bversus\b|\bcontre\b", words, re.I):
            names = re.split(r"\s+(?:vs\.?|versus|contre)\s+", words, flags=re.I)[:2]
            cols = [{"title": _cut(n, 80), "items": []} for n in names]
    cols = [c for c in cols if c["title"] or c["items"]][:3]
    for c in cols:
        c["items"] = c["items"][:6]
    return {"t": "compare", "columns": cols} if len(cols) >= 2 else None


def code_lang(word: object) -> str:
    w = str(word or "").strip().lower()
    aliases = {"htm": "html", "xhtml": "html", "javascript": "js", "jsx": "js", "mjs": "js", "py": "python",
               "python3": "python", "md": "markdown", "mmd": "mermaid", "flowchart": "mermaid", "graph": "mermaid",
               "txt": "text", "plain": "text", "": "text", "svg+xml": "svg", "xml": "html", "typescript": "ts",
               "tsx": "ts", "sh": "bash", "shell": "bash", "zsh": "bash", "yml": "yaml", "postgresql": "sql",
               "mysql": "sql", "sqlite": "sql"}  # fmt: skip
    w = aliases.get(w, w)
    return w if w in CODE_LANGS else "text"


def _list_item(line: str) -> str:
    m = _BULLET.match(line) or _ORDERED.match(line)
    if not m:
        return _cut(_clean_inline(line), 600)
    indent = len(m.group(1).replace("\t", "    "))
    text = _cut(_clean_inline(m.groups()[-1]), 600)
    return ("  " + text) if indent >= 2 else text


# ------------------------------------------------------------------ the free content of a block


_PLACEHOLDER = re.compile(
    r"^\s*(?:[-*•+]\s+|\d+[.)]\s+)?[\[(]\s*(photo|image|illustration|visuel|picture|img|pictogramme|icône|icone)s?"
    r"\s*(?:[:：–—-]|d['’]un[e]?|de)\s*(.+?)\s*[\])]\s*\.?\s*$",
    re.I,
)


def _content_parts(lines: list[str], repairs: list[str]) -> list[dict]:
    """Paragraphs, lists, tables, quotes, code fences, Markdown images and sub-headings of a block's free text."""
    # « [Photo : chaton heureux] » written as text or as a bullet is a picture the model meant, never words to print:
    # it becomes an image search (the same path as « ::: image query=… », licence checked, credit shown)
    fixed = []
    for line in lines:
        ph = _PLACEHOLDER.match(line)
        if ph and ph.group(2).strip():
            repairs.append("image placeholder written as text became an image search")
            fixed.append(f"![{ph.group(2).strip()}](placeholder)")
        else:
            fixed.append(line)
    lines = fixed
    parts: list[dict] = []
    i, n = 0, len(lines)
    para: list[str] = []

    def flush() -> None:
        if para:
            text = " ".join(_clean_inline(p) for p in para if p.strip())
            if text:
                if _WARN.match(text) or _INFO.match(text):
                    parts.append({"t": "callout", "tone": _tone("", text), "text": _cut(text, MAX_TEXT)})
                else:
                    parts.append({"t": "text", "text": _cut(text, MAX_TEXT)})
            para.clear()

    while i < n:
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            flush()
            mark, lang = fence.group(1), fence.group(2)
            j, code = i + 1, []
            while j < n and not lines[j].strip().startswith(mark[0] * 3):
                code.append(lines[j])
                j += 1
            if j >= n:
                repairs.append("unclosed code fence closed at the end of its block")
            if "\n".join(code).strip():
                parts.append({"t": "code", "lang": code_lang(lang), "text": "\n".join(code)[:MAX_CODE]})
            i = j + 1
            continue
        head = _HEADING.match(line)
        if head:
            flush()
            text = _clean_inline(head.group(2))
            if text:
                parts.append({"t": "heading", "text": _cut(text, MAX_TITLE), "level": min(len(head.group(1)), 4)})
            i += 1
            continue
        img = _MD_IMAGE.match(line)
        if img:
            flush()
            alt, target = img.group(1).strip(), img.group(2).strip()
            query = alt or re.sub(r"[_\-./]+", " ", re.sub(r"^https?://[^/]+/?", "", target)).strip()
            if target.startswith(("http://", "https://", "data:", "//")):
                repairs.append("image URL ignored: its words became the search query")
            if query:
                parts.append({"t": "image", "query": _cut(query, 120), "alt": _cut(alt or query, 160), "caption": ""})
            i += 1
            continue
        if _BULLET.match(line) or _ORDERED.match(line):
            flush()
            ordered = bool(_ORDERED.match(line)) and not _BULLET.match(line)
            items = []
            while i < n and lines[i].strip() and (_BULLET.match(lines[i]) or _ORDERED.match(lines[i])
                                                  or (items and lines[i].startswith("   "))):  # fmt: skip
                if not (_BULLET.match(lines[i]) or _ORDERED.match(lines[i])):
                    items[-1] = _cut(items[-1] + " " + _clean_inline(lines[i]), 600)  # a wrapped item
                else:
                    items.append(_list_item(lines[i]))
                i += 1
            items = [x for x in items if x.strip()]
            if len(items) > MAX_ITEMS:
                repairs.append(f"list cut to {MAX_ITEMS} items")
            if items:
                parts.append({"t": "list", "items": items[:MAX_ITEMS], "ordered": ordered})
            continue
        if line.lstrip().startswith(">"):
            flush()
            q = []
            while i < n and lines[i].lstrip().startswith(">"):
                q.append(lines[i])
                i += 1
            if i < n and re.match(r"^\s*[—–]\s*\S", lines[i]):  # « — Auteur » just under the quotation
                q.append(lines[i])
                i += 1
            text = " ".join(_clean_inline(re.sub(r"^\s*>\s?", "", x)) for x in q)
            if _WARN.match(text) or _INFO.match(text):
                parts.append({"t": "callout", "tone": _tone("", text), "text": _cut(text, MAX_TEXT)})
            else:
                part = quote_part(q, {})
                if part:
                    parts.append(part)
            continue
        if "|" in line and i + 1 < n and "|" in lines[i + 1]:
            flush()
            rows = []
            while i < n and "|" in lines[i]:
                rows.append(lines[i])
                i += 1
            parts.append({"t": "table", "rows": table_rows(rows)})
            continue
        para.append(line)
        i += 1
    flush()
    return parts


# ------------------------------------------------------------------ the document


def _front_matter(lines: list[str], repairs: list[str]) -> tuple[dict, int]:
    """Front matter between ``---`` lines, or « Titre : … » lines at the very top. Returns (fields, next line)."""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    meta: dict = {}
    if i < len(lines) and re.fullmatch(r"\s*-{3,}\s*", lines[i]):
        j = i + 1
        while j < len(lines) and j - i <= 10:
            if re.fullmatch(r"\s*-{3,}\s*", lines[j]):
                return meta, j + 1
            m = _KV.match(lines[j])
            if m and m.group(1).strip().lower() in _FRONT_KEYS:
                meta[_FRONT_KEYS[m.group(1).strip().lower()]] = _clean_inline(m.group(2)).strip("\"'«» ")
            elif lines[j].strip():
                break
            j += 1
        if meta:
            repairs.append("unclosed front matter closed")
            return meta, j
        return {}, i + 1  # a lone separator at the top
    j = i
    end = 0
    while j < len(lines):
        if not lines[j].strip() and meta:  # « title: … », a blank line, « image: … » (a 4B habit): still the head
            j += 1
            continue
        m = _KV.match(lines[j])
        if not (m and m.group(1).strip().lower() in _FRONT_KEYS):
            break
        meta[_FRONT_KEYS[m.group(1).strip().lower()]] = _clean_inline(m.group(2)).strip("\"'«» ")
        j += 1
        end = j
    if meta and end < len(lines):
        k = end
        while k < len(lines) and not lines[k].strip():
            k += 1
        if k < len(lines) and re.fullmatch(r"\s*-{3,}\s*", lines[k]):
            end = k + 1  # the closing « --- » of a front matter whose opening one was left out
            repairs.append("front matter without its opening line read")
    return meta, (end if meta else 0)


def _clean_heading(text: str) -> tuple[str, str | None]:
    """'[b3] Diapositive 3 : **Les risques**' -> ('Les risques', 'b3'). A layout tag ``{versus}`` is cut off
    (``_heading_layout`` reads it)."""
    s = _clean_inline(_LAYOUT_TAG.sub("", text))
    m = _ID_TAG.match(s)
    bid = m.group(1) if m else None
    if m:
        s = s[m.end() :]
    s2 = _NUMBERED_HEAD.sub("", s, count=1).strip()
    s = _clean_inline(s2 if s2 else s)
    return _cut(s.strip(" :–—-"), MAX_TITLE), bid


def _block_level(lines: list[str]) -> tuple[int | None, bool]:
    """(the heading level that starts a block, whether the first heading is the document title)."""
    levels, in_fence = [], False
    for ln in lines:
        if _FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(ln)
        if m and m.group(2).strip():
            levels.append(len(m.group(1)))
    if not levels:
        return None, False
    low = min(levels)
    if levels.count(low) == 1 and levels[0] == low and len(levels) > 1:
        rest = [lv for lv in levels[1:]]
        return min(rest), True
    return low, False


def parse(text: object, kind: str = "deck", lang: str = "fr", repairs: list[str] | None = None,
          title_hint: str = "") -> dict:  # fmt: skip
    """The document written in ``text`` (any string). Never raises; ``repairs`` receives what was fixed."""
    repairs = repairs if repairs is not None else []
    doc = empty(kind, lang)
    src = str(text if text is not None else "")
    if len(src) > 120_000:
        src = src[:120_000]
        repairs.append("input cut to 120 000 characters")
    src = src.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    lines = src.split("\n")
    meta, start = _front_matter(lines, repairs)
    lines = lines[start:]
    if meta.get("kind") in ("deck", "slides", "présentation", "presentation"):
        doc["kind"] = "deck"
    elif meta.get("kind") in ("doc", "document", "rapport", "report"):
        doc["kind"] = "doc"
    doc["title"] = _cut(meta.get("title") or "", MAX_TITLE)
    doc["subtitle"] = _cut(meta.get("subtitle") or "", MAX_TITLE)
    for key in ("template", "author", "recipient"):  # read as written; turn.finish_doc checks them
        if meta.get(key):
            doc[key] = _cut(meta[key], 120)
    notes, kept, fence = [], [], False
    for ln in lines:  # footnote definitions, wherever the model put them, outside code
        if _FENCE.match(ln):
            fence = not fence
        m = None if fence else FOOTNOTE_DEF.match(ln)
        if m and len(notes) < MAX_FOOTNOTES:
            notes.append({"n": m.group(1), "text": _cut(_clean_inline(m.group(2)), 600)})
        elif not m:
            kept.append(ln)
    if notes:
        lines = kept
        doc["footnotes"] = notes
    if meta.get("theme"):
        doc["theme"] = theme_of(meta["theme"])
        if doc["theme"] is None:
            repairs.append("unknown theme ignored")
    level, titled = _block_level(lines)
    blocks: list[dict] = []
    cur: dict | None = None
    body: list[str] = []

    def close() -> None:
        nonlocal cur
        if cur is None:
            if any(ln.strip() for ln in body):
                cur = {"title": "", "lines": list(body), "bid": None}
            else:
                body.clear()
                return
        else:
            cur["lines"] = list(body)
        blocks.append(cur)
        cur = None
        body.clear()

    in_fence = None
    saw_title = False
    for ln in lines:
        fm = _FENCE.match(ln)
        if fm and in_fence is None:
            in_fence = fm.group(1)[0]
        elif in_fence and ln.strip().startswith(in_fence * 3):
            in_fence = None
            body.append(ln)
            continue
        if in_fence:
            body.append(ln)
            continue
        h = _HEADING.match(ln)
        if h and h.group(2).strip() and level is not None and len(h.group(1)) <= level:
            title, bid = _clean_heading(h.group(2))
            tag = _LAYOUT_TAG.search(h.group(2))
            hint = layout_of(tag.group(1)) if tag else None
            if titled and not saw_title and len(h.group(1)) < level:
                saw_title = True
                if not doc["title"]:
                    doc["title"] = title
                continue
            close()
            cur = {"title": title, "bid": bid, "layout": hint}
            continue
        if _HR.match(ln) and cur is not None and any(x.strip() for x in body):
            close()  # Marp-style separator between two slides
            cur = {"title": "", "bid": None}
            continue
        if _HR.match(ln):
            continue
        body.append(ln)
    close()
    if in_fence:
        repairs.append("unclosed code fence closed at the end")

    if len(blocks) > 1 and not blocks[0]["title"] and blocks[0].get("bid") is None:
        pre = _block_parts(blocks[0]["lines"], "", [])[0]
        if all(p["t"] == "text" for p in pre) and sum(len(p["text"]) for p in pre) <= 300:
            blocks.pop(0)  # « Voici la présentation : » before the first heading is chat, not a slide
            repairs.append("preamble before the first heading left out")
    if meta.get("image"):
        q = _cut(re.sub(r"^https?://\S+$", "", meta["image"]).strip(), 120)
        if q:
            doc["cover"] = {"query": q}
    for raw in blocks:
        lines_ = list(raw["lines"])
        hint = raw.get("layout")
        first = next((k for k, x in enumerate(lines_) if x.strip()), None)
        if first is not None and (lm := _LAYOUT_LINE.match(lines_[first])):
            hint = hint or layout_of(lm.group(1))
            if not layout_of(lm.group(1)):
                repairs.append("unknown layout ignored")
            lines_.pop(first)
        raw["lines"] = lines_
        parts, notes = _block_parts(raw["lines"], raw["title"], repairs)
        title = raw["title"]
        if not title and parts and parts[0]["t"] == "text" and len(parts[0]["text"]) <= 80 and len(parts) > 1:
            title = parts.pop(0)["text"].rstrip(".:")  # a slide written without a heading: its first short line
        if not title and not parts:
            continue
        if len(parts) > MAX_PARTS:
            repairs.append(f"block cut to {MAX_PARTS} parts")
        blk = {"id": "", "title": _cut(title, MAX_TITLE), "parts": parts[:MAX_PARTS], "notes": _cut(notes, MAX_TEXT)}
        if hint:
            blk["layout"] = hint
        if raw.get("bid"):
            blk["id"] = raw["bid"]
        blocks_out = doc["blocks"]
        if len(blocks_out) >= MAX_BLOCKS:
            repairs.append(f"document cut to {MAX_BLOCKS} blocks")
            break
        blocks_out.append(blk)
    _assign_ids(doc)
    if not doc["title"]:
        doc["title"] = _cut(_clean_inline(title_hint), MAX_TITLE) or (
            doc["blocks"][0]["title"] if doc["blocks"] and doc["kind"] == "doc" else ""
        )
    return doc


def _assign_ids(doc: dict) -> None:
    seen: set[str] = set()
    for b in doc["blocks"]:
        if b.get("id") and b["id"] not in seen and re.fullmatch(r"b\d{1,4}", b["id"]):
            seen.add(b["id"])
        else:
            b["id"] = ""
    for b in doc["blocks"]:
        if not b["id"]:
            b["id"] = new_id(doc)
            seen.add(b["id"])
    used = [int(b["id"][1:]) for b in doc["blocks"]]
    doc["_next"] = max([doc.get("_next") or 1, *[u + 1 for u in used]])


def _block_parts(lines: list[str], title: str, repairs: list[str]) -> tuple[list[dict], str]:
    parts: list[dict] = []
    notes: list[str] = []
    free: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        d = _DIRECTIVE.match(ln)
        if d and d.group(1):
            parts += _content_parts(free, repairs)
            free = []
            word, rest = d.group(1), d.group(2) or ""
            j, body = i + 1, []
            closed = False
            while j < n:
                dj = _DIRECTIVE.match(lines[j])
                if dj and not dj.group(1) and not (dj.group(2) or "").strip():
                    closed = True
                    break
                if dj and dj.group(1):
                    break  # a new block opens: the current one was not closed
                body.append(lines[j])
                j += 1
            if not closed and any(x.strip() for x in body) and j >= n:
                repairs.append(f"unclosed '{word[:20]}' block closed")
            elif not closed and j < n:
                repairs.append(f"unclosed '{word[:20]}' block closed")
            out = directive_part(word, rest, body, title, repairs)
            if isinstance(out, str):
                notes.append(out)
            else:
                parts += out
            i = j + 1 if closed else j
            continue
        if d and not d.group(1):
            i += 1  # a stray closing ':::'
            continue
        nm = _NOTES.match(ln)
        if nm:
            parts += _content_parts(free, repairs)
            free = []
            text = [nm.group(1)]
            i += 1
            while (
                i < n
                and lines[i].strip()
                and not _DIRECTIVE.match(lines[i])
                and not _FENCE.match(lines[i])
                and not _BULLET.match(lines[i])
                and not _HEADING.match(lines[i])
            ):
                text.append(lines[i])
                i += 1
            notes.append(" ".join(_clean_inline(x) for x in text if x.strip()))
            continue
        free.append(ln)
        i += 1
    parts += _content_parts(free, repairs)
    return [p for p in parts if p], " ".join(x for x in notes if x).strip()


# ------------------------------------------------------------------ code


_ANY_FENCE = re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,})[ \t]*([\w+#.-]*)[^\n]*\n(.*?)(?:^[ \t]*\1[ \t]*$|\Z)")


def parse_code(text: object, want: str | None = None) -> dict | None:
    """The main code of an answer, as {'lang', 'text', 'before', 'after'}: the longest fence of a previewable or
    asked language; a bare HTML or SVG document without fence counts. None when there is no code."""
    src = str(text or "").replace("\r\n", "\n")
    best = None
    for m in _ANY_FENCE.finditer(src):
        lang = code_lang(m.group(2)) if m.group(2) else _sniff(m.group(3))
        code = m.group(3).rstrip("\n")
        if not code.strip():
            continue
        score = (
            len(code)
            + (100_000 if lang in ("html", "svg", "mermaid") else 0)
            + (200_000 if want and lang == want else 0)
        )
        if best is None or score > best[0]:
            best = (score, lang, code, m.start(), m.end())
    if best is None:
        s = src.strip()
        if re.match(r"(?is)^(?:<!doctype html|<html|<svg)\b", s):
            return {"lang": "svg" if s.lower().startswith("<svg") else "html", "text": s[:MAX_CODE],
                    "before": "", "after": ""}  # fmt: skip
        return None
    _, lang, code, a, b = best
    return {"lang": lang, "text": code[:MAX_CODE], "before": src[:a].strip(), "after": src[b:].strip()}


def _sniff(code: str) -> str:
    s = code.lstrip().lower()
    if s.startswith(("<!doctype html", "<html", "<div", "<body", "<head", "<section", "<main", "<style", "<p>")):
        return "html"
    if s.startswith("<svg"):
        return "svg"
    if re.match(r"(?:flowchart|graph)\s+(?:td|tb|lr|rl|bt)\b|sequencediagram", s):
        return "mermaid"
    if re.search(r"^\s*(?:def |import |from \w+ import |class \w+[:(])", code, re.M):
        return "python"
    if re.search(r"\b(?:function|const|let|=>|document\.)", code):
        return "js"
    return "text"


# ------------------------------------------------------------------ where the content is in an answer

_CANVAS_FENCE = re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,})[ \t]*(canvas|bird|deck|slides|doc|document|markdown|md)?[ \t]*"
                           r"\n(.*?)(?:^[ \t]*\1[ \t]*$|\Z)")  # fmt: skip


def split_answer(text: object) -> tuple[str, str, str]:
    """(prose before, canvas content, prose after) of a model answer on a canvas turn.

    The content is the first fenced block tagged canvas/markdown (or untagged) that holds headings; else, from the
    front matter or the first heading to the end. A model that wrote a friendly sentence first keeps it in the chat.
    """
    src = str(text or "").replace("\r\n", "\n")
    for m in _CANVAS_FENCE.finditer(src):
        inner = m.group(3)
        if re.search(r"(?m)^\s{0,3}#{1,3}\s+\S", inner) or re.search(r"(?m)^\s*:::", inner):
            return src[: m.start()].strip(), inner, src[m.end() :].strip()
    fm = re.search(r"(?m)^-{3,}\s*\n(?:\s*[A-Za-zÀ-ÿ -]{1,20}\s*:.*\n){1,8}", src)
    hm = re.search(r"(?m)^\s{0,3}#{1,3}\s+\S", src)
    km = re.search(r"(?mi)^\s*(?:titre|title)\s*:\s*\S", src)
    starts = [m.start() for m in (fm, hm, km) if m]
    if not starts:
        return "", src, ""
    at = min(starts)
    before = src[:at].strip()
    content = src[at:]
    # a closing remark after the last block (« N'hésitez pas à me demander… ») goes back to the chat
    tail = re.search(r"(?s)\n\s*\n((?:N['’]h[ée]sitez|Dites-moi|Souhaitez-vous|Voulez-vous|Je peux|Let me know|"
                     r"Would you like|Feel free|Do you want)[^\n]*)\s*$", content)  # fmt: skip
    after = ""
    if tail:
        after, content = tail.group(1).strip(), content[: tail.start()]
    return before, content, after


# ------------------------------------------------------------------ back to text (the outline the model is given)


def _part_dsl(p: dict) -> list[str]:
    t = p.get("t")
    if t == "text":
        return [p.get("text", ""), ""]
    if t == "heading":
        return ["#" * (int(p.get("level") or 2)) + " " + p.get("text", "")]
    if t == "list":
        return [(f"{i}. " if p.get("ordered") else "- ") + it.strip() if not it.startswith("  ")
                else ("  - " + it.strip()) for i, it in enumerate(p.get("items") or [], 1)]  # fmt: skip
    if t == "kpi":
        return ["::: kpi"] + [" | ".join(x for x in (k.get("value"), k.get("label"), k.get("delta")) if x)
                              for k in p.get("items") or []] + [":::"]  # fmt: skip
    if t == "image":
        return [f'::: image query="{p.get("query", "")}"', ":::"]
    if t == "chart":
        head = f"::: chart type={p.get('type', 'bar')}" + (f' unit="{p["unit"]}"' if p.get("unit") else "")
        cols = p.get("columns") or []
        rows = []
        if len(cols) > 2:
            rows.append(" | ".join(str(c) for c in cols))
        for r in p.get("rows") or []:
            vals = [_fmt(v) for v in r[1:]]
            rows.append(f"{r[0]}: {vals[0]}" if len(vals) == 1 else " | ".join([str(r[0])] + vals))
        return [head] + rows + [":::"]
    if t == "table":
        rows = p.get("rows") or []
        out = []
        for k, r in enumerate(rows):
            out.append("| " + " | ".join(str(c) for c in r) + " |")
            if k == 0:
                out.append("|" + "---|" * len(r))
        return out
    if t == "timeline":
        return ["::: timeline"] + [f"{x.get('when')}: {x.get('what')}" if x.get("when") else str(x.get("what"))
                                   for x in p.get("items") or []] + [":::"]  # fmt: skip
    if t == "quote":
        return [f"> {p.get('text', '')}"] + ([f"> — {p['by']}"] if p.get("by") else [])
    if t == "code":
        return [f"```{p.get('lang', '')}", p.get("text", ""), "```"]
    if t == "callout":
        word = {"warn": "attention", "ok": "ok", "key": "cle"}.get(p.get("tone"), "note")
        return [f"::: {word}", p.get("text", ""), ":::"]
    if t == "compare":
        cols = p.get("columns") or []
        depth = max([len(c.get("items") or []) for c in cols] + [0])
        rows = [" | ".join(c.get("title") or "" for c in cols)]
        for k in range(depth):
            rows.append(" | ".join(((c.get("items") or [])[k] if k < len(c.get("items") or []) else "") for c in cols))
        return ["::: compare"] + rows + [":::"]
    if t in ("steps", "cards"):
        return [f"::: {t}"] + [f"{x.get('title')} : {x.get('text')}" if x.get("text") and x.get("title")
                               else str(x.get("title") or x.get("text") or "") for x in p.get("items") or []] + [":::"]
    return []


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace(".", ",")


def block_dsl(b: dict, ids: bool = True, level: int = 1) -> str:
    lines = ["#" * level + " " + (f"[{b['id']}] " if ids else "") + (b.get("title") or "")
             + (f" {{{b['layout']}}}" if b.get("layout") in LAYOUT_NAMES else "")]
    for p in b.get("parts") or []:
        lines += _part_dsl(p)
    if b.get("notes"):
        lines.append(f"Notes : {b['notes']}")
    return "\n".join(lines).rstrip() + "\n"


def to_dsl(doc: dict, ids: bool = True) -> str:
    """The document as the text format (``ids``: block ids in the headings, for a patch turn)."""
    if doc.get("kind") == "code":
        from .code import files_of

        return "".join(f"```{f['lang']} {f['name']}\n{f['text']}\n```\n" for f in files_of(doc))
    if doc.get("kind") == "sheet":
        sh = doc.get("sheet") or {}
        rows = [sh.get("columns") or []] + list(sh.get("rows") or [])
        return "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows) + "\n"
    head = ["---", f"title: {doc.get('title', '')}"]
    if doc.get("subtitle"):
        head.append(f"subtitle: {doc['subtitle']}")
    if doc.get("theme"):
        head.append(f"theme: {doc['theme']}")
    for key in ("template", "author", "recipient"):
        if doc.get(key):
            head.append(f"{key}: {doc[key]}")
    if (doc.get("cover") or {}).get("query"):
        head.append(f"image: {doc['cover']['query']}")
    head.append("---")
    notes = "".join(f"[^{x['n']}]: {x['text']}\n" for x in doc.get("footnotes") or [])
    return "\n".join(head) + "\n" + "\n".join(block_dsl(b, ids) for b in doc.get("blocks") or []) + (
        "\n" + notes if notes else "")


def summary_line(b: dict) -> str:
    """'[b3] Les risques — 3 points, image « vélo »': one line of an outline."""
    bits = []
    for p in b.get("parts") or []:
        t = p.get("t")
        if t == "list":
            bits.append(f"{len(p.get('items') or [])} points")
        elif t == "image":
            bits.append(f"image « {p.get('query', '')[:40]} »")
        elif t == "kpi":
            bits.append(f"{len(p.get('items') or [])} chiffres")
        elif t in ("chart", "table", "timeline", "quote", "code", "callout", "compare", "steps", "cards"):
            bits.append(t)
        elif t == "text":
            bits.append("texte")
    return f"[{b.get('id')}] {b.get('title') or '(sans titre)'}" + (f" — {', '.join(bits)}" if bits else "")


def outline(doc: dict, limit: int = 6000) -> str:
    """What the model is given of the current artifact on a patch turn: the full text with ids when it is short,
    else one line per block."""
    full = to_dsl(doc, ids=True)
    if len(full) <= limit:
        return full
    return f"title: {doc.get('title', '')}\n" + "\n".join(summary_line(b) for b in doc.get("blocks") or [])


# ------------------------------------------------------------------ validation of a document sent back by the browser


class Invalid(ValueError):
    pass


def _str(v, n: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, str | int | float) or isinstance(v, bool):
        raise Invalid("text expected")
    return _cut(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(v)), n)


def _part_ok(p) -> dict:
    if not isinstance(p, dict) or p.get("t") not in PART_TYPES:
        raise Invalid("unknown part")
    t = p["t"]
    if t in ("text", "heading", "callout"):
        out = {"t": t, "text": _str(p.get("text"), MAX_TEXT)}
        if t == "heading":
            lv = p.get("level", 2)
            out["level"] = lv if isinstance(lv, int) and 1 <= lv <= 4 else 2
        if t == "callout":
            out["tone"] = p.get("tone") if p.get("tone") in TONES else "info"
            if p.get("need") == "figures":
                out["need"] = "figures"  # a chart's place, waiting for the user's figures (birds/canvas/figures.py)
        return out
    if t == "list":
        items = p.get("items")
        if not isinstance(items, list):
            raise Invalid("list items")
        return {"t": t, "items": [_str(x, 600) for x in items[:MAX_ITEMS]], "ordered": bool(p.get("ordered"))}
    if t == "kpi":
        items = p.get("items")
        if not isinstance(items, list):
            raise Invalid("kpi items")
        return {
            "t": t,
            "items": [
                {
                    "value": _str(k.get("value"), 40),
                    "label": _str(k.get("label"), 120),
                    "delta": _str(k.get("delta"), 24),
                }
                for k in items[:6]
                if isinstance(k, dict)
            ],
        }
    if t == "image":
        out = {"t": t, "query": _str(p.get("query"), 120), "alt": _str(p.get("alt"), 160),
               "caption": _str(p.get("caption"), 200)}  # fmt: skip
        if isinstance(p.get("media"), str) and re.fullmatch(r"[a-z]{1,2}\d{1,4}", p["media"]):
            out["media"] = p["media"]
        elif p.get("missing") is True:
            out["missing"] = True  # searched, none found: a designed placeholder (« Chercher » / « Importer »)
        return out
    if t == "chart":
        cols, rows = p.get("columns"), p.get("rows")
        if not isinstance(cols, list) or not isinstance(rows, list) or not 2 <= len(cols) <= 7 or len(rows) > MAX_ROWS:
            raise Invalid("chart shape")
        clean_rows = []
        for r in rows:
            if not isinstance(r, list) or len(r) != len(cols):
                raise Invalid("chart row")
            vals = []
            for v in r[1:]:
                if v is None or v == "":
                    vals.append(None)
                elif isinstance(v, int | float) and not isinstance(v, bool) and abs(v) < 1e15 and v == v:
                    vals.append(v)
                else:
                    raise Invalid("chart value")
            clean_rows.append([_str(r[0], 80)] + vals)
        return {
            "t": t,
            "type": p.get("type") if p.get("type") in CHART_TYPES else "bar",
            "unit": _str(p.get("unit"), 8),
            "title": _str(p.get("title"), 120),
            "columns": [_str(c, 80) for c in cols],
            "rows": clean_rows,
            "source": _str(p.get("source"), 200),
        }
    if t == "table":
        rows = p.get("rows")
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise Invalid("table rows")
        return {"t": t, "rows": [[_str(c, 300) for c in r[:8]] for r in rows if isinstance(r, list)]}
    if t == "timeline":
        items = p.get("items")
        if not isinstance(items, list):
            raise Invalid("timeline items")
        return {"t": t, "items": [{"when": _str(x.get("when"), 40), "what": _str(x.get("what"), 300)}
                                  for x in items[:MAX_ITEMS] if isinstance(x, dict)]}  # fmt: skip
    if t == "quote":
        return {"t": t, "text": _str(p.get("text"), 600), "by": _str(p.get("by"), 120)}
    if t == "compare":
        cols = p.get("columns")
        if not isinstance(cols, list) or not 2 <= len(cols) <= 3:
            raise Invalid("compare columns")
        return {"t": t, "columns": [{"title": _str(c.get("title"), 80),
                                     "items": [_str(x, 300) for x in (c.get("items") or [])[:6]]}
                                    for c in cols if isinstance(c, dict) and isinstance(c.get("items") or [], list)]}
    if t in ("steps", "cards"):
        items = p.get("items")
        if not isinstance(items, list):
            raise Invalid("card items")
        return {"t": t, "items": [{"title": _str(x.get("title"), 80), "text": _str(x.get("text"), 300)}
                                  for x in items[:8] if isinstance(x, dict)]}  # fmt: skip
    return {"t": "code", "lang": code_lang(p.get("lang")), "text": _str(p.get("text"), MAX_CODE)}


def validate(doc) -> dict:
    """A clean copy of a document that came back from the browser (edited in the canvas): every field typed and
    capped, unknown fields dropped. Raises ``Invalid`` on a shape that cannot be a document."""
    if not isinstance(doc, dict):
        raise Invalid("document expected")
    kind = doc.get("kind")
    if kind not in KINDS:
        raise Invalid("unknown kind")
    out = empty(kind, str(doc.get("lang") or "fr"))
    out["title"] = _str(doc.get("title"), MAX_TITLE)
    out["subtitle"] = _str(doc.get("subtitle"), MAX_TITLE)
    out["theme"] = doc.get("theme") if doc.get("theme") in THEMES else None
    if kind in ("deck", "doc"):
        blocks = doc.get("blocks")
        if not isinstance(blocks, list) or len(blocks) > MAX_BLOCKS:
            raise Invalid("blocks")
        seen = set()
        for b in blocks:
            if not isinstance(b, dict):
                raise Invalid("block")
            bid = b.get("id")
            if not isinstance(bid, str) or not re.fullmatch(r"b\d{1,4}", bid) or bid in seen:
                raise Invalid("block id")
            seen.add(bid)
            parts = b.get("parts") or []
            if not isinstance(parts, list) or len(parts) > MAX_PARTS:
                raise Invalid("parts")
            blk = {
                "id": bid,
                "title": _str(b.get("title"), MAX_TITLE),
                "parts": [_part_ok(p) for p in parts],
                "notes": _str(b.get("notes"), MAX_TEXT),
            }
            if b.get("layout") in LAYOUT_NAMES:
                blk["layout"] = b["layout"]
            out["blocks"].append(blk)
        cover = doc.get("cover")
        if isinstance(cover, dict) and (cover.get("query") or cover.get("media")):
            out["cover"] = {"query": _str(cover.get("query"), 120)}
            if isinstance(cover.get("media"), str) and re.fullmatch(r"[a-z]{1,2}\d{1,4}", cover["media"]):
                out["cover"]["media"] = cover["media"]
            if cover.get("off") is True:
                out["cover"]["off"] = True
        if kind == "doc":
            _doc_fields(doc, out)
    elif kind == "code":
        from .code import normalize

        try:
            out["code"] = normalize(doc.get("code"))
        except ValueError as e:
            raise Invalid(str(e)) from None
    else:
        sh = doc.get("sheet")
        if not isinstance(sh, dict) or not isinstance(sh.get("columns"), list) or not isinstance(sh.get("rows"), list):
            raise Invalid("sheet")
        if len(sh["columns"]) > MAX_SHEET_COLS or len(sh["rows"]) > MAX_SHEET_ROWS:
            raise Invalid("sheet too large")
        width = len(sh["columns"])
        out["sheet"] = {"columns": [_str(c, 120) for c in sh["columns"]],
                        "rows": [[_str(c, 1000) for c in (r + [""] * width)[:width]]
                                 for r in sh["rows"] if isinstance(r, list)]}  # fmt: skip
    media = doc.get("media") or {}
    if isinstance(media, dict):
        for mid, m in list(media.items())[:24]:
            if isinstance(mid, str) and re.fullmatch(r"[a-z]{1,2}\d{1,4}", mid) and isinstance(m, dict):
                out["media"][mid] = {
                    "kind": m.get("kind") if m.get("kind") in ("web", "user", "gen") else "user",
                    **{k: _str(m.get(k), 300) for k in ("alt", "credit", "licence", "source", "query")},
                    "w": m.get("w") if isinstance(m.get("w"), int) and 0 < m["w"] < 20000 else 0,
                    "h": m.get("h") if isinstance(m.get("h"), int) and 0 < m["h"] < 20000 else 0,
                }
    nxt = doc.get("_next")
    out["_next"] = nxt if isinstance(nxt, int) and 0 < nxt < 100_000 else len(out["blocks"]) + 1
    if out["blocks"]:
        top = max(int(b["id"][1:]) for b in out["blocks"])
        out["_next"] = max(out["_next"], top + 1)
    return out


def _doc_fields(doc: dict, out: dict) -> None:
    """The fields of a Word-like document: its template, author, recipient (letters), date and footnotes."""
    from . import templates

    tpl = templates.of(doc.get("template"))
    if tpl:
        out["template"] = tpl
    for key, n in (("author", 120), ("recipient", 300), ("date", 40)):
        if doc.get(key):
            out[key] = _str(doc.get(key), n)
    notes = doc.get("footnotes")
    if isinstance(notes, list):
        clean = [{"n": _str(x.get("n"), 8), "text": _str(x.get("text"), 600)}
                 for x in notes[:MAX_FOOTNOTES] if isinstance(x, dict) and x.get("text")]  # fmt: skip
        if clean:
            out["footnotes"] = clean


def footnote_order(doc: dict) -> list[dict]:
    """The footnotes as numbered on the page: by first call in the text (blocks in order), then the ones never
    called. [{'key', 'n' (1, 2…), 'text'}]. The preview and the .docx number them the same way."""
    defs = {str(x.get("n")): x.get("text") or "" for x in doc.get("footnotes") or []}
    order: list[str] = []
    for b in doc.get("blocks") or []:
        for p in b.get("parts") or []:
            texts = [p.get("text") or ""] + [str(i) for i in p.get("items") or [] if isinstance(i, str)]
            texts += [str(c) for r in p.get("rows") or [] for c in r if isinstance(c, str)]
            for t in texts:
                for m in FOOTNOTE_REF.finditer(t):
                    if m.group(1) in defs and m.group(1) not in order:
                        order.append(m.group(1))
    order += [k for k in defs if k not in order]
    return [{"key": k, "n": i, "text": defs[k]} for i, k in enumerate(order, 1)]


def clone(doc: dict) -> dict:
    return copy.deepcopy(doc)
