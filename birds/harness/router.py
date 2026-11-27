"""Model-driven router: Bird itself decides which modules a request needs, before the main generation.

Until now the rich modules (weather, places, company, currencies, clock, events, pictures, charts) were started by
deterministic parsers (``intents.py``, ``clock.py``, ``when.py``, ``agent.route``), because Bird S 4B was never
trained on them. Here the model decides, in ONE short call (≤ 80 output tokens, temperature 0):

    {"modules": [{"tool": "get_weather", "args": {"place": "Lyon", "day": "demain"}}], "agent": "off",
     "needs_web": false}

The prompt is the static catalogue of ``catalog.py`` (shared prefix: vLLM caches it), a few fixed examples, then
the turn: the previous turn's context (the server's memo, never the model's text), the HINTS of the regex parsers
(« indices », which can be wrong) and the user's own words.

The regex parsers keep three roles, never the primary decider when the router answered:

- hints in the prompt;
- the FALLBACK when the router is unavailable, too slow (latency budget), or answers something unusable, and per
  module when the model named a module the parsers also see but wrote invalid arguments;
- a SAFETY VETO for the known false-trigger families of the trigger bench (« météo des marchés », « charte
  graphique », « image de marque », « heures de pointe »…): a module the model proposes is dropped only when its
  family's false-trigger pattern matches AND the family's own parser does not fire.

Every argument is validated (``catalog.check_args``) and must be GROUNDED: written in the user's words or in the
previous turn's context (a small model must not look up a place it made up).

``BIRD_ROUTER`` (or ``Config.router``): ``model`` (the router decides), ``hybrid`` (the router decides, and a
confident parser call the router missed is kept), ``regex`` (no router call: the previous behaviour), ``auto``
(default): ``model`` when the endpoint enforces JSON schemas (structured outputs, detected once and cached),
``hybrid`` when it does not, ``regex`` for an in-process or scripted client that cannot be probed.

Structured outputs: vLLM ≥ 0.10 (``structured_outputs: {json}``), older vLLM (``guided_json``), OpenAI-style
``response_format: json_schema``, llama.cpp (``json_schema``). Unknown request fields are ignored by vLLM rather
than refused, so each form is tried on a tiny probe whose answer can only be right if the schema was enforced.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field

from birds.harness import catalog

log = logging.getLogger("bird.router")

MODES = ("model", "hybrid", "regex")
MAX_TOKENS = 80
BUDGET_S = 3.0  # latency budget of one router call; beyond it the turn goes on with the parsers
PROBE_S = 6.0
FAIL_TTL_S = 60.0  # a probe that could not reach the endpoint is retried after this long
MAX_MESSAGE_CHARS = 600  # the router reads the start of a long paste: the intent is there
STOP = ["<|im_end|>", "<|endoftext|>", "\n\n"]
PREFIX = '{"modules":'  # written for the model when the endpoint cannot enforce the schema

STRUCTURED_KINDS = ("structured_outputs", "guided_json", "response_format", "json_schema")


@dataclass
class Call:
    tool: str
    args: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"tool": self.tool, "args": dict(self.args)}


@dataclass
class Decision:
    modules: list[Call] = field(default_factory=list)
    agent: str = "auto"
    needs_web: bool = False
    source: str = "model"  # model | hybrid | regex (router off) | fallback (router failed: parsers)
    meta: dict = field(default_factory=dict)

    def tools(self) -> list[str]:
        return [c.tool for c in self.modules]

    def get(self, tool: str) -> Call | None:
        return next((c for c in self.modules if c.tool == tool), None)

    def as_dict(self) -> dict:
        return {"modules": [c.as_dict() for c in self.modules], "agent": self.agent, "needs_web": self.needs_web}


# ---------------------------------------------------------------- the parsers' decision (hints, fallback, baseline)


def _cities(found: dict, lang: str) -> list[str]:
    return [c.get("en" if lang == "en" else "fr") or c["fr"] for c in found.get("cities") or []]


def regex_decision(
    text: str, *, history: list[dict] | None = None, attached: bool = False, lang: str = "fr", now=None
) -> Decision:
    """What the deterministic parsers decide for these words, in the router's format. Mirrors ``Agent.run``:
    a confident widget call (or a follow-up of the previous one) first, else the clock, an event, pictures; then
    a chart and an office file. Pure (no network)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from birds.harness import agent as A
    from birds.harness import clock, followup, intents, when

    text = text or ""
    mods: list[Call] = []
    found = intents.detect(text, attached, lang)
    prev = followup.previous(history) if history and not attached else None
    again = None if any(i.args for i in found) else followup.resolve(text, prev, lang)
    clock_text = text
    if again is not None and again.tool == "clock":
        clock_text = again.args["text"]
    elif again is not None:
        found = [again]
    pre = next((i for i in found if i.args), None)
    if pre is not None:
        mods.append(Call(pre.tool, dict(pre.args)))
    else:
        got = clock.detect(clock_text)
        now = now or datetime.now(ZoneInfo("Europe/Paris"))
        if got and got["cities"]:
            mods.append(Call("clock", {"cities": _cities(got, lang), "mode": got["mode"]}))
        elif not A._NEEDS_WEB.search(text) and when.event_ask(text, now, lang) is not None:
            mods.append(Call("event", {}))
        elif not attached and (img := intents.images(text, lang)) is not None:
            mods.append(Call("images", {"subject": img.args["query"]}))
    last = next((m for m in reversed(history or []) if m.get("role") in ("user", "assistant")), None) or {}
    retype = (
        last.get("role") == "assistant"
        and bool(A._CHART_MEMO.search(str(last.get("content") or "") + str(last.get("memo") or "")))
        and followup.chart_retype(text)
    )
    if retype or ("make_chart" not in A.route(text, attached) and (A.chart_ask(text) or A.trend_ask(text))):
        kind = next((k for k, rx in A._KIND_ASKED if rx.search(text)), "")
        mods.append(Call("make_chart", {"type": kind} if kind else {}))
    office = A._FILE_ASK.search(text)
    if office and len(mods) < catalog.MAX_MODULES:
        word = office.group(0).lower()
        kind = (
            "slides" if re.match(r"pr|dia|slide|ppt|power|deck", word)
            else "sheet" if re.match(r"tab|exc|xls|spread|feuille", word)
            else "email" if re.search(r"mail|courriel", word)
            else "document"
        )  # fmt: skip
        mods.append(Call("office", {"kind": kind}))
    agent = "auto"
    try:
        from birds.harness import crew

        if crew.decide(text, mode="auto", lang=lang, history=bool(history)).recipe:
            agent = "on"
    except Exception:  # the crew's own heuristics must never break routing
        pass
    return Decision(mods[: catalog.MAX_MODULES], agent, bool(A._NEEDS_WEB.search(text)), "regex")


