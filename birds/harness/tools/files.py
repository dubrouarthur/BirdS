"""read_file (workspace only) and the generators make_slides / make_document / make_sheet."""

from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

from birds.harness.guard import Blocked, ToolError

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml", ".xml", ".html"}
OUT_DIR = "bird_out"


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


def _pdf(p: Path) -> str:
    reader = _need("pypdf", "pypdf").PdfReader(str(p))
    return "\n\n".join(f"[page {i}]\n{(page.extract_text() or '').strip()}" for i, page in enumerate(reader.pages, 1))


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
    return f"File created: {rel} ({summary})"


def make_slides(args: dict, ctx) -> str:
    prs = _need("pptx", "python-pptx").Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[0])
    first.shapes.title.text = args["title"]
    for s in args["slides"]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = s["title"]
        frame = slide.placeholders[1].text_frame
        for i, bullet in enumerate(s["bullets"]):
            (frame.paragraphs[0] if i == 0 else frame.add_paragraph()).text = bullet
    p = _new_path(ctx, args["title"], ".pptx")
    prs.save(str(p))
    return _done(ctx, p, f"title slide + {len(args['slides'])} slides")


def make_document(args: dict, ctx) -> str:
    doc = _need("docx", "python-docx").Document()
    doc.add_heading(args["title"], level=0)
    for s in args["sections"]:
        doc.add_heading(s["heading"], level=1)
        for para in s["content"].split("\n"):
            if para.strip():
                doc.add_paragraph(para.strip())
    p = _new_path(ctx, args["title"], ".docx")
    doc.save(str(p))
    return _done(ctx, p, f"{len(args['sections'])} sections")


def make_sheet(args: dict, ctx) -> str:
    wb = _need("openpyxl", "openpyxl").Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", " ", args["title"])[:31] or "Sheet"
    ws.append(list(args["columns"]))
    for row in args["rows"]:
        ws.append(list(row))
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.data_type = "s"  # model-written cells stay plain text, never formulas
    p = _new_path(ctx, args["title"], ".xlsx")
    wb.save(str(p))
    return _done(ctx, p, f"{len(args['columns'])} columns, {len(args['rows'])} rows")
