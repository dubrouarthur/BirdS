"""Reading a table from a CSV / TSV / XLSX file or from text (a pasted Markdown or tab-separated table).

Messy files are the rule: a French CSV separated by ``;`` with decimal commas, a BOM, a title line and blank lines
above the header, a trailing « Total » row, an Excel sheet whose header spans two merged rows (« 2024 » over
« T1 T2 T3 T4 »). Everything here is deterministic and bounded (rows, columns, characters, zip size).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from birds.harness.analysis.cells import is_gap, plain

MAX_ROWS = 50_000
MAX_COLS = 60
MAX_CELL = 400
TABULAR = (".csv", ".tsv", ".tab", ".xlsx", ".xlsm")
_TOTAL = re.compile(r"^\s*(?:total|totaux|sous-total|somme|ensemble|grand total|sum)\b", re.I)


class TableError(ValueError):
    pass


@dataclass
class Table:
    """Header names and raw rows (strings, numbers, datetimes or None), all rows of the same width."""

    columns: list[str]
    rows: list[list]
    name: str = ""
    meta: dict = field(default_factory=dict)  # source, sheet, separator, encoding, skipped, total_row, truncated

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.rows), len(self.columns)


# ---------------------------------------------------------------- text


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc), "utf-8"
        except UnicodeDecodeError:
            continue
    try:
        return raw.decode("cp1252"), "windows-1252"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def sniff_separator(lines: list[str]) -> str:
    """The separator that splits the most lines into the same number (> 1) of fields: ``;`` ``,`` tab or ``|``."""
    best, score = ",", -1.0
    sample = [ln for ln in lines if ln.strip()][:40]
    for sep in ("\t", ";", ",", "|"):
        counts = []
        for ln in sample:
            try:
                counts.append(len(next(csv.reader([ln], delimiter=sep))))
            except (csv.Error, StopIteration):
                counts.append(1)
        if not counts:
            continue
        common = max(set(counts), key=counts.count)
        if common < 2:
            continue
        share = counts.count(common) / len(counts)
        s = share * 10 + min(common, 12) * 0.1 + (0.05 if sep in ";\t" else 0)
        if s > score:
            best, score = sep, s
    return best


def _markdown_rows(lines: list[str]) -> list[list[str]] | None:
    rows = [ln for ln in lines if ln.strip().startswith("|")]
    if len(rows) < 2:
        return None
    out = []
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        out.append([re.sub(r"^\*\*(.*)\*\*$", r"\1", c) for c in cells])
    return out


def read_text_table(text: str, name: str = "table.csv") -> Table:
    """A table from text: CSV/TSV (separator sniffed) or a Markdown table."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    md = _markdown_rows(lines)
    if md:
        return _shape(md, name, {"source": "markdown"})
    sep = "\t" if name.lower().endswith((".tsv", ".tab")) else sniff_separator(lines)
    reader = csv.reader(io.StringIO(text), delimiter=sep)
    rows = []
    try:
        for i, r in enumerate(reader):
            if i > MAX_ROWS + 50:
                break
            rows.append(r)
    except csv.Error as e:
        raise TableError(f"this CSV cannot be read ({e})") from None
    return _shape(rows, name, {"source": "csv", "separator": {"\t": "tab"}.get(sep, sep)})


# ---------------------------------------------------------------- xlsx


def _xlsx_rows(path: Path) -> tuple[list[list], dict]:
    from birds.harness.tools.files import _check_zip, _need

    _check_zip(path)
    openpyxl = _need("openpyxl", "openpyxl")
    # not read_only: merged header cells are only known in the full mode (the zip is size-checked above)
    wb = openpyxl.load_workbook(str(path), data_only=True)
    try:
        best, best_n = None, -1
        for ws in wb.worksheets:
            n = sum(1 for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 400), values_only=True)
                    if sum(c is not None for c in row) >= 2)  # fmt: skip
            if n > best_n:
                best, best_n = ws, n
        if best is None:
            raise TableError("this workbook has no sheet")
        ws = best
        grid: list[list] = []
        for row in ws.iter_rows(values_only=True, max_row=min(ws.max_row, MAX_ROWS + 50)):
            grid.append(list(row[:MAX_COLS]))
        for rng in ws.merged_cells.ranges:  # a merged cell's value fills the whole range (headers spanning)
            r0, c0, r1, c1 = rng.min_row - 1, rng.min_col - 1, rng.max_row - 1, rng.max_col - 1
            if r0 >= len(grid) or c0 >= MAX_COLS:
                continue
            v = grid[r0][c0] if c0 < len(grid[r0]) else None
            for r in range(r0, min(r1, len(grid) - 1) + 1):
                for c in range(c0, min(c1, MAX_COLS - 1) + 1):
                    while len(grid[r]) <= c:
                        grid[r].append(None)
                    grid[r][c] = v
        return grid, {"source": "xlsx", "sheet": ws.title, "sheets": [w.title for w in wb.worksheets]}
    finally:
        wb.close()


# ---------------------------------------------------------------- shaping


def _texty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, int | float | dt.date):
        return False
    s = str(v).strip()
    return bool(s) and not re.fullmatch(r"[-+−(]?[\d\s.,  ]+\)?\s*(%|€|\$|k€|M€)?", s)