# ---------------------------------------------------------------- grounding: arguments come from the user's words


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").replace("’", "'").casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", t).split())


_LINK_WORDS = frozenset("de du des la le les l d a au aux en the of in at et and sur pres near".split())


def grounded(value: str, *sources: str) -> bool:
    """Every meaningful word of ``value`` is in one of ``sources`` (accents, case and plurals ignored)."""
    words = [w for w in fold(value).split() if w not in _LINK_WORDS]
    pool = set(" ".join(fold(s) for s in sources).split())
    if not words:
        return False

    def seen(w: str) -> bool:
        if w in pool or (w.isdigit() and w in "".join(pool)):
            return True
        # plural only (« koalas » / « koala »): never a cut-off word
        return len(w) >= 4 and any(p in (w + "s", w + "x") or w in (p + "s", p + "x") for p in pool)

    return all(seen(w) for w in words)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def ground(call: Call, text: str, context: str, lang: str = "fr") -> str:
    """'' when the call's arguments come from the user's words (or the previous turn's context), else why not."""
    from birds.harness import clock, intents
    from birds.harness.tools.places import _KIND_KEYS

    a = call.args
    if call.tool == "get_weather":
        return "" if grounded(a["place"], text, context) else "place not in the user's words"
    if call.tool == "find_places":
        q = a["query"]
        kind = q.lower() in _KIND_KEYS and (intents._kind_in(text) or intents._kind_in(context) or grounded(q, text))
        if not (kind or grounded(q, text, context)):
            return "query not in the user's words"
        if a.get("near") and not grounded(a["near"], text, context):
            return "near not in the user's words"
        return ""
    if call.tool == "find_company":
        name = a["name"]
        if _digits(name) and len(_digits(name)) in (9, 14):
            return "" if _digits(name) in _digits(text) else "SIREN not in the user's words"
        return "" if grounded(name, text, context) else "name not in the user's words"
    if call.tool == "convert_currency":
        if "amount" in a:
            n = a["amount"]
            whole = str(int(n)) if float(n).is_integer() else str(n).replace(".", "")
            amounts = [intents.parse_amount(m.group(0)) for m in re.finditer(r"\d[\d\s  .,]*(?:\s*[kKmM]\b)?", text)]
            if whole not in _digits(text) and n not in amounts and whole not in _digits(context):
                return "amount not in the user's words"
        return ""
    if call.tool == "clock":
        named = {fold(c["fr"]) for c in clock._names_in(text + " " + context)}
        for c in a["cities"]:
            if not (grounded(c, text, context) or fold(c) in named):
                return "city not in the user's words"
        return ""
    if call.tool == "images":
        return "" if grounded(a["subject"], text) else "subject not in the user's words"
    if call.tool == "event":
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from birds.harness import when

        now = datetime.now(ZoneInfo("Europe/Paris"))
        return "" if when.event_ask(text, now, lang) or when.parse(text, now, lang) else "no date in the user's words"
    return ""


