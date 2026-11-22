"""make_chart: check and normalise a chart a model asked for. The browser draws it (birds/web/static/chart.js).

The arguments have the make_sheet shape ({title, type?, columns, rows, unit?}); birds.harness.coerce already turned
the other shapes into it. Here every cell becomes a number (``"12,5 %"`` -> 12.5, unit %), and the chart is reshaped
where a reader would be misled otherwise (a Total row next to its parts, 20 pie slices). Every error names the cell
and says how to fix it, so a small model can call again. Nothing here writes a file or reaches the network.
"""

from __future__ import annotations

import math
import re
import unicodedata

from birds.harness.coerce import CHART_LABEL, CHART_SERIES, CHART_VALUE, _number
from birds.harness.guard import EXAMPLES, ToolError

MAX_ROWS, MAX_SERIES, MAX_CHARTS, MAX_SLICES = 50, 6, 3, 8
TYPES = ("bar", "line", "pie")
_EN_NAMES = {CHART_LABEL: "Label", CHART_VALUE: "Value"}
_OTHER = {"fr": "Autres", "en": "Other"}
_GAPS = {"", "-", "–", "—", "n/a", "na", "nd", "n.d.", "?", "null", "none", "nan"}
_SPACES = re.compile(r"[\s    ]+")
_PREFIX = re.compile(r"^([€$£])\s*")
_SPLIT = re.compile(r"^([-+−]?\s*[\d][\d\s.,]*)\s*([^\d\s.,][^\d]{0,7})?$")
_TOTAL = re.compile(r"^\s*(?:total|totaux|somme|sum|ensemble)\b", re.I)
_MONTHS = (
    "janvier|janv|jan|fevrier|fevr|fev|mars|mar|avril|avr|mai|juin|juillet|juil|aout|septembre|sept|sep|octobre|oct|"
    "novembre|nov|decembre|dec|january|february|feb|march|april|apr|may|june|jun|july|jul|august|aug|september|"
    "october|november|december"
)
_DAYS = (
    "lundi|lun|mardi|mercredi|mer|jeudi|jeu|vendredi|ven|samedi|sam|dimanche|dim|monday|mon|tuesday|tue|tues|"
    "wednesday|wed|thursday|thu|thurs|friday|fri|saturday|sat|sunday|sun"
)
_TEMPORAL = re.compile(
    rf"^(?:(?:19|20)\d\d\b|(?:{_MONTHS})\.?\b|[tqs]\d{{1,2}}\b|\d{{4}}-\d{{2}}(?:-\d{{2}})?\b|"
    rf"\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b|(?:{_DAYS})\.?\b|(?:semaine|week|mois|month|annee|year)\s*\d)",
    re.I,
)
_SHARE_WORDS = re.compile(r"r[ée]partition|\bparts?\b|\bshares?\b|camembert|\bpie\b", re.I)


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower().strip()


class NotANumber(ValueError):
    pass


def chart_number(value, lang: str = "fr") -> tuple[float | int | None, str | None, bool]:
    """(number or None for a gap, unit peeled from the text or None, ambiguous). Raises NotANumber."""
    if value is None:
        return None, None, False
    if isinstance(value, bool):
        raise NotANumber("a true/false value is not a number")
    if isinstance(value, int | float):
        if not math.isfinite(value):
            raise NotANumber("not a finite number")
        return value, None, False
    s = _SPACES.sub(" ", str(value)).strip()
    if _plain(s) in _GAPS:
        return None, None, False
    if s.startswith("="):
        raise NotANumber("formula")
    if "," not in s:  # the plain case ("12", "12.5", "1 200"); a comma may be a decimal or a thousands separator
        try:
            return _number(s), None, False
        except ValueError:
            pass
    unit = None
    m = _PREFIX.match(s)
    if m:
        unit, s = m.group(1), s[m.end() :]
    m = _SPLIT.match(s)
    if not m:
        raise NotANumber("not a number")
    num, suffix = m.group(1).replace("−", "-"), (m.group(2) or "").strip()
    if suffix:
        if len(suffix) > 6 or unit:
            raise NotANumber("not a number")
        unit = suffix
    num = num.replace(" ", "")
    ambiguous = False
    if "." in num and "," in num:
        dec = "." if num.rfind(".") > num.rfind(",") else ","
        num = num.replace("," if dec == "." else ".", "").replace(",", ".")
    elif "," in num:
        if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3}){2,}", num):
            num = num.replace(",", "")
        elif re.fullmatch(r"[-+]?\d{1,3},\d{3}", num):
            ambiguous = True
            num = num.replace(",", ".") if lang != "en" else num.replace(",", "")
        else:
            num = num.replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3}){2,}", num):
        num = num.replace(".", "")
    try:
        n = float(num)
    except ValueError:
        raise NotANumber("not a number") from None
    if not math.isfinite(n):
        raise NotANumber("not a finite number")
    return (int(n) if n.is_integer() and "." not in num else n), unit, ambiguous


