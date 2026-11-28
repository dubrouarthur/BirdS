"""Small deterministic modules from the user's own data or from what the harness computed (never from model prose).

* ``matrix_from_costs``: the comparison matrix of Mode Agent's offers (costs computed by the harness, the verdict).
* ``checklist_from_actions``: the action items of minutes (owners and due dates checked in code), tickable.
* ``from_words``: what the user's own message holds, when they ask for it: a timeline (« fais une frise
  chronologique : 2019 création, 2021 levée de fonds… »), a comparison matrix of a table they pasted (« compare ces
  offres » + a Markdown, CSV or tab-separated table), a checklist of the items they listed (« transforme en liste de
  tâches : … »).

Every value of a card is copied from that data; the harness only orders, sorts and marks the best value of a column
whose direction is certain (a price, a cost, a delay is better low; a score, a rating better high).
"""

from __future__ import annotations

import json
import re

from birds.harness import crew_checks as cc

CARD_BYTES = 7600


def _size(w: dict) -> int:
    return len(json.dumps(w, ensure_ascii=False, separators=(",", ":")))


def _money(v, lang: str) -> str:
    return cc.money(float(v), lang) if v is not None else "—"


# ------------------------------------------------------------------ comparison matrix

_LOW = re.compile(r"prix|co[ûu]t|tarif|montant|budget|d[ée]lai|dur[ée]e d'intervention|frais|price|cost|fee|delay|"
                  r"latency|response time|\bsla\b|consommation|poids|weight", re.I)  # fmt: skip
_HIGH = re.compile(r"note|score|satisfaction|avis|rating|qualit[ée]|capacit[ée]|autonomie|stockage|storage|"
                   r"vitesse|speed|r[ée]tention|garantie|warranty", re.I)  # fmt: skip


def direction(header: str) -> str | None:
    """ "min" | "max" | None for a column, from its header only."""
    if _LOW.search(header or ""):
        return "min"
    if _HIGH.search(header or ""):
        return "max"
    return None


def _value(cell: str) -> float | None:
    vals = cc.numbers(str(cell or ""))
    return vals[0] if len(vals) == 1 or (vals and re.match(r"^\D{0,3}\d", str(cell))) else None


def matrix(columns: list[str], rows: list[list[str]], *, title: str, lang: str = "fr", verdict: int | None = None,
           origin: str = "user", notes: list[str] | None = None) -> dict | None:  # fmt: skip
    """A comparison matrix: the first column names the options, the others are criteria. ``best`` marks, per
    column with a certain direction and a number in every row, the row(s) with the best value."""
    columns = [" ".join(str(c).split())[:60] for c in columns][:8]
    rows = [[" ".join(str(c).split())[:80] for c in r][: len(columns)] for r in rows if isinstance(r, list | tuple)]
    rows = [r + [""] * (len(columns) - len(r)) for r in rows if any(r)][:12]
    if len(columns) < 2 or len(rows) < 2:
        return None
    best: dict[str, list[int]] = {}
    dirs: dict[str, str] = {}
    for j, head in enumerate(columns[1:], 1):
        d = direction(head)
        vals = [_value(r[j]) for r in rows]
        numeric = all(v is not None for v in vals)
        if numeric:
            dirs[str(j)] = d or ""
        if d and numeric and len(set(vals)) > 1:
            target = min(vals) if d == "min" else max(vals)
            best[str(j)] = [i for i, v in enumerate(vals) if v == target]
    w = {"type": "matrix", "v": 1, "title": title[:100], "columns": columns, "rows": rows, "best": best,
         "numeric": dirs, "verdict": verdict, "origin": origin, "notes": (notes or [])[:3]}  # fmt: skip
    while _size(w) > CARD_BYTES and len(w["rows"]) > 2:
        w["rows"] = w["rows"][:-1]
    return w if _size(w) <= CARD_BYTES else None


