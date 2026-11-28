"""Check a .docx downloaded from the canvas against the page the preview showed (tests/e2e/canvas_docs.spec.js
writes the preview's headings next to the file as <file>.json): same headings in the same order, with their
numbers, at the same levels; and what the file holds (tables, pictures, captions, notes, page numbers).

    .venv/bin/python scripts/check_docx.py /tmp/shots/docs-desktop-light.docx [--render out_dir]

``--render`` also converts it with LibreOffice (when installed) and writes one PNG per page, to look at.
Exit 1 on a difference.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--render", default="")
    args = ap.parse_args()
    import docx

    path = Path(args.docx)
    want = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))["headings"]
    d = docx.Document(str(path))
    heads = [p.text.strip() for p in d.paragraphs if p.style.name.startswith("Heading") and p.text.strip()]
    heads = [h for h in heads if h != "Notes"]
    norm = [re.sub(r"\s+", " ", h) for h in want if h != "Notes"]
    caps = [p.text for p in d.paragraphs if p.style.name == "Caption"]
    footer = d.sections[0].footer._element.xml
    report = {
        "headings_match": heads == norm,
        "headings": heads,
        "preview": norm,
        "tables": len(d.tables),
        "pictures": len(d.inline_shapes),
        "captions": caps,
        "notes": [p.text for p in d.paragraphs if p.style.name == "Bird Source"],
        "page_numbers": 'w:instr="PAGE"' in footer,
    }
    if args.render and shutil.which("soffice"):
        out = Path(args.render)
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(out), str(path)],
                       check=True, capture_output=True, timeout=180)  # fmt: skip
        pdf = out / (path.stem + ".pdf")
        if shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-r", "50", "-png", str(pdf), str(out / path.stem)], check=True, timeout=180)
        report["rendered"] = sorted(str(p) for p in out.glob(path.stem + "*.png"))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["headings_match"] and report["page_numbers"] else 1


if __name__ == "__main__":
    sys.exit(main())
