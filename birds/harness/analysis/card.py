"""The data card (a widget computed by the harness) and the sentences that state a computed result.

The card carries the profile, the first rows, the totals and the suggested analyses with their results and charts,
so every chip runs at once in the browser; the whole table is fetched on demand (``birds.web.data_api``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from birds.harness.analysis.cells import fmt_value
from birds.harness.analysis.profile import Frame, _r

SAMPLE_ROWS = 60
MAX_CARD_BYTES = 60_000


def cell_out(v):
    """A typed cell for the browser: numbers stay numbers, dates become 'YYYY-MM-DD', the rest text."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return _r(v, 6)
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d") if not (v.hour or v.minute) else v.strftime("%Y-%m-%d %H:%M")
    return str(v)


def table_rows(f: Frame, limit: int | None = None) -> list[list]:
    n = f.n if limit is None else min(limit, f.n)
    return [[cell_out(c.values[i]) for c in f.columns] for i in range(n)]


def totals(f: Frame) -> list:
    """The footer of the table: the sum of each measure (not of percentages or prices), the count otherwise."""
    out = []
    for c in f.columns:
        if c.type == "number":
            xs = [v for v in c.values if v is not None]
            additive = c.unit != "%" and not any(w in c.name.lower() for w in ("prix", "price", "taux", "rate", "pu "))
            out.append({"sum": _r(sum(xs))} if additive else {"mean": _r(sum(xs) / len(xs)) if xs else None})
        else:
            out.append({"count": sum(v is not None for v in c.values)})
    return out


def card_id(name: str, f: Frame) -> str:
    h = hashlib.sha256(f"{name}|{f.n}|{[c.name for c in f.columns]}".encode()).hexdigest()
    return "d" + h[:12]