def matrix_from_costs(costs: dict | None, lang: str = "fr") -> dict | None:
    """Mode Agent's offers: the costs the harness computed from the analyst's typed description, and its verdict."""
    rows = [r for r in (costs or {}).get("rows") or [] if isinstance(r, dict)]
    if len(rows) < 2:
        return None
    fr = lang != "en"
    cols = ["Offre" if fr else "Offer", "Mensuel" if fr else "Monthly", "Coût 1re année" if fr else "Year-1 cost",
            "Coût par an (durée)" if fr else "Cost per year (term)", "Durée" if fr else "Term",
            "Délai d'intervention" if fr else "Response time", "Conforme" if fr else "Meets needs"]  # fmt: skip
    out, verdict = [], None
    best = (costs or {}).get("verdict")
    for i, r in enumerate(rows[:10]):
        name = r["offer"] + (f" + {r['option']}" if r.get("option") else "")
        fails = ", ".join(r.get("fails") or [])
        out.append([name, _money(r.get("monthly"), lang), _money(r.get("year1"), lang), _money(r.get("per_year"), lang),
                    f"{r.get('months')} mois" if fr else f"{r.get('months')} months",
                    (f"{r['sla_hours']:g} h" if r.get("sla_hours") else "—"),
                    ("oui" if fr else "yes") if r.get("ok") else (("non : " if fr else "no: ") + fails)])  # fmt: skip
        if (
            best
            and r is best
            or (best and r.get("offer") == best.get("offer") and r.get("option") == best.get("option"))
        ):
            verdict = i
    w = matrix(cols, out, title="Comparaison des offres" if fr else "Offers compared", lang=lang, verdict=verdict,
               origin="harness",
               notes=["Coûts calculés par Bird à partir des offres collées." if fr else
                      "Costs computed by Bird from the pasted offers."])  # fmt: skip
    if w:
        w["best"].pop("4", None)  # a longer term is not « worse »: no mark on the term
    return w


