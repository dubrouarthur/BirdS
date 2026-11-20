"""Automatic checks used as data filters and RL rewards.

numbers_check: does an answer contain the expected figures (FR or EN formatting)?
It is the guard that rejects any teacher answer with a wrong or missing number.
Convention: generated figures carry at most 2 decimals, so a separator followed by
exactly 3 digits is read as a thousands separator ("1,234" -> 1234, "1.234" -> 1234).
"""

from __future__ import annotations

import math
import re

_SEP = "   .,"
_NUM_RE = re.compile(
    r"(?<![\d.,])[−\-–]?"
    r"(?:\d{1,3}(?:["
    + _SEP
    + r"]\d{3}(?!\d))+|\d+)"  # integer part, optional thousands groups
    r"(?:[.,]\d{1,2}(?!\d))?"  # decimal part (max 2 digits)
)


def _parse(tok: str) -> float:
    t = tok.replace("−", "-").replace("–", "-")
    neg = t.startswith("-")
    t = t.lstrip("-")
    for sp in (" ", " ", " "):
        t = t.replace(sp, "")
    # the last separator followed by 1-2 digits is the decimal mark; every other separator is a thousands mark
    m = re.search(r"[.,](\d{1,2})$", t)
    if m:
        int_part = re.sub(r"[.,]", "", t[: m.start()])
        v = float(f"{int_part}.{m.group(1)}")
    else:
        v = float(re.sub(r"[.,]", "", t))
    return -v if neg else v


def extract_numbers(text: str) -> list[float]:
    return [_parse(m.group(0)) for m in _NUM_RE.finditer(text)]


def numbers_check(
    text: str,
    expected: dict[str, float | None],
    rel_tol: float = 0.01,
    abs_tol: float = 0.15,
) -> dict:
    """Fraction of expected values found in `text` (each within tolerance). None/NaN expectations are skipped."""
    found = extract_numbers(text)
    missing, checked = [], 0
    for name, want in expected.items():
        if want is None or (isinstance(want, float) and math.isnan(want)):
            continue
        checked += 1
        if not any(
            math.isclose(v, want, rel_tol=rel_tol, abs_tol=abs_tol) for v in found
        ):
            missing.append(name)
    return {
        "score": 1.0 if checked == 0 else (checked - len(missing)) / checked,
        "missing": missing,
        "checked": checked,
    }