# ---------------------------------------------------------------- safety veto: known false-trigger families

_EVENT_NOT = re.compile(
    r"\b(?:annul\w*|d[ée]cal\w*|cancel\w*|reschedul\w*|compte[- ]rendu|r[ée]sum\w*|ordre du jour|comment|how (?:do|to)|"
    r"merci|remerci\w*|explique\w*|quelle est la date|recherche\w*|actualit\w*|fonction|formation choisir)\b",
    re.I,
)
_CLOCK_NOT = re.compile(r"\bentre\s+\d{1,2}\s*h|\bbetween\s+\d{1,2}\s*(?:am|pm)?\s+and\b|^\s*(?:à|a)\s+quelle\s+heure\b",
                        re.I)  # fmt: skip
_IMG_NOT = re.compile(
    r"\b(?:image de marque|droit à l'image|image (?:de|du) (?:l'entreprise|la soci[ée]t[ée]|service)|vaut mille mots|"
    r"photos? de profil|images? de synth[èe]se|photo sur un cv)\b",
    re.I,
)


_CHART_FALSE = re.compile(  # trends and careers with no chart noun: « les tendances du marketing digital en 2026 »
    r"\btendances?\s+(?:mode|de\s+la\s+mode|du\s+marketing|d[ue]s?\s+\w+\s+(?:en|pour)\s+20\d\d)|"
    r"[ée]volu\w*\s+(?:de\s+carri[èe]re|vers)|\bcomment\s+[ée]voluer\b|\bcareer\s+(?:path|growth)\b",
    re.I,
)
_PLACE_ARGS = {
    "get_weather": ("place",),
    "find_places": ("query", "near"),
    "clock": ("cities",),
    "images": ("subject",),
}


def _bad_place(call: Call) -> bool:
    """A 'place' that names a document, a meeting, an office notion or a person (« document », « projet »)."""
    from birds.harness import clock, intents

    for k in _PLACE_ARGS.get(call.tool, ()):
        v = call.args.get(k)
        for x in v if isinstance(v, list) else [v or ""]:
            if not x or (call.tool == "clock" and clock._names_in(x)):  # « Saint-Denis (La Réunion) » is a city
                continue
            if intents._NEVER.search(x) or intents._not_a_place(x) or intents._NOT_TARGET.match(x):
                return True
    return False


def veto_reason(call: Call, text: str, *, attached: bool = False, lang: str = "fr", context: str = "") -> str:
    """'' or the false-trigger family that blocks this module. Only blocks what the family's own parser would not
    start: the veto never removes something the regex also sees. A follow-up of the previous turn's module
    (``context`` names it: « et 500 ? » after a conversion) needs no currency or company word of its own."""
    from birds.harness import agent as A
    from birds.harness import clock, intents, when

    t = text or ""
    if _bad_place(call):
        return "not a place"
    follow = bool(context) and f": {call.tool} " in context
    if call.tool == "get_weather":
        bad = intents._WX_NEVER.search(t) or intents._WX_FALSE_ASK.search(t)
        fires = (w := intents.weather(t)) is not None and w.args
        return "weather false trigger" if bad and not fires else ""
    if call.tool == "find_places":
        q = call.args.get("query", "")
        bad = intents._NEVER.search(t) or intents._APPS.fullmatch(q) or intents._DOC_TARGET.search(t)
        return "map false trigger" if bad and not intents.places(t) else ""
    if call.tool == "find_company":
        bad = intents._DEFINE.search(t) or intents._NOT_A_COMPANY.match(call.args.get("name", ""))
        bad = bad or re.search(r"\b(?:conseils?|tips|astuces?)\b", t, re.I)
        name = call.args.get("name", "")
        # a lowercase word with no register cue is not a company name (« ses résultats », « €/mois »)
        if not (follow or name[:1].isupper() or _digits(name) or intents._COMPANY_HINT.search(t)):
            bad = bad or not re.search(r"\b(?:soci[ée]t[ée]|entreprise|company|bo[iî]te)\b", t, re.I)
        return "company false trigger" if bad and not intents.company(t) else ""
    if call.tool == "convert_currency":
        bad = not (follow or intents._CUR_ANY.search(t) or intents._FX_HINT.search(t) or re.search(r"\b[A-Z]{3}\b", t))
        return "fx false trigger" if bad and not intents.fx(t) else ""
    if call.tool == "clock":
        bad = clock._NOT_CLOCK.search(t) or _CLOCK_NOT.search(t)
        return "clock false trigger" if bad and not clock.detect(t) else ""
    if call.tool == "make_chart":
        bad = A._NOT_CHART.search(t) or A.chart_howto(t) or (_CHART_FALSE.search(t) and not A._CHART_ASK.search(t))
        fires = "make_chart" not in A.route(t, attached)
        return "chart false trigger" if bad and not fires else ""
    if call.tool == "images":
        s = call.args.get("subject", "")
        bad = intents._IMG_MAKE.search(t) or _IMG_NOT.search(t) or intents._IMG_NOT_SUBJECT.match(s)
        bad = bad or intents._person(s)
        return "images false trigger" if bad and not intents.images(t) else ""
    if call.tool == "event":
        from datetime import datetime
        from zoneinfo import ZoneInfo

        fires = when.event_ask(t, datetime.now(ZoneInfo("Europe/Paris")), lang) is not None
        return "event false trigger" if _EVENT_NOT.search(t) and not fires else ""
    return ""