_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def table_in(text: str) -> tuple[list[str], list[list[str]]] | None:
    """The first table of the user's text: Markdown (| a | b |), tab-separated or semicolon-separated lines."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    md = [ln for ln in lines if _TABLE_ROW.match(ln)]
    if len(md) >= 3:
        cells = [[c.strip() for c in _TABLE_ROW.match(ln).group(1).split("|")] for ln in md if not _SEP.match(ln)]
        if len(cells) >= 3 and len({len(c) for c in cells}) == 1:
            return cells[0], cells[1:]
    for sep in ("\t", ";"):
        rows = [[c.strip() for c in ln.split(sep)] for ln in lines if ln.count(sep) >= 1]
        if len(rows) >= 3 and len({len(r) for r in rows}) == 1 and len(rows[0]) >= 2:
            return rows[0], rows[1:]
    return None


# ------------------------------------------------------------------ checklist


def checklist(items: list[dict], *, title: str, origin: str = "user", lang: str = "fr") -> dict | None:
    """items: [{text, owner?, due?, done?}]. Ticks are kept by the browser with the conversation."""
    clean = []
    for it in items[:40]:
        text = " ".join(str(it.get("text") or "").split())[:200]
        if text:
            clean.append({"text": text, "owner": str(it.get("owner") or "")[:60], "due": str(it.get("due") or "")[:40],
                          "done": bool(it.get("done"))})  # fmt: skip
    if len(clean) < 2:
        return None
    w = {"type": "checklist", "v": 1, "title": title[:100], "items": clean, "origin": origin}
    while _size(w) > CARD_BYTES and len(w["items"]) > 2:
        w["items"] = w["items"][:-1]
    return w


def checklist_from_actions(actions: list[dict] | None, lang: str = "fr") -> dict | None:
    """The action items of minutes, as Mode Agent checked them (owner in the attendee list and on the line)."""
    items = [{"text": a.get("action"), "owner": a.get("owner"), "due": a.get("due")} for a in actions or []
             if isinstance(a, dict)]  # fmt: skip
    return checklist(items, title="Actions à suivre" if lang != "en" else "Action items", origin="minutes", lang=lang)


_ITEM = re.compile(r"^\s*(?:[-*•–]|\d{1,2}[.)]|\[[ xX]?\])\s+(?P<t>.+)$")
_DONE = re.compile(r"^\s*(?:[-*•–]\s+)?\[[xX]\]")


# ------------------------------------------------------------------ timeline from the user's text

_DATED = re.compile(
    r"^\s*(?:[-*•–]\s*)?(?P<d>(?:(?:le\s+)?\d{1,2}(?:er)?\s+[a-zéû]+\s+)?(?:(?:en|in)\s+)?(?:janvier|février|fevrier|mars|"
    r"avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre|january|february|march|april|"
    r"may|june|july|august|september|october|november|december)?\s*(?:1[89]|20)\d\d)\s*(?:[:–—-]|,)\s*(?P<t>.{3,200})$",
    re.I,
)
_INLINE_DATED = re.compile(r"(?:^|[,;:]\s*)(?P<d>(?:1[89]|20)\d\d)\s*(?:[:–—-]\s*|\s+)(?P<t>[^,;\n]{3,120})")

_TIMELINE_ASK = re.compile(r"\b(?:frise(?:\s+chronologique)?|chronologie|timeline|ligne du temps|historique des "
                           r"(?:dates|[ée]tapes|jalons)|jalons|r[ée]troplanning|r[ée]tro-planning)\b", re.I)  # fmt: skip
_MATRIX_ASK = re.compile(r"\b(?:compar\w*|matrice|meilleure? (?:offre|option)|tableau comparatif|versus|\bvs\b|"
                         r"classe(?:-les| ces)|trie(?:-les| ces)|which is best|rank)\b", re.I)  # fmt: skip
_CHECK_ASK = re.compile(r"\b(?:check-?list|liste de (?:t[âa]ches|choses [àa] faire|contr[ôo]le)|to-?do(?: list)?|"
                        r"t[âa]ches [àa] cocher|[àa] cocher|tickable|task list)\b", re.I)  # fmt: skip


def _date_key(d: str) -> str | None:
    from birds.harness.research import date_key

    return date_key(d)


def timeline_from_text(text: str, lang: str = "fr") -> dict | None:
    lines = (text or "").splitlines()
    events = []
    for ln in lines:
        m = _DATED.match(ln)
        if m and _date_key(m["d"]):
            events.append(
                {"key": _date_key(m["d"]), "date": " ".join(m["d"].split()), "label": m["t"].strip(" .")[:160]}
            )
    if len(events) < 3:  # « 2019 création, 2021 levée de fonds, 2023 export » on one line
        events = []
        for m in _INLINE_DATED.finditer(text or ""):
            events.append({"key": m["d"], "date": m["d"], "label": m["t"].strip(" .")[:160]})
    if len({e["key"] for e in events}) < 3:
        return None
    events.sort(key=lambda e: e["key"])
    w = {"type": "timeline", "v": 1, "title": "Chronologie" if lang != "en" else "Timeline", "events": events[:20],
         "origin": "user"}  # fmt: skip
    while _size(w) > CARD_BYTES and len(w["events"]) > 3:
        w["events"] = w["events"][:-1]
    return w


def from_words(text: str, lang: str = "fr") -> list[dict]:
    """The modules the user's own message asks for and holds the data of. Empty when either is missing."""
    words = str(text or "")
    if len(words) > 20_000:
        return []
    head = words[:300]
    out = []
    if _TIMELINE_ASK.search(head):
        w = timeline_from_text(words, lang)
        if w:
            out.append(w)
    if _MATRIX_ASK.search(head):
        got = table_in(words)
        if got:
            w = matrix(got[0], got[1], title="Comparaison" if lang != "en" else "Comparison", lang=lang)
            if w:
                out.append(w)
    if _CHECK_ASK.search(head):
        w = _tasks(words, lang)
        if w:
            out.append(w)
    return out


def _tasks(words: str, lang: str) -> dict | None:
    items = []
    for ln in words.splitlines()[1:] if "\n" in words else []:
        m = _ITEM.match(ln)
        if m:
            items.append({"text": re.sub(r"^\[[ xX]?\]\s*", "", m["t"]).strip(), "done": bool(_DONE.match(ln))})
    if not items:
        m = re.search(r":\s*(.+)$", words.split("\n")[0])
        parts = [p.strip(" .") for p in re.split(r"[;,]\s*|\s+(?:et|puis|and)\s+", m.group(1))] if m else []
        items = [{"text": p} for p in parts if len(p) > 2]
    return checklist(items, title="Liste de tâches" if lang != "en" else "Task list", origin="user", lang=lang)


# ------------------------------------------------------------------ pros and cons, key figures, glossary

_PROS = re.compile(r"\b(?:avantages?|points? forts?|pour|atouts?|pros?|advantages?|upsides?|strengths?)\s*:", re.I)
_CONS = re.compile(r"\b(?:inconv[ée]nients?|points? faibles?|contre|limites?|risques?|cons|disadvantages?|downsides?|"
                   r"weaknesses?)\s*:", re.I)  # fmt: skip
