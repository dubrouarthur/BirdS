"""Typing and profiling the columns of a table: what the data card shows, what the queries and suggestions use.

Types: ``number`` (with ``unit`` « € », « % », « h »…), ``date`` (with the ``grain`` the cells are written at),
``category``, ``bool``, ``id`` and ``text``. Each column also gets a role: ``measure`` (numbers to add up or
average), ``time``, ``dimension`` (categories to group by) or ``key`` (identifiers, free text).
"""

from __future__ import annotations

import datetime as dt
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from birds.harness.analysis.cells import (
    MONTHS,
    as_float,
    bool_column,
    date_order,
    is_gap,
    number_style,
    parse_bool,
    parse_date,
    parse_number,
    plain,
)
from birds.harness.analysis.table import Table

HIST_BINS = 12
_ID_NAME = re.compile(r"^(?:id|code|ref|reference|n|no|num|numero|siren|siret|iban|e-?mail|mail|tel|telephone|"
                      r"uuid|matricule|sku|ean)\b|\b(?:id|n°|no|ref|code)$", re.I)  # fmt: skip
_YEAR_NAME = re.compile(r"\b(?:annee|annees|year|years|an|exercice|millesime)\b")
_MONTH_ONLY = set(MONTHS)
_COUNT_NAME = re.compile(r"\b(?:nombre|nb|qte|quantite|quantity|qty|volume|unites|units|count|effectif)\b")


@dataclass
class Column:
    name: str
    type: str
    values: list  # float | datetime | str | bool | None, one per row
    unit: str = ""
    grain: str = ""  # date columns: day / month / quarter / year
    order: list[str] = field(default_factory=list)  # categories with a natural order (month names)
    decimal: str = ","

    @property
    def role(self) -> str:
        if self.type == "number":
            return "measure"
        if self.type == "date":
            return "time"
        if self.type in ("category", "bool"):
            return "dimension"
        return "key"


