"""The slide layouts of a canvas deck: a catalogue of designed layouts, and the choice of one per slide.

The model writes a TYPED slide (its blocks say what the content is: ``kpi``, ``compare``, ``steps``, ``cards``,
``chart``, ``image``…) and may name a layout (``# Titre {versus}``); the harness picks the layout from the content and
keeps the model's choice only when the content fits it (a « versus » needs two columns, an « image-left » a
picture). The browser (``canvas-layouts.js``) and the .pptx (``deck_pptx.py``) draw the SAME choice: the two
implementations are checked against one fixture (``tests/fixtures/canvas_layouts.json``), so the preview and the
exported file never disagree.

Pure functions, no I/O.
"""

from __future__ import annotations

import re

from . import dsl

# id -> (French name, English name, what it is for) : the catalogue shown in the « Mise en page » menu
CATALOGUE: dict[str, tuple[str, str, str]] = {
    "section": ("Intercalaire", "Section divider", "a slide with a title only, opening a part"),
    "agenda": ("Sommaire", "Agenda", "the parts of the talk, numbered"),
    "statement": ("Message clé", "Statement", "one sentence, large"),
    "bullets": ("Points", "Bullets", "a title and 3 to 6 short points"),
    "columns": ("Deux colonnes", "Two columns", "a long list, in two columns"),
    "figure": ("Chiffre clé", "Key figure", "one giant figure and what it measures"),
    "kpis": ("Chiffres clés", "Key figures", "two to four figure tiles"),
    "versus": ("Face à face", "Versus", "two options side by side, VS"),
    "compare": ("Comparaison", "Comparison", "two or three columns compared"),
    "timeline": ("Frise", "Timeline", "dated steps on a line"),
    "steps": ("Étapes", "Process", "numbered steps of a method"),
    "quote": ("Citation", "Quote", "a quotation and its author"),
    "image-left": ("Image à gauche", "Image left", "a picture beside the text"),
    "image-right": ("Image à droite", "Image right", "the text beside a picture"),
    "image-full": ("Plein cadre", "Full bleed", "one picture, the title over it"),
    "image-grid": ("Galerie", "Image grid", "two to four pictures"),
    "chart": ("Graphique", "Chart", "a chart and its key message"),
    "table": ("Tableau", "Table", "rows and columns"),
    "cards": ("Cartes", "Cards", "three to six cards: a team, pillars, offers"),
    "closing": ("Clôture", "Closing", "the last word, a call to action"),
    "code": ("Code", "Code", "a code sample"),
}
assert tuple(CATALOGUE) == dsl.LAYOUT_NAMES

MAIN = ("chart", "table", "compare", "steps", "cards", "timeline", "kpi", "quote", "code")
TEXT = ("list", "text", "callout", "heading")
_AGENDA = re.compile(r"^\s*(?:sommaire|agenda|programme|au menu|plan de la pr[ée]sentation|ordre du jour|outline|"
                     r"contents|table des mati[èe]res)\b", re.I)  # fmt: skip
_CLOSING = re.compile(r"^\s*(?:merci|thank|questions?\b|conclusion|en conclusion|pour conclure|contact|"
                      r"et maintenant|à vous|a vous|next steps|prochaines? [ée]tapes|passons [àa] l'action|"
                      r"call to action|rejoignez|let's|lan[çc]ons)", re.I)  # fmt: skip


def _parts(b: dict, t: str | tuple) -> list[dict]:
    ts = (t,) if isinstance(t, str) else t
    return [p for p in b.get("parts") or [] if p.get("t") in ts]


def main_part(b: dict) -> dict | None:
    for t in MAIN:
        p = next((x for x in b.get("parts") or [] if x.get("t") == t), None)
        if p:
            return p
    return None


def groups(b: dict) -> list[dict]:
    """Two or three sub-headings each followed by a list, read as columns (« Avant » / « Après »)."""
    out: list[dict] = []
    for p in b.get("parts") or []:
        if p.get("t") == "heading":
            out.append({"title": p.get("text") or "", "items": []})
        elif p.get("t") == "list" and out and not out[-1]["items"]:
            out[-1]["items"] = [x.strip() for x in p.get("items") or [] if x.strip()][:6]
        elif p.get("t") in TEXT and out:
            return []
    return out if 2 <= len(out) <= 3 and all(g["items"] for g in out) else []


def columns_of(b: dict) -> list[dict]:
    p = next(iter(_parts(b, "compare")), None)
    return (p.get("columns") or []) if p else groups(b)


def items_of(b: dict) -> list[dict]:
    """Steps or cards: [{title, text}] from a steps / cards part, a timeline, or a list."""
    p = next(iter(_parts(b, ("steps", "cards"))), None)
    if p:
        return p.get("items") or []
    tl = next(iter(_parts(b, "timeline")), None)
    if tl:
        return [{"title": x.get("when") or "", "text": x.get("what") or ""} for x in tl.get("items") or []]
    out = []
    for p in _parts(b, "list"):
        for it in p.get("items") or []:
            if not it.strip() or it.startswith("  "):
                continue
            m = dsl._CARD.match(it.strip())
            out.append({"title": m.group("title"), "text": m.group("text")} if m else {"title": it.strip(), "text": ""})
    return out[:8]