_PROSCONS_ASK = re.compile(r"\b(?:avantages?\s+et\s+inconv[ée]nients?|pour\s+et\s+(?:le\s+)?contre|pros?\s+(?:and|&)\s+"
                           r"cons|points? forts? et (?:points? )?faibles?|forces et faiblesses)\b", re.I)  # fmt: skip
_FIGURES_ASK = re.compile(r"\b(?:chiffres?[- ]cl[ée]s|indicateurs? cl[ée]s|kpis?|key figures|key metrics|tableau de "
                          r"bord|fiche (?:de )?chiffres)\b", re.I)  # fmt: skip
_GLOSSARY_ASK = re.compile(r"\b(?:glossaire|lexique|glossary|d[ée]finitions? des termes|vocabulaire)\b", re.I)


def _items_of(text: str) -> list[str]:
    """« a ; b ; c », « a, b et c » or one per line (bullets) -> the items."""
    lines = [m["t"].strip(" .;") for ln in text.splitlines() if (m := _ITEM.match(ln))]
    if len(lines) >= 1 and "\n" in text.strip():
        return [x for x in lines if len(x) > 2][:10]
    parts = re.split(r"\s*[;•]\s*|,\s*(?![^()]*\))|\s+(?:et|and)\s+(?=\S+\s)", text)
    return [p.strip(" .") for p in parts if len(p.strip(" .")) > 2][:10]


def proscons_from_text(text: str, lang: str = "fr") -> dict | None:
    """« avantages : a, b ; inconvénients : c » (or « pour : … contre : … », or lines + / -): the user's points."""
    words = str(text or "")
    pro, con = _PROS.search(words), _CONS.search(words)
    pros, cons = [], []
    if pro and con:
        if pro.start() < con.start():
            pros, cons = _items_of(words[pro.end() : con.start()]), _items_of(words[con.end() :])
        else:
            cons, pros = _items_of(words[con.end() : pro.start()]), _items_of(words[pro.end() :])
    else:
        for ln in words.splitlines():
            m = re.match(r"^\s*([+\-–])\s+(.{3,200})$", ln)
            if m:
                (pros if m.group(1) == "+" else cons).append(m.group(2).strip(" ."))
    if not pros or not cons:
        return None
    fr = lang != "en"
    w = {"type": "proscons", "v": 1, "title": "Avantages et inconvénients" if fr else "Pros and cons",
         "pros": [p[:160] for p in pros[:8]], "cons": [c[:160] for c in cons[:8]], "origin": "user"}  # fmt: skip
    return w if _size(w) <= CARD_BYTES else None


_FIG_PAIR = re.compile(
    r"(?P<label>[A-Za-zÀ-ÿ][\wÀ-ÿ'’ ./-]{1,50}?)\s*(?::|=|—|–)\s*(?P<value>[-+]?\d[\d   .,]*\s?(?:%|‰|€|\$|£|k€|M€|"
    r"Md€|[A-Za-zÀ-ÿ€$%]{0,12})(?:\s?(?:HT|TTC|par an|/an|/mois|par mois))?)",
)


def figures_from_text(text: str, lang: str = "fr") -> dict | None:
    """« CA 2025 : 1,2 M€ ; marge : 18 % ; effectif : 45 »: each label and value as the user wrote them."""
    words = str(text or "")
    head = words.split(":", 1)
    body = head[1] if len(head) == 2 and _FIGURES_ASK.search(head[0]) else words
    items, seen = [], set()
    for m in _FIG_PAIR.finditer(body):
        label = " ".join(m["label"].split()).strip(" .-")
        label = re.sub(r"^(?:et|and|puis|avec)\s+", "", label, flags=re.I)
        value = " ".join(m["value"].split()).strip(" ,.")
        if len(label) < 2 or cc.fold(label) in seen or _FIGURES_ASK.fullmatch(label):
            continue
        seen.add(cc.fold(label))
        items.append({"label": label[:60], "value": value[:30]})
    if len(items) < 2:
        return None
    w = {"type": "figures", "v": 1, "title": "Chiffres clés" if lang != "en" else "Key figures", "items": items[:8],
         "origin": "user"}  # fmt: skip
    return w if _size(w) <= CARD_BYTES else None