@dataclass
class Frame:
    name: str
    columns: list[Column]
    n: int
    meta: dict

    def col(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(name)

    def by_role(self, role: str) -> list[Column]:
        return [c for c in self.columns if c.role == role]


def _month_word(v) -> str | None:
    s = plain(v).rstrip(".") if isinstance(v, str) else ""
    return s if s in _MONTH_ONLY else None


def type_column(name: str, raw: list) -> Column:
    filled = [v for v in raw if not is_gap(v)]
    n = len(filled)
    texts = [v for v in filled if isinstance(v, str)]
    if not n:
        return Column(name, "text", [None] * len(raw))
    pname = plain(name)
    # dates first: real datetimes (Excel) or text that reads as dates
    order = date_order(texts)
    dates, grains = [], Counter()
    for v in raw:
        if is_gap(v):
            dates.append(None)
            continue
        try:
            d, g = parse_date(v, order)
            dates.append(d)
            grains[g] += 1
        except ValueError:
            dates.append(None)
    ok_dates = sum(d is not None for d in dates)
    if ok_dates >= max(1, 0.9 * n) and not all(isinstance(v, int | float) for v in filled):
        grain = grains.most_common(1)[0][0] if grains else "day"
        return Column(name, "date", dates, grain=grain)
    if bool_column(texts) and len(texts) == n:
        return Column(name, "bool", [None if is_gap(v) else parse_bool(v) for v in raw])
    months = [_month_word(v) for v in filled]
    if all(months) and len(set(months)) >= 2:
        values = [None if is_gap(v) else str(v).strip() for v in raw]
        seen = sorted({str(v).strip() for v in filled}, key=lambda s: MONTHS[_month_word(s)])
        return Column(name, "category", values, order=seen)
    style = number_style(texts)
    nums, units = [], Counter()
    for v in raw:
        if is_gap(v):
            nums.append(None)
            continue
        try:
            x, u = parse_number(v, style)
            nums.append(None if x is None else float(x))
            if u:
                units[u] += 1
        except ValueError:
            nums.append(None)
    ok_nums = sum(x is not None for x in nums)
    distinct = len({str(v) for v in filled})
    if ok_nums >= max(1, 0.9 * n):
        ints = all(x is None or x.is_integer() for x in nums)
        if ints and _YEAR_NAME.search(pname) and all(1900 <= x <= 2100 for x in nums if x is not None):
            return Column(name, "date", [None if x is None else dt.datetime(int(x), 1, 1) for x in nums],
                          grain="year")  # fmt: skip
        if ints and (_ID_NAME.search(pname) or (distinct == n and n >= 20 and _sequential(nums))):
            return Column(name, "id", [None if is_gap(v) else _id_text(v) for v in raw])
        unit = units.most_common(1)[0][0] if units else _unit_from_name(name)
        return Column(name, "number", nums, unit=unit, decimal=style)
    values = [None if is_gap(v) else " ".join(str(v).split()) for v in raw]
    if _ID_NAME.search(pname) or (distinct == n and n >= 20 and all(len(str(v)) <= 24 for v in filled)):
        return Column(name, "id", values)
    avg = sum(len(str(v)) for v in filled) / n
    if avg <= 40 and (distinct <= 30 or distinct <= 0.5 * n):
        return Column(name, "category", values)
    return Column(name, "text", values)


def _sequential(nums: list) -> bool:
    xs = [x for x in nums if x is not None]
    # a row number: 0, 1, 2… or 1, 2, 3… (« Montant » 10, 11, 12… is a measure that happens to grow by one)
    return len(xs) >= 20 and xs[0] in (0, 1) and all(b - a == 1 for a, b in zip(xs, xs[1:], strict=False))


def _id_text(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _unit_from_name(name: str) -> str:
    """« CA (k€) », « Montant HT € », « Taux % »: the unit written in the header."""
    m = re.search(r"\(([^)]{1,6})\)\s*$|\[([^\]]{1,6})\]\s*$", name)
    u = (m.group(1) or m.group(2)).strip() if m else ""
    if u:
        return u
    low = name.lower()
    if "€" in low or re.search(r"\beur(os?)?\b", low):
        return "€"
    if "%" in low or re.search(r"\b(taux|pourcentage|part|percent)\b", plain(name)):
        return "%" if "%" in low or "pourcentage" in plain(name) or "percent" in plain(name) else ""
    return ""


def frame_of(table: Table) -> Frame:
    cols = []
    for j, name in enumerate(table.columns):
        cols.append(type_column(name, [r[j] if j < len(r) else None for r in table.rows]))
    return Frame(table.name, cols, len(table.rows), dict(table.meta))


# ---------------------------------------------------------------- statistics


def _r(x: float | None, digits: int = 4) -> float | int | None:
    if x is None or not math.isfinite(x):
        return None
    x = round(x, digits)
    return int(x) if x.is_integer() and abs(x) < 2**53 else x


def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return math.nan
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def histogram(xs: list[float], bins: int = HIST_BINS) -> tuple[list[int], float, float]:
    lo, hi = min(xs), max(xs)
    if hi == lo:
        return [len(xs)], lo, hi
    counts = [0] * bins
    w = (hi - lo) / bins
    for x in xs:
        counts[min(bins - 1, int((x - lo) / w))] += 1
    return counts, lo, hi


def number_stats(xs: list[float]) -> dict:
    if not xs:
        return {}
    q1, q3 = quantile(xs, 0.25), quantile(xs, 0.75)
    iqr = q3 - q1
    lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    out_lo = [x for x in xs if x < lo_f] if iqr > 0 else []
    out_hi = [x for x in xs if x > hi_f] if iqr > 0 else []
    return {
        "min": _r(min(xs)),
        "max": _r(max(xs)),
        "mean": _r(statistics.fmean(xs)),
        "median": _r(statistics.median(xs)),
        "sum": _r(math.fsum(xs)),
        "std": _r(statistics.pstdev(xs)) if len(xs) > 1 else 0,
        "q1": _r(q1),
        "q3": _r(q3),
        "outliers": {
            "n": len(out_lo) + len(out_hi),
            "low": [_r(x) for x in sorted(out_lo)[:3]],
            "high": [_r(x) for x in sorted(out_hi)[-3:]],
        },  # fmt: skip
        "negative": sum(x < 0 for x in xs),
    }


def _period_key(d: dt.datetime, grain: str) -> dt.datetime:
    if grain == "year":
        return dt.datetime(d.year, 1, 1)
    if grain == "quarter":
        return dt.datetime(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    if grain == "month":
        return dt.datetime(d.year, d.month, 1)
    if grain == "week":
        return dt.datetime.combine((d - dt.timedelta(days=d.weekday())).date(), dt.time())
    return dt.datetime(d.year, d.month, d.day)


def best_grain(dates: list[dt.datetime], cell_grain: str = "day") -> str:
    """The resample grain that gives a readable series: months for one to three years of daily data, etc."""
    if not dates:
        return "month"
    span = (max(dates) - min(dates)).days
    rank = {"day": 0, "week": 1, "month": 2, "quarter": 3, "year": 4}
    want = "day" if span <= 45 else "week" if span <= 120 else "month" if span <= 1100 else \
        "quarter" if span <= 2600 else "year"  # fmt: skip
    return want if rank[want] >= rank.get(cell_grain, 0) else cell_grain


def profile_column(c: Column, n: int) -> dict:
    filled = [v for v in c.values if v is not None]
    out = {"name": c.name, "type": c.type, "role": c.role, "unit": c.unit, "count": len(filled),
           "missing": n - len(filled), "distinct": len({str(v) for v in filled})}  # fmt: skip
    if c.type == "number" and filled:
        st = number_stats(filled)
        out["stats"] = st
        counts, lo, hi = histogram(filled)
        out["hist"] = counts
        out["range"] = [_r(lo), _r(hi)]
        out["integer"] = all(float(x).is_integer() for x in filled)
    elif c.type == "date" and filled:
        lo, hi = min(filled), max(filled)
        grain = best_grain(filled, c.grain)
        buckets = Counter(_period_key(d, grain) for d in filled)
        keys = sorted(buckets)
        out["span"] = {"start": lo.isoformat()[:10], "end": hi.isoformat()[:10], "days": (hi - lo).days,
                       "grain": c.grain, "resample": grain, "periods": len(keys)}  # fmt: skip
        out["spark"] = [buckets[k] for k in keys][-48:]
    elif c.type in ("category", "bool", "id", "text") and filled:
        counter = Counter(str(v) for v in filled)
        top = counter.most_common(6)
        out["top"] = [[k, v] for k, v in top]
        out["other"] = len(filled) - sum(v for _, v in top)
        if c.type == "text":
            out["avg_len"] = _r(sum(len(str(v)) for v in filled) / len(filled), 1)
    if c.order:
        out["order"] = c.order
    return out


def profile_table(table_or_frame) -> dict:
    """The JSON-safe profile of a table: rows × columns, one entry per column, notes about how it was read."""
    f = table_or_frame if isinstance(table_or_frame, Frame) else frame_of(table_or_frame)
    cols = [profile_column(c, f.n) for c in f.columns]
    missing = sum(c["missing"] for c in cols)
    meta = {k: v for k, v in f.meta.items() if k != "total_cells"}
    return {
        "name": f.name,
        "rows": f.n,
        "cols": len(cols),
        "columns": cols,
        "missing": missing,
        "complete": _r(1 - missing / max(1, f.n * len(cols)), 4),
        "meta": meta,
    }


def numeric(c: Column) -> list[float]:
    return [v for v in c.values if isinstance(v, float)]


__all__ = ["Column", "Frame", "as_float", "best_grain", "frame_of", "profile_table", "quantile", "type_column"]