# ---------------------------------------------------------------- reading what the model wrote

_ALIASES = {
    "weather": "get_weather", "meteo": "get_weather", "météo": "get_weather", "forecast": "get_weather",
    "places": "find_places", "place": "find_places", "map": "find_places", "maps": "find_places",
    "carte": "find_places", "company": "find_company", "entreprise": "find_company", "fx": "convert_currency",
    "currency": "convert_currency", "devises": "convert_currency", "chart": "make_chart", "graph": "make_chart",
    "graphique": "make_chart", "calendar": "event", "agenda": "event", "ics": "event", "image": "images",
    "photos": "images", "pictures": "images", "time": "clock", "horloge": "clock", "files": "office",
    "document": "office",
}  # fmt: skip


def parse_raw(raw: str, prefix: str = "") -> dict:
    """The JSON object in the router's answer (code fences, prose around it, a missing closing bracket, single
    quotes or a trailing comma are tolerated). Raises ValueError when there is no object to read."""
    from birds.harness.coerce import parse_json_like

    raw = (raw or "").lstrip()
    s = (raw if raw.startswith("{") else prefix + raw).strip()  # a model that restarts the object: its own
    s = re.sub(r"^<think>.*?</think>\s*", "", s, flags=re.S)
    start = s.find("{")
    if start < 0:
        raise ValueError("no JSON object")
    s = s[start:]
    depth, in_str, esc, end = 0, False, False, len(s)
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if depth > 0 and end == len(s):
        raise ValueError("truncated")  # cut off mid-object: its last value cannot be trusted
    obj = parse_json_like(s[:end])
    if not isinstance(obj, dict):
        raise ValueError("not an object")
    return obj


def _bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "oui", "yes", "1")
    return bool(v) if isinstance(v, (bool, int)) else False


def validate(
    obj: dict,
    text: str,
    *,
    context: str = "",
    names: set[str] | None = None,
    attached: bool = False,
    lang: str = "fr",
) -> tuple[Decision, list[tuple[str, str]], list[tuple[str, str]]]:
    """(decision, dropped [(tool, why)], vetoed [(tool, why)]). Invalid or ungrounded modules are dropped, never
    repaired by guessing; modules outside ``names`` (the catalogue shown) are dropped too."""
    allowed = {m.name for m in catalog.available(names)}
    mods = obj.get("modules", [])
    if isinstance(mods, dict):
        mods = [mods]
    if not isinstance(mods, list):
        mods = []
    out: list[Call] = []
    dropped: list[tuple[str, str]] = []
    vetoed: list[tuple[str, str]] = []
    for m in mods:
        if isinstance(m, str):
            m = {"tool": m, "args": {}}
        if not isinstance(m, dict):
            dropped.append(("?", "module is not an object"))
            continue
        tool = str(m.get("tool") or m.get("name") or "").strip()
        tool = _ALIASES.get(tool.lower(), tool)
        if tool not in allowed:
            dropped.append((tool or "?", "not in the catalogue"))
            continue
        if any(c.tool == tool for c in out):
            continue
        raw_args = m.get("args", m.get("arguments", {}))
        if isinstance(raw_args, str):
            try:
                raw_args = parse_raw(raw_args)
            except ValueError:
                raw_args = None
        args, why = catalog.check_args(tool, raw_args)
        if args is None:
            dropped.append((tool, why))
            continue
        call = Call(tool, args)
        why = ground(call, text, "" if attached else context, lang)
        if why:
            dropped.append((tool, why))
            continue
        why = veto_reason(call, text, attached=attached, lang=lang, context=context)
        if why:
            vetoed.append((tool, why))
            continue
        out.append(call)
    agent = str(obj.get("agent", "auto")).strip().lower()
    d = Decision(out[: catalog.MAX_MODULES], agent if agent in catalog.AGENT_MODES else "auto",
                 _bool(obj.get("needs_web", False)), "model")  # fmt: skip
    return d, dropped, vetoed


