"""read_file (workspace only) and the generators make_slides / make_document / make_sheet."""

from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

from birds.harness.guard import Blocked, ToolError

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml", ".xml", ".html"}
OUT_DIR = "bird_out"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"}


def safe_path(workspace: Path, path: str) -> Path:
    """Resolve `path` inside the workspace. Symlinks are followed BEFORE the check, so a link pointing out is refused."""
    root = workspace.resolve()
    p = Path(path)
    full = (p if p.is_absolute() else root / p).resolve()
    if full != root and root not in full.parents:
        raise Blocked("path is outside the workspace")
    return full


def _need(module: str, package: str):
    try:
        return __import__(module)
    except ImportError:
        raise ToolError(f"this file type needs the '{package}' package, which is not installed") from None


SCANNED_CHARS = 40  # a PDF page with less extractable text than this is treated as a scanned image


def pdf_pages(p: Path) -> list[str]:
    """The text layer of each page ('' for a scanned page)."""
    reader = _need("pypdf", "pypdf").PdfReader(str(p))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def pdf_scanned(pages: list[str]) -> list[int]:
    """1-based numbers of the pages that carry (almost) no text: scans or photos to be read as images."""
    return [i for i, t in enumerate(pages, 1) if len(t) < SCANNED_CHARS]


def pdf_sidecar(p: Path) -> Path:
    """Where the transcriptions of a PDF's scanned pages are kept for read_file (written by the web backend)."""
    return p.with_name(f".{p.name}.pages.json")


def render_pdf_page(p: Path, number: int, max_side: int = 1568) -> str:
    """One page as a JPEG data URL for the vision model (pypdfium2; long side ``max_side`` px)."""
    import base64
    import io

    pdfium = _need("pypdfium2", "pypdfium2")
    doc = pdfium.PdfDocument(str(p))
    try:
        page = doc[number - 1]
        w, h = page.get_size()
        image = page.render(scale=max_side / max(w, h)).to_pil().convert("RGB")
    finally:
        doc.close()
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _pdf(p: Path) -> str:
    import json

    pages = pdf_pages(p)
    side = pdf_sidecar(p)
    read = json.loads(side.read_text(encoding="utf-8")) if side.is_file() else {}
    parts, unknown = [], []
    for i, text in enumerate(pages, 1):
        if len(text) >= SCANNED_CHARS:
            parts.append(f"[page {i}]\n{text}")
        elif read.get(str(i)):
            parts.append(f"[page {i}, scanned, read as an image]\n{read[str(i)].strip()}")
        else:
            unknown.append(i)
            parts.append(f"[page {i}: scanned image, its text could not be read]")
    if unknown:
        parts.insert(
            0,
            f"Note: {len(unknown)} page(s) of this PDF ({', '.join(map(str, unknown[:20]))}) are images without a "
            "text layer and could not be read. Their content is unknown: say so, never guess or invent it.",
        )
    return "\n\n".join(parts)


