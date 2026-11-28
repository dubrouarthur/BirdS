"""Deep research, after the claims are checked: cross-checks, confidence, key figures, the comparison the writer
proposed, the live board and the full report widget. Pure functions on the verified claims and the pages read
(no model, no I/O): every value shown comes from a quote found in a page or from a count made by code.

* ``cross_check``: two claims of different sites that say the same thing (most long words in common, no figure in
  conflict) corroborate each other; two that talk about the same thing with different figures of the same unit
  (« 26 % » against « 31 % » of the same year) are a contradiction, shown as such, never silently resolved.
* Confidence of a claim: ``high`` (corroborated by another site), ``medium`` (its quote is in its page, one site),
  ``low`` (contradicted, or the report sentence citing it is weak).
* ``key_figures``: the figures of the claims (value and unit as written in the quote), most confident first.
* ``check_comparison``: the writer's optional comparison table, kept only when each figure of each cell is in a
  verified quote and each option is named in a page read.
* ``report_widget``: the full-screen report (table of contents, sentences with their citations, sources cited and
  consulted, claims with their confidence, figures, contradictions).
"""

from __future__ import annotations

import json
import re

from birds.harness import crew_checks as cc

REPORT_BYTES = 16_000
BOARD_BYTES = 14_000

_STOP = {
    "aussi", "autre", "autres", "avant", "avoir", "selon", "entre", "depuis", "comme", "leurs", "notre", "votre",
    "toute", "toutes", "plusieurs", "encore", "cette", "celle", "ceux", "dont", "elles", "their", "there", "which",
    "about", "would", "could", "these", "those", "other", "after", "since", "where", "while", "being",
}  # fmt: skip


def _size(w) -> int:
    return len(json.dumps(w, ensure_ascii=False, separators=(",", ":")))


def content_words(text: str) -> set[str]:
    """Long words of a text (5 letters or more, compared on their first 6), citation marks and figures out."""
    words = re.findall(r"[a-z]{5,}", cc.fold(cc._CITE.sub(" ", text or "")))
    return {w[:6] for w in words if w not in _STOP}


def similarity(a: str, b: str) -> float:
    x, y = content_words(a), content_words(b)
    if len(x) < 3 or len(y) < 3:
        return 0.0
    return len(x & y) / min(len(x), len(y))


_UNIT = re.compile(
    r"\s*(%|‰|€|\$|£|M€|Md€|k€|Mds?|milliards?|millions?|milliers?|mille|billions?|thousands?|GW|MW|kW|TWh|GWh|MWh|"
    r"kWh|km|kg|tonnes?|t\b|ans?|years?|mois|months?|jours?|days?|heures?|hours?|salariés|employés|employees|"
    r"habitants|people|personnes|points?|fois|times|[a-zà-ÿ]{3,14})?"
    r"(\s+(?:d['’]euros|de dollars|d['’]habitants|de personnes|de salariés|d['’]emplois|de tonnes|of euros|of dollars|"
    r"euros|dollars))?",
    re.I,
)


def figures_of(text: str) -> list[tuple[str, float, str]]:
    """(value as written with its unit, value, unit key) for each figure of a text that is not a year."""
    from birds.harness.research import nums

    clean = cc._CITE.sub(" ", text or "")
    out, at = [], 0
    for raw, v, is_year in nums(clean):
        i = clean.find(raw, at)
        if i < 0:
            continue
        at = i + len(raw)
        if is_year:
            continue
        m = _UNIT.match(clean, at)
        unit = (m.group(1) or "") if m else ""
        written = " ".join(clean[i : m.end() if (m and unit) else at].split())  # as written in the text
        scale, key = _unit_key(unit, (m.group(2) or "") if (m and unit) else "")
        out.append((written, v * scale, key))
    return out


# scale words go into the value (« 1,2 million » is 1 200 000, « 1,2 milliard » 1 200 000 000): never compared on
# their first letters, where « million » and « milliard » would look alike
_SCALES = (
    (re.compile(r"^(?:md€?|mds|milliards?|billions?)$"), 1e9),
    (re.compile(r"^(?:m€|millions?)$"), 1e6),
    (re.compile(r"^(?:k€|milliers?|mille|thousands?)$"), 1e3),
)
_CURRENCY = (("€", "eur"), ("euro", "eur"), ("$", "usd"), ("dollar", "usd"), ("£", "gbp"))


def _unit_key(unit: str, tail: str) -> tuple[float, str]:
    """(scale, comparable unit key) of a figure's unit: « M€ » and « millions d'euros » are both (1e6, « eur »)."""
    raw, t = unit.lower().strip(), tail.lower().strip()
    u = cc.fold(unit).strip()
    scale = next((f for rx, f in _SCALES if rx.match(raw)), 1.0)
    money = next((k for w, k in _CURRENCY if w in raw or w in t), "")
    if money:
        return scale, money
    if scale != 1.0:  # « 3 millions d'habitants », or a bare « 3 millions »
        return scale, cc.fold(re.sub(r"^(?:d['’]|de |of )", "", t))[:5] or "#"
    return scale, u[:5]


