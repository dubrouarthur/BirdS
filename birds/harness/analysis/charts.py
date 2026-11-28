"""The richer chart spec (version 2) the browser draws with ``static/charts2.js``.

A forgiving input — the make_chart shape {title, type, columns, rows}, or {labels, series: [{name, values}]},
or {points: [[label, x, y, size?]]} — becomes one checked, JSON-safe spec:

    {"v": 2, "type": "hbar", "title": …, "labels": [...], "series": [{"name", "values", "unit", "axis", "mark"}],
     "unit": "€", "x": {"name", "kind"}, "annotations": [{"kind": "max"|"min"|"mean"|"target", ...}],
     "points": [[label, x, y, size]], "matrix": {...}, "box": {...}, "kpi": {...}, "alts": [...], "source": …}

Types: bar, stacked, hbar, line, area, stacked_area, scatter, bubble, pie, donut, histogram, box, heatmap,
waterfall, funnel, combo (bars + a line on a second axis), kpi. With no type, ``auto_type`` picks one: dates ->
line, parts of a whole (<= 6) -> donut, a ranking -> horizontal bars, two measures -> scatter.

When ``allowed`` numbers are given (the user's data, a computed result, a tool result), every value of the chart
must be one of them: a chart never shows a number nobody gave.
"""

from __future__ import annotations

import math
import re

from birds.harness.analysis.cells import as_float, plain
from birds.harness.guard import ToolError

TYPES = ("bar", "stacked", "hbar", "line", "area", "stacked_area", "scatter", "bubble", "pie", "donut", "histogram",
         "box", "heatmap", "waterfall", "funnel", "combo", "kpi")  # fmt: skip
ALIASES = {
    "barres": "bar", "bars": "bar", "column": "bar", "columns": "bar", "colonnes": "bar", "grouped": "bar",
    "grouped_bar": "bar", "groupedbar": "bar", "barresgroupees": "bar", "stackedbar": "stacked", "empile": "stacked",
    "empilees": "stacked", "barresempilees": "stacked", "horizontal": "hbar", "barh": "hbar", "horizontalbar": "hbar",
    "barreshorizontales": "hbar", "classement": "hbar", "ranking": "hbar", "courbe": "line", "lines": "line",
    "multiline": "line", "courbes": "line", "aire": "area", "aires": "area", "stackedarea": "stacked_area",
    "airesempilees": "stacked_area", "nuage": "scatter", "points": "scatter", "xy": "scatter", "bulles": "bubble",
    "bulle": "bubble", "camembert": "pie", "secteurs": "pie", "doughnut": "donut", "anneau": "donut",
    "histogramme": "histogram", "distribution": "histogram", "boxplot": "box", "boite": "box", "moustaches": "box",
    "carte_de_chaleur": "heatmap", "chaleur": "heatmap", "matrix": "heatmap", "cascade": "waterfall",
    "entonnoir": "funnel", "mixte": "combo", "barline": "combo", "barsline": "combo", "indicateur": "kpi",
    "chiffre": "kpi", "metric": "kpi", "stat": "kpi",
}  # fmt: skip
MAX_LABELS, MAX_SERIES, MAX_POINTS, MAX_SLICES = 60, 6, 2000, 8
SWITCH = {  # what the reader may switch to from the chart's own toolbar
    "bar": ["bar", "hbar", "line", "donut"],
    "hbar": ["hbar", "bar", "donut"],
    "line": ["line", "area", "bar"],
    "area": ["area", "line", "bar"],
    "donut": ["donut", "pie", "hbar", "bar"],
    "pie": ["pie", "donut", "hbar"],
    "stacked": ["stacked", "bar", "line"],
    "stacked_area": ["stacked_area", "line", "stacked"],
    "combo": ["combo", "bar", "line"],
    "histogram": ["histogram", "box"],
    "box": ["box", "histogram"],
    "funnel": ["funnel", "hbar"],
    "waterfall": ["waterfall", "bar"],
}
_TEMPORAL = re.compile(
    r"^(?:(?:19|20)\d\d\b|(?:janv|fevr|mars|avr|mai|juin|juil|aout|sept|oct|nov|dec|jan|feb|mar|apr|may|jun|jul|aug|"
    r"sep)\w*\.?(?:\s+\d{2,4})?$|[tqs]\d{1,2}\b|\d{4}-\d{2}(?:-\d{2})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?|"
    r"(?:semaine|week|mois|month)\s*\d)",
    re.I,
)
_SHARE = re.compile(r"r[ée]partition|\bparts?\b|\bshares?\b|camembert|\bpie\b|donut|proportion|breakdown", re.I)


