"""The canvas document to .pptx, .docx and .xlsx, through the office engine (same themes, layouts, pictures and
charts as the files Bird makes in the chat). No model call. The export follows the canvas: no agenda or closing
slide is added that the canvas does not show, and each picture goes where the canvas put it.
"""

from __future__ import annotations

import base64
import binascii
import re
import tempfile
from pathlib import Path

from birds.harness import office_media as om

from . import dsl, sheetfx

MIME = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class ExportError(ValueError):
    pass


def media_list(doc: dict, data: dict[str, str]) -> list[om.Media]:
    """The pictures the document uses, rebuilt from the bytes the browser holds (base64), re-encoded and checked.
    A web picture without its credit and licence is left out (never placed uncredited)."""
    out: list[om.Media] = []
    used = {p.get("media") for b in doc.get("blocks") or [] for p in b.get("parts") or [] if p.get("t") == "image"}
    for mid, meta in (doc.get("media") or {}).items():
        if mid not in used or mid not in data:
            continue
        try:
            raw = base64.b64decode(data[mid], validate=True)
        except (binascii.Error, ValueError):
            raise ExportError("a picture is not valid base64") from None
        kind = meta.get("kind") if meta.get("kind") in ("web", "user") else "user"
        try:
            m = om.prepare(
                raw, mid, kind, alt=str(meta.get("alt") or "")[:160], title=str(meta.get("title") or "")[:120]
            )
        except om.ImageError:
            continue
        m.credit, m.licence, m.source = (str(meta.get(k) or "")[:300] for k in ("credit", "licence", "source"))
        if kind == "web" and not (m.credit and m.licence):
            continue
        out.append(m)
    return om.budget(out)


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace(".", ",")


def _kpi_bullet(k: dict) -> str:
    label, value, delta = k.get("label") or "", k.get("value") or "", k.get("delta") or ""
    s = f"{label} : {value}" if label else value
    return s + (f" ({delta})" if delta else "")


def primary(parts: list[dict]) -> dict | None:
    """The part that gives a slide its look (the canvas draws the same): chart, table, timeline, kpi, quote, code,
    then a picture beside the text; None for a text slide."""
    for t in ("chart", "table", "timeline", "kpi", "quote", "code"):
        p = next((x for x in parts if x.get("t") == t), None)
        if p:
            return p
    return None


def _text_lines(parts: list[dict]) -> list[str]:
    out = []
    for p in parts:
        t = p.get("t")
        if t == "list":
            out += [x for x in p.get("items") or [] if str(x).strip()]
        elif t in ("text", "callout", "heading"):
            out.append(p.get("text") or "")
    return [x for x in out if x.strip()]


def deck_args(doc: dict, media_ids: set[str]) -> tuple[list[dict], list[om.Media]]:
    """(slides for office_deck.build, chart media): one slide per block, its look decided by its main part."""
    slides, charts = [], []
    for k, b in enumerate(doc.get("blocks") or [], 1):
        parts = b.get("parts") or []
        main = primary(parts)
        img = next((p for p in parts if p.get("t") == "image" and p.get("media") in media_ids), None)
        lines = _text_lines(parts)
        s: dict = {"title": b.get("title") or "", "bullets": [], "notes": b.get("notes") or ""}
        if main is None:
            s["bullets"] = lines
        elif main["t"] == "chart":
            cid = f"c{k}"
            spec = {key: main[key] for key in ("type", "columns", "rows", "unit", "title", "source") if main.get(key)}
            spec.setdefault("title", b.get("title") or "")
            if om.chart_spec_ok(spec):
                charts.append(om.chart_media(spec, cid))
                s["chart"] = cid
            s["bullets"] = lines[:3]
        elif main["t"] == "table":
            rows = main.get("rows") or []
            s["bullets"] = [" | ".join(c or "—" for c in r) for r in rows]
            s["notes"] = "\n".join(x for x in [s["notes"], *lines] if x)
        elif main["t"] == "timeline":
            items = main.get("items") or []
            s["bullets"] = [f"{x.get('when')} : {x.get('what')}" if x.get("when") else x.get("what", "") for x in items]
            if not 3 <= len(items) <= 6 or not all(x.get("when") for x in items):
                s["layout"] = "auto"
            s["notes"] = "\n".join(x for x in [s["notes"], *lines] if x)
        elif main["t"] == "kpi":
            s["bullets"] = [_kpi_bullet(x) for x in main.get("items") or []][:4]
            s["notes"] = "\n".join(x for x in [s["notes"], *lines] if x)
        elif main["t"] == "quote":
            q = f"« {main.get('text', '')} »" + (f" — {main['by']}" if main.get("by") else "")
            s["bullets"] = [q]
            s["notes"] = "\n".join(x for x in [s["notes"], *lines] if x)
        else:  # code: its first lines, as written
            code = [ln for ln in (main.get("text") or "").split("\n") if ln.strip()][:10]
            s["bullets"] = lines[:2] + code
        if img is not None and main is None:
            s["image"] = img["media"]
        elif main is not None or img is None:
            s["image"] = "none"  # the engine places no picture of its own on a slide the canvas shows without one
        if not s["notes"]:
            s.pop("notes")
        slides.append(s)
    return slides, charts