# ---------------------------------------------------------------- the prompt

_FEW_SHOT = {
    "fr": (
        ("Message : météo à Lyon demain", '{"modules":[{"tool":"get_weather","args":{"place":"Lyon","day":"demain"}}],'
         '"agent":"off","needs_web":false}'),
        ("Message : fais-moi la météo des marchés", '{"modules":[],"agent":"off","needs_web":true}'),
        ("Tour précédent : contexte : find_places {\"query\": \"restaurant\", \"near\": \"gare de Lyon\"}\n"
         "Message : et des hôtels ?", '{"modules":[{"tool":"find_places","args":{"query":"hotel","near":"gare de '
         'Lyon"}}],"agent":"off","needs_web":false}'),
        ("Message : rédige un mail à Paul pour décaler la réunion",
         '{"modules":[{"tool":"office","args":{"kind":"email"}}],"agent":"off","needs_web":false}'),
        ("Message : fais une étude comparative des 3 principaux CRM du marché avec des sources",
         '{"modules":[{"tool":"office","args":{"kind":"document"}}],"agent":"on","needs_web":true}'),
    ),
    "en": (
        ("Message: will it rain in Berlin on Friday?", '{"modules":[{"tool":"get_weather","args":{"place":"Berlin",'
         '"day":"Friday"}}],"agent":"off","needs_web":false}'),
        ("Message: sales forecast for Q3", '{"modules":[],"agent":"off","needs_web":false}'),
        ("Message: time difference between Paris and Los Angeles", '{"modules":[{"tool":"clock","args":{"cities":'
         '["Paris","Los Angeles"],"mode":"offset"}}],"agent":"off","needs_web":false}'),
        ("Message: draft an email to John to move the meeting",
         '{"modules":[{"tool":"office","args":{"kind":"email"}}],"agent":"off","needs_web":false}'),
        ("Message: write a comparative study of the main project management tools on the market",
         '{"modules":[{"tool":"office","args":{"kind":"document"}}],"agent":"on","needs_web":true}'),
    ),
}  # fmt: skip


def _hint_text(d: Decision | None, lang: str) -> str:
    if d is None or not d.modules:
        return "aucun" if lang != "en" else "none"
    return " ; ".join(f"{c.tool} {json.dumps(c.args, ensure_ascii=False, separators=(',', ':'))}" for c in d.modules)


def previous_summary(history: list[dict] | None, lang: str = "fr") -> str:
    """The previous turn for the router: the server's memo context (« contexte : get_weather {…} »), a chart shown,
    and the start of the previous request. Never the model's own text."""
    from birds.harness import followup
    from birds.harness.agent import _CHART_MEMO

    if not history:
        return ""
    parts = []
    prev = followup.previous(history)
    if prev:
        parts.append(followup.memo_part(prev, lang))
    last = next((m for m in reversed(history) if m.get("role") == "assistant"), None) or {}
    if _CHART_MEMO.search(str(last.get("content") or "") + str(last.get("memo") or "")):
        parts.append("graphique affiché" if lang != "en" else "a chart was shown")
    ask = next((m for m in reversed(history) if m.get("role") == "user"), None)
    if ask and isinstance(ask.get("content"), str):
        parts.append(("demande : " if lang != "en" else "request: ") + " ".join(ask["content"].split())[:160])
    return " | ".join(p for p in parts if p)


def messages(text: str, *, history=None, hints: Decision | None = None, lang: str = "fr", names=None) -> list[dict]:
    """[system, user]: the catalogue and the fixed examples (static: the endpoint reuses them from its prefix
    cache), then this turn. The examples sit in the system message, not as earlier turns, so a training record
    built from these messages (scripts/build_tools_mix.py) has a single assistant turn to learn."""
    lg = "en" if lang == "en" else "fr"
    shots = "\n".join(q.replace("\n", " / ") + " → " + a for q, a in _FEW_SHOT[lg])
    head = "Examples:" if lg == "en" else "Exemples :"
    msgs = [{"role": "system", "content": catalog.text(lg, names) + "\n" + head + "\n" + shots}]
    sep = ": " if lg == "en" else " : "
    turn = []
    prev = previous_summary(history, lg)
    if prev:
        turn.append(("Previous turn" if lg == "en" else "Tour précédent") + sep + prev)
    turn.append(("Hints" if lg == "en" else "Indices") + sep + _hint_text(hints, lg))
    msg = " ".join((text or "").split())[:MAX_MESSAGE_CHARS]
    turn.append("Message" + sep + msg)
    msgs.append({"role": "user", "content": "\n".join(turn)})
    return msgs