def _err(message: str) -> ToolError:
    return ToolError(
        f"invalid arguments for make_chart: {message}. Call make_chart again with corrected arguments, for example "
        f"{EXAMPLES['make_chart']}"
    )


def _label(value, i: int) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _err(f"rows/{i}/0: a label is missing")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).split())
    return text if len(text) <= 60 else text[:59].rstrip() + "…"


def _numbers_in(text: str) -> set[float]:
    """Every number written in a text, both readings of an ambiguous one ('1,234')."""
    out: set[float] = set()
    for m in re.finditer(r"[-+−]?\d[\d\s  .,]*", text or ""):
        raw = m.group(0).rstrip(" .,  ")
        for lang in ("fr", "en"):
            for cand in (raw, raw.replace(" ", "")):
                try:
                    n, _, _ = chart_number(cand, lang)
                except NotANumber:
                    continue
                if n is not None:
                    out.add(float(n))
        for part in re.split(r"[\s  ]+", raw):  # "10 et 12": each part on its own too
            try:
                n, _, _ = chart_number(part, "fr")
            except NotANumber:
                continue
            if n is not None:
                out.add(float(n))
    return out


def _infer_type(rows: list[list], unit: str | None, request: str) -> tuple[str, str]:
    series = len(rows[0]) - 1 if rows else 0
    values = [r[1] for r in rows if r[1] is not None] if series == 1 else []
    if series == 1 and values and all(v >= 0 for v in values) and len(rows) <= MAX_SLICES:
        total = sum(values)
        if (unit == "%" and 95 <= total <= 105) or _SHARE_WORDS.search(request or ""):
            return "pie", "type 'pie' chosen (shares of a whole)"
    if len(rows) >= 3 and all(_TEMPORAL.match(_plain(r[0])) for r in rows):
        return "line", "type 'line' chosen (labels look like dates)"
    return "bar", "type 'bar' chosen"


def normalize_chart(args: dict, lang: str = "fr", request: str = "") -> tuple[dict, list[str]]:
    """(chart spec, notes). The spec is JSON-safe: {title, type, unit, columns, rows, notes, reshaped}."""
    notes: list[str] = []
    reshaped: list[str] = []
    title = " ".join(str(args.get("title") or "").split())
    if len(title) > 120:
        title, _ = title[:119].rstrip() + "…", notes.append("title cut to 120 characters")
    columns = [" ".join(str(c).split())[:60] for c in (args.get("columns") or [])]
    if lang == "en":
        columns = [_EN_NAMES.get(c, re.sub(r"^Série (\d+)$", r"Series \1", c)) for c in columns]
    raw_rows = args.get("rows") or []
    if not raw_rows:
        raise _err("rows is empty: give at least one row, a label then its numbers")
    if len(raw_rows) > MAX_ROWS:
        raise _err(f"at most {MAX_ROWS} rows; group them (e.g. by month)")
    unit = " ".join(str(args.get("unit") or "").split())[:12] or None
    if not columns:
        raise _err("columns is empty: give the label column then one name per series")
    width = max(len(r) for r in raw_rows) if raw_rows else 0
    if len(columns) == 1 and width >= 2:
        columns.append(unit or ({"en": "Value"}.get(lang, CHART_VALUE)))
        notes.append("a series column was added")
    if len(columns) < 2:
        raise _err('columns needs the label column then at least one series, e.g. ["Mois", "Ventes"]')
    if len(columns) - 1 > MAX_SERIES:
        raise _err(f"at most {MAX_SERIES} series (columns after the label column)")
    rows: list[list] = []
    units: list[set[str]] = [set() for _ in columns[1:]]
    parsed_text, ambiguous = False, False
    for i, raw in enumerate(raw_rows):
        if not isinstance(raw, list):
            raise _err(f"rows/{i} must be a list: a label then its numbers")
        if len(raw) > len(columns):
            raise _err(
                f"rows/{i} has {len(raw)} cells but there are {len(columns)} columns. Give one label then one "
                "number per series"
            )
        if len(raw) < len(columns):
            notes.append(f"rows/{i}: missing cells left empty")
            raw = list(raw) + [None] * (len(columns) - len(raw))
        row = [_label(raw[0], i)]
        for j, cell in enumerate(raw[1:], 1):
            try:
                n, u, amb = chart_number(cell, lang)
            except NotANumber as e:
                if str(e) == "formula":
                    raise _err(f"rows/{i}/{j} is a formula; write the computed number") from None
                raise _err(
                    f"rows/{i}/{j}: {str(cell)[:40]!r} is not a number. Write numbers only, e.g. 12 or 12.5; put "
                    "the unit in 'unit'"
                ) from None
            if isinstance(cell, str) and n is not None:
                parsed_text = True
            ambiguous |= amb
            if u:
                units[j - 1].add(u)
            row.append(n)
        rows.append(row)
    if parsed_text:
        notes.append("numbers read from text")
    if ambiguous:
        notes.append(
            "'1,234'-style numbers read as " + ("1.234 (French decimal comma)" if lang != "en" else "1234 (thousands)")
        )
    for j, us in enumerate(units):
        if len(us) > 1:
            raise _err(f"series '{columns[j + 1]}' mixes {' and '.join(sorted(us))}: one unit per series")
    peeled = set().union(*units) if units else set()
    if not unit and len(peeled) == 1:
        unit = next(iter(peeled))
        notes.append(f"unit '{unit}' read from the values")
    elif not unit and len(peeled) > 1:
        notes.append("units differ between series: no common unit")
    for j in range(1, len(columns)):
        if all(r[j] is None for r in rows):
            raise _err(f"series '{columns[j]}' has no number: give at least one")
    kind = args.get("type") if args.get("type") in TYPES else None
    total_row = (
        len(rows) >= 3
        and _TOTAL.match(rows[-1][0])
        and all(
            rows[-1][j] is not None
            and abs(rows[-1][j] - sum(r[j] or 0 for r in rows[:-1])) <= 0.01 * max(abs(rows[-1][j]), 1e-9)
            for j in range(1, len(columns))
        )
    )
    if kind is None:
        kind, why = _infer_type(rows[:-1] if total_row else rows, unit, request)
        notes.append(why)
    if total_row and kind in ("bar", "pie"):
        rows.pop()
        reshaped.append("'Total' row dropped: it would dwarf the bars")
    if kind == "line" and len(rows) < 2:
        kind = "bar"
        reshaped.append("a line needs at least 2 points: shown as bars")
    if kind == "pie":
        if len(columns) > 2:
            raise _err("a pie shows one series; use type bar to compare several")
        if any(r[1] is not None and r[1] < 0 for r in rows):
            raise _err("a pie cannot show a negative value; use type bar")
        gaps = [r[0] for r in rows if r[1] is None]
        if gaps:
            rows = [r for r in rows if r[1] is not None]
            reshaped.append("empty slices dropped: " + ", ".join(gaps[:5]))
        if sum(r[1] for r in rows) <= 0:
            raise _err("a pie needs a total above 0")
        if len(rows) > MAX_SLICES:
            keep = sorted(range(len(rows)), key=lambda k: -rows[k][1])[: MAX_SLICES - 1]
            folded = [rows[k] for k in range(len(rows)) if k not in keep]
            other = sum(r[1] for r in folded)
            rows = [rows[k] for k in sorted(keep)] + [[_OTHER.get(lang, _OTHER["fr"]), round(other, 10)]]
            reshaped.append(
                f"{len(folded)} small slices grouped in '{rows[-1][0]}': " + ", ".join(r[0] for r in folded[:6])
            )
    spec = {
        "title": title or ("Graphique" if lang != "en" else "Chart"),
        "type": kind,
        "unit": unit or "",
        "columns": columns,
        "rows": rows,
        "notes": notes + reshaped,
        "reshaped": reshaped,
    }
    return spec, notes + reshaped


