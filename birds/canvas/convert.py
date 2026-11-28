"""Other ways into the document model, and the harness's reading of plain bullets.

* ``from_tool``: the trained tools (make_slides, make_document, make_sheet) keep working. Whatever arguments the
  model gave them become a canvas document too, so a turn where the model falls back on its training (a JSON
  tool call instead of the text format) still opens a canvas, and the Mode Agent's decks do as well.
* ``enrich``: a small model writes bullets, not blocks. A slide that is one list of « 2023 : 1,1 M€ » lines is a
  chart; dated steps are a timeline; « « … » — Auteur » is a quotation; 1 to 4 short figures are key-figure tiles;
  « Item : label value, label value » rows are a table. Same rules as the office engine (office_plan), so the
  canvas and the .pptx agree. Nothing is invented: every value comes from the bullets.
"""

from __future__ import annotations

import re

from . import dsl, sheetfx


def _list_items(bullets) -> list[str]:
    out = []
    for b in bullets or []:
        s = str(b if b is not None else "")
        if not s.strip():
            continue
        lvl = 1 if s.startswith(("  ", "\t")) else 0
        out.append(("  " if lvl else "") + dsl._cut(dsl._clean_inline(s), 600))
    return out


def slide_parts(title: str, bullets: list[str]) -> list[dict]:
    """The parts a list of bullets really is (see the module doc); a plain list when it is nothing else."""
    from birds.harness import office, office_plan

    items = [b for b in bullets if str(b).strip()]
    # a bullet that is a picture (« [Albatros en vol](…commons…File:….jpg) », « [Photo : X] ») is an image search,
    # never a line of text with an address in it
    pics = [{"t": "image", "query": dsl._cut(w, 120), "alt": dsl._cut(w, 160), "caption": ""}
            for w in (dsl.image_line(str(b)) for b in items) if w]  # fmt: skip
    if pics:
        items = [b for b in items if not dsl.image_line(str(b))]
        return [*(slide_parts(title, items) if items else []), *pics[:2]]
    if not items:
        return []
    if q := office_plan.quote_of(items):
        return [{"t": "quote", "text": dsl._cut(q[0], 600), "by": dsl._cut(q[1], 120)}]
    if spec := office_plan.series_of(title, items):
        part = {
            "t": "chart",
            "type": spec["type"],
            "unit": spec.get("unit") or "",
            "title": spec.get("title") or "",
            "columns": [str(c) for c in spec["columns"]],
            "rows": spec["rows"][: dsl.MAX_ROWS],
            "source": "",
        }
        rest = [{"t": "text", "text": dsl._cut(office_plan._plain(x), 600)} for x in spec.get("takeaway") or []]
        return [part, *rest]
    if tl := office_plan.timeline_of(items):
        return [{"t": "timeline", "items": [{"when": dsl._cut(w, 40), "what": dsl._cut(x, 300)} for w, x in tl]}]
    if rows := office_plan.table_of(items):
        return [{"t": "table", "rows": [[dsl._cut(c, 300) for c in r] for r in rows][: dsl.MAX_ROWS]}]
    if not any(s.startswith("  ") for s in items) and office.render_kind([str(x) for x in items]) == "kpi":
        tiles = []
        for b in items:
            try:
                big, label, delta = office._kpi_split(str(b))
            except (IndexError, ValueError):
                return [{"t": "list", "items": _list_items(items)[: dsl.MAX_ITEMS], "ordered": False}]
            tiles.append({"value": dsl._cut(big, 40), "label": dsl._cut(label, 120), "delta": dsl._cut(delta, 24)})
        return [{"t": "kpi", "items": tiles[:6]}]
    return [{"t": "list", "items": _list_items(items)[: dsl.MAX_ITEMS], "ordered": False}]


def enrich(doc: dict) -> dict:
    """Read the plain lists of a deck as what they are (in place); a slide with a block already chosen by the
    model, or with more than one list, is left as written."""
    if doc.get("kind") != "deck":
        return doc
    for b in doc.get("blocks") or []:
        parts = b.get("parts") or []
        lists = [p for p in parts if p.get("t") == "list"]
        others = [p for p in parts if p.get("t") not in ("list", "image", "text")]
        if len(lists) != 1 or others or lists[0].get("ordered") and len(lists[0]["items"]) > 6:
            continue
        new = slide_parts(b.get("title") or "", lists[0]["items"])
        if new and new[0]["t"] != "list":
            at = parts.index(lists[0])
            b["parts"] = parts[:at] + new + parts[at + 1 :]
    return doc


_CODE_NAME = re.compile(r"\.(?:html?|css|js|ts|jsx|tsx|py|svg)$", re.I)
_CODE_BODY = re.compile(r"(?is)```\s*(?:html|css|javascript|js|python|py|svg)\b|<!doctype html|<html[\s>]|<script[\s>]")


def _is_code(a: dict) -> bool:
    """A make_document call that is really code: a file name for a title, or sections that are code."""
    text = " ".join(str(s.get("content") or "") for s in (a.get("sections") or []) if isinstance(s, dict))
    return bool(_CODE_NAME.search(str(a.get("title") or "").strip())) or bool(_CODE_BODY.search(text[:20000]))


