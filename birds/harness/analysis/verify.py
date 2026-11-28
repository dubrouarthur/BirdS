"""Every number in an answer about a table must come from the computed result (or the user's own words).

The model may round (« 243 706,63 € » -> « 243 707 € », « environ 244 k€ », « 0,24 M€ ») and quote shares or a change
it was given; it may not write a figure that is nowhere. ``check_numbers`` returns the numbers it cannot trace.
"""

from __future__ import annotations

import math
import re

from birds.harness.analysis.cells import parse_number

_NUM = re.compile(
    r"(?<![\w.,])[-+−]?\d[\d    ]*(?:[.,]\d+)*(?:\s?(?:k|K|M|Md|Mds|Mrd|bn|millions?|milliards?|"
    r"milliers?|thousand|billion)\b)?(?:\s?(?:%|€|\$|£|k€|M€))?"
)
_SCALE_WORD = {"millions": 1e6, "million": 1e6, "milliards": 1e9, "milliard": 1e9, "milliers": 1e3, "millier": 1e3,
               "thousand": 1e3, "billion": 1e9}  # fmt: skip


def numbers_in(text: str) -> list[tuple[float, str]]:
    """(value, as written) of every number in a text. « 1,2 M€ » -> 1 200 000; « 12,5 % » -> 12.5; « 2024 » -> 2024."""
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).strip()
        s = raw.replace(" ", " ").replace(" ", " ").replace(" ", " ").strip()
        scale = 1.0
        for w, k in _SCALE_WORD.items():
            if s.endswith(w):
                s, scale = s[: -len(w)].strip(), k
                break
        # « 1 234,5 » (French) or « 1,234.5 » (English): the last mark followed by 1-2 digits is the decimal one
        style = (
            ","
            if re.search(r",\d{1,2}(?:\D|$)", s) or ("," in s and "." not in s and not re.search(r",\d{3}\b", s))
            else "."
        )
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?.*", s):
            style = "."
        try:
            v, _ = parse_number(s, style)
        except ValueError:
            try:
                v, _ = parse_number(s.split(" ")[0], style)
            except ValueError:
                continue
        if v is None:
            continue
        out.append((float(v) * scale, raw))
    return out


def _decimals(raw: str) -> int:
    m = re.search(r"[.,](\d+)(?!.*[.,]\d)", raw.replace(" ", ""))
    return len(m.group(1)) if m else 0


def _tolerance(value: float, raw: str) -> float:
    """How far a written number may be from the true one: half a unit of its last written digit, or 2 % of it when it
    is scaled (« 1,2 M€ », « 244 k€ »), at least the rounding to a whole number."""
    d = _decimals(raw)
    tol = 0.5 * 10 ** (-d)
    if re.search(_SCALED, raw):
        tol = max(tol * _scale_of(raw), abs(value) * 0.02)
    elif d == 0:
        # « environ 35 000 € » for 34 812: rounded to its last significant (non-zero) digit, as « 35 k€ » is
        digits = re.sub(r"\D", "", raw)
        zeros = len(digits) - len(digits.rstrip("0"))
        if zeros and digits.strip("0"):
            tol = 0.5 * 10**zeros
    return max(tol, 1e-9)


_SCALED = r"\d\s?(?:k|K|M|Md|Mds|Mrd|bn|millions?|milliards?|milliers?|thousand|billion)\b"


def _bare(raw: str) -> bool:
    """A number with no unit (%, a currency, a scale) and no decimals: may be a count or a year."""
    return not re.search(r"[%€$£]", raw) and not re.search(_SCALED, raw) and _decimals(raw) == 0


def _scale_of(raw: str) -> float:
    if re.search(r"\b(?:Md|Mds|Mrd|bn|milliards?|billion)\b", raw):
        return 1e9
    if re.search(r"\d\s?(?:M|millions?)\b", raw):
        return 1e6
    if re.search(r"\d\s?(?:k|K|milliers?|thousand)\b", raw):
        return 1e3
    return 1.0


def check_numbers(answer: str, allowed, request: str = "", extra_ok: int = 12) -> list[str]:
    """The numbers of ``answer`` (as written) found neither in ``allowed`` (with rounding), nor in ``request``.
    Small whole numbers up to ``extra_ok`` (« les 3 premiers », « 2 régions ») and years are fine when written bare:
    « 8 % », « 12 € » or « 2 050 € » must be found like any other figure."""
    pool = sorted({float(a) for a in allowed if isinstance(a, int | float) and math.isfinite(a)})
    pool += [abs(a) for a in pool if a < 0]
    given = [v for v, _ in numbers_in(request)]
    bad = []
    for v, raw in numbers_in(answer):
        if float(v).is_integer() and (0 <= v <= extra_ok or 1900 <= v <= 2100) and _bare(raw):
            continue
        tol = _tolerance(v, raw)
        if any(abs(v - a) <= tol for a in pool) or any(abs(v - a) <= tol for a in given):
            continue
        if "%" in raw and any(abs(v - a * 100) <= tol for a in pool if abs(a) <= 1):
            continue
        bad.append(raw)
    return bad