def chart_source(spec: dict, ctx) -> str:
    """Where the numbers come from: the user's words, a file they gave, the web, or the model itself."""
    values = [float(v) for r in spec["rows"] for v in r[1:] if v is not None]
    if values and all(v in _numbers_in(ctx.request) for v in values):
        return "request"
    if "read_file" in ctx.used or (ctx.message != ctx.request and all(v in _numbers_in(ctx.message) for v in values)):
        return "file"
    if "web_search" in ctx.used or "read_page" in ctx.used:
        return "web"
    return "model"


def _fmt(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def make_chart(args: dict, ctx) -> str:
    if len(ctx.charts) >= MAX_CHARTS:
        raise ToolError(f"at most {MAX_CHARTS} charts per request: answer the user now")
    spec, notes = normalize_chart(args, ctx.lang, ctx.request)
    spec = {"id": f"c{len(ctx.charts) + 1}", **spec, "source": chart_source(spec, ctx)}
    ctx.charts.append(spec)
    series = spec["columns"][1:]
    values = [v for r in spec["rows"] for v in r[1:] if v is not None]
    unit = f" {spec['unit']}" if spec["unit"] else ""
    ctx.step_info = {"chart": spec["id"], "values": len(spec["rows"]), "series": len(series), "type": spec["type"]}
    kind = {"bar": "bar chart", "line": "line chart", "pie": "pie chart"}[spec["type"]]
    out = (
        f"Chart shown to the user in the chat: {kind} « {spec['title']} », {len(spec['rows'])} labels, "
        f"{len(series)} series ({', '.join(series)}), values from {_fmt(min(values))} to {_fmt(max(values))}{unit}. "
        "Do not draw it again in text or as a table; comment on it in 1 to 3 sentences."
    )
    if spec["reshaped"]:
        out += "\nAdjusted: " + "; ".join(spec["reshaped"])
    if spec["source"] == "model":
        out += "\nThese figures are not from the user, a file or the web: say they are your own, unverified."
    return out


__all__ = ["CHART_SERIES", "chart_number", "chart_source", "make_chart", "normalize_chart"]