def _err(msg: str) -> ToolError:
    return ToolError(f"invalid chart: {msg}")


def _type(value) -> str | None:
    if not value:
        return None
    w = re.sub(r"[^a-z_]", "", plain(value).replace(" ", "_").replace("-", "_"))
    if w in TYPES:
        return w
    return ALIASES.get(w.replace("_", ""), ALIASES.get(w))


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v) if math.isfinite(v) else None
    x = as_float(v, ",")
    if x is None and isinstance(v, str) and v.strip() and plain(v) not in ("", "-", "n/a", "null", "none"):
        raise _err(f"{v[:30]!r} is not a number")
    return x


def _clean(text, n: int = 60) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def temporal(labels: list[str]) -> bool:
    return len(labels) >= 3 and all(_TEMPORAL.match(plain(x)) for x in labels)


def auto_type(labels: list[str], series: list[dict], request: str = "", kind: str = "") -> tuple[str, str]:
    """(type, why). ``kind`` is the result kind when the harness computed it (time, ranking, share, compare…)."""
    one = len(series) == 1
    vals = [v for v in series[0]["values"] if v is not None] if series else []
    if kind == "scalar":
        return "kpi", "one number: a key figure"
    if kind == "scatter":
        return "scatter", "two measures: a scatter plot"
    if kind == "describe":
        return "box", "a distribution: a box plot"
    if kind == "time" or temporal(labels):
        if len(labels) < 2:
            return "bar", "one period: bars"
        return "line", "labels are dates: a line"
    if kind == "compare":
        return "bar", "two years side by side: grouped bars"
    nonneg = vals and all(v >= 0 for v in vals)
    if one and nonneg and len(labels) <= 6 and (kind == "share" or _SHARE.search(request or "")):
        return "donut", "parts of a whole: a donut"
    if one and nonneg and len(labels) <= 6 and kind != "ranking" and abs(sum(vals) - 100) <= 1.5 and len(vals) >= 2:
        return "donut", "percentages adding up to 100: a donut"
    if kind == "ranking" or len(labels) > 8 or max((len(str(x)) for x in labels), default=0) > 14:
        return "hbar", "a ranking or long labels: horizontal bars"
    if not one and kind == "pivot":
        return "stacked", "parts of each group: stacked bars"
    return "bar", "categories: bars"


def _close(v: float, allowed: list[float]) -> bool:
    for a in allowed:
        if v == a or abs(v - a) <= 1e-6 * max(1.0, abs(a)):
            return True
        # the chart may round what it was given (12.345 -> 12.35), never more than that
        if abs(v - a) <= 0.005 + 1e-9 or (abs(a) >= 100 and abs(v - a) <= 0.5):
            return True
    return False


def unverified(values: list[float], allowed) -> list[float]:
    pool = sorted({float(a) for a in allowed if isinstance(a, int | float) and math.isfinite(a)})
    return [v for v in values if not _close(v, pool)]


