"""3 to 5 analyses suggested from the column types, each already computed (no model): the chips of the data card.

« Évolution mensuelle » (a date and a measure), « Total par région » (a short category), « Top 10 clients »
(a long category or an identifier), « Répartition » (a category of at most 6 values), « 2024 vs 2025 » (two years),
« Corrélation prix / volume » (two measures), « Distribution » (a single measure).
"""

from __future__ import annotations

from birds.harness.analysis.ask import main_measure
from birds.harness.analysis.cells import plain
from birds.harness.analysis.charts import chart_from_result
from birds.harness.analysis.profile import Frame, best_grain
from birds.harness.analysis.query import QueryError, run_query

_PERIOD_ADJ = {
    "fr": {"day": "quotidienne", "week": "hebdomadaire", "month": "mensuelle", "quarter": "trimestrielle",
           "year": "annuelle"},
    "en": {"day": "Daily", "week": "Weekly", "month": "Monthly", "quarter": "Quarterly", "year": "Yearly"},
}  # fmt: skip
_PREFERRED = __import__("re").compile(
    r"\b(?:region|zone|secteur|categorie|famille|produit|product|category|type|"
    r"segment|pays|country|canal|channel|service|departement)s?\b"
)
_PRICE = ("prix", "price", "tarif", "pu", "cout", "cost")
_VOLUME = ("quantite", "qte", "volume", "unites", "units", "qty", "quantity", "nombre", "nb")


def _distinct(c) -> int:
    return len({v for v in c.values if v is not None})


def _short(name: str, n: int = 28) -> str:
    import re

    s = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip() or name
    return s if len(s) <= n else s[: n - 1] + "…"


def suggestions(f: Frame, lang: str = "fr", limit: int = 5, source_label: str = "") -> list[dict]:
    """[{id, label, icon, query, result, chart}] computed now; the browser runs them with one click."""
    en = lang == "en"
    m = main_measure(f)
    times = [c for c in f.columns if c.type == "date" and _distinct(c) >= 2]
    dims = sorted([c for c in f.columns if c.type in ("category", "bool") and 2 <= _distinct(c) <= 40],
                  key=lambda c: (_distinct(c) > 12, not _PREFERRED.search(plain(c.name)), _distinct(c)))  # fmt: skip
    longs = [c for c in f.columns if c.type in ("category", "id", "text") and _distinct(c) > 6]
    nums = [c for c in f.columns if c.type == "number"]
    out: list[tuple[str, str, str, dict]] = []  # (id, label, icon, query)
    if m and times:
        t = times[0]
        g = best_grain([v for v in t.values if v is not None], t.grain)
        adj = _PERIOD_ADJ["en" if en else "fr"][g]
        label = f"{adj} trend" if en else f"Évolution {adj}"
        out.append(("trend", label, "line", {"op": "aggregate", "measure": m.name, "agg": "sum", "time": t.name,
                                             "period": g}))  # fmt: skip
    if m and dims:
        d = dims[0]
        label = f"Total by {_short(d.name).lower()}" if en else f"Total par {_short(d.name).lower()}"
        out.append(("by", label, "bar", {"op": "aggregate", "measure": m.name, "agg": "sum", "by": d.name,
                                         "sort": "desc"}))  # fmt: skip
    if m and longs:
        c = next((x for x in longs if x not in dims[:1]), longs[0])
        n = 10 if _distinct(c) > 10 else 5
        word = _short(c.name).lower()
        label = f"Top {n} {word if word.endswith(('s', 'x')) else word + 's'}"
        out.append(("top", label, "rank", {"op": "aggregate", "measure": m.name, "agg": "sum", "by": c.name,
                                           "top": n, "sort": "desc"}))  # fmt: skip
    small = [d for d in dims if _distinct(d) <= 6]
    if small:
        d = next((x for x in small if x is not dims[0]), small[0]) if m else small[0]
        label = f"Share by {_short(d.name).lower()}" if en else f"Répartition par {_short(d.name).lower()}"
        q = {"op": "aggregate", "agg": "sum" if m else "count", "by": d.name, "share": True}
        if m:
            q["measure"] = m.name
        if not any(x[3].get("by") == d.name and x[0] == "by" for x in out) or len(dims) == 1:
            out.append(("share", label, "donut", q))
    if times and m:
        years = sorted({v.year for v in times[0].values if v is not None})
        if len(years) >= 2:
            a, b = years[-2:]
            out.append(("yoy", f"{a} vs {b}", "compare", {"op": "compare", "measure": m.name, "agg": "sum",
                                                          "time": times[0].name, "years": [a, b]}))  # fmt: skip
    if len(nums) >= 2:
        price = next((c for c in nums if any(w in plain(c.name) for w in _PRICE)), None)
        vol = next((c for c in nums if any(w in plain(c.name) for w in _VOLUME) and c is not price), None)
        x, y = (price, vol) if price and vol else (nums[0], nums[1])
        label = f"Correlation {_short(x.name, 14).lower()} / {_short(y.name, 14).lower()}" if en else \
            f"Corrélation {_short(x.name, 14).lower()} / {_short(y.name, 14).lower()}"  # fmt: skip
        out.append(("corr", label, "scatter", {"op": "corr", "x": x.name, "y": y.name}))
    if m and len(out) < 3:
        out.append(("dist", ("Distribution of " if en else "Distribution de ") + _short(m.name).lower(), "box",
                    {"op": "describe", "measure": m.name}))  # fmt: skip
    if not m and dims and not any(x[0] == "share" for x in out):
        d = dims[0]
        out.append(("count", (f"Rows by {d.name}" if en else f"Lignes par {d.name}"), "bar",
                    {"op": "aggregate", "agg": "count", "by": d.name, "sort": "desc"}))  # fmt: skip
    # keep the most useful: trend, by, top, yoy, share, corr, dist (at most ``limit``)
    rank = {"trend": 0, "by": 1, "top": 2, "share": 3, "yoy": 4, "corr": 5, "dist": 6, "count": 7}
    out.sort(key=lambda x: rank[x[0]])
    done = []
    for sid, label, icon, q in out:
        try:
            res = run_query(f, q, lang)
        except QueryError:
            continue
        if not res.get("rows"):
            continue
        chart = chart_from_result(res, lang, "analysis", source_label)
        chart["id"] = f"s-{sid}"
        done.append({"id": sid, "label": label, "icon": icon, "query": res["query"], "result": slim_result(res),
                     "chart": chart})  # fmt: skip
        if len(done) >= limit:
            break
    return done


def slim_result(res: dict, max_rows: int = 30) -> dict:
    keep = {k: res[k] for k in ("title", "kind", "columns", "unit", "n", "total", "change_pct", "r", "strength",
                                "scalar", "totals", "folded") if k in res}  # fmt: skip
    keep["rows"] = (res.get("rows") or [])[:max_rows]
    keep["more"] = max(0, len(res.get("rows") or []) - max_rows)
    return keep
