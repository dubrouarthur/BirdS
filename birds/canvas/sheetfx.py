"""The mini-sheet's formulas to OOXML and back.

The canvas mini-sheet (static/canvas-sheet.js) reads French function names (SOMME, MOYENNE, SI, ARRONDI…), « ; »
or « , » as separators and French decimals (« 1,5 »); its A1 is the first DATA row (the header row has no number).
An .xlsx stores formulas with the English names and « , » separators, and its row 1 is the header. So:

* ``to_ooxml``: panel formula -> the text of the file's ``<f>`` (names, separators, decimals, rows + 1);
* ``from_ooxml``: a trained make_sheet formula (file conventions, header in row 1) -> the panel's rows (rows - 1).

Text inside double quotes is never touched.
"""

from __future__ import annotations

import re

# the same table as canvas-sheet.js FUNCS, to the Excel names
NAMES = {
    "SOMME": "SUM", "SUM": "SUM", "MOYENNE": "AVERAGE", "AVERAGE": "AVERAGE", "AVG": "AVERAGE", "MIN": "MIN",
    "MAX": "MAX", "NB": "COUNT", "COUNT": "COUNT", "ARRONDI": "ROUND", "ROUND": "ROUND", "ABS": "ABS", "SI": "IF",
    "IF": "IF", "PRODUIT": "PRODUCT", "PRODUCT": "PRODUCT",
}  # fmt: skip
_FN = re.compile(r"(?<![A-Za-z0-9_.$])([A-Za-z][A-Za-z0-9_.]*)(?=\s*\()")
_REF = re.compile(r"(?<![A-Za-z0-9_.$])(\$?)([A-Za-z]{1,3})(\$?)(\d{1,7})(?![A-Za-z0-9_(])")
_DECIMAL = re.compile(r"(?<![A-Za-z0-9_$])(\d+),(\d+)(?![A-Za-z0-9_])")


def _outside_strings(formula: str, fn) -> str:
    """``fn`` applied to the parts of the formula outside "…" strings."""
    parts = re.split(r'("(?:[^"]|"")*"?)', formula)
    return "".join(p if p.startswith('"') else fn(p) for p in parts)


def _shift(code: str, dr: int) -> str:
    def one(m: re.Match) -> str:
        row = int(m.group(4)) + dr
        if row < 1:
            return m.group(0)  # a reference to the header row: left as written
        return f"{m.group(1)}{m.group(2).upper()}{m.group(3)}{row}"

    return _REF.sub(one, code)


def to_ooxml(value: str) -> str:
    """« =SOMME(A1:A3;1,5) » -> « =SUM(A2:A4,1.5) ». Anything that is not a formula is returned as is."""
    if not isinstance(value, str) or not value.startswith("="):
        return value
    semi = ";" in _outside_strings(value, lambda p: p if ";" in p else "")

    def code(p: str) -> str:
        p = _FN.sub(lambda m: NAMES.get(m.group(1).upper(), m.group(1)), p)
        if semi:  # « ; » separates the arguments: a comma between digits is a French decimal
            p = _DECIMAL.sub(r"\1.\2", p).replace(";", ",")
        return _shift(p, 1)

    return "=" + _outside_strings(value[1:], code)


def from_ooxml(value):
    """A formula written for the file (header in row 1) as the panel reads it (first data row = 1)."""
    if not isinstance(value, str) or not value.startswith("="):
        return value
    return "=" + _outside_strings(value[1:], lambda p: _shift(p, -1))