def from_tool(tool: str, args: dict, lang: str = "fr") -> dict | None:
    """The document a make_slides / make_document / make_sheet call describes (None for anything else)."""
    a = args if isinstance(args, dict) else {}
    if tool == "make_slides":
        doc = dsl.empty("deck", lang)
        for s in (a.get("slides") or [])[: dsl.MAX_BLOCKS]:
            if not isinstance(s, dict):
                continue
            bullets = [str(x) for x in (s.get("bullets") or []) if isinstance(x, str | int | float)]
            doc["blocks"].append({"id": dsl.new_id(doc), "title": dsl._cut(str(s.get("title") or ""), dsl.MAX_TITLE),
                                  "parts": slide_parts(str(s.get("title") or ""), bullets),
                                  "notes": dsl._cut(str(s.get("notes") or ""), dsl.MAX_TEXT)})  # fmt: skip
    elif tool == "make_document" and _is_code(a):
        # code the model put in a « document » (« code moi une mini calculatrice web » → mini-calculatrice.html):
        # the canvas shows it as code with its live preview, never as a one-section report
        from birds.canvas import code as codefiles
        from birds.canvas import turn as cturn

        text = "\n\n".join(str(s.get("content") or "") for s in (a.get("sections") or []) if isinstance(s, dict))
        found = codefiles.parse_files(text)
        name = codefiles.safe_name(str(a.get("title") or ""))
        if found and found.get("files") and len(found["files"]) == 1 and name and "." in name:
            found["files"][0]["name"] = name  # the title the model gave the file (« mini-calculatrice.html »)
        title = re.sub(r"\.(?:html?|css|js|ts|py|svg)$", "", str(a.get("title") or ""), flags=re.I).replace("-", " ")
        doc = cturn.code_doc(found, lang, dsl._cut(title.strip().capitalize(), dsl.MAX_TITLE))
        if doc is None:
            return None
        return doc
    elif tool == "make_document":
        doc = dsl.empty("doc", lang)
        for s in (a.get("sections") or [])[: dsl.MAX_BLOCKS]:
            if not isinstance(s, dict):
                continue
            lines = str(s.get("content") or "").replace("\r\n", "\n").split("\n")
            parts = dsl._content_parts(lines, [])[: dsl.MAX_PARTS]
            doc["blocks"].append({"id": dsl.new_id(doc), "title": dsl._cut(str(s.get("heading") or ""), dsl.MAX_TITLE),
                                  "parts": parts, "notes": ""})  # fmt: skip
    elif tool == "make_sheet":
        doc = dsl.empty("sheet", lang)
        cols = [dsl._cut(str(c), 120) for c in (a.get("columns") or [])[: dsl.MAX_SHEET_COLS]]
        rows = []
        for r in (a.get("rows") or [])[: dsl.MAX_SHEET_ROWS]:
            if isinstance(r, list):
                # the file's formulas count the header as row 1, the panel's A1 is the first data row
                cells = ["" if c is None else sheetfx.from_ooxml(str(c)) for c in r][: len(cols)]
                rows.append(cells + [""] * (len(cols) - len(cells)))
        doc["sheet"] = {"columns": cols, "rows": rows}
        doc.pop("blocks", None)
    else:
        return None
    doc["title"] = dsl._cut(str(a.get("title") or ""), dsl.MAX_TITLE)
    doc["subtitle"] = dsl._cut(str(a.get("subtitle") or ""), dsl.MAX_TITLE)
    return doc


def sheet_from_table(text: str, title: str = "", lang: str = "fr") -> dict | None:
    """The first Markdown table of a text as a sheet (« Ouvrir en tableur » on an answer's table)."""
    lines = str(text or "").split("\n")
    rows = dsl.table_rows([ln for ln in lines if "|" in ln])
    if len(rows) < 2:
        return None
    doc = dsl.empty("sheet", lang)
    doc.pop("blocks", None)
    doc["title"] = title
    doc["sheet"] = {"columns": rows[0], "rows": rows[1:]}
    return doc


def subject(words: str) -> str:
    """A title from the request when the model gave none: « fais une présentation sur le télétravail en 2026 »
    -> 'Le télétravail en 2026'."""
    m = re.search(r"\b(?:sur|about|on|concernant|à propos d[eu]|de|pour)\s+(?P<s>[^.?!:\n]{3,90})", words or "", re.I)
    if not m:
        return ""
    s = re.split(r"\s+(?:avec|with|en \d+ (?:slides?|diapos?)|de \d+ (?:slides?|diapos?)|pour (?:lundi|demain|le)|,)",
                 m.group("s"))[0]  # fmt: skip
    s = s.strip(" ,;")
    return s[:1].upper() + s[1:] if s else ""


def from_json_text(text: str, lang: str = "fr") -> dict | None:
    """A small model sometimes writes the trained tool's arguments as JSON text instead of calling the tool
    (« {"title": …, "slides": [...]} », in a fence or not). That JSON, when it is one, becomes the document."""
    import json

    src = str(text or "")
    start, end = src.find("{"), src.rfind("}")
    if start < 0 or end <= start or not re.search(r'"(?:slides|sections)"\s*:', src):
        return None
    try:
        args = json.loads(src[start : end + 1])
    except ValueError:
        return None
    if not isinstance(args, dict):
        return None
    if isinstance(args.get("arguments"), dict):  # {"name": "make_slides", "arguments": {...}}
        args = args["arguments"]
    tool = "make_slides" if isinstance(args.get("slides"), list) else "make_document"
    if tool == "make_document" and not isinstance(args.get("sections"), list):
        return None
    doc = from_tool(tool, args, lang)
    return doc if doc and doc.get("blocks") else None
