"""A tiny, safe query over a profiled table: filter, group by a category or a period, aggregate, sort, top-n, pivot,
year-over-year comparison and correlation. A query is plain JSON (never code); every column it names must exist and
every operation is from a fixed list, so a question can be turned into one without any risk.

    {"op": "aggregate", "measure": "CA", "agg": "sum", "by": "Région", "sort": "desc", "top": 5}
    {"op": "aggregate", "measure": "CA", "agg": "mean", "time": "Date", "period": "month"}
    {"op": "compare", "measure": "CA", "time": "Date", "years": [2024, 2025], "by": "Produit"}
    {"op": "corr", "x": "Prix", "y": "Volume"}
    {"op": "aggregate", "measure": "CA", "agg": "sum", "time": "Date", "period": "month", "window": 3, "change": true}

``window`` adds a moving average over that many periods, ``change`` the percent change from the previous period
(both on a time series without pivot). The model writes such a query as structured output (``planner.py``); the
harness checks it here and computes it: no code from the model is ever run.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import defaultdict

from birds.harness.analysis.cells import fmt_period, plain
from birds.harness.analysis.profile import Column, Frame, _period_key, _r, best_grain

AGGS = ("sum", "mean", "median", "count", "min", "max", "distinct")
OPS = ("aggregate", "compare", "corr", "describe")
FILTER_OPS = ("eq", "ne", "gt", "ge", "lt", "le", "in", "contains", "year", "between")
PERIODS = ("day", "week", "month", "quarter", "year")
MAX_GROUPS = 60
MAX_TOP = 50
MAX_WINDOW = 24
_AGG_FR = {"sum": "Total", "mean": "Moyenne", "median": "Médiane", "count": "Nombre", "min": "Minimum",
           "max": "Maximum", "distinct": "Nombre distinct"}  # fmt: skip
_AGG_EN = {"sum": "Total", "mean": "Average", "median": "Median", "count": "Count", "min": "Minimum",
           "max": "Maximum", "distinct": "Distinct count"}  # fmt: skip
_PERIOD_FR = {"day": "jour", "week": "semaine", "month": "mois", "quarter": "trimestre", "year": "année"}
_PERIOD_EN = {"day": "day", "week": "week", "month": "month", "quarter": "quarter", "year": "year"}


class QueryError(ValueError):
    pass


def _col(f: Frame, name, kinds: tuple[str, ...] | None = None) -> Column:
    if not isinstance(name, str):
        raise QueryError("a column name is missing")
    for c in f.columns:
        if c.name == name:
            if kinds and c.type not in kinds:
                raise QueryError(f"column '{name}' is {c.type}, expected {' or '.join(kinds)}")
            return c
    key = plain(name)
    for c in f.columns:
        if plain(c.name) == key:
            return _col(f, c.name, kinds)
    raise QueryError(f"unknown column '{name}'. Columns: {', '.join(c.name for c in f.columns)}")


def _match(v, op: str, target) -> bool:
    if v is None:
        return False
    if op == "year":
        return isinstance(v, dt.datetime) and v.year == int(target)
    if op == "between":
        lo, hi = target
        return _cmp(v, lo) >= 0 and _cmp(v, hi) <= 0
    if op in ("eq", "ne", "in", "contains") and not isinstance(v, float | dt.datetime):
        sv = plain(v)
        if op == "contains":
            return plain(target) in sv
        if op == "in":
            return sv in {plain(t) for t in target}
        return (sv == plain(target)) == (op == "eq")
    c = _cmp(v, target)
    return {"eq": c == 0, "ne": c != 0, "gt": c > 0, "ge": c >= 0, "lt": c < 0, "le": c <= 0}.get(op, False)


def _cmp(v, target) -> int:
    if isinstance(v, dt.datetime):
        if isinstance(target, int | float):
            target = dt.datetime(int(target), 1, 1)
        elif isinstance(target, str):
            target = dt.datetime.fromisoformat(target[:10])
    elif isinstance(v, float):
        target = float(target)
    else:
        v, target = plain(v), plain(target)
    return (v > target) - (v < target)


def _rows_kept(f: Frame, filters) -> list[int]:
    keep = list(range(f.n))
    for flt in filters or []:
        if not isinstance(flt, dict) or flt.get("op") not in FILTER_OPS:
            raise QueryError("a filter needs {col, op, value} with op in " + ", ".join(FILTER_OPS))
        c = _col(f, flt.get("col"))
        keep = [i for i in keep if _match(c.values[i], flt["op"], flt.get("value"))]
    return keep


def _agg(xs: list, agg: str) -> float | None:
    if agg == "count":
        return float(len(xs))
    if agg == "distinct":
        return float(len(set(xs)))
    nums = [x for x in xs if isinstance(x, float)]
    if not nums:
        return None
    if agg == "sum":
        return math.fsum(nums)
    if agg == "mean":
        return statistics.fmean(nums)
    if agg == "median":
        return statistics.median(nums)
    if agg == "min":
        return min(nums)
    if agg == "max":
        return max(nums)
    raise QueryError(f"unknown aggregate '{agg}'")


def _label_of(v, c: Column, grain: str, lang: str) -> tuple[object, str]:
    """(sort key, label) of one group."""
    if isinstance(v, dt.datetime):
        k = _period_key(v, grain)
        return k, fmt_period(k, grain, lang)
    if isinstance(v, bool):
        return (not v), ("Oui" if v else "Non") if lang != "en" else ("Yes" if v else "No")
    if c.order and v in c.order:
        return c.order.index(v), str(v)
    return plain(v), str(v)


def _names(lang: str):
    return (_AGG_EN, _PERIOD_EN) if lang == "en" else (_AGG_FR, _PERIOD_FR)


def _title(q: dict, lang: str) -> str:
    aggs, periods = _names(lang)
    measure = q.get("measure")
    by = q.get("by")
    period = q.get("period")
    if q["agg"] in ("count", "distinct") and not measure:
        head = "Nombre de lignes" if lang != "en" else "Row count"
    elif q["agg"] == "sum":
        head = f"{aggs['sum']} {measure}"
    elif lang == "en":
        head = f"{aggs[q['agg']]} {measure}"
    else:
        de = "d'" if plain(str(measure))[:1] in "aeiouyh" else "de "
        head = f"{aggs[q['agg']]} {de}{measure}"
    word = " by " if lang == "en" else " par "
    if q.get("top"):
        if not by:
            return head
        flop = q.get("sort") == "asc"
        lead = ("Bottom" if lang == "en" else "Flop") if flop else "Top"
        return f"{lead} {q['top']} {by}{word}{measure}" if measure else f"{lead} {q['top']} {by}"
    if period:
        head += word + periods[period]
    if by:
        head += (" and " if lang == "en" else " et ") + by if period else word + by
    return head


def normalize(f: Frame, q: dict) -> dict:
    """The query checked and completed (column names resolved, defaults set). Raises QueryError."""
    if not isinstance(q, dict):
        raise QueryError("a query is an object")
    op = q.get("op", "aggregate")
    if op not in OPS:
        raise QueryError(f"op must be one of {', '.join(OPS)}")
    out: dict = {"op": op}
    if q.get("filters"):
        _rows_kept(f, q["filters"])  # validates
        out["filters"] = [dict(x) for x in q["filters"]]
    if op == "corr":
        out["x"] = _col(f, q.get("x"), ("number",)).name
        out["y"] = _col(f, q.get("y"), ("number",)).name
        if out["x"] == out["y"]:
            raise QueryError("a correlation needs two different columns")
        return out
    if op == "describe":
        out["measure"] = _col(f, q.get("measure"), ("number",)).name
        return out
    agg = q.get("agg", "sum")
    if agg not in AGGS:
        raise QueryError(f"agg must be one of {', '.join(AGGS)}")
    measure = q.get("measure")
    if measure is not None:
        mc = _col(f, measure, ("number",) if agg not in ("count", "distinct") else None)
        out["measure"] = mc.name
    elif agg not in ("count", "distinct"):
        raise QueryError(f"'{agg}' needs a numeric measure column")
    out["agg"] = agg
    if q.get("by"):
        out["by"] = _col(f, q["by"]).name
    if q.get("period") or op == "compare":
        t = _col(f, q.get("time") or next((c.name for c in f.columns if c.type == "date"), None), ("date",))
        out["time"] = t.name
        period = q.get("period")
        if period is not None and period not in PERIODS:
            raise QueryError(f"period must be one of {', '.join(PERIODS)}")
        dates = [v for v in t.values if v is not None]
        out["period"] = period or (best_grain(dates, t.grain) if op != "compare" else "month")
    if q.get("pivot"):
        out["pivot"] = _col(f, q["pivot"], ("category", "bool", "date")).name
    if op == "compare":
        years = q.get("years") or []
        t = f.col(out["time"])
        have = sorted({v.year for v in t.values if v is not None})
        if not years:
            years = have[-2:]
        if len(years) != 2 or any(int(y) not in have for y in years):
            raise QueryError(f"compare needs two years present in the data ({', '.join(map(str, have))})")
        out["years"] = [int(y) for y in years]
    sort = q.get("sort")
    if sort not in (None, "desc", "asc", "natural"):
        raise QueryError("sort must be desc, asc or natural")
    out["sort"] = sort or ("natural" if out.get("period") else "desc")
    if q.get("top") is not None:
        try:
            top = int(q["top"])
        except (TypeError, ValueError):
            raise QueryError("top must be a whole number") from None
        if not 1 <= top <= MAX_TOP:
            raise QueryError(f"top must be between 1 and {MAX_TOP}")
        out["top"] = top
    if q.get("share"):
        out["share"] = True
    for key in ("window", "change"):
        if q.get(key) in (None, False, 0):
            continue
        if not out.get("period") or out.get("pivot") or out.get("by") or op != "aggregate":
            raise QueryError(f"{key} needs a time series: op aggregate with time and period, no by, no pivot")
        if key == "change":
            out["change"] = True
            continue
        try:
            w = int(q["window"])
        except (TypeError, ValueError):
            raise QueryError("window must be a whole number of periods") from None
        if not 2 <= w <= MAX_WINDOW:
            raise QueryError(f"window must be between 2 and {MAX_WINDOW}")
        out["window"] = w
    return out


def run_query(f: Frame, q: dict, lang: str = "fr") -> dict:
    """Run a query. The result is JSON-safe: {title, kind, columns, rows, unit, scalar?, n, query, facts}."""
    q = normalize(f, q)
    keep = _rows_kept(f, q.get("filters"))
    if q["op"] == "corr":
        return _corr(f, q, keep, lang)
    if q["op"] == "describe":
        return _describe(f, q, keep, lang)
    if q["op"] == "compare":
        return _compare(f, q, keep, lang)
    measure = f.col(q["measure"]) if q.get("measure") else None
    unit = measure.unit if measure and q["agg"] not in ("count", "distinct") else ""
    vals = (lambda i: measure.values[i]) if measure else (lambda i: 1.0)
    aggs, periods = _names(lang)
    title = _title(q, lang)
    value_name = (measure.name if measure else ("Lignes" if lang != "en" else "Rows")) if q["agg"] != "count" \
        else ("Nombre" if lang != "en" else "Count")  # fmt: skip
    if q["agg"] not in ("sum", "count") and measure:
        value_name = f"{measure.name} ({aggs[q['agg']].lower()})"
    keys = []
    if q.get("period"):
        keys.append((f.col(q["time"]), q["period"]))
    if q.get("by"):
        keys.append((f.col(q["by"]), ""))
    if not keys:  # one number
        xs = [vals(i) for i in keep if vals(i) is not None or q["agg"] == "count"]
        v = _agg(xs, q["agg"])
        return {"title": title, "kind": "scalar", "columns": [aggs[q["agg"]], value_name],
                "rows": [[aggs[q["agg"]], _r(v)]], "unit": unit, "scalar": _r(v), "n": len(keep), "query": q,
                "facts": [f"{title}: {_r(v)}{(' ' + unit) if unit else ''} ({len(keep)} rows)"]}  # fmt: skip
    pivot = f.col(q["pivot"]) if q.get("pivot") else None
    if pivot is None and len(keys) == 2:
        pivot, keys = keys[1][0], keys[:1]
    kc, grain = keys[0]
    groups: dict = defaultdict(list)
    labels: dict = {}
    series_keys: dict = {}
    for i in keep:
        v = kc.values[i]
        if v is None:
            continue
        k, label = _label_of(v, kc, grain, lang)
        labels[k] = label
        if pivot is not None:
            pv = pivot.values[i]
            if pv is None:
                continue
            pk, plabel = _label_of(pv, pivot, best_grain([x for x in pivot.values if x is not None], pivot.grain)
                                   if pivot.type == "date" else "", lang)  # fmt: skip
            series_keys[pk] = plabel
            groups[(k, pk)].append(vals(i))
        else:
            groups[k].append(vals(i))
    if pivot is not None:
        skeys = sorted(series_keys)[:6]
        rows = []
        for k in sorted(labels):
            row = [labels[k]]
            for pk in skeys:
                xs = [x for x in groups.get((k, pk), []) if x is not None or q["agg"] == "count"]
                row.append(_r(_agg(xs, q["agg"])) if xs else None)
            rows.append(row)
        columns = [kc.name if not grain else periods[grain].capitalize(), *[series_keys[k] for k in skeys]]
    else:
        rows = []
        for k in labels:
            xs = [x for x in groups[k] if x is not None or q["agg"] == "count"]
            rows.append((k, [labels[k], _r(_agg(xs, q["agg"]))]))
        if q["sort"] == "natural" or grain:
            rows.sort(key=lambda kr: kr[0])
        else:
            rows.sort(key=lambda kr: (kr[1][1] is None, -(kr[1][1] or 0) if q["sort"] == "desc" else (kr[1][1] or 0)))
        rows = [r for _, r in rows]
        columns = [kc.name if not grain else periods[grain].capitalize(), value_name]
    folded = 0
    if q.get("top"):
        rows = rows[: q["top"]]
    elif len(rows) > MAX_GROUPS and not grain:
        folded = len(rows) - (MAX_GROUPS - 1)
        rest = rows[MAX_GROUPS - 1 :]
        rows = rows[: MAX_GROUPS - 1]
        if q["agg"] in ("sum", "count") and pivot is None:
            rows.append([("Autres" if lang != "en" else "Other"), _r(math.fsum(r[1] or 0 for r in rest))])
    elif len(rows) > 400:
        rows, folded = rows[-400:], len(rows) - 400
    kind = "time" if grain else "ranking" if q.get("top") or q["sort"] in ("desc", "asc") else "category"
    out = {"title": title, "kind": kind, "columns": columns, "rows": rows, "unit": unit, "n": len(keep),
           "query": q, "folded": folded}  # fmt: skip
    if q.get("share") and pivot is None:
        total = math.fsum(r[1] or 0 for r in rows)
        if total > 0:
            out["columns"] = [*columns, "Part (%)" if lang != "en" else "Share (%)"]
            out["rows"] = [[*r, _r(100 * (r[1] or 0) / total, 1)] for r in rows]
            out["kind"] = "share"
    if pivot is None and grain and (q.get("window") or q.get("change")):
        _time_extras(out, q, lang)
    if pivot is None and rows:
        total = math.fsum(r[1] or 0 for r in rows if isinstance(r[1], int | float))
        if q["agg"] in ("sum", "count"):
            out["total"] = _r(total)
        best = max((r for r in rows if r[1] is not None), key=lambda r: r[1], default=None)
        worst = min((r for r in rows if r[1] is not None), key=lambda r: r[1], default=None)
        out["facts"] = [f"{title}: {len(rows)} groups", f"highest: {best[0]} = {best[1]}" if best else "",
                        f"lowest: {worst[0]} = {worst[1]}" if worst else ""]  # fmt: skip
        if grain and len(rows) >= 2 and rows[0][1] not in (None, 0) and rows[-1][1] is not None:
            change = _r(100 * (rows[-1][1] - rows[0][1]) / abs(rows[0][1]), 1)
            out["change_pct"] = change
            out["facts"].append(f"change from {rows[0][0]} to {rows[-1][0]}: {change} %")
        out["facts"] = [x for x in out["facts"] if x]
    else:
        out["facts"] = [f"{title}: {len(rows)} rows × {len(out['columns']) - 1} series"]
    return out


def _time_extras(out: dict, q: dict, lang: str) -> None:
    """A moving average over ``window`` periods and / or the percent change from the previous period, as extra
    columns of a time series (first periods without enough history stay empty)."""
    rows = out["rows"]
    vals = [r[1] for r in rows]
    cols = list(out["columns"])
    if q.get("window"):
        w = q["window"]
        cols.append(f"Moyenne mobile ({w})" if lang != "en" else f"Moving average ({w})")
        for i, r in enumerate(rows):
            win = vals[i - w + 1 : i + 1] if i >= w - 1 else []
            r.append(_r(statistics.fmean(win)) if win and all(v is not None for v in win) else None)
    if q.get("change"):
        cols.append("Évolution (%)" if lang != "en" else "Change (%)")
        for i, r in enumerate(rows):
            prev = vals[i - 1] if i else None
            r.append(_r(100 * (vals[i] - prev) / abs(prev), 1) if prev not in (None, 0) and vals[i] is not None
                     else None)  # fmt: skip
    out["columns"] = cols
    out["kind"] = "time"


def _compare(f: Frame, q: dict, keep: list[int], lang: str) -> dict:
    t = f.col(q["time"])
    measure = f.col(q["measure"]) if q.get("measure") else None
    a, b = q["years"]
    aggs, periods = _names(lang)
    by = f.col(q["by"]) if q.get("by") else None
    groups: dict = defaultdict(list)
    labels: dict = {}
    for i in keep:
        d = t.values[i]
        if d is None or d.year not in (a, b):
            continue
        if by is not None:
            v = by.values[i]
            if v is None:
                continue
            k, label = _label_of(v, by, "", lang)
        else:
            grain = q["period"] if q["period"] in ("month", "quarter", "week") else "month"
            pk = _period_key(d, grain)
            if grain == "month":
                k, label = pk.month, fmt_period(pk, "month", lang).rsplit(" ", 1)[0]
            elif grain == "quarter":
                k, label = (pk.month - 1) // 3 + 1, f"{'T' if lang != 'en' else 'Q'}{(pk.month - 1) // 3 + 1}"
            else:
                k, label = pk.isocalendar()[1], f"{'S' if lang != 'en' else 'W'}{pk.isocalendar()[1]:02d}"
        labels[k] = label
        groups[(k, d.year)].append(measure.values[i] if measure else 1.0)
    agg = q["agg"]
    rows = []
    for k in sorted(labels):
        va = _agg([x for x in groups.get((k, a), []) if x is not None], agg) if groups.get((k, a)) else None
        vb = _agg([x for x in groups.get((k, b), []) if x is not None], agg) if groups.get((k, b)) else None
        delta = _r(100 * (vb - va) / abs(va), 1) if va not in (None, 0) and vb is not None else None
        rows.append([labels[k], _r(va), _r(vb), delta])
    if by is not None and q.get("sort") == "desc":
        rows.sort(key=lambda r: -(r[2] or 0))
    if q.get("top"):
        rows = rows[: q["top"]]
    ta = _agg([x for k in labels for x in groups.get((k, a), []) if x is not None], agg)
    tb = _agg([x for k in labels for x in groups.get((k, b), []) if x is not None], agg)
    change = _r(100 * (tb - ta) / abs(ta), 1) if ta not in (None, 0) and tb is not None else None
    name = measure.name if measure else ("Lignes" if lang != "en" else "Rows")
    title = (f"{name} : {a} vs {b}" if lang != "en" else f"{name}: {a} vs {b}") + \
        ((" par " if lang != "en" else " by ") + by.name if by else "")  # fmt: skip
    var = "Évolution (%)" if lang != "en" else "Change (%)"
    return {"title": title, "kind": "compare", "columns": [by.name if by else periods["month"].capitalize(),
            str(a), str(b), var], "rows": rows, "unit": measure.unit if measure else "", "n": len(keep), "query": q,
            "totals": [_r(ta), _r(tb)], "change_pct": change,
            "facts": [f"{agg} {name} {a}: {_r(ta)}", f"{agg} {name} {b}: {_r(tb)}",
                      f"change {a}->{b}: {change} %" if change is not None else ""]}  # fmt: skip


def _corr(f: Frame, q: dict, keep: list[int], lang: str) -> dict:
    x, y = f.col(q["x"]), f.col(q["y"])
    pts = [(x.values[i], y.values[i]) for i in keep if x.values[i] is not None and y.values[i] is not None]
    r = None
    if len(pts) >= 3:
        try:
            r = statistics.correlation([p[0] for p in pts], [p[1] for p in pts])
        except statistics.StatisticsError:
            r = None
    label = next((c for c in f.columns if c.type in ("category", "id")), None)
    rows = []
    for i in keep:
        if x.values[i] is None or y.values[i] is None:
            continue
        rows.append([str(label.values[i]) if label and label.values[i] is not None else str(i + 1),
                     _r(x.values[i]), _r(y.values[i])])  # fmt: skip
        if len(rows) >= 2000:
            break
    strength = "" if r is None else ("forte" if abs(r) >= 0.7 else "moyenne" if abs(r) >= 0.4 else "faible") \
        if lang != "en" else ("strong" if abs(r) >= 0.7 else "moderate" if abs(r) >= 0.4 else "weak")  # fmt: skip
    title = f"{'Corrélation' if lang != 'en' else 'Correlation'} {x.name} / {y.name}"
    return {"title": title, "kind": "scatter", "columns": [label.name if label else "#", x.name, y.name],
            "rows": rows, "unit": "", "units": [x.unit, y.unit], "n": len(pts), "query": q, "r": _r(r, 3),
            "strength": strength, "facts": [f"Pearson r = {_r(r, 3)} over {len(pts)} rows ({strength})"]}  # fmt: skip


def _describe(f: Frame, q: dict, keep: list[int], lang: str) -> dict:
    from birds.harness.analysis.profile import number_stats

    c = f.col(q["measure"])
    st = number_stats([c.values[i] for i in keep if c.values[i] is not None])
    names = [("min", "Minimum"), ("q1", "1er quartile" if lang != "en" else "1st quartile"),
             ("median", "Médiane" if lang != "en" else "Median"), ("mean", "Moyenne" if lang != "en" else "Mean"),
             ("q3", "3e quartile" if lang != "en" else "3rd quartile"), ("max", "Maximum")]  # fmt: skip
    rows = [[label, st.get(k)] for k, label in names]
    return {"title": f"{'Distribution' if lang == 'en' else 'Distribution de'} {c.name}", "kind": "describe",
            "columns": ["Statistique" if lang != "en" else "Statistic", c.name], "rows": rows, "unit": c.unit,
            "n": len(keep), "query": q, "stats": st, "values": [c.values[i] for i in keep if c.values[i] is not None],
            "facts": [f"{k}: {v}" for k, v in rows]}  # fmt: skip


def result_numbers(res: dict) -> list[float]:
    """Every number of a result (cells, totals, changes, scalar): what an answer may quote."""
    out = []
    for r in res.get("rows") or []:
        out.extend(float(v) for v in r[1:] if isinstance(v, int | float) and not isinstance(v, bool))
        if isinstance(r[0], int | float):
            out.append(float(r[0]))
    for k in ("scalar", "total", "change_pct", "r", "n"):
        if isinstance(res.get(k), int | float):
            out.append(float(res[k]))
    out.extend(float(v) for v in res.get("totals") or [] if isinstance(v, int | float))
    out.extend(float(v) for v in (res.get("stats") or {}).values() if isinstance(v, int | float))
    return out