def build_card(f: Frame, profile: dict, suggestions: list[dict], *, name: str, origin: str = "attachment",
               lang: str = "fr", answer: dict | None = None) -> dict:  # fmt: skip
    """The JSON-safe ``datacard`` widget. ``origin``: attachment (fetch the full table by file name) or pasted."""
    card = {
        "type": "datacard",
        "id": card_id(name, f),
        "name": name,
        "origin": origin,
        "rows": f.n,
        "cols": len(f.columns),
        "columns": profile["columns"],
        "complete": profile.get("complete"),
        "meta": profile.get("meta", {}),
        "sample": table_rows(f, SAMPLE_ROWS),
        "totals": totals(f),
        "suggestions": suggestions,
        "lang": lang,
    }
    if answer:
        card["answer"] = answer  # the question's own result: the chip that is shown open
    if f.n <= SAMPLE_ROWS:
        card["complete_rows"] = True
    while len(json.dumps(card, ensure_ascii=False)) > MAX_CARD_BYTES and len(card["sample"]) > 10:
        card["sample"] = card["sample"][: len(card["sample"]) // 2]
        card.pop("complete_rows", None)
    return card


# ---------------------------------------------------------------- stating a result


def _v(v, unit, lang):
    return fmt_value(v, unit, lang) if isinstance(v, int | float) else "—"


def explain(res: dict, lang: str = "fr") -> str:
    """A short, exact statement of a computed result (used when there is no model, or when the model's numbers do
    not match the result)."""
    en = lang == "en"
    unit = res.get("unit") or ""
    rows = res.get("rows") or []
    title = res.get("title") or ""
    kind = res.get("kind")
    if kind == "scalar":
        return f"**{title}** : {_v(res.get('scalar'), unit, lang)}" + (
            f" ({res.get('n')} lignes)" if not en else f" ({res.get('n')} rows)"
        )
    if kind == "scatter":
        r = res.get("r")
        if r is None:
            return f"**{title}** : " + ("pas assez de points." if not en else "not enough points.")
        return (f"**{title}** : r = {fmt_value(r, '', lang)}, " + (
            f"corrélation {res.get('strength')} sur {res.get('n')} lignes." if not en else
            f"{res.get('strength')} correlation over {res.get('n')} rows."))  # fmt: skip
    if kind == "describe":
        st = res.get("stats") or {}
        return (f"**{title}** : " + ("médiane" if not en else "median") + f" {_v(st.get('median'), unit, lang)}, "
                + ("moyenne" if not en else "mean") + f" {_v(st.get('mean'), unit, lang)}, "
                + ("de" if not en else "from") + f" {_v(st.get('min'), unit, lang)} "
                + ("à" if not en else "to") + f" {_v(st.get('max'), unit, lang)}.")  # fmt: skip
    if kind == "compare":
        cols = res.get("columns") or ["", "A", "B"]
        ta, tb = (res.get("totals") or [None, None])[:2]
        ch = res.get("change_pct")
        s = f"**{title}** : {cols[1]} {_v(ta, unit, lang)}, {cols[2]} {_v(tb, unit, lang)}"
        if ch is not None:
            s += f" ({'+' if ch > 0 else ''}{fmt_value(ch, '%', lang)})"
        return s + "."
    if not rows:
        return f"**{title}** : " + ("aucune ligne ne correspond." if not en else "no row matches.")
    if len(rows[0]) > 2 and kind != "share":
        return f"**{title}** : " + (
            f"{len(rows)} lignes × {len(rows[0]) - 1} séries, détail dans le tableau."
            if not en
            else f"{len(rows)} rows × {len(rows[0]) - 1} series, see the table."
        )
    vals = [r for r in rows if isinstance(r[1], int | float)]
    if not vals:
        return f"**{title}**."
    if kind == "time":
        hi = max(vals, key=lambda r: r[1])
        lo = min(vals, key=lambda r: r[1])
        ch = res.get("change_pct")
        s = (f"**{title}** : " + ("pic en" if not en else "peak in") + f" {hi[0]} ({_v(hi[1], unit, lang)}), "
             + ("creux en" if not en else "low in") + f" {lo[0]} ({_v(lo[1], unit, lang)})")  # fmt: skip
        if ch is not None and len(vals) >= 2:
            s += ("; de" if not en else "; from") + f" {rows[0][0]} " + ("à" if not en else "to") + \
                f" {rows[-1][0]} : {'+' if ch > 0 else ''}{fmt_value(ch, '%', lang)}"  # fmt: skip
        return s + "."
    first = vals[0]
    s = (
        f"**{title}** : {first[0]} "
        + ("arrive en tête avec" if not en else "leads with")
        + f" {_v(first[1], unit, lang)}"
    )
    if kind == "share" and len(first) > 2:
        s += f" ({fmt_value(first[2], '%', lang)})"
    if len(vals) > 1:
        second = vals[1]
        s += (", devant" if not en else ", ahead of") + f" {second[0]} ({_v(second[1], unit, lang)})"
    if res.get("total") is not None and kind in ("share", "category", "ranking") and not res["query"].get("top"):
        s += ("; total" if not en else "; total") + f" {_v(res['total'], unit, lang)}"
    return s + "."


def _exact(v, lang: str) -> str:
    from birds.harness.analysis.cells import fmt_number

    return fmt_number(v, lang, 0 if float(v).is_integer() else 2)


def result_text(res: dict, lang: str = "fr", max_rows: int = 24) -> str:
    """The result as compact text lines for the model (what it may quote)."""
    cols = res.get("columns") or []
    lines = [" | ".join(str(c) for c in cols)]
    for r in (res.get("rows") or [])[:max_rows]:
        lines.append(" | ".join("—" if v is None else (_exact(v, lang) if isinstance(v, int | float) else str(v))
                                for v in r))  # fmt: skip
    more = len(res.get("rows") or []) - max_rows
    if more > 0:
        lines.append(f"… (+{more})")
    extra = []
    for k, label in (("total", "total"), ("change_pct", "évolution %" if lang != "en" else "change %"),
                     ("scalar", "valeur" if lang != "en" else "value"), ("r", "r")):  # fmt: skip
        if isinstance(res.get(k), int | float):
            extra.append(f"{label} = {fmt_value(res[k], '', lang)}")
    if res.get("totals"):
        extra.append(" / ".join(fmt_value(x, "", lang) for x in res["totals"] if isinstance(x, int | float)))
    return "\n".join(lines + extra)


def profile_text(profile: dict, lang: str = "fr") -> str:
    """What the model may say about a table it was not asked to compute anything on."""
    en = lang == "en"
    parts = [f"{profile['rows']} " + ("lignes" if not en else "rows") + f" × {profile['cols']} " +
             ("colonnes" if not en else "columns")]  # fmt: skip
    for c in profile["columns"][:14]:
        d = f"{c['name']} ({c['type']}{', ' + c['unit'] if c.get('unit') else ''}"
        st = c.get("stats")
        if st:
            d += f", min {fmt_value(st['min'], '', lang)}, max {fmt_value(st['max'], '', lang)}, " + \
                ("total" if not en else "sum") + f" {fmt_value(st['sum'], '', lang)}"  # fmt: skip
        elif c.get("span"):
            d += f", {c['span']['start']} → {c['span']['end']}"
        elif c.get("top"):
            d += ", " + ", ".join(str(k) for k, _ in c["top"][:3])
        if c.get("missing"):
            d += f", {c['missing']} " + ("vides" if not en else "empty")
        parts.append(d + ")")
    return "\n".join(parts)
