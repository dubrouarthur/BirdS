"""Repair the common argument-shape mistakes of a small model BEFORE schema validation.

Nothing here widens what is accepted: every value still goes through the JSON schema afterwards. We only turn a
value into the type the schema asks for when the intent is unambiguous:

- an array or object written as a JSON string (``"slides": "[{...}]"``), even when the model forgot the last
  closing bracket(s) or left a trailing comma (the real make_slides failure seen on the live endpoint);
- a number or boolean written as a string (``"5"``, ``"12,5"``, ``"true"``);
- a single object or a single string where the schema wants a list of them;
- a list of strings given as one string with one item per line or separated by commas (``to``, ``bullets``);
- in ``make_sheet``, rows given as objects keyed by column name, or a row given as a JSON string.

Each repair is recorded so the audit log can say what was changed.
"""

from __future__ import annotations

import ast
import json
import re

_BULLET = re.compile(r"^\s*(?:[-*•·]|\d{1,2}[.)])\s+")


def _balance(text: str) -> str:
    """Close brackets/braces/quotes left open at the end of a JSON text and drop trailing commas."""
    stack, in_str, esc = [], False, False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append("]" if ch == "[" else "}")
        elif ch in "]}" and stack and stack[-1] == ch:
            stack.pop()
    out = text + ('"' if in_str else "")
    out = re.sub(r",\s*$", "", out)
    return out + "".join(reversed(stack))