def _docx(p: Path) -> str:
    doc = _need("docx", "python-docx").Document(str(p))
    parts = [
        ("#" * int(par.style.name[-1]) + " " if re.fullmatch(r"Heading \d", par.style.name or "") else "") + par.text
        for par in doc.paragraphs
        if par.text.strip()
    ]
    for table in doc.tables:
        parts += [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
    return "\n".join(parts)


def _xlsx(p: Path) -> str:
    wb = _need("openpyxl", "openpyxl").load_workbook(str(p), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"[sheet {ws.title}]")
        for row in ws.iter_rows(values_only=True):
            if any(c is not None for c in row):
                parts.append(" | ".join("" if c is None else str(c) for c in row))
    return "\n".join(parts)


def _pptx(p: Path) -> str:
    prs = _need("pptx", "python-pptx").Presentation(str(p))
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        parts.append(f"[slide {i}]")
        parts += [sh.text_frame.text.strip() for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
    return "\n".join(parts)


READERS = {".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}


def read_file(args: dict, ctx) -> str:
    p = safe_path(ctx.workspace, args["path"])
    if p.suffix.lower() in IMAGE_SUFFIXES and not p.is_file():
        side = p.with_name(p.name + ".txt")  # an image sent with the message: what the model read in it
        if side.is_file():
            return side.read_text(encoding="utf-8").strip() or "(the image has no readable text)"
    if not p.is_file():
        raise ToolError(f"file not found in the workspace: {args['path']}")
    size, suffix = p.stat().st_size, p.suffix.lower()
    if size > ctx.config.max_file_bytes:
        raise ToolError(f"file too large ({size} bytes; limit {ctx.config.max_file_bytes})")
    if suffix in READERS:
        try:
            text = READERS[suffix](p)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"could not read this {suffix} file ({type(e).__name__})") from e
    elif suffix in TEXT_SUFFIXES or not suffix:
        text = p.read_bytes().decode("utf-8", errors="replace")
    else:
        raise ToolError(f"unsupported file type: {suffix}")
    return text.strip() or "(the file has no extractable text)"


def _new_path(ctx, title: str, suffix: str) -> Path:
    """A fresh file under <workspace>/bird_out; the name is derived from the title but never chosen by the model."""
    slug = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:40] or "bird"
    out = ctx.workspace.resolve() / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    stamp, n = time.strftime("%Y%m%d-%H%M%S"), 0
    while (p := out / f"{slug}-{stamp}{f'-{n}' if n else ''}{suffix}").exists():
        n += 1
    return p


def _done(ctx, p: Path, summary: str) -> str:
    rel = str(p.relative_to(ctx.workspace.resolve()))
    ctx.files.append(rel)
    return f"File created and shown to the user as a download card: {p.name} ({summary}). Do not write its path."


def make_slides(args: dict, ctx) -> str:
    _need("pptx", "python-pptx")
    from birds.harness.office import KEY_FIGURES, build_pptx, figure_bullets, missing_figures, plain

    slides = [dict(s) for s in args["slides"]]
    # A small model drops figures the user gave ("CA 1,2 M€ (+8 %), marge 31 %") and then says they are in the
    # deck. Every figure of the request that is nowhere in the slides goes on a key-figures slide, first.
    missing = missing_figures(getattr(ctx, "request", "") or "", slides, args["title"])
    added = ""
    if missing:
        lang = getattr(ctx, "lang", "fr")
        slides.insert(0, {"title": KEY_FIGURES[lang if lang in KEY_FIGURES else "fr"],
                          "bullets": figure_bullets(ctx.request, missing)})
        added = f" A 'key figures' slide was added first with figures from the request that were missing: " \
                f"{', '.join(missing)}."
    p = _new_path(ctx, args["title"], ".pptx")
    n = build_pptx(p, args["title"], slides, args.get("subtitle") or "")
    extra = f", {n - 1} after splitting long slides" if n - 1 != len(slides) else ""
    titles = "; ".join(f"{i}. {plain(str(s.get('title') or ''))[:60]}" for i, s in enumerate(slides, 2))
    return _done(ctx, p, f"title slide + {len(slides)} slides{extra}") + (
        f"\nSlides: {titles}.{added}\nDescribe the deck from this list only: do not claim content that is not in it."
    )


def make_document(args: dict, ctx) -> str:
    _need("docx", "python-docx")
    from birds.harness.office import build_docx

    p = _new_path(ctx, args["title"], ".docx")
    stats = build_docx(p, args["title"], args["sections"], args.get("subtitle") or "")
    tables = f", {stats['tables']} table(s)" if stats["tables"] else ""
    return _done(ctx, p, f"{len(args['sections'])} sections{tables}")


def make_sheet(args: dict, ctx) -> str:
    _need("openpyxl", "openpyxl")
    from birds.harness.office import build_xlsx

    p = _new_path(ctx, args["title"], ".xlsx")
    stats = build_xlsx(p, args["title"], args["columns"], args["rows"])
    extra = f", {stats['formulas']} formula(s)" if stats["formulas"] else ""
    if stats["blocked_formulas"]:
        extra += f", {stats['blocked_formulas']} formula(s) reaching outside the file written as text"
    return _done(ctx, p, f"{len(args['columns'])} columns, {len(args['rows'])} rows{extra}")