def build_prompt(tok, text: str, *, history=None, hints=None, lang="fr", names=None, structured: str = "") -> str:
    from birds.render import prompt as render_prompt

    p = render_prompt(tok, messages(text, history=history, hints=hints, lang=lang, names=names), [], False)
    return p if structured else p + PREFIX


# ---------------------------------------------------------------- structured outputs: request shapes, detection

_PROBE_SCHEMA = {
    "type": "object",
    "properties": {"probe": {"type": "string", "enum": ["bird-router-ok"]}},
    "required": ["probe"],
    "additionalProperties": False,
}
_cache: dict[tuple, tuple[str, float]] = {}  # (url, model) -> (kind, monotonic time; 0 = for good)


def structured_extra(kind: str, schema: dict) -> dict:
    """Request fields that make the endpoint enforce ``schema`` on a /v1/completions call."""
    if kind == "structured_outputs":  # vLLM >= 0.10
        return {"structured_outputs": {"json": schema}}
    if kind == "guided_json":  # vLLM before 0.10 (removed later)
        return {"guided_json": schema}
    if kind == "response_format":  # OpenAI-style, accepted on completions by recent vLLM and SGLang
        return {"response_format": {"type": "json_schema", "json_schema": {"name": "bird_route", "schema": schema}}}
    if kind == "json_schema":  # llama.cpp server
        return {"json_schema": schema}
    return {}


def _key(llm) -> tuple:
    return (getattr(llm, "url", None) or id(llm), getattr(llm, "model", ""))


def probeable(llm) -> bool:
    """A remote OpenAI-compatible client we can ask (CompletionsClient), or a client that declares its support."""
    return hasattr(llm, "router_structured") or (hasattr(llm, "url") and hasattr(llm, "generate"))


def structured_kind(llm, *, deadline: float | None = None) -> str:
    """The structured-output form this endpoint enforces, or ''. Detected once per (URL, model) and cached; a
    probe that could not reach the endpoint (paused, waking) is retried after ``FAIL_TTL_S``."""
    if hasattr(llm, "router_structured"):
        return str(llm.router_structured or "")
    if not probeable(llm):
        return ""
    key = _key(llm)
    got = _cache.get(key)
    if got is not None and (got[1] == 0 or time.monotonic() - got[1] < FAIL_TTL_S):
        return got[0]
    from birds.harness.llm import EndpointError

    end = deadline or time.monotonic() + PROBE_S
    reached = False
    for kind in STRUCTURED_KINDS:
        if time.monotonic() > end - 1.2:
            break
        try:
            out = llm.generate(
                "Écris le mot bonjour.\n", 16, ["<|im_end|>"],
                deadline=min(end, time.monotonic() + 4.0),
                extra={"temperature": 0, **structured_extra(kind, _PROBE_SCHEMA)},
            )  # fmt: skip
        except EndpointError as e:
            if e.kind in ("bad_request",):
                reached = True
                continue  # this server refuses the field: try the next form
            break  # unreachable, paused, waking, timeout: do not conclude
        except Exception:
            break
        reached = True
        try:
            if json.loads((out.get("text") or "").strip()) == {"probe": "bird-router-ok"}:
                _cache[key] = (kind, 0)
                log.info(json.dumps({"event": "router_structured", "kind": kind}))
                return kind
        except ValueError:
            pass
    _cache[key] = ("", 0 if reached else time.monotonic())
    return ""


def resolve_mode(cfg=None, llm=None, *, deadline: float | None = None) -> tuple[str, str]:
    """(mode, structured kind). ``BIRD_ROUTER`` / ``Config.router``: model | hybrid | regex | auto (default)."""
    want = str(getattr(cfg, "router", None) or os.environ.get("BIRD_ROUTER") or "auto").strip().lower()
    if want == "regex" or (cfg is not None and not getattr(cfg, "widgets", True)):
        return "regex", ""
    if want in ("model", "hybrid"):
        return want, structured_kind(llm, deadline=deadline) if llm is not None else ""
    if llm is None or not probeable(llm):
        return "regex", ""  # in-process or scripted client: nothing to ask, keep the parsers
    kind = structured_kind(llm, deadline=deadline)
    return ("model" if kind else "hybrid"), kind


