"""Bird decides which analysis to compute on an attached table, as a small typed spec (structured output).

The model never computes and never writes code: it reads the columns of the table (names, types, a few values) and
the question, and answers ONE JSON line, constrained by a JSON schema built from the table itself (the column names
are enums, so it cannot name a column that does not exist):

    {"analysis": {"op": "aggregate", "measure": "CA (€)", "agg": "sum", "by": "Région", "sort": "desc", "top": 5},
     "chart": "hbar"}

``analysis`` is a ``query.py`` query (group-by, filter, pivot, top-N, share, year-over-year, percent change from the
previous period, moving average, correlation, distribution) or ``null`` when the question asks for no computation
(« résume ce fichier »); ``chart`` is the chart the reader should see (bar, hbar, line, area, scatter, donut,
stacked, combo, heatmap) or ``auto``. The harness checks the spec (``query.normalize``) and runs it: every number
of the answer comes from the engine.

The fixed templates of ``ask.py`` keep two roles: hints in the prompt, and the fallback when the endpoint is
unavailable, slow or answers something unusable. An explicit ``null`` from the model is its decision: no template
overrules it, in ``hybrid`` mode (the default, as ``BIRD_ROUTER``) too. A follow-up (« en courbe plutôt »,
« seulement le top 5 », « par trimestre ») gets the previous turn's spec, written in the memo by the server, and
the model edits it; without a model, ``revise`` applies the same edits by rule.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from birds.harness.analysis.ask import plan_question
from birds.harness.analysis.cells import plain
from birds.harness.analysis.profile import Frame
from birds.harness.analysis.query import AGGS, FILTER_OPS, MAX_TOP, MAX_WINDOW, OPS, PERIODS, QueryError, normalize

log = logging.getLogger("bird.analysis")

CHARTS = ("auto", "bar", "hbar", "line", "area", "scatter", "donut", "stacked", "combo", "heatmap")
MAX_TOKENS = 140
BUDGET_S = 4.0
MAX_QUESTION_CHARS = 400
MAX_FILTERS = 3
STOP = ["<|im_end|>", "<|endoftext|>", "\n\n"]
PREFIX = '{"analysis":'
KEYS = frozenset({"op", "measure", "agg", "by", "time", "period", "pivot", "filters", "sort", "top", "share", "window",
                  "change", "years", "x", "y"})
MEMO_RE = re.compile(r"\[(?:Analyse de|Analysis of) « [^»\n]{0,120} » — (\{.*?\})\]")

_HEAD = {
    "fr": (
        "Tu es le planificateur d'analyse de Bird. Un tableau est joint ; Bird calcule lui-même, tu choisis seulement "
        "QUOI calculer. Réponds par UNE ligne JSON : "
        '{"analysis":{…}|null,"chart":"auto|bar|hbar|line|area|scatter|donut|stacked|combo|heatmap"}.\n'
        "analysis : op aggregate (measure + agg sum|mean|median|count|min|max|distinct, by = catégorie, time + "
        "period day|week|month|quarter|year, pivot = 2e catégorie, filters [{col, op eq|ne|gt|ge|lt|le|in|contains|"
        "year|between, value}], sort desc|asc|natural, top N, share = parts en %, window = moyenne mobile sur N "
        "périodes, change = évolution en % d'une période à l'autre), op compare (deux années : time, years "
        "[a, b], by facultatif), op corr (x, y : deux nombres), op describe (measure : distribution).\n"
        "Noms de colonnes recopiés tels quels. null si la demande ne demande aucun calcul (résumer, traduire, "
        "corriger, écrire un mail, expliquer le fichier). chart : courbe ou aire pour le temps, hbar pour un "
        "classement, donut pour des parts (≤ 6), stacked ou heatmap pour un croisement, scatter pour deux mesures, "
        "combo pour une valeur et son évolution. Tour précédent : modifie son analyse si la demande la change "
        "(« en courbe », « top 5 seulement », « par trimestre »). Les indices (règles fixes) peuvent se tromper."
    ),
    "en": (
        "You are Bird's analysis planner. A table is attached; Bird computes by itself, you only choose WHAT to "
        "compute. Answer with ONE JSON line: "
        '{"analysis":{…}|null,"chart":"auto|bar|hbar|line|area|scatter|donut|stacked|combo|heatmap"}.\n'
        "analysis: op aggregate (measure + agg sum|mean|median|count|min|max|distinct, by = a category, time + "
        "period day|week|month|quarter|year, pivot = a 2nd category, filters [{col, op eq|ne|gt|ge|lt|le|in|"
        "contains|year|between, value}], sort desc|asc|natural, top N, share = shares in %, window = moving average "
        "over N periods, change = percent change from one period to the next), op compare (two years: time, years "
        "[a, b], optional by), op corr (x, y: two numbers), op describe (measure: distribution).\n"
        "Column names copied exactly. null when the message asks for no computation (summarise, translate, proofread, "
        "write an email, explain the file). chart: line or area for time, hbar for a ranking, donut for shares "
        "(≤ 6), stacked or heatmap for a cross-tab, scatter for two measures, combo for a value and its change. "
        'Previous turn: edit its analysis when the message changes it ("as a line", "only the top 5", "by '
        'quarter"). Hints (fixed rules) can be wrong.'
    ),
}

# The fixed examples (system message: static, so the endpoint reuses them from its prefix cache). Also the
# training records of scripts/build_tools_mix.py and the cases of the catalogue entry ``analyze_table``.
EXAMPLE_COLUMNS = (
    "Date (date, 02/01/2024 → 30/12/2025) ; Région (catégorie : Nord, Sud, Est, Ouest) ; Produit (catégorie : "
    "Alpha, Beta, Gamma) ; Montant (€) (nombre, €) ; Quantité (nombre)"
)
EXAMPLES: tuple[tuple[str, str, dict], ...] = (  # (previous spec or "", message, answer)
    ("", "montant total par région", {"analysis": {"op": "aggregate", "measure": "Montant (€)", "agg": "sum",
                                                    "by": "Région", "sort": "desc"}, "chart": "bar"}),
    ("", "évolution mensuelle du montant avec une moyenne mobile sur 3 mois",
     {"analysis": {"op": "aggregate", "measure": "Montant (€)", "agg": "sum", "time": "Date", "period": "month",
                   "window": 3}, "chart": "combo"}),
    ("", "les 3 produits les plus vendus en quantité dans le Nord",
     {"analysis": {"op": "aggregate", "measure": "Quantité", "agg": "sum", "by": "Produit", "sort": "desc", "top": 3,
                   "filters": [{"col": "Région", "op": "eq", "value": "Nord"}]}, "chart": "hbar"}),
    ("", "montant par région et par produit", {"analysis": {"op": "aggregate", "measure": "Montant (€)", "agg": "sum",
                                                             "by": "Région", "pivot": "Produit"}, "chart": "stacked"}),
    ("", "how did the amount change from 2024 to 2025 in each region?",
     {"analysis": {"op": "compare", "measure": "Montant (€)", "agg": "sum", "time": "Date", "years": [2024, 2025],
                   "by": "Région"}, "chart": "bar"}),
    ("", "variation de la quantité en % d'une semaine à l'autre",
     {"analysis": {"op": "aggregate", "measure": "Quantité", "agg": "sum", "time": "Date", "period": "week",
                   "change": True}, "chart": "combo"}),
    ("", "résume ce fichier en trois lignes", {"analysis": None, "chart": "auto"}),
    ('{"analysis":{"op":"aggregate","measure":"Montant (€)","agg":"sum","by":"Région","sort":"desc"},"chart":"bar"}',
     "plutôt en camembert", {"analysis": {"op": "aggregate", "measure": "Montant (€)", "agg": "sum", "by": "Région",
                                          "sort": "desc", "share": True}, "chart": "donut"}),
)  # fmt: skip


@dataclass
class Planned:
    plan: dict | None  # {"query": …, "chart": type | None, "why": …} or None (no computation)
    source: str = "rules"  # model | hybrid | rules (no model call) | fallback (the call failed: rules)
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------- the prompt


def _sample(c, k: int = 4) -> str:
    seen: list[str] = []
    for v in c.values:
        if v is None:
            continue
        s = str(v) if not hasattr(v, "strftime") else v.strftime("%d/%m/%Y")
        if s not in seen:
            seen.append(s[:24])
        if len(seen) >= k:
            break
    return ", ".join(seen)


def columns_text(f: Frame, lang: str = "fr") -> str:
    """One line: each column with its type and a few values (never the whole table)."""
    names = {"fr": {"number": "nombre", "date": "date", "category": "catégorie", "text": "texte", "bool": "oui/non",
                    "id": "identifiant"},
             "en": {"number": "number", "date": "date", "category": "category", "text": "text", "bool": "yes/no",
                    "id": "identifier"}}["en" if lang == "en" else "fr"]  # fmt: skip
    out = []
    for c in f.columns[:24]:
        kind = names.get(c.type, c.type)
        if c.type == "date":
            ds = [v for v in c.values if v is not None]
            extra = f"{min(ds).strftime('%d/%m/%Y')} → {max(ds).strftime('%d/%m/%Y')}" if ds else ""
        elif c.type == "number":
            extra = c.unit
        else:
            distinct = len({v for v in c.values if v is not None})
            extra = (": " if lang == "en" else " : ") + _sample(c) + ("…" if distinct > 4 else "")
            out.append(f"{c.name} ({kind}{extra})")
            continue
        out.append(f"{c.name} ({kind}{', ' + extra if extra else ''})")
    return " ; ".join(out)


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def messages(f: Frame, question: str, *, previous: dict | None = None, hints: dict | None = None,
             lang: str = "fr") -> list[dict]:  # fmt: skip
    lg = "en" if lang == "en" else "fr"
    cols = "Columns" if lg == "en" else "Colonnes"
    prev_l = "Previous turn" if lg == "en" else "Tour précédent"
    sep = ": " if lg == "en" else " : "
    shots = [f"{cols}{sep}{EXAMPLE_COLUMNS}"]
    for prev, q, a in EXAMPLES:
        shots.append((f"{prev_l}{sep}{prev} | " if prev else "") + f"« {q} » → {_dump(a)}")
    head = "Examples:" if lg == "en" else "Exemples :"
    system = _HEAD[lg] + "\n" + head + "\n" + "\n".join(shots)
    turn = [f"{cols}{sep}{columns_text(f, lg)}"]
    if previous:
        turn.append(prev_l + sep + _dump(previous))
    hint = _dump({"analysis": hints["query"], "chart": hints.get("chart") or "auto"}) if hints else "null"
    turn.append(("Hints" if lg == "en" else "Indices") + sep + hint)
    turn.append("Message" + sep + " ".join((question or "").split())[:MAX_QUESTION_CHARS])
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(turn)}]


def build_prompt(tok, f: Frame, question: str, *, previous=None, hints=None, lang="fr", structured: str = "") -> str:
    from birds.render import prompt as render_prompt

    p = render_prompt(tok, messages(f, question, previous=previous, hints=hints, lang=lang), [], False)
    return p if structured else p + PREFIX


# ---------------------------------------------------------------- the schema (built from the table)


def schema(f: Frame) -> dict:
    """The JSON schema of a planner answer for THIS table: column names are enums of its own columns."""
    every = [c.name for c in f.columns]
    nums = [c.name for c in f.columns if c.type == "number"] or every
    cats = [c.name for c in f.columns if c.type in ("category", "bool", "id", "text")] or every
    dates = [c.name for c in f.columns if c.type == "date"] or every
    enum = lambda xs: {"type": "string", "enum": list(dict.fromkeys(xs))}  # noqa: E731
    value = {"anyOf": [{"type": "string", "maxLength": 80}, {"type": "number"},
                       {"type": "array", "items": {"anyOf": [{"type": "string", "maxLength": 80}, {"type": "number"}]},
                        "maxItems": 6}]}  # fmt: skip
    analysis = {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": list(OPS)},
            "measure": enum(nums),
            "agg": {"type": "string", "enum": list(AGGS)},
            "by": enum(cats + dates),
            "time": enum(dates),
            "period": {"type": "string", "enum": list(PERIODS)},
            "pivot": enum(cats + dates),
            "filters": {"type": "array", "maxItems": MAX_FILTERS, "items": {
                "type": "object", "properties": {"col": enum(every), "op": {"type": "string", "enum": list(FILTER_OPS)},
                                                  "value": value},
                "required": ["col", "op", "value"], "additionalProperties": False}},
            "sort": {"type": "string", "enum": ["desc", "asc", "natural"]},
            "top": {"type": "integer", "minimum": 1, "maximum": MAX_TOP},
            "share": {"type": "boolean"},
            "window": {"type": "integer", "minimum": 2, "maximum": MAX_WINDOW},
            "change": {"type": "boolean"},
            "years": {"type": "array", "items": {"type": "integer", "minimum": 1900, "maximum": 2100}, "minItems": 2,
                      "maxItems": 2},
            "x": enum(nums),
            "y": enum(nums),
        },
        "required": ["op"],
        "additionalProperties": False,
    }  # fmt: skip
    return {
        "type": "object",
        "properties": {"analysis": {"anyOf": [{"type": "null"}, analysis]},
                       "chart": {"type": "string", "enum": list(CHARTS)}},
        "required": ["analysis", "chart"],
        "additionalProperties": False,
    }  # fmt: skip


# ---------------------------------------------------------------- validation


def check(f: Frame, obj) -> tuple[dict | None, str]:
    """(plan, '') for a usable answer — plan None when the model asked for no computation — or (None, why)."""
    if not isinstance(obj, dict) or "analysis" not in obj:
        return None, "no analysis key"
    chart = obj.get("chart")
    chart = chart if chart in CHARTS and chart != "auto" else None
    q = obj.get("analysis")
    if q is None:
        return None, ""
    if not isinstance(q, dict):
        return None, "analysis is not an object"
    q = {k: v for k, v in q.items() if v not in (None, "", [], False)}
    unknown = sorted(set(q) - KEYS)
    if unknown:  # the schema forbids them; without schema enforcement they are refused here (never guessed)
        return None, f"invalid: unknown keys {', '.join(unknown)}"
    if isinstance(q.get("filters"), list) and len(q["filters"]) > MAX_FILTERS:
        return None, "too many filters"
    try:
        return {"query": normalize(f, q), "chart": chart, "why": "model"}, ""
    except QueryError as e:
        # call repair: a moving average or a period change asked of a query that is not a time series (a small
        # model adds « window » to a ranking): dropped, the rest of its spec is kept
        extras = [k for k in ("window", "change") if k in q]
        if extras and ("window" in str(e) or "change" in str(e)):
            try:
                kept = normalize(f, {k: v for k, v in q.items() if k not in extras})
            except QueryError:
                return None, f"invalid: {e}"
            return {"query": kept, "chart": chart, "why": "model", "repaired": extras}, ""
        return None, f"invalid: {e}"


# ---------------------------------------------------------------- the rules (hints, fallback, no model)

_TOP = re.compile(r"\b(?:top|les|the|premiers?|first)\s*(\d{1,2})\b|\b(\d{1,2})\s+(?:premiers?|meilleurs?|best)\b")
_RETYPE = (
    ("donut", r"camembert|donut|anneau|\bpie\b|secteurs?|parts?\b|r[ée]partition|share"),
    ("line", r"courbe|ligne|\bline\b"),
    ("area", r"\baires?\b|\barea\b"),
    ("hbar", r"horizonta|classement|ranking"),
    ("stacked", r"empil|stack"),
    ("heatmap", r"chaleur|heat ?map|matrice|matrix"),
    ("scatter", r"nuage|scatter"),
    ("combo", r"combin|combo|mixte"),
    ("bar", r"barres?|histogramme|colonnes?|\bbars?\b|columns?"),
)
_PERIOD = (("day", r"\bjour|\bday|quotidien|daily"), ("week", r"semaine|week|hebdo"),
           ("month", r"\bmois\b|mensuel|month"), ("quarter", r"trimestr|quarter"),
           ("year", r"\bann[ée]e|\ban\b|annuel|year"))  # fmt: skip


def revise(f: Frame, previous: dict, words: str) -> dict | None:
    """By rule, without a model: the previous spec edited by a short follow-up (« en courbe », « top 5 seulement »,
    « par trimestre », « avec une moyenne mobile », « en pourcentage »). None when the words change nothing."""
    q = dict((previous or {}).get("analysis") or {})
    if not q:
        return None
    t = plain(words)
    if len(t.split()) > 12:
        return None  # a new question of its own, not an edit
    chart = (previous or {}).get("chart")
    changed = False
    for kind, pat in _RETYPE:
        if re.search(pat, t):
            chart, changed = kind, True
            if kind == "donut" and q.get("op") == "aggregate" and q.get("by") and not q.get("pivot"):
                q["share"] = True
            break
    m = _TOP.search(t)
    if m and q.get("op") in ("aggregate", "compare") and (q.get("by") or q.get("op") == "compare"):
        q["top"], changed = int(m.group(1) or m.group(2)), True
        q["sort"] = "asc" if re.search(r"moins|pires?|flop|bottom|worst|least", t) else "desc"
    dates = [c.name for c in f.columns if c.type == "date"]
    col = _by_column(f, t)
    if col is not None and col != q.get("by") and q.get("op") in ("aggregate", "compare", "describe"):
        # « Par Produit » after « Quantité moyenne par région »: the same measure and aggregation, another category
        if q["op"] == "describe":  # a distribution per category: its mean in each
            q = {"op": "aggregate", "measure": q["measure"], "agg": "mean",
                 **({"filters": q["filters"]} if q.get("filters") else {})}  # fmt: skip
        if q["op"] == "aggregate":
            for k in ("time", "period", "window", "change"):
                q.pop(k, None)
            chart = chart if chart in ("bar", "hbar", "donut") else "bar"
        if q.get("pivot") == col:
            q.pop("pivot")
        q["by"], q["sort"], changed = col, "desc", True
    for period, pat in _PERIOD:
        if re.search(r"\b(?:par|by|per|en|au|a la)\b.*" + pat, t) and (q.get("time") or dates):
            if not q.get("time") and q.get("op") == "aggregate":  # « par mois » after « par région »: over time
                q["time"] = dates[0]
                q.pop("by", None), q.pop("top", None), q.pop("share", None)
                q["sort"] = "natural"
                chart = chart if chart in ("line", "area", "combo") else "line"
            q["period"], changed = period, True
            break
    def over_time() -> None:
        q.setdefault("time", dates[0])
        q.setdefault("period", "month")
        for k in ("by", "pivot", "top", "share"):
            q.pop(k, None)
        q["sort"] = "natural"

    if re.search(r"moyenne mobile|moving average|liss|rolling", t) and (q.get("time") or dates):
        over_time()
        n = re.search(r"(\d{1,2})", t)
        q["window"], changed = int(n.group(1)) if n else 3, True
        chart = chart if chart in ("line", "area") else "combo"
    if re.search(r"evolution en %|variation|en pourcentage|percent change|% change|d'un mois a l'autre", t) \
            and (q.get("time") or dates):  # fmt: skip
        over_time()
        q["change"], changed = True, True
        chart = "combo"
    if not changed:
        return None
    try:
        return {"query": normalize(f, q), "chart": chart, "why": "revised"}
    except QueryError:
        return None


_BY = re.compile(r"\b(?:par|by|per|selon|pour chaque|for each)\s+(?:les?\s+|la\s+|l'|des\s+|the\s+|each\s+)?"
                 r"([\w'-]+(?:\s+[\w'-]+)?)")  # fmt: skip


def _by_column(f: Frame, t: str) -> str | None:
    """The category column named after « par / by » in a short follow-up (``t`` is plain), or None (« par mois »)."""
    from birds.harness.analysis.ask import _named, column_score, tokens

    found = list(_BY.finditer(t))
    words = set(tokens(t))
    if len(found) != 1 or any(c.type == "number" and column_score(c, words) > 0.5 for c in f.columns):
        return None  # « CA par région et par produit » is a question of its own, not an edit
    c = _named(f, set(tokens(found[0].group(1))), ("category", "bool", "id", "text"))
    return c.name if c else None


def rule_plan(f: Frame, question: str, previous: dict | None = None) -> dict | None:
    """The fixed rules: a follow-up edit of the previous spec, else a template of ``ask.py``."""
    if previous:
        got = revise(f, previous, question)
        if got:
            return got
    plan = plan_question(f, question) if question else None
    return {**plan, "chart": plan.get("chart")} if plan else None


def previous_spec(history: list[dict] | None) -> dict | None:
    """The spec of the last analysis shown in this conversation (the memo line the server writes), or None."""
    for m in reversed(history or []):
        if m.get("role") != "assistant":
            continue
        text = str(m.get("content") or "") + "\n" + str(m.get("memo") or "")
        found = MEMO_RE.findall(text)
        if found:
            try:
                obj = json.loads(found[-1])
            except ValueError:
                return None
            return obj if isinstance(obj, dict) and isinstance(obj.get("analysis"), dict) else None
        return None  # only the previous answer counts: an older analysis is not « it »
    return None


def memo_line(name: str, plan: dict | None, lang: str = "fr") -> str:
    """« [Analyse de « ventes.csv » — {"analysis":…,"chart":…}] »: what a follow-up edits next turn."""
    if not plan:
        return ""
    head = "Analysis of" if lang == "en" else "Analyse de"
    spec = {"analysis": plan["query"], "chart": plan.get("chart") or "auto"}
    return f"[{head} « {name[:120]} » — {_dump(spec)}]"


# ---------------------------------------------------------------- the decision


def decide(llm, tok, f: Frame, question: str, *, history=None, lang: str = "fr", mode: str = "hybrid",
           structured: str = "", budget: float = BUDGET_S, cache_salt: str | None = None) -> Planned:  # fmt: skip
    """One planner call. Never raises: any failure gives the rules' plan with ``source == "fallback"``."""
    from birds.harness.router import parse_raw, structured_extra

    previous = previous_spec(history)
    base = rule_plan(f, question, previous)
    meta: dict = {"mode": mode, "structured": structured or "prompt", "hint": bool(base), "followup": bool(previous)}
    if mode == "rules" or llm is None:
        return Planned(base, "rules", meta)
    prompt = build_prompt(tok, f, question, previous=previous, hints=base, lang=lang, structured=structured)
    extra = {"temperature": 0, **structured_extra(structured, schema(f))}
    if cache_salt:
        extra["cache_salt"] = cache_salt
    t0 = time.monotonic()
    try:
        out = llm.generate(prompt, MAX_TOKENS, STOP, deadline=t0 + budget, extra=extra)
    except Exception as e:  # an endpoint error, or a client bug: the turn goes on with the rules
        meta.update({"fallback": getattr(e, "kind", type(e).__name__), "seconds": round(time.monotonic() - t0, 3)})
        return Planned(base, "fallback", meta)
    meta["seconds"] = round(time.monotonic() - t0, 3)
    meta["usage"] = {k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "cached_tokens") if k in out}
    try:
        obj = parse_raw(out.get("text") or "", "" if structured else PREFIX)
    except ValueError:
        meta.update({"fallback": "invalid_json", "invalid": True})
        return Planned(base, "fallback", meta)
    plan, why = check(f, obj)
    if why:
        meta.update({"fallback": why, "invalid": True})
        return Planned(base, "fallback", meta)
    if plan and plan.get("repaired"):
        meta["repaired"] = plan.pop("repaired")
    meta["model"] = {"analysis": plan["query"] if plan else None, "chart": plan.get("chart") if plan else None}
    # an explicit null is the model's decision (« Quelle est la population de Canberra ? » with a table in the
    # conversation): the rules never overrule it; they only stand in when the call itself failed (above)
    if plan is not None and not plan.get("chart") and base and base.get("query") == plan["query"]:
        plan["chart"] = base.get("chart")
    return Planned(plan, "model", meta)


def resolve_mode(cfg=None, llm=None, *, deadline: float | None = None) -> tuple[str, str]:
    """(mode, structured kind): the module router's setting (``BIRD_ROUTER``) — regex means rules only."""
    from birds.harness import router

    mode, kind = router.resolve_mode(cfg, llm, deadline=deadline)
    return ("rules" if mode == "regex" else mode), kind


__all__ = ["CHARTS", "EXAMPLES", "Planned", "check", "columns_text", "decide", "memo_line", "messages",
           "previous_spec", "resolve_mode", "revise", "rule_plan", "schema"]  # fmt: skip