def _years(text: str) -> set[str]:
    return set(re.findall(r"\b(?:19|20)\d\d\b", text or ""))


def cross_check(claims: list[dict], pages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Annotate each claim with ``also`` (other sources that say the same), ``against`` (sources that contradict
    it) and ``conf``; return (claims, contradictions). Claims of the same site never corroborate each other."""
    domain = {p["n"]: p.get("domain") or f"#{p['n']}" for p in pages}
    for c in claims:
        c["also"], c["against"] = [], []
    contradictions = []
    for i, a in enumerate(claims):
        fa = figures_of(a["claim"])
        for j in range(i + 1, len(claims)):
            b = claims[j]
            if domain.get(a["n"]) == domain.get(b["n"]):
                continue
            sim = max(similarity(a["claim"], b["claim"]), similarity(a["claim"], b["quote"]),
                      similarity(b["claim"], a["quote"]))  # fmt: skip
            if sim < 0.45:
                continue
            fb = figures_of(b["claim"])
            ya, yb = _years(a["claim"] + " " + a["quote"]), _years(b["claim"] + " " + b["quote"])
            same_time = not ya or not yb or bool(ya & yb)
            units = {u for _, _, u in fa} & {u for _, _, u in fb}
            shared = {round(v, 6) for _, v, _ in fa} & {round(v, 6) for _, v, _ in fb}
            if fa and fb and units and not shared and same_time and sim >= 0.5:
                conflict = [(x, y) for x in fa for y in fb if x[2] == y[2] and x[2]]
                if conflict:
                    (wa, va, _), (wb, vb, _) = conflict[0]
                    if abs(va - vb) > 0.02 * max(abs(va), abs(vb), 1e-9):
                        a["against"].append(b["n"])
                        b["against"].append(a["n"])
                        contradictions.append({"a": {"i": i, "n": a["n"], "text": a["claim"][:200], "value": wa},
                                               "b": {"i": j, "n": b["n"], "text": b["claim"][:200], "value": wb}})  # fmt: skip
                        continue
            if sim >= 0.5 and (not fa or not fb or shared):
                a["also"].append(b["n"])
                b["also"].append(a["n"])
    for c in claims:
        c["also"] = sorted(set(c["also"]))
        c["against"] = sorted(set(c["against"]))
        c["conf"] = "low" if c["against"] else "high" if c["also"] else "medium"
    return claims, contradictions[:6]


_RANK = {"high": 0, "medium": 1, "low": 2}


def key_figures(claims: list[dict], limit: int = 6) -> list[dict]:
    """Figures of the verified claims, as written: one per claim, with a unit or a large value, most confident and
    most corroborated first. The label is the claim (cut), the value is copied from it."""
    out, seen = [], set()
    order = sorted(range(len(claims)), key=lambda i: (_RANK.get(claims[i].get("conf", "medium"), 1),
                                                      -len(claims[i].get("also", [])), i))  # fmt: skip
    for i in order:
        c = claims[i]
        for written, v, unit in figures_of(c["claim"]):
            if not unit and v < 100:
                continue
            key = (round(v, 6), unit)
            if key in seen:
                break
            seen.add(key)
            out.append({"value": written[:40], "label": c["claim"][:140], "n": c["n"], "i": i,
                        "date": c.get("date", ""), "conf": c.get("conf", "medium")})  # fmt: skip
            break
        if len(out) >= limit:
            break
    return out


def check_comparison(raw, claims: list[dict], pages: list[dict], lang: str = "fr") -> tuple[dict | None, int]:
    """The writer's comparison table, checked: options named in a page, every figure of a cell in a verified quote
    (else the cell becomes « — »). (matrix widget or None, cells blanked)."""
    from birds.harness import modules
    from birds.harness.research import _named, numbers_in

    if isinstance(raw, str):
        raw = cc.json_repair(raw)
    if not isinstance(raw, dict):
        return None, 0
    cols = [" ".join(str(c).split())[:60] for c in raw.get("columns") or [] if str(c).strip()][:6]
    rows_in = raw.get("rows") or []
    if len(cols) < 2 or not isinstance(rows_in, list):
        return None, 0
    quotes = " ".join(c["quote"] + " " + c["claim"] for c in claims)
    text = " ".join(p["text"] for p in pages)
    rows, blanked = [], 0
    for r in rows_in[:8]:
        if isinstance(r, dict):
            r = [r.get("name") or r.get("option") or "", *(r.get("cells") or r.get("values") or [])]
        if not isinstance(r, list) or not r:
            continue
        cells = [" ".join(str(x).split())[:80] for x in r][: len(cols)]
        cells += [""] * (len(cols) - len(cells))
        if not cells[0] or not _named(cells[0], text):
            continue
        for j in range(1, len(cells)):
            if cells[j] and cc._NUM.search(cells[j]) and not numbers_in(cells[j], quotes):
                cells[j] = "—"
                blanked += 1
        if sum(1 for x in cells[1:] if x and x != "—"):
            rows.append(cells)
    if len(rows) < 2:
        return None, blanked
    fr = lang != "en"
    w = modules.matrix(cols, rows, title="Comparaison d'après les sources" if fr else "Comparison from the sources",
                       lang=lang, origin="sources",
                       notes=[("Chaque chiffre est retrouvé dans une citation vérifiée ; « — » : chiffre sans source."
                               if fr else "Each figure is found in a verified quote; « — »: figure with no source.")])  # fmt: skip
    return w, blanked


def _sents(parts: list[dict]) -> list[dict]:
    return [{"t": p["t"][:600], "c": p["c"][:4]} for p in parts if p.get("t")]


def report_widget(*, title: str, summary: list[dict], sections: list[dict], pages: list[dict], consulted: list[dict],
                  claims: list[dict], figures: list[dict], contradictions: list[dict], questions: list[dict],
                  counts: dict, lang: str = "fr") -> dict:  # fmt: skip
    """The full report: everything the full-screen view shows, from the checked report and the claims only."""
    cited = {n for s in [*summary, *[x for sec in sections for x in sec["sents"]]] for n in s["c"]}
    by_n: dict[int, int] = {}
    for c in claims:
        by_n[c["n"]] = by_n.get(c["n"], 0) + 1
    w = {
        "type": "report",
        "v": 1,
        "title": title[:140],
        "summary": _sents(summary),
        "sections": [{"id": f"s{i + 1}", "heading": s["heading"][:90], "sents": _sents(s["sents"])}
                     for i, s in enumerate(sections)][:8],
        "sources": [{"n": p["n"], "title": p["title"][:110], "url": p.get("url", "")[:300], "domain": p.get("domain", ""),
                     "cited": p["n"] in cited, "claims": by_n.get(p["n"], 0)} for p in pages],
        "consulted": consulted[:12],
        "claims": [{"i": i, "t": c["claim"][:220], "n": c["n"], "q": c["quote"][:260], "date": c.get("date", ""),
                    "conf": c.get("conf", "medium"), "also": c.get("also", [])[:4], "against": c.get("against", [])[:4]}
                   for i, c in enumerate(claims)],
        "figures": figures[:6],
        "contradictions": contradictions[:4],
        "questions": questions[:5],
        "counts": counts,
    }  # fmt: skip
    # the history keeps it under REPORT_BYTES: quotes shortened first, then the last claims, then consulted pages
    for c in w["claims"]:
        if _size(w) <= REPORT_BYTES:
            break
        c["q"] = c["q"][:120]
    while _size(w) > REPORT_BYTES and len(w["claims"]) > 6:
        w["claims"].pop()
    while _size(w) > REPORT_BYTES and w["consulted"]:
        w["consulted"].pop()
    while _size(w) > REPORT_BYTES and len(w["sections"]) > 1:
        w["sections"].pop()
    return w


def board_snapshot(board: dict) -> dict:
    """The live board as one event (agent_research), capped: the browser replaces its copy with each one."""
    snap = {
        "type": "agent_research",
        "v": 1,
        "phase": board.get("phase", "plan"),
        "topic": str(board.get("topic") or "")[:160],
        "questions": [{"id": q["id"], "text": q["text"][:160], "query": q.get("query", "")[:90], "status": q["status"],
                       "claims": q.get("claims", 0)} for q in board.get("questions", [])][:5],
        "queries": [{"q": q["q"][:90], "status": q["status"], "results": q.get("results", 0)}
                    for q in board.get("queries", [])][:6],
        "sources": [{"domain": s.get("domain", "")[:60], "title": s.get("title", "")[:90], "status": s["status"],
                     "n": s.get("n"), "claims": s.get("claims", 0)} for s in board.get("sources", [])][:16],
        "claims": dict(board.get("claims") or {}),
        "contradictions": [{"a": c["a"]["value"], "b": c["b"]["value"], "na": c["a"]["n"], "nb": c["b"]["n"],
                            "text": c["a"]["text"][:140]} for c in board.get("contradictions", [])][:4],
        "graph": board.get("graph"),
    }  # fmt: skip
    if _size(snap) > BOARD_BYTES:
        snap["graph"] = None
    return snap