# ---------------------------------------------------------------- the decision


def _fallback(base: Decision, why: str, meta: dict) -> Decision:
    return Decision(list(base.modules), base.agent, base.needs_web, "fallback", {**meta, "fallback": why})


def merge(model: Decision, base: Decision) -> Decision:
    """hybrid: the model's decision, plus a confident parser call of a family the model left out."""
    mods = list(model.modules)
    fam = {catalog.BY_NAME[c.tool].family for c in mods}
    for c in base.modules:
        if catalog.BY_NAME[c.tool].kind != catalog.HINT and catalog.BY_NAME[c.tool].family not in fam:
            mods.append(c)
    return Decision(mods[: catalog.MAX_MODULES], model.agent, model.needs_web or base.needs_web, "hybrid",
                    dict(model.meta))  # fmt: skip


def decide(
    llm,
    tok,
    text: str,
    *,
    history: list[dict] | None = None,
    attached: bool = False,
    lang: str = "fr",
    mode: str = "model",
    structured: str = "",
    budget: float = BUDGET_S,
    names: set[str] | None = None,
    cache_salt: str | None = None,
    base: Decision | None = None,
) -> Decision:
    """One router call. Never raises: any failure gives the parsers' decision with ``source == "fallback"``."""
    from birds.harness.llm import EndpointError

    base = base or regex_decision(text, history=history, attached=attached, lang=lang)
    meta: dict = {"mode": mode, "structured": structured or "prompt", "hint_tools": base.tools()}
    if mode == "regex":
        return Decision(list(base.modules), base.agent, base.needs_web, "regex", meta)
    prompt = build_prompt(tok, text, history=history, hints=base, lang=lang, names=names, structured=structured)
    extra = {"temperature": 0, **structured_extra(structured, catalog.decision_schema(names))}
    if cache_salt:
        extra["cache_salt"] = cache_salt
    t0 = time.monotonic()
    try:
        out = llm.generate(prompt, MAX_TOKENS, STOP, deadline=t0 + budget, extra=extra)
    except EndpointError as e:
        return _fallback(base, e.kind, {**meta, "seconds": round(time.monotonic() - t0, 3)})
    except Exception as e:  # a client bug must not break the turn
        return _fallback(base, type(e).__name__, {**meta, "seconds": round(time.monotonic() - t0, 3)})
    seconds = round(time.monotonic() - t0, 3)
    meta["seconds"] = seconds
    meta["usage"] = {k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds", "busy_seconds",
                                               "cached_tokens", "finish_reason") if k in out}  # fmt: skip
    if seconds > budget * 1.5:
        return _fallback(base, "over_budget", meta)
    try:
        obj = parse_raw(out.get("text") or "", "" if structured else PREFIX)
    except ValueError:
        return _fallback(base, "invalid_json", {**meta, "invalid": True})
    context = previous_summary(history, lang)
    d, dropped, vetoed = validate(obj, text, context=context, names=names, attached=attached, lang=lang)
    # a module the model named with unusable arguments: the parser's call of the same tool, if it has one
    for tool, _why in dropped:
        sub = base.get(tool)
        if sub is not None and d.get(tool) is None and len(d.modules) < catalog.MAX_MODULES:
            d.modules.append(Call(sub.tool, dict(sub.args)))
            meta.setdefault("substituted", []).append(tool)
    meta.update({"dropped": dropped, "vetoed": [t for t, _ in vetoed], "repaired": not structured})
    d.meta = meta
    if mode == "hybrid":
        d = merge(d, base)
    d.meta.update({"tools": d.tools(), "arg_keys": {c.tool: sorted(c.args) for c in d.modules}, "agent": d.agent,
                   "needs_web": d.needs_web, "source": d.source})  # fmt: skip
    return d


def log_meta(d: Decision) -> dict:
    """Metadata only (tool names, argument NAMES, timings, reasons): never what the user wrote or an argument."""
    m = d.meta
    return {
        "mode": m.get("mode"),
        "source": d.source,
        "structured": m.get("structured"),
        "tools": d.tools(),
        "arg_keys": {c.tool: sorted(c.args) for c in d.modules},
        "hint_tools": m.get("hint_tools", []),
        "agent": d.agent,
        "needs_web": d.needs_web,
        "seconds": m.get("seconds"),
        "fallback": m.get("fallback"),
        "dropped": [[t, w] for t, w in m.get("dropped", [])],
        "vetoed": m.get("vetoed", []),
        "substituted": m.get("substituted", []),
        "agree": sorted(d.tools()) == sorted(m.get("hint_tools", [])),
    }


# ---------------------------------------------------------------- the hook Agent.run uses