def glossary_from_text(text: str, lang: str = "fr") -> dict | None:
    """« RGPD : règlement général sur la protection des données » one per line (or « ; »): the user's own terms."""
    words = str(text or "")
    if "\n" in words:
        lines = [ln for ln in words.splitlines()[1:] if ln.strip()]
    else:  # one line: the ask (« Fais un glossaire : ») is not the first term
        head = words.split(":", 1)
        body = head[1] if len(head) == 2 and _GLOSSARY_ASK.search(head[0]) else words
        lines = re.split(r"\s*;\s*", body)
    items = []
    for ln in lines:
        m = re.match(r"^\s*(?:[-*•–]\s*)?(?P<term>[^:=—–\n]{1,40}?)\s*(?::|=|—|–)\s*(?P<def>.{4,240})$", ln.strip())
        if m and not _GLOSSARY_ASK.search(m["term"]):
            items.append({"term": m["term"].strip(" ."), "def": m["def"].strip()})
    if len(items) < 2:
        return None
    items.sort(key=lambda x: cc.fold(x["term"]))
    w = {"type": "glossary", "v": 1, "title": "Glossaire" if lang != "en" else "Glossary", "items": items[:20],
         "origin": "user"}  # fmt: skip
    while _size(w) > CARD_BYTES and len(w["items"]) > 2:
        w["items"] = w["items"][:-1]
    return w


# ------------------------------------------------------------------ the « card » module (the router decides)

ASKS = {"timeline": _TIMELINE_ASK, "matrix": _MATRIX_ASK, "tasks": _CHECK_ASK, "proscons": _PROSCONS_ASK,
        "figures": _FIGURES_ASK, "glossary": _GLOSSARY_ASK}  # fmt: skip
_SOURCES_ASK = re.compile(r"\b(?:(?:tes|vos|les|des|with|your|the)\s+sources|sources?\s+(?:de ta|de votre|of your)|"
                          r"cite\s+(?:tes|vos)\s+sources|liens? vers les sources|show (?:me )?(?:the )?sources)\b",
                          re.I)  # fmt: skip


def asked_kinds(text: str) -> list[str]:
    """The parsers' guess of the cards the words ask for (hints for the router, its fallback when it is off)."""
    from birds.harness import calc

    head = str(text or "")[:300]
    out = [k for k, rx in ASKS.items() if rx.search(head)]
    if calc.detect(text or "") is not None:
        out.append("calc")
    if _SOURCES_ASK.search(head):
        out.append("sources")
    return out


def card(kind: str, text: str, lang: str = "fr") -> dict | None:
    """The card of one kind from the user's own data, or None when their message does not hold it (nothing is
    invented: the router may decide a timeline, three dates are still needed). ``calc`` and ``sources`` are built
    by the agent (birds.harness.calc, the run's sources)."""
    words = str(text or "")
    if len(words) > 20_000:
        return None
    if kind == "timeline":
        return timeline_from_text(words, lang)
    if kind == "matrix":
        got = table_in(words)
        return matrix(got[0], got[1], title="Comparaison" if lang != "en" else "Comparison", lang=lang) if got else None
    if kind == "tasks":
        return _tasks(words, lang)
    if kind == "proscons":
        return proscons_from_text(words, lang)
    if kind == "figures":
        return figures_from_text(words, lang)
    if kind == "glossary":
        return glossary_from_text(words, lang)
    return None


def cards(text: str, lang: str = "fr", kinds: list[str] | None = None) -> list[dict]:
    """The cards of the user's message: ``kinds`` as the router decided them, or (router off) the parsers' guess."""
    want = asked_kinds(text) if kinds is None else list(kinds)
    out = []
    for k in dict.fromkeys(want):
        w = card(k, text, lang)
        if w and w["type"] not in {x["type"] for x in out}:
            out.append(w)
    return out


def source_cards(sources: list[str], lang: str = "fr") -> dict | None:
    """« donne-moi tes sources »: the pages this answer read, as cards (the browser fills them from the answer's
    sources: title, site, snippet, date). Nothing without a source read."""
    if not sources:
        return None
    return {"type": "sourcecards", "v": 1, "title": "Sources" if lang != "en" else "Sources", "n": len(sources[:12])}