def normalize_spec(args: dict, lang: str = "fr", request: str = "", allowed=None, kind: str = "") -> dict:
    """The checked v2 spec. Raises ToolError (a message a small model can act on)."""
    if not isinstance(args, dict):
        raise _err("give an object {title, type, columns, rows}")
    want = _type(args.get("type") or args.get("chart_type") or args.get("kind"))
    title = _clean(args.get("title") or ("Graphique" if lang != "en" else "Chart"), 120)
    unit = _clean(args.get("unit") or "", 12)
    labels: list[str] = []
    series: list[dict] = []
    points: list[list] = []
    if isinstance(args.get("points"), list):  # scatter / bubble: [label, x, y, size?]
        for i, p in enumerate(args["points"][:MAX_POINTS]):
            if not isinstance(p, list | tuple) or len(p) < 3:
                raise _err(f"points/{i} must be [label, x, y] or [label, x, y, size]")
            x, y = _num(p[1]), _num(p[2])
            if x is None or y is None:
                continue
            size = _num(p[3]) if len(p) > 3 else None
            points.append([_clean(p[0], 40), x, y, size])
        if not points:
            raise _err("points has no [label, x, y] with numbers")
    elif isinstance(args.get("labels"), list) and isinstance(args.get("series"), list):
        labels = [_clean(x) for x in args["labels"]]
        for j, s in enumerate(args["series"][:MAX_SERIES]):
            if not isinstance(s, dict) or not isinstance(s.get("values"), list):
                raise _err(f"series/{j} must be {{name, values}}")
            if len(s["values"]) != len(labels):
                raise _err(f"series/{j} has {len(s['values'])} values for {len(labels)} labels")
            series.append({"name": _clean(s.get("name") or f"Série {j + 1}"), "values": [_num(v) for v in s["values"]],
                           "unit": _clean(s.get("unit") or "", 12), "axis": "y2" if s.get("axis") == "y2" else "y",
                           "mark": s.get("mark") if s.get("mark") in ("bar", "line") else None})  # fmt: skip
    else:
        columns = [_clean(c) for c in args.get("columns") or []]
        rows = args.get("rows") or []
        if not rows:
            raise _err("rows is empty: give a label then its numbers on each row")
        width = max(len(r) for r in rows if isinstance(r, list | tuple)) if rows else 0
        if len(columns) < width:
            columns += [f"Série {j}" if lang != "en" else f"Series {j}" for j in range(len(columns), width)]
        for j in range(1, min(width, MAX_SERIES + 1)):
            series.append({"name": columns[j], "values": [], "unit": "", "axis": "y", "mark": None})
        for i, r in enumerate(rows):
            if not isinstance(r, list | tuple) or not r:
                raise _err(f"rows/{i} must be a list: a label then its numbers")
            labels.append(_clean(r[0] if r[0] is not None else "—"))
            for j, s in enumerate(series, 1):
                s["values"].append(_num(r[j]) if j < len(r) else None)
        x_name = columns[0] if columns else ""
        args = {**args, "x_name": args.get("x_name") or x_name}
    if len(labels) > MAX_LABELS and want not in ("histogram", "line", "area", "heatmap"):
        raise _err(f"at most {MAX_LABELS} labels; group them or use top")
    for s in series:
        if all(v is None for v in s["values"]):
            raise _err(f"series '{s['name']}' has no number")
    # ---- sort / top
    sort = args.get("sort") if args.get("sort") in ("asc", "desc") else None
    top = args.get("top")
    if (sort or top) and series and labels:
        order = list(range(len(labels)))
        if sort:
            order.sort(key=lambda i: (series[0]["values"][i] is None, (series[0]["values"][i] or 0) * (-1 if sort ==
                                                                                                         "desc" else 1)))  # fmt: skip
        if isinstance(top, int) and 0 < top < len(order):
            order = order[:top]
        labels = [labels[i] for i in order]
        for s in series:
            s["values"] = [s["values"][i] for i in order]
    # ---- the numbers must come from somewhere
    if allowed is not None:
        values = [v for s in series for v in s["values"] if v is not None] + \
            [v for p in points for v in p[1:] if v is not None]  # fmt: skip
        bad = unverified(values, allowed)
        if bad:
            shown = ", ".join(f"{v:g}" for v in bad[:5])
            raise _err(f"{len(bad)} value(s) are not in the data, the computed result or a tool result ({shown}). "
                       "Chart only numbers you were given")  # fmt: skip
    if want is None:
        if points:
            want, why = ("bubble" if any(p[3] is not None for p in points) else "scatter"), "points: a scatter plot"
        else:
            want, why = auto_type(labels, series, request, kind)
    else:
        why = "type asked"
    notes = [why]
    if not series and not points and not (args.get("bins") or args.get("box") or args.get("matrix")):
        raise _err("no series: give the label column then at least one column of numbers")
    if want in ("pie", "donut", "waterfall", "funnel", "kpi") and not series:
        raise _err(f"a {want} needs one series of numbers")
    # ---- type-specific checks and reshaping
    if want in ("pie", "donut"):
        if len(series) > 1:
            want, _ = "bar", notes.append("several series: bars instead of a donut")
        elif any(v is not None and v < 0 for v in series[0]["values"]):
            want, _ = "bar", notes.append("a negative value: bars instead of a donut")
        else:
            keep = [i for i, v in enumerate(series[0]["values"]) if v]
            labels = [labels[i] for i in keep]
            series[0]["values"] = [series[0]["values"][i] for i in keep]
            if len(labels) > MAX_SLICES:
                idx = sorted(range(len(labels)), key=lambda i: -series[0]["values"][i])
                big, small = idx[: MAX_SLICES - 1], idx[MAX_SLICES - 1 :]
                other = math.fsum(series[0]["values"][i] for i in small)
                labels = [labels[i] for i in big] + ["Autres" if lang != "en" else "Other"]
                series[0]["values"] = [series[0]["values"][i] for i in big] + [round(other, 6)]
                notes.append(f"{len(small)} small slices grouped")
    if want in ("scatter", "bubble") and not points:
        if len(series) >= 2:
            points = [[labels[i], series[0]["values"][i], series[1]["values"][i],
                       series[2]["values"][i] if len(series) > 2 and want == "bubble" else None]
                      for i in range(len(labels)) if series[0]["values"][i] is not None and
                      series[1]["values"][i] is not None]  # fmt: skip
        else:
            want = "bar"
            notes.append("a scatter needs two measures: bars instead")
    if want == "combo" and len(series) < 2:
        want = "bar"
    if want == "combo":
        series[0]["mark"] = series[0]["mark"] or "bar"
        for s in series[1:]:
            s["mark"] = s["mark"] or "line"
        if series[-1]["axis"] != "y2" and _scale_gap(series):
            series[-1]["axis"] = "y2"
    if want in ("line", "area", "stacked_area") and len(labels) < 2:
        want = "bar"
    if want == "kpi" and series:
        v = next((x for x in series[0]["values"] if x is not None), None)
        spec_kpi = {
            "value": v,
            "label": series[0]["name"],
            "spark": [x for x in series[0]["values"][1:] if x is not None][:48],
        }
    else:
        spec_kpi = None
    annotations = []
    for a in args.get("annotations") or []:
        if isinstance(a, str):
            a = {"kind": a}
        if not isinstance(a, dict) or a.get("kind") not in ("max", "min", "mean", "target"):
            continue
        item = {"kind": a["kind"], "label": _clean(a.get("label") or "", 40)}
        if a["kind"] == "target":
            t = _num(a.get("value"))
            if t is None:
                continue
            if allowed is not None and unverified([t], list(allowed) + _numbers_in(request)):
                raise _err(f"target {t:g} is not a number the user gave")
            item["value"] = t
        annotations.append(item)
    spec = {
        "v": 2,
        "type": want,
        "title": title,
        "unit": unit or (series[0]["unit"] if series else ""),
        "labels": labels,
        "series": series,
        "x": {
            "name": _clean(args.get("x_name") or "", 60),
            "kind": "time" if temporal(labels) or kind == "time" else "category",
        },  # fmt: skip
        "annotations": annotations,
        "notes": notes,
        "alts": SWITCH.get(want, [want]),
    }
    if points:
        spec["points"] = points
        xs = args.get("axes") or []
        spec["axes"] = [_clean(x, 40) for x in xs[:2]] if xs else []
    if spec_kpi:
        spec["kpi"] = spec_kpi
    for k in ("box", "matrix", "bins"):
        if isinstance(args.get(k), dict | list):
            spec[k] = args[k]
    # the make_chart shape too: the turn memo (« refais-le en courbe »), the conversation export and older readers
    if points:
        spec["columns"] = ["", *(spec["axes"] or ["x", "y"])]
        spec["rows"] = [[p[0], p[1], p[2]] for p in points[:200]]
    else:
        spec["columns"] = [spec["x"]["name"], *[s["name"] for s in series]]
        spec["rows"] = [[lab, *[s["values"][i] for s in series]] for i, lab in enumerate(labels)]
    return spec