_CLOCK_ASK = {
    "time": "quelle heure est-il à {}",
    "offset": "décalage horaire avec {}",
    "slot": "créneau commun entre {}",
}


def clock_text(call: Call) -> str:
    """Words ``clock.detect`` reads back into the same cities and mode."""
    cities, mode = call.args["cities"], call.args.get("mode") or ("slot" if len(call.args["cities"]) > 2 else "time")
    if mode == "slot" and len(cities) < 2:
        mode = "offset"
    joined = ", ".join(cities[:-1]) + " et " + cities[-1] if len(cities) > 1 else cities[0]
    return _CLOCK_ASK[mode].format(joined)


@dataclass
class Plan:
    """What the router decided for this turn, in the terms ``Agent.run`` uses. ``active`` False (router off, or it
    failed and the parsers took over): every method returns what the parsers would, so the turn is unchanged."""

    decision: Decision | None = None

    @property
    def active(self) -> bool:
        return self.decision is not None and self.decision.source in ("model", "hybrid")

    def found(self, found: list) -> list:
        """Replaces ``intents.detect`` (+ follow-up): the router's prefilled widget call, if any."""
        if not self.active:
            return found
        from birds.harness import intents

        d = self.decision
        return [intents.Intent(c.tool, dict(c.args), keep_web=d.needs_web) for c in d.modules
                if catalog.BY_NAME[c.tool].kind == catalog.PREFILL][:1]  # fmt: skip

    def clock_words(self, words: str) -> str:
        if not self.active:
            return words
        c = self.decision.get("clock")
        return clock_text(c) if c else ""

    def allows(self, tool: str) -> bool:
        """event / images / make_chart: may the harness start it this turn?"""
        return not self.active or self.decision.get(tool) is not None

    def images(self, req: str, lang: str):
        from birds.harness import intents

        if not self.active:
            return intents.images(req, lang)
        c = self.decision.get("images")
        return intents.Intent("web_search", {"query": c.args["subject"]}, keep_web=True, mode="images") if c else None

    def routed(self, routed: set[str]) -> set[str]:
        """Tools withheld this turn: the chart offer follows the router; an office file with no need for the web
        loses the web tools (as ``agent.route``), and a need for the web keeps them."""
        if not self.active:
            return routed
        d, out = self.decision, set(routed)
        if d.get("make_chart"):
            out.discard("make_chart")
        else:
            out.add("make_chart")
        if d.needs_web:
            out -= {"web_search", "read_page"}
        elif d.get("office"):
            out |= {"web_search", "read_page"}
        return out

    def chart(self, chartable: bool) -> bool:
        return chartable if not self.active else self.decision.get("make_chart") is not None


def plan_turn(agent, req: str, history, *, attached: bool, lang: str, deadline: float) -> Plan:
    """Called by ``Agent.run`` before the first generation. Never raises; logs metadata only."""
    cfg, llm = agent.cfg, agent.llm
    try:
        left = deadline - time.monotonic() - 5.0
        if left < 1.5:
            return Plan(None)  # no time for a router call: the parsers decide
        mode, kind = resolve_mode(cfg, llm, deadline=time.monotonic() + min(PROBE_S, max(0.0, left)))
        if mode == "regex":
            return Plan(None)
        budget = float(os.environ.get("BIRD_ROUTER_BUDGET_S") or getattr(cfg, "router_budget_s", None) or BUDGET_S)
        names = available_names(cfg, agent)
        d = decide(llm, agent.tok, req, history=history, attached=attached, lang=lang, mode=mode, structured=kind,
                   budget=max(1.5, min(budget, left)), names=names, cache_salt=cfg.cache_salt)  # fmt: skip
    except Exception as e:  # routing must never break a turn
        log.warning(json.dumps({"event": "router_error", "error": type(e).__name__}))
        return Plan(None)
    meta = log_meta(d)
    log.info(json.dumps({"event": "router", **meta}, ensure_ascii=False))
    try:
        agent.audit.log("router", **meta)
    except Exception:
        pass
    return Plan(d)


def available_names(cfg, agent=None) -> set[str]:
    """The catalogue for this deployment: modules whose tool is allowed (and data analysis when run_python is)."""
    names = {m.name for m in catalog.MODULES if m.available}
    allowed = agent._allowed() if agent is not None else set(getattr(cfg, "allowed_tools", ()))
    for tool in ("get_weather", "find_places", "find_company", "convert_currency", "make_chart"):
        if tool not in allowed:
            names.discard(tool)
    if "web_search" not in allowed:
        names.discard("images")
    if getattr(cfg, "allow_python", False):
        names.add("data_analysis")
    return names
