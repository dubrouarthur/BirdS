"""Where the numbers of a chart come from: a chart of the canvas is drawn only from figures the conversation holds.

A small model asked for « une présentation sur la livraison à vélo » happily writes ``::: chart`` with « 2023 : 12 %,
2024 : 15 % » — figures no one gave. ``check`` keeps a chart only when every value it plots is in the sources of the
turn: the user's words (this message and the earlier ones), what the tools returned (statistics, open data, the
data engine, a page read), the earlier answers of the conversation (they came from those tools) and the artifact
being edited (« fais un graphique de ce tableau »). A chart with a value found nowhere is replaced by a short
note that asks for the figures: the slide stays, nothing is made up, and the chat offers to add them.

Numbers are compared as values: « 85 000 € », « 85000 », « 85,0 » are the same; « 120 k€ » is 120 (the unit is the
chart's ``unit``). A value may also be the difference of two figures of the sources (« +15 » from 120 and 135): a
computation on what was given is not an invention.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"(?<![\w.,])[-−]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w.,])[-−]?\d+(?:[.,]\d+)?(?![\d])")
NOTE = {
    "fr": "Graphique à compléter : donnez vos chiffres ({labels}) et Bird le trace. Aucun chiffre n'est inventé.",
    "en": "Chart to complete: give your figures ({labels}) and Bird draws it. No figure is made up.",
}


def numbers(text: str) -> set[float]:
    """Every number written in ``text``, as a value (thousands spaces, decimal commas and signs read)."""
    out: set[float] = set()
    for m in _NUM.finditer(str(text or "")):
        raw = re.sub(r"[   ]", "", m.group(0)).replace("−", "-").replace(",", ".")
        try:
            v = float(raw)
        except ValueError:
            continue
        out.add(v)
        out.add(abs(v))
    return out


def doc_numbers(doc: dict | None) -> set[float]:
    """The numbers an artifact already holds (its text, tables, tiles and charts)."""
    if not doc:
        return set()
    import json

    return numbers(json.dumps(doc.get("blocks") or [], ensure_ascii=False))


def _known(v: float, have: set[float], pairs: set[float]) -> bool:
    return any(abs(v - h) <= 1e-9 * max(1.0, abs(h)) for h in have) or round(v, 6) in pairs


def _pairs(have: set[float]) -> set[float]:
    vals = sorted(have)[:80]  # the differences of two figures of the sources (bounded)
    return {round(b - a, 6) for i, a in enumerate(vals) for b in vals[i + 1 :]}


def chart_values(part: dict) -> list[float]:
    return [float(v) for r in part.get("rows") or [] for v in list(r)[1:] if isinstance(v, (int, float))
            and not isinstance(v, bool)]  # fmt: skip


def check(doc: dict, sources: str, base: dict | None = None, lang: str = "fr",
          repairs: list[str] | None = None) -> int:  # fmt: skip
    """Replace, in place, each chart of ``doc`` whose values are not all in ``sources`` (or ``base``) by a note
    asking for the figures. Returns the number of charts replaced. A chart already in ``base`` unchanged stays."""
    repairs = repairs if repairs is not None else []
    have = numbers(sources) | doc_numbers(base)
    pairs = _pairs(have)
    kept_before = {
        _sig(p) for b in (base or {}).get("blocks") or [] for p in b.get("parts") or [] if p.get("t") == "chart"
    }
    lg = "en" if lang == "en" else "fr"
    replaced = 0
    for b in doc.get("blocks") or []:
        parts = b.get("parts") or []
        for k, p in enumerate(parts):
            if p.get("t") != "chart" or _sig(p) in kept_before:
                continue
            vals = chart_values(p)
            missing = [v for v in vals if not _known(v, have, pairs)]
            if vals and not missing:
                continue
            labels = ", ".join(str(r[0]) for r in (p.get("rows") or [])[:6] if r) or (p.get("title") or "")
            parts[k] = {"t": "callout", "tone": "info", "text": NOTE[lg].format(labels=labels)[:600], "need": "figures"}
            replaced += 1
            repairs.append(f"chart '{b.get('title') or ''}' with {len(missing)} figure(s) found in no source: "
                           "replaced by a note asking for them")  # fmt: skip
    return replaced


TODO = {"fr": "à compléter", "en": "to be completed"}
_AMOUNT = re.compile(r"^\s*[~≈+−-]?\s*\d[\d\s\u00a0\u202f.,]*\s*(?:%|k€|M€|Md€|€|k\$|\$|pts?|x|×)?\s*$", re.I)


def _year(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:19|20)\d\d\s*", text))


def cells(doc: dict, sources: str, base: dict | None = None, lang: str = "fr",
          repairs: list[str] | None = None) -> int:  # fmt: skip
    """The figures of tables and key-figure tiles found in no source become « à compléter » (in place): the table
    and the tiles stay, an invented amount does not (« 120 € par semaine » for a bakery nobody described). A cell
    that is text (« Semaine 3 », « 7h-19h ») or a year is not a figure. Returns the number of cells blanked."""
    repairs = repairs if repairs is not None else []
    have = numbers(sources) | doc_numbers(base)
    pairs = _pairs(have)
    todo = TODO["en" if lang == "en" else "fr"]
    n = 0

    def ok(text: str) -> bool:
        if not _AMOUNT.match(text or "") or _year(text):
            return True
        vals = numbers(text)
        return bool(vals) and all(_known(v, have, pairs) for v in vals)

    for b in doc.get("blocks") or []:
        for p in b.get("parts") or []:
            if p.get("t") == "table":
                for r in (p.get("rows") or [])[1:]:
                    for k, c in enumerate(r):
                        if k and isinstance(c, str) and not ok(c):
                            r[k] = todo
                            n += 1
            elif p.get("t") == "kpi":
                for it in p.get("items") or []:
                    if not ok(str(it.get("value") or "")):
                        it["value"], it["delta"] = todo, ""
                        n += 1
    if n:
        repairs.append(f"{n} figure(s) of tables / tiles found in no source: « {todo} »")
    return n


def _sig(p: dict) -> str:
    return repr((p.get("type"), p.get("unit"), p.get("rows")))


def sources_of(words: str, history: list[dict] | None, run=None) -> str:
    """The text the figures may come from: the user's words, the earlier messages, the turn's tool results."""
    out = [str(words or "")]
    for m in history or []:
        c = m.get("content")
        out.append(c if isinstance(c, str) else str(c or ""))
    for m in getattr(run, "messages", None) or []:
        if m.get("role") == "tool":
            out.append(str(m.get("content") or ""))
    for fig in getattr(run, "figures", None) or []:
        out.append(" ".join(str(x) for x in fig))
    return "\n".join(out)


_TAIL = re.compile(
    r"(?<![\d.,])(?P<value>[-−]?\d{1,3}(?:[\u00a0\u202f ]\d{3})+(?:[.,]\d+)?|[-−]?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>%|k€|M€|Md€|€|k\$|\$|kg|t|km|h|pts?)?\s*$",
    re.I,
)
UNITS = {"%": "%", "k€": "k€", "m€": "M€", "md€": "Md€", "€": "€", "k$": "k$", "$": "$", "kg": "kg", "t": "t",
         "km": "km", "h": "h", "pt": "pts", "pts": "pts"}  # fmt: skip


def pairs(words: str) -> list[tuple[str, float, str]]:
    """« nous 34 %, Alpha 28 %, Beta 21 % et autres 17 % » -> [('Nous', 34, '%'), …]; « T1 : 120 k€, T2 : 135 k€ »,
    « 2022 80, 2023 95 »: the label / figure pairs a person typed for a chart. Each piece between commas,
    semicolons, lines or « et » ends with its figure; what comes before it is the label."""
    out = []
    pieces = re.split(r"[,;\n]|\s+(?:et|and)\s+", str(words or ""))
    for piece in pieces:
        piece = piece.strip()
        m = _TAIL.search(piece)
        if not m:
            continue
        label = piece[: m.start()].strip()
        if ":" in label and re.search(r"[^\W\d_]", label.rsplit(":", 1)[1]):
            label = label.rsplit(":", 1)[1]  # « Voici les chiffres : nous 34 % » -> « nous »
        label = label.strip(" :=-–—()")
        if not label or len(label) > 40:
            continue
        raw = re.sub(r"[\u00a0\u202f ]", "", m.group("value")).replace("−", "-").replace(",", ".")
        try:
            v = float(raw)
        except ValueError:
            continue
        unit = UNITS.get((m.group("unit") or "").lower(), "")
        out.append((label[:1].upper() + label[1:], int(v) if v.is_integer() else v, unit))
    return out


def _chart_of(got: list, title: str) -> dict:
    units = {u for _, _, u in got}
    unit = units.pop() if len(units) == 1 else ""
    share = unit == "%" and 95 <= sum(v for _, v, _ in got) <= 105
    return {"t": "chart", "type": "pie" if share else "bar", "unit": unit, "title": title, "columns": ["", title],
            "rows": [[label, v] for label, v, _ in got][:24], "source": ""}  # fmt: skip


def _fold(x: str) -> str:
    import unicodedata

    flat = unicodedata.normalize("NFKD", str(x or "").lower())
    return "".join(c for c in flat if not unicodedata.combining(c)).strip()


def fill_ops(words: str, doc: dict, chart: bool = True) -> list[dict] | None:
    """The person gives the figures of a chart: drawn from them at once, without a model call (their own numbers,
    read as typed), in place of the chart that waits for them (``need: figures``), else of the table whose rows
    they name (« pain 45 %, viennoiseries 30 % » for a table « pain | à compléter »). None when there is no such
    place or fewer than two label / figure pairs in the words. ``chart`` False (the words do not ask for a chart):
    the table keeps its form and its « à compléter » cells of the rows named get the figures."""
    if not doc or doc.get("kind") not in ("deck", "doc"):
        return None
    got = pairs(words)
    if len(got) < 2:
        return None
    blocks = doc.get("blocks") or []
    for b in blocks:
        for k, p in enumerate(b.get("parts") or []):
            if p.get("t") == "callout" and p.get("need") == "figures":
                new = {**b, "parts": [*b["parts"][:k], _chart_of(got, b.get("title") or ""), *b["parts"][k + 1 :]]}
                return [{"op": "replace", "id": b["id"], "block": new}]
    said = {_fold(label) for label, _, _ in got}
    for b in blocks:
        for k, p in enumerate(b.get("parts") or []):
            if p.get("t") != "table":
                continue
            rows = {_fold(r[0]) for r in (p.get("rows") or [])[1:] if r}
            if len(said & rows) < max(2, (len(said) + 1) // 2):
                continue
            if chart:
                new = {**b, "parts": [*b["parts"][:k], _chart_of(got, b.get("title") or ""), *b["parts"][k + 1 :]]}
                return [{"op": "replace", "id": b["id"], "block": new}]
            todo = set(TODO.values())
            table = [list(r) for r in p.get("rows") or []]
            filled = 0
            for label, v, unit in got:
                for r in table[1:]:
                    if r and _fold(r[0]) == _fold(label):
                        j = next((j for j, c in enumerate(r) if j and str(c).strip() in todo), None)
                        if j is not None:
                            r[j] = f"{v} {unit}".strip()
                            filled += 1
                        break
            if not filled:
                return None
            new = {**b, "parts": [*b["parts"][:k], {**p, "rows": table}, *b["parts"][k + 1 :]]}
            return [{"op": "replace", "id": b["id"], "block": new}]
    return None