def _scale_gap(series: list[dict]) -> bool:
    def top(s):
        return max((abs(v) for v in s["values"] if v is not None), default=0)

    a, b = top(series[0]), top(series[-1])
    return bool(a and b) and (max(a, b) / max(min(a, b), 1e-9) > 8 or series[0]["unit"] != series[-1]["unit"])


def _numbers_in(text: str) -> list[float]:
    from birds.harness.analysis.verify import numbers_in

    return [n for n, _ in numbers_in(text or "")]


def chart_from_result(res: dict, lang: str = "fr", source: str = "analysis", source_label: str = "",
                      type_: str | None = None) -> dict:  # fmt: skip
    """The chart of a computed result (``query.run_query``), the type chosen from its kind."""
    kind = res.get("kind", "")
    cols, rows = res.get("columns") or [], res.get("rows") or []
    unit = res.get("unit") or ""
    args: dict = {"title": res.get("title"), "unit": unit, "x_name": cols[0] if cols else ""}
    if kind == "scatter":
        ux, uy = (res.get("units") or ["", ""])[:2]
        args["points"] = [[r[0], r[1], r[2]] for r in rows]
        args["axes"] = [cols[1], cols[2]]
        spec = normalize_spec(args, lang, kind=kind)
        spec["units"] = [ux, uy]
        spec["stat"] = {"r": res.get("r"), "strength": res.get("strength"), "n": res.get("n")}
    elif kind == "describe":
        st = res.get("stats") or {}
        values = [v for v in res.get("values") or [] if isinstance(v, int | float)]
        from birds.harness.analysis.profile import histogram

        counts, lo, hi = histogram(values, 12) if values else ([], 0, 0)
        args.update({"type": type_ or "box", "columns": cols, "rows": rows})
        spec = normalize_spec(args, lang, kind=kind)
        spec["box"] = {k: st.get(k) for k in ("min", "q1", "median", "mean", "q3", "max")} | {
            "outliers": (st.get("outliers") or {}).get("low", []) + (st.get("outliers") or {}).get("high", [])
        }
        spec["bins"] = {"counts": counts, "lo": lo, "hi": hi}
        spec["alts"] = ["box", "histogram"]
    elif kind == "compare":
        a, b = cols[1], cols[2]
        args.update({"labels": [r[0] for r in rows],
                     "series": [{"name": a, "values": [r[1] for r in rows], "unit": unit},
                                {"name": b, "values": [r[2] for r in rows], "unit": unit}]})  # fmt: skip
        args["type"] = type_ or "bar"
        spec = normalize_spec(args, lang, kind=kind)
        spec["alts"] = ["bar", "line", "hbar"]
        spec["change"] = {"pct": res.get("change_pct"), "totals": res.get("totals")}
    elif kind == "scalar":
        spec = normalize_spec({"title": res.get("title"), "unit": unit, "type": "kpi",
                               "labels": [cols[0] if cols else ""],
                               "series": [{"name": res.get("title"), "values": [res.get("scalar")], "unit": unit}]},
                              lang, kind=kind)  # fmt: skip
    else:
        width = len(cols)
        use = cols[:2] if kind == "share" else cols
        args.update({"columns": use, "rows": [r[: len(use)] for r in rows]})
        if type_:
            args["type"] = type_
        if width > 2 and kind != "share":
            kind2 = "time" if kind == "time" else "pivot"
            spec = normalize_spec(args, lang, kind=kind2)
            if kind2 == "pivot" and spec["type"] == "stacked":
                spec["alts"] = ["stacked", "bar", "hbar"]
        else:
            spec = normalize_spec(args, lang, kind=kind)
        if kind == "time" and len(spec["labels"]) >= 3:
            spec["annotations"] = [{"kind": "max", "label": ""}, {"kind": "min", "label": ""}]
        if kind == "share":
            spec["alts"] = ["donut", "pie", "hbar", "bar"]
    spec["source"] = source
    if source_label:
        spec["source_label"] = _clean(source_label, 80)
    if res.get("folded"):
        spec["notes"].append(f"{res['folded']} groups folded")
    return spec