def parse_json_like(text: str):
    """Best-effort decoding of a JSON array/object written by a model. Raises ValueError when hopeless."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s)
    candidates = [s, re.sub(r",\s*([\]}])", r"\1", s)]
    candidates.append(_balance(candidates[-1]))
    for c in candidates:
        try:
            return json.loads(c)
        except ValueError:
            pass
    try:  # Python-style literal: single quotes, True/False/None
        value = ast.literal_eval(_balance(s))
        # '["Mon", 120], ["Tue", 98]' (outer brackets forgotten, seen live) reads as a tuple: it is a list
        return list(value) if isinstance(value, tuple) else value
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        raise ValueError("not JSON") from None


def _types(spec: dict) -> list[str]:
    t = spec.get("type")
    return t if isinstance(t, list) else [t] if t else []


def _number(text: str):
    s = text.strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?\d*[.,]\d+", s):
        return float(s.replace(",", "."))
    raise ValueError


def _split_list(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return [_BULLET.sub("", ln).strip() for ln in lines]
    parts = [p.strip() for p in re.split(r"[;,]", text) if p.strip()]
    return parts if len(parts) > 1 else [_BULLET.sub("", text).strip()]


def coerce(value, spec: dict, path: str, notes: list[str]):
    """Return ``value`` converted towards ``spec`` when the intent is clear; otherwise return it unchanged."""
    types = _types(spec)
    if not types or ("string" in types and isinstance(value, str)):
        return value
    if isinstance(value, str) and ("array" in types or "object" in types):
        s = value.strip()
        if s[:1] in "[{" or s.startswith("```"):
            try:
                decoded = parse_json_like(s)
                notes.append(f"{path}: JSON text decoded")
                return coerce(decoded, spec, path, notes)
            except ValueError:
                pass
        if "array" in types and _types(spec.get("items") or {}) == ["string"] and s:
            notes.append(f"{path}: text split into a list")
            return _split_list(s)
        return value
    if isinstance(value, str) and ("integer" in types or "number" in types):
        try:
            n = _number(value)
        except ValueError:
            return value
        if "integer" in types and isinstance(n, float) and n.is_integer():
            n = int(n)
        if "integer" in types and not isinstance(n, int) and "number" not in types:
            return value
        notes.append(f"{path}: number read from text")
        return n
    if isinstance(value, str) and "boolean" in types and value.strip().lower() in ("true", "false", "oui", "non"):
        notes.append(f"{path}: boolean read from text")
        return value.strip().lower() in ("true", "oui")
    if "array" in types and not isinstance(value, list) and value is not None:
        item_types = _types(spec.get("items") or {})
        if isinstance(value, dict) and "object" in item_types:
            notes.append(f"{path}: single object wrapped in a list")
            return coerce([value], spec, path, notes)
        if isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
            notes.append(f"{path}: object of objects turned into a list")  # {"1": {...}, "2": {...}}
            return coerce(list(value.values()), spec, path, notes)
        return value
    if isinstance(value, list) and "array" in types:
        items = spec.get("items") or {}
        return [coerce(v, items, f"{path}/{i}", notes) for i, v in enumerate(value)]
    if isinstance(value, dict) and "object" in types:
        props = spec.get("properties") or {}
        return {k: coerce(v, props[k], f"{path}/{k}", notes) if k in props else v for k, v in value.items()}
    return value


def _sheet_rows(args: dict, notes: list[str]) -> None:
    """make_sheet: rows written as objects (column -> value) become lists in column order."""
    cols, rows = args.get("columns"), args.get("rows")
    if not isinstance(rows, list) or not isinstance(cols, list):
        return
    fixed, changed = [], False
    for row in rows:
        if isinstance(row, dict):
            row, changed = [row.get(c) for c in cols], True
        elif isinstance(row, str):
            try:
                decoded = parse_json_like(row)
            except ValueError:
                decoded = None
            if isinstance(decoded, list):
                row, changed = decoded, True
        fixed.append(row)
    if changed:
        notes.append("rows: objects or JSON text turned into lists")
        args["rows"] = fixed


_ALIASES = {  # tool -> (list argument, {expected key: [names a model uses instead]})
    "make_slides": ("slides", {"bullets": ["points", "items", "content", "text", "body"], "title": ["heading"]}),
    "make_document": ("sections", {"heading": ["title", "name"], "content": ["text", "body", "paragraphs"]}),
}


def _rename(args: dict, tool: str, notes: list[str]) -> None:
    """An item that lacks a required key but carries an obvious synonym gets the synonym renamed."""
    key, table = _ALIASES.get(tool, (None, {}))
    items = args.get(key)
    if not isinstance(items, list):
        return
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for want, alts in table.items():
            if want in item:
                continue
            alt = next((a for a in alts if a in item), None)
            if alt is not None:
                item[want] = item.pop(alt)
                notes.append(f"{key}/{i}: '{alt}' read as '{want}'")


class ArgError(ValueError):
    """A repair found a mistake it must not guess around. ``path`` names the argument, for the error message."""

    def __init__(self, path: str, message: str):
        super().__init__(message)
        self.path = path


# Default names a repair gives to a chart's label column and series (French; birds.harness.tools.chart translates
# them for an English conversation).
CHART_LABEL, CHART_VALUE, CHART_SERIES = "Libellé", "Valeur", "Série {i}"
_CHART_TYPES = {
    "bar": "bar bars barre barres histogram histogramme histogrammes column columns colonne colonnes baton batons "
    "barchart",
    "line": "line lines ligne lignes courbe courbes curve area aire linechart",
    "pie": "pie camembert camemberts donut doughnut secteur secteurs circulaire piechart",
}
_CHART_TYPE = {w: k for k, words in _CHART_TYPES.items() for w in words.split()}


def _fold(text: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def _decoded(value):
    if isinstance(value, str) and value.strip()[:1] in '[{`"':
        try:
            return parse_json_like(value)
        except ValueError:
            return _row_lines(value)
    return value


def _row_lines(text: str):
    """Rows written as broken JSON text, one row per line, with brackets missing (seen live on make_chart):
    '["T1", 120],\\n"T2", 135],\\n"T3", 128]'. Each line is read as one row; anything else stays text."""
    lines = [ln.strip() for ln in text.strip().strip("[]").splitlines() if ln.strip()]
    if len(lines) < 2:
        return text
    rows = []
    for ln in lines:
        body = re.sub(r"^\[+|[\],\s]+$", "", ln)
        try:
            row = json.loads("[" + body + "]")
        except ValueError:
            return text
        if not isinstance(row, list) or len(row) < 2 or any(isinstance(c, list | dict) for c in row):
            return text
        rows.append(row)
    return rows


def _series_list(series) -> list:
    """series as a list of {name, values} / bare lists, or as an object {name: values} / one {name, values}."""
    if isinstance(series, dict):
        if any(k in series for k in ("values", "data", "y")):
            return [series]
        return [{"name": k, "values": v} for k, v in series.items()]
    return series if isinstance(series, list) else [series]


def _chart_shape(a: dict, notes: list[str]) -> None:
    """make_chart: the other shapes a model writes ({labels, series}, {labels, values}, {data: {k: v}}, x/y...)
    become columns/rows. Labels and values of different lengths are an error, never truncated."""
    for src, dst in (("chart_type", "type"), ("kind", "type"), ("name", "title"), ("x", "labels"),
                     ("categories", "labels"), ("y", "values")):  # fmt: skip
        if src in a and dst not in a:
            a[dst] = a.pop(src)
            notes.append(f"'{src}' read as '{dst}'")
    for k in ("labels", "values", "series", "data", "points", "rows", "columns"):
        if k in a:
            before = a[k]
            a[k] = _decoded(before)
            if a[k] is not before:
                notes.append(f"{k}: JSON text decoded")
    if "type" in a and isinstance(a["type"], str):
        word = _fold(a["type"])
        if word in _CHART_TYPE:
            if a["type"] != _CHART_TYPE[word]:
                notes.append(f"type '{a['type']}' read as '{_CHART_TYPE[word]}'")
            a["type"] = _CHART_TYPE[word]
        else:
            notes.append(f"type '{a.pop('type')}' unknown: chosen from the data")
    for k in ("data", "points"):
        v = a.get(k)
        if "rows" not in a and (
            isinstance(v, dict) or (isinstance(v, list) and v and all(isinstance(r, list | dict) for r in v))
        ):
            a["rows"] = a.pop(k)
            notes.append(f"'{k}' read as 'rows'")
    value_name = (
        str(a.get("unit") or a.get("title") or CHART_VALUE)[:60] if not isinstance(a.get("unit"), dict) else CHART_VALUE
    )
    rows = a.get("rows")
    if isinstance(rows, dict):  # {label: value} or {label: [v1, v2]}
        a["rows"] = [[str(k), *(v if isinstance(v, list) else [v])] for k, v in rows.items()]
        notes.append("rows: object {label: value} turned into rows")
        if "columns" not in a:
            width = max((len(r) for r in a["rows"]), default=2)
            a["columns"] = (
                [CHART_LABEL, value_name]
                if width <= 2
                else [CHART_LABEL] + [CHART_SERIES.format(i=i) for i in range(1, width)]
            )
    if "labels" in a and ("series" in a or "values" in a) and "rows" not in a:
        labels, series, values = a.pop("labels"), a.pop("series", None), a.pop("values", None)
        if not isinstance(labels, list):
            raise ArgError("labels", "'labels' must be a list of labels")
        if series is None:
            series = [{"name": value_name, "values": values}]
        names, columns_of_values = [], []
        for i, s in enumerate(_series_list(series)):
            if isinstance(s, dict):
                name = s.get("name") or s.get("label") or s.get("title") or CHART_SERIES.format(i=i + 1)
                vals = _decoded(s.get("values", s.get("data", s.get("y"))))
            else:
                name, vals = CHART_SERIES.format(i=i + 1), _decoded(s)
            if isinstance(vals, dict):  # {label: value} inside a series
                vals = [vals.get(str(lab), vals.get(lab)) for lab in labels]
            if not isinstance(vals, list):
                raise ArgError(f"series/{i}", "'values' must be a list of numbers, one per label")
            if len(vals) != len(labels):
                raise ArgError(
                    f"series/{i}",
                    f"'values' has {len(vals)} numbers but there are {len(labels)} labels. Give one number per "
                    "label (null for a missing one)",
                )
            names.append(str(name))
            columns_of_values.append(vals)
        a["rows"] = [[lab, *(col[j] for col in columns_of_values)] for j, lab in enumerate(labels)]
        if not isinstance(a.get("columns"), list) or len(a["columns"]) != len(names) + 1:
            a["columns"] = [CHART_LABEL, *names]
        notes.append("labels/series turned into columns/rows")
    rows = a.get("rows")
    if isinstance(rows, list) and rows and "columns" not in a:
        if all(isinstance(r, dict) for r in rows):
            a["columns"] = [str(k) for k in rows[0]]
        elif all(isinstance(r, list) for r in rows):
            width = max(len(r) for r in rows)
            a["columns"] = (
                [CHART_LABEL, value_name]
                if width <= 2
                else [CHART_LABEL] + [CHART_SERIES.format(i=i) for i in range(1, width)]
            )
        if "columns" in a:
            notes.append("columns missing: named from the rows")


def coerce_args(tool: str, args: dict, schema: dict) -> tuple[dict, list[str]]:
    """(repaired arguments, notes). Unknown keys are kept: validation refuses them afterwards."""
    notes: list[str] = []
    props = schema.get("properties") or {}
    if tool == "make_chart":
        _chart_shape(args, notes)
    out = {k: coerce(v, props[k], k, notes) if k in props else v for k, v in args.items()}
    if tool in _ALIASES:
        _rename(out, tool, notes)
        key = _ALIASES[tool][0]
        if key in out:  # second pass: renamed values (e.g. "content" text -> bullets list) get their types fixed
            out[key] = coerce(out[key], props[key], key, notes)
    if tool in ("make_sheet", "make_chart"):
        _sheet_rows(out, notes)
        if isinstance(out.get("rows"), list):
            out["rows"] = coerce(out["rows"], props["rows"], "rows", notes)
    return out, notes