def _header_rows(grid: list[list]) -> tuple[int, int]:
    """(index of the first header row, number of header rows: 1 or 2)."""
    width = max((sum(not is_gap(c) for c in r) for r in grid[:30]), default=0)
    start = 0
    for i, r in enumerate(grid[:30]):
        filled = sum(not is_gap(c) for c in r)
        # the header: the first wide-enough row made mostly of text (a title line above it has one cell)
        if filled >= max(2, width * 0.5) and sum(_texty(c) for c in r) >= filled * 0.6:
            start = i
            break
    n = 1
    if start + 2 < len(grid):
        a, b, c = grid[start], grid[start + 1], grid[start + 2]
        b_text = sum(_texty(x) for x in b)
        b_fill = sum(not is_gap(x) for x in b)
        c_text = sum(_texty(x) for x in c)
        c_fill = max(1, sum(not is_gap(x) for x in c))
        repeats = len({str(x) for x in a if not is_gap(x)}) < sum(not is_gap(x) for x in a)
        gaps_a = sum(is_gap(x) for x in a[: len(b)])
        # two header rows: the second is text too, and the row after it is data (« 2024 | 2024 » over « T1 | T2 »)
        if b_fill >= 2 and b_text >= b_fill * 0.8 and c_text < c_fill * 0.6 and (repeats or gaps_a):
            n = 2
    if n == 1 and start > 0:
        # « 2024 | 2024 | 2025 » (years, merged) above « Prévu | Réel | Prévu »: the upper row was not text enough
        # to be taken for the header, but it is its first line
        p = grid[start - 1]
        p_fill = sum(not is_gap(x) for x in p)
        p_repeats = len({str(x) for x in p if not is_gap(x)}) < p_fill
        p_years = all(re.fullmatch(r"(?:19|20)\d\d", str(x).strip()) or _texty(x) for x in p if not is_gap(x))
        if p_fill >= 2 and p_repeats and p_years:
            start, n = start - 1, 2
    return start, n


def _name(parts: list, j: int) -> str:
    words = []
    for p in parts:
        s = " ".join(str(p).split()) if not is_gap(p) else ""
        if isinstance(p, dt.datetime | dt.date):
            s = p.strftime("%d/%m/%Y")
        if isinstance(p, float) and p.is_integer():
            s = str(int(p))
        if s and s not in words:
            words.append(s)
    return " ".join(words)[:80] or f"Colonne {j + 1}"


def _shape(grid: list[list], name: str, meta: dict) -> Table:
    grid = [[(c.strip()[:MAX_CELL] if isinstance(c, str) else c) for c in r[:MAX_COLS]] for r in grid]
    grid = [r for r in grid if any(not is_gap(c) for c in r)]  # blank lines
    if not grid:
        raise TableError("this table is empty")
    start, n = _header_rows(grid)
    skipped = start
    head = grid[start : start + n]
    body = grid[start + n :]
    width = max(len(r) for r in [*head, *body[:2000]])
    head = [r + [None] * (width - len(r)) for r in head]
    if n == 2:  # « 2024 » merged over « T1 T2 »: the upper name runs on to the right until the next one
        top = head[0]
        last = None
        for j in range(width):
            if not is_gap(top[j]):
                last = top[j]
            elif last is not None and not is_gap(head[1][j]):
                top[j] = last
    columns = [_name([r[j] for r in head], j) for j in range(width)]
    seen: dict[str, int] = {}
    for j, c in enumerate(columns):  # unique names: « Montant », « Montant (2) »
        k = plain(c)
        if k in seen:
            seen[k] += 1
            columns[j] = f"{c} ({seen[k]})"
        else:
            seen[k] = 1
    keep = [j for j in range(width) if any(j < len(r) and not is_gap(r[j]) for r in body) or
            not columns[j].startswith("Colonne ")]  # fmt: skip
    columns = [columns[j] for j in keep]
    rows = [[(r[j] if j < len(r) else None) for j in keep] for r in body]
    rows = [r for r in rows if not all(is_gap(c) for c in r)]
    # rows repeating the header (a CSV made by pasting several exports together) are dropped
    head_key = [plain(c) for c in columns]
    rows = [r for r in rows if [plain(c) if c is not None else "" for c in r] != head_key]
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    total_row = None
    if rows and any(isinstance(c, str) and _TOTAL.match(c) for c in rows[-1][:2]):
        total_row = rows.pop()  # a Total row would double every sum: kept aside, shown in the table's footer
    if not rows:
        raise TableError("this table has a header but no data rows")
    meta = {**meta, "skipped": skipped, "header_rows": n, "truncated": truncated,
            "total_row": total_row is not None}  # fmt: skip
    t = Table(columns, rows, name, meta)
    t.meta["total_cells"] = total_row
    return t


def read_table(path: Path | str, name: str | None = None) -> Table:
    """A table from a file on disk (CSV, TSV, XLSX) or a text file holding a Markdown table."""
    p = Path(path)
    suffix = p.suffix.lower()
    name = name or p.name
    if suffix in (".xlsx", ".xlsm"):
        grid, meta = _xlsx_rows(p)
        return _shape(grid, name, meta)
    raw = p.read_bytes()[:20_000_000]
    text, enc = _decode(raw)
    t = read_text_table(text, name)
    t.meta["encoding"] = enc
    return t


def is_tabular(name: str) -> bool:
    return str(name).lower().endswith(TABULAR)


def looks_like_table(text: str) -> bool:
    """Pasted text that is a table: a Markdown table, or at least 3 lines split alike by tab or ';'."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    if sum(ln.strip().startswith("|") and ln.count("|") >= 3 for ln in lines) >= 3:
        return True
    for sep in ("\t", ";"):
        counts = [ln.count(sep) for ln in lines[:30]]
        common = max(set(counts), key=counts.count)
        if common >= 1 and counts.count(common) >= max(3, 0.8 * len(counts)):
            return True
    return False