def _list_items(b: dict) -> list[str]:
    return [x for p in _parts(b, "list") for x in p.get("items") or [] if x.strip()]


def _short_text(b: dict, limit: int) -> bool:
    """The block is one short sentence (a text part, or a list of one item)."""
    text = _parts(b, TEXT)
    if len(text) != 1:
        return False
    p = text[0]
    s = p.get("text") if p.get("t") != "list" else (" ".join(p.get("items") or []) if len(p.get("items") or []) == 1
                                                     else None)  # fmt: skip
    return bool(s) and len(s) <= limit


def fits(b: dict, name: str) -> bool:
    """Can this block be drawn with this layout without losing or inventing anything?"""
    main = main_part(b)
    imgs = _parts(b, "image")
    text = _parts(b, TEXT)
    mt = main.get("t") if main else None
    if name in ("section", "closing"):
        return mt is None and len(text) <= 2 and len(imgs) <= 1
    if name == "statement":
        return mt is None and _short_text(b, 220) and len(imgs) <= 1
    if name == "agenda":
        return mt is None and len(_list_items(b)) >= 2 and not imgs
    if name in ("bullets", "columns"):
        return mt is None and bool(text) and not imgs
    if name == "figure":
        return mt == "kpi" and len(imgs) <= 1
    if name == "kpis":
        return mt == "kpi" and len(main.get("items") or []) >= 2 and not imgs
    if name in ("versus", "compare"):
        cols = columns_of(b)
        return (mt in (None, "compare")) and 2 <= len(cols) <= (2 if name == "versus" else 3) and not imgs
    if name == "steps":
        return (mt in ("steps", "timeline", None)) and 2 <= len(items_of(b)) <= 6 and not imgs
    if name == "cards":
        return (mt in ("cards", "steps", None)) and 2 <= len(items_of(b)) <= 6 and not imgs
    if name == "timeline":
        return mt == "timeline" and not imgs
    if name == "quote":
        return mt == "quote" and len(imgs) <= 1
    if name in ("image-left", "image-right"):
        return mt is None and len(imgs) == 1
    if name == "image-full":
        return mt is None and len(imgs) == 1 and (not text or _short_text(b, 160))
    if name == "image-grid":
        return mt is None and 2 <= len(imgs) <= 4
    if name in ("chart", "table", "code"):
        return mt == name and not imgs
    return False


def pick(b: dict, index: int, total: int) -> str:
    """The layout of block ``b`` (``index`` among ``total`` blocks): the model's choice when the content fits it,
    else the one the content calls for."""
    hint = b.get("layout")
    if hint in CATALOGUE and fits(b, hint):
        return hint
    main = main_part(b)
    imgs = _parts(b, "image")
    title = b.get("title") or ""
    last = total > 1 and index == total - 1
    if main is not None:
        t = main["t"]
        if t == "kpi":
            return "figure" if len(main.get("items") or []) == 1 or imgs else "kpis"
        if t == "compare":
            cols = main.get("columns") or []
            return "versus" if len(cols) == 2 and all(len(c.get("items") or []) <= 4 for c in cols) else "compare"
        if t == "steps":
            return "steps"
        if t == "cards":
            return "cards"
        if t == "timeline":
            return "timeline"
        return t  # chart, table, quote, code
    text = _parts(b, TEXT)
    if len(imgs) >= 2:
        return "image-grid"
    if len(imgs) == 1:
        if not text or _short_text(b, 160):
            return "image-full"
        return "image-right" if index % 2 == 0 else "image-left"
    if not text:
        return "closing" if last else "section"
    if last and _CLOSING.match(title) and len(_list_items(b)) <= 4:
        return "closing"
    if _AGENDA.match(title) and fits(b, "agenda"):
        return "agenda"
    if groups(b):
        return "versus" if len(groups(b)) == 2 else "compare"
    if _short_text(b, 180):
        return "statement"
    items = _list_items(b)
    if len(items) > 6 and all(len(x) <= 90 for x in items):
        return "columns"
    return "bullets"


def compatible(b: dict) -> list[str]:
    """The layouts this block can take (the « Mise en page » menu), the current one first."""
    return [n for n in CATALOGUE if fits(b, n)]


def assign(doc: dict) -> dict:
    """``doc['layouts']``: the layout of every block, by id (what the canvas and the .pptx draw). Returns doc."""
    blocks = doc.get("blocks") or []
    doc["layouts"] = (
        {b["id"]: pick(b, k, len(blocks)) for k, b in enumerate(blocks)} if doc.get("kind") == "deck" else {}
    )
    return doc


def variety(doc: dict) -> dict[str, int]:
    """How many slides of each layout (the cover counted once): the measure of a deck's variety."""
    out: dict[str, int] = {"cover": 1}
    blocks = doc.get("blocks") or []
    for k, b in enumerate(blocks):
        name = pick(b, k, len(blocks))
        out[name] = out.get(name, 0) + 1
    return out