def _md_part(p: dict) -> str:
    t = p.get("t")
    if t == "text":
        return p.get("text") or ""
    if t == "heading":
        return "### " + (p.get("text") or "")
    if t == "list":
        out = []
        for i, it in enumerate(p.get("items") or [], 1):
            lead = f"{i}. " if p.get("ordered") and not it.startswith("  ") else "- "
            out.append(("  - " + it.strip()) if it.startswith("  ") else lead + it.strip())
        return "\n".join(out)
    if t == "kpi":
        return "\n".join(f"- **{k.get('value')}** {k.get('label')}" + (f" ({k['delta']})" if k.get("delta") else "")
                         for k in p.get("items") or [])  # fmt: skip
    if t == "table":
        rows = p.get("rows") or []
        if not rows:
            return ""
        out = ["| " + " | ".join(c or " " for c in rows[0]) + " |", "|" + "---|" * len(rows[0])]
        out += ["| " + " | ".join(c or " " for c in r) + " |" for r in rows[1:]]
        return "\n".join(out)
    if t == "timeline":
        return "\n".join(f"- **{x.get('when')}** : {x.get('what')}" if x.get("when") else f"- {x.get('what')}"
                         for x in p.get("items") or [])  # fmt: skip
    if t == "quote":
        return f"> {p.get('text', '')}" + (f"\n> — {p['by']}" if p.get("by") else "")
    if t == "callout":
        lead = {"warn": "Attention", "ok": "À retenir"}.get(p.get("tone"), "À retenir")
        text = p.get("text") or ""
        return text if re.match(r"^\W{0,3}\w+[^:]{0,30}:", text) else f"{lead} : {text}"
    if t == "code":
        return f"```{p.get('lang', '')}\n{p.get('text', '')}\n```"
    if t == "chart":  # a table of the figures under the chart picture, so the numbers stay readable and copyable
        cols = p.get("columns") or []
        rows = p.get("rows") or []
        out = ["| " + " | ".join(c or " " for c in cols) + " |", "|" + "---|" * len(cols)]
        out += ["| " + " | ".join([str(r[0])] + [_fmt(v) for v in r[1:]]) + " |" for r in rows]
        return "\n".join(out)
    return ""


def doc_args(doc: dict, media_ids: set[str]) -> tuple[list[dict], list[om.Media]]:
    sections, charts = [], []
    for k, b in enumerate(doc.get("blocks") or [], 1):
        figs, text = [], []
        for j, p in enumerate(b.get("parts") or []):
            if p.get("t") == "image":
                if p.get("media") in media_ids:
                    figs.append(p["media"])
                continue
            if p.get("t") == "chart":
                cid = f"c{k}x{j}"[:12]
                spec = {key: p[key] for key in ("type", "columns", "rows", "unit", "title", "source") if p.get(key)}
                spec.setdefault("title", b.get("title") or "")
                if om.chart_spec_ok(spec):
                    charts.append(om.chart_media(spec, cid))
                    figs.append(cid)
            md = _md_part(p)
            if md:
                text.append(md)
        sections.append({"heading": b.get("title") or "", "content": "\n\n".join(text), "figures": figs})
    return sections, charts


def safe_name(title: str, ext: str) -> str:
    base = re.sub(r"[^\w\- ]+", "", str(title or ""), flags=re.UNICODE).strip().replace(" ", "-")[:60] or "bird"
    return f"{base}.{ext}"


def export(doc: dict, fmt: str, media_data: dict[str, str] | None = None) -> tuple[bytes, str, str]:
    """(bytes, mime type, file name). ``doc`` must have gone through ``dsl.validate``."""
    from birds.harness import office, office_deck, office_doc

    kind = doc.get("kind")
    lang = doc.get("lang") or "fr"
    title = doc.get("title") or ("Présentation" if kind == "deck" else "Document")
    with tempfile.TemporaryDirectory(prefix="bird-canvas-") as tmp:
        path = Path(tmp) / f"out.{fmt}"
        if fmt == "pptx" and kind == "deck":
            media = media_list(doc, media_data or {})
            slides, charts = deck_args(doc, {m.id for m in media})
            if not slides:
                raise ExportError("the deck has no slide")
            office_deck.build(path, title, slides, doc.get("subtitle") or "", lang, {}, media=media + charts,
                              theme=doc.get("theme"), sources=[], request="",
                              options={"agenda": False, "closing": False, "cover": "none"})  # fmt: skip
        elif fmt == "docx" and kind == "doc":  # the page the canvas shows: template, numbering, figures, notes
            from . import docx_out

            if not doc.get("blocks"):
                raise ExportError("the document has no section")
            docx_out.build(path, doc, media_list(doc, media_data or {}))
        elif fmt == "docx" and kind == "deck":
            media = media_list(doc, media_data or {})
            sections, charts = doc_args(doc, {m.id for m in media})
            if not sections:
                raise ExportError("the document has no section")
            office_doc.build(path, title, sections, doc.get("subtitle") or "", {}, media=media + charts,
                             theme=doc.get("theme"), sources=[], lang=lang, request="",
                             options={"toc": len(sections) >= 6, "cover": "none"})  # fmt: skip
        elif fmt == "xlsx" and kind == "sheet":
            sh = doc.get("sheet") or {}
            cols = sh.get("columns") or []
            if not cols:
                raise ExportError("the sheet has no column")
            rows = [[sheetfx.to_ooxml(v) for v in row] for row in sh.get("rows") or []]
            office.build_xlsx(path, title, cols, rows, {}, lang)
            cache_values(path)
        else:
            raise ExportError(f"cannot export a {kind} as {fmt}")
        data = path.read_bytes()
    return data, MIME[fmt], safe_name(title, fmt)


def cache_values(path: Path) -> None:
    """Write each formula's value as the cell's cached <v> (file previewers show only that; Excel recalculates on
    opening anyway). A formula beyond the small evaluator keeps no cached value rather than an empty one."""
    import zipfile

    from openpyxl import load_workbook

    from birds.harness import office

    ws = load_workbook(str(path)).active
    values = {}
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("="):
                v = office._evaluate(ws, c.value)
                if isinstance(v, int | float) and not isinstance(v, bool) and abs(v) < 1e300:
                    values[c.coordinate] = repr(v) if isinstance(v, float) else str(v)
    name = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]

    def fill(m: re.Match) -> str:
        v = values.get(m.group(1))
        return m.group(0).replace("<v></v>", f"<v>{v}</v>" if v is not None else "").replace("<v />", "")

    out = path.with_suffix(".tmp")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in items:
            if info.filename == name:
                data = re.sub(r'<c r="([A-Z]{1,3}\d{1,7})"[^>]*><f>[^<]*</f><v(?:></v>| />)</c>', fill,
                              data.decode("utf-8")).encode("utf-8")  # fmt: skip
            z.writestr(info, data)
    out.replace(path)


def validated(doc) -> dict:
    """``dsl.validate`` with the error the endpoint reports."""
    try:
        return dsl.validate(doc)
    except dsl.Invalid as e:
        raise ExportError(f"invalid document: {e}") from None
