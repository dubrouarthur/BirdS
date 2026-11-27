"""One source of truth for Bird's modules: what the model router may decide, and how each decision is checked.

A *module* is something the harness can do for a request besides plain writing: a widget tool it calls itself
(weather, places, company register, currencies), a card it computes (world clock, calendar event, pictures, a
chart), or a hint about the trained tools (office files, research, data analysis). Each entry has a name, one
line in French and English, a tiny argument schema (flat: strings, a number, a short list of strings, an enum)
and a few examples. From it come:

- ``text(lang)``: the catalogue the router prompt shows the model (static, so it stays in the prefix cache; kept
  under 600 tokens, ``tests/test_router.py`` checks it);
- ``decision_schema()``: the JSON schema of a router decision, sent to vLLM as a structured-output constraint;
- ``check_args()``: validation of what the model wrote (types, enums, sizes); an invalid module is dropped.

Pure data and pure functions: no I/O, no model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# kind of execution, for the harness hook (router.Plan) and for the docs
PREFILL = "prefill"  # a tool the harness calls itself before the first generation (same path as a model call)
CARD = "card"  # a card the harness computes from the user's words, no tool (clock, event, pictures, chart)
HINT = "hint"  # no call: only steers which trained tools are offered (office files, research, data, calculator)

AGENT_MODES = ("off", "auto", "on")
MAX_MODULES = 2  # like intents.detect: at most one prefilled call plus one offered tool
MAX_STR = 80  # every string argument (a place, a company, a subject): longer is not a name, it is a paste


@dataclass(frozen=True)
class Arg:
    type: str  # "str" | "num" | "list" (list of short strings) | "enum"
    required: bool = False
    choices: tuple[str, ...] = ()  # enum values
    fr: str = ""
    en: str = ""
    max_items: int = 4  # list only


@dataclass(frozen=True)
class Module:
    name: str
    kind: str  # PREFILL | CARD | HINT
    family: str  # bench family it belongs to (router_eval, veto)
    fr: str
    en: str
    args: dict[str, Arg] = field(default_factory=dict)
    examples: tuple[tuple[str, dict], ...] = ()  # (user words, args); the first one is shown in the catalogue
    available: bool = True  # False: the module is described here but not offered (no executor in this build)


_DAY = Arg("str", fr="jour (demain, jeudi, 2026-12-03)", en="day (tomorrow, Thursday, 2026-12-03)")

MODULES: tuple[Module, ...] = (
    Module(
        "get_weather", PREFILL, "weather",
        "météo d'une ville (prévision, pluie, température)",
        "weather forecast for a town (rain, temperature)",
        {"place": Arg("str", True, fr="ville ou lieu", en="town or place"), "day": _DAY},
        (("météo à Lyon demain", {"place": "Lyon", "day": "demain"}),
         ("will it rain in Berlin on Friday?", {"place": "Berlin", "day": "Friday"}),
         ("il fait beau à Nice ?", {"place": "Nice"})),
    ),
    Module(
        "find_places", PREFILL, "maps",
        "carte : un lieu, une adresse, des lieux d'un type près d'un endroit",
        "map: a place, an address, or places of a kind near somewhere",
        {"query": Arg("str", True, fr="lieu ou type (restaurant, pharmacie)", en="place or kind (restaurant)"),
         "near": Arg("str", fr="autour de", en="around")},
        (("restaurants près de la gare de Lyon", {"query": "restaurant", "near": "gare de Lyon"}),
         ("où est la tour Eiffel ?", {"query": "tour Eiffel"}),
         ("coffee shops near Times Square", {"query": "cafe", "near": "Times Square"})),
    ),
    Module(
        "find_company", PREFILL, "company_fx",
        "fiche d'entreprise française (SIREN, dirigeants, adresse)",
        "French company record (register: SIREN, officers, address)",
        {"name": Arg("str", True, fr="nom, SIREN ou SIRET", en="name, SIREN or SIRET")},
        (("qui dirige Michelin ?", {"name": "Michelin"}), ("siren 552 100 554", {"name": "552100554"})),
    ),
    Module(
        "convert_currency", PREFILL, "company_fx",
        "conversion de devises au taux BCE du jour",
        "currency conversion at the ECB rate of the day",
        {"amount": Arg("num", fr="montant", en="amount"),
         "from": Arg("str", True, fr="code ISO (USD)", en="ISO code (USD)"),
         "to": Arg("str", True, fr="code ISO (EUR)", en="ISO code (EUR)")},
        (("1 200 dollars en euros", {"amount": 1200, "from": "USD", "to": "EUR"}),
         ("le taux euro/livre", {"from": "EUR", "to": "GBP"})),
    ),
    Module(
        "clock", CARD, "clock",
        "heure dans d'autres villes, décalage horaire, créneau commun",
        "time in other cities, time difference, common meeting slot",
        {"cities": Arg("list", True, fr="villes", en="cities"),
         "mode": Arg("enum", choices=("time", "offset", "slot"), fr="heure, décalage ou créneau",
                     en="time, offset or slot")},
        (("décalage horaire avec Tokyo", {"cities": ["Tokyo"], "mode": "offset"}),
         ("what time is it in Sydney?", {"cities": ["Sydney"], "mode": "time"}),
         ("créneau commun Paris Montréal Singapour", {"cities": ["Paris", "Montréal", "Singapour"], "mode": "slot"})),
    ),
    Module(
        "event", CARD, "events",
        "ajouter un rendez-vous daté à l'agenda (fiche .ics)",
        "add a dated meeting to the calendar (.ics card)",
        {},
        (("cale une réunion avec Paul jeudi à 14h", {}), ("schedule a meeting with John next Tuesday at 3pm", {})),
    ),
    Module(
        "make_chart", CARD, "charts",
        "graphique (barres, courbe, camembert) de chiffres ou d'une évolution",
        "chart (bar, line, pie) of figures or of a trend",
        {"type": Arg("enum", choices=("bar", "line", "pie"), fr="type", en="type")},
        (("graphique des ventes : janvier 120, février 135", {"type": "line"}),
         ("un camembert de la répartition des dépenses", {"type": "pie"}),
         ("la population de Paris depuis 2012", {"type": "line"})),
    ),
    Module(
        "images", CARD, "images",
        "photos d'un lieu, d'un monument, d'un animal, d'une œuvre (recherche web)",
        "pictures of a place, landmark, animal or artwork (web search)",
        {"subject": Arg("str", True, fr="sujet", en="subject")},
        (("montre-moi une photo de la tour Eiffel", {"subject": "tour Eiffel"}),
         ("show me a picture of a koala", {"subject": "koala"})),
    ),
    Module(
        "office", HINT, "office",
        "un fichier ou un brouillon : présentation, document, tableur, mail",
        "a file or a draft: slides, document, spreadsheet, email",
        {"kind": Arg("enum", choices=("slides", "document", "sheet", "email"), fr="type", en="kind")},
        (("fais une présentation de 4 slides sur le télétravail", {"kind": "slides"}),
         ("rédige un mail de relance pour la facture 2024-118", {"kind": "email"})),
    ),
    Module(
        "data_analysis", HINT, "data",
        "analyse d'un fichier de données joint (calculs, tableaux croisés)",
        "analysis of an attached data file (computations, pivots)",
        {},
        (("calcule la moyenne par région dans ce fichier", {}),),
        available=False,  # run_python is off by default; enabled by router.available_modules(cfg)
    ),
    Module(
        "calculator", HINT, "calc",
        "calcul exact (pourcentages, TVA, sommes)",
        "exact calculation (percentages, VAT, sums)",
        {"expression": Arg("str", True, fr="expression", en="expression")},
        (("combien font 17 % de 3 450 € ?", {"expression": "3450*0.17"}),),
        available=False,  # no calculator tool in this build: described for the training data only
    ),
)  # fmt: skip

BY_NAME = {m.name: m for m in MODULES}
FAMILIES = sorted({m.family for m in MODULES})

_HEAD = {
    "fr": (
        "Tu es le routeur de Bird : choisis les modules utiles au message, ou aucun. Réponds par UNE ligne "
        'JSON : {"modules":[{"tool":"…","args":{…}}],"agent":"off|auto|on","needs_web":true|false}. '
        "Un module seulement si l'utilisateur le demande vraiment (« météo des marchés », « charte "
        "graphique », « où en est le projet », « image de marque » : aucun) ; arguments copiés de ses mots ; "
        'au plus 2 modules ; sinon {"modules":[]}. agent "on" pour une étude, un dossier ou un livrable sourcé '
        'en plusieurs étapes, "off" pour une question simple, sinon "auto". needs_web : il faut chercher des faits '
        "récents ou extérieurs. Les indices (règles fixes) peuvent se tromper.\nModules :"
    ),
    "en": (
        "You are Bird's router: pick the modules useful to the message, or none. Answer with ONE JSON line: "
        '{"modules":[{"tool":"…","args":{…}}],"agent":"off|auto|on","needs_web":true|false}. '
        'Rules: a module only if the user really asks for it ("sales forecast", "brand image", "where are we '
        'on the project": none); arguments copied from their words; at most 2 modules; otherwise '
        '{"modules":[]}. agent "on" for a study, a report or a sourced multi-step deliverable, "off" for a simple '
        'question, else "auto". needs_web: recent or outside facts must be searched. Hints (fixed rules) can be '
        "wrong.\nModules:"
    ),
}


def _sig(m: Module) -> str:
    parts = []
    for k, a in m.args.items():
        t = "|".join(a.choices) if a.type == "enum" else {"str": "", "num": "nombre", "list": "[…]"}[a.type]
        parts.append(k + ("*" if a.required else "") + (f"={t}" if t else ""))
    return f"{m.name}({', '.join(parts)})"


def _json(args: dict) -> str:
    import json

    return json.dumps(args, ensure_ascii=False, separators=(",", ":"))


def text(lang: str = "fr", names: set[str] | None = None) -> str:
    """The catalogue shown to the router: one line per available module, with one example. Static per language
    and per set of modules, so the router prompt shares its prefix across turns (vLLM prefix cache)."""
    lg = "en" if lang == "en" else "fr"
    lines = [_HEAD[lg]]
    for m in available(names):
        ex, args = m.examples[0]
        lines.append(f"- {_sig(m)} : {m.fr if lg == 'fr' else m.en}. « {ex} » → {_json(args)}")
    return "\n".join(lines)


def available(names: set[str] | None = None) -> list[Module]:
    """Modules offered to the router: ``names`` when given, else every module marked available."""
    return [m for m in MODULES if (m.name in names if names is not None else m.available)]


# ---------------------------------------------------------------- JSON schema of a decision (structured outputs)


def _arg_schema(a: Arg) -> dict:
    if a.type == "num":
        return {"type": "number"}
    if a.type == "enum":
        return {"type": "string", "enum": list(a.choices)}
    if a.type == "list":
        return {"type": "array", "items": {"type": "string", "maxLength": MAX_STR}, "minItems": 1,
                "maxItems": a.max_items}  # fmt: skip
    return {"type": "string", "minLength": 1, "maxLength": MAX_STR}


def module_schema(m: Module) -> dict:
    return {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": [m.name]},
            "args": {
                "type": "object",
                "properties": {k: _arg_schema(a) for k, a in m.args.items()},
                "required": [k for k, a in m.args.items() if a.required],
                "additionalProperties": False,
            },
        },
        "required": ["tool", "args"],
        "additionalProperties": False,
    }


def decision_schema(names: set[str] | None = None) -> dict:
    """What the router must answer. Key order (modules, agent, needs_web) is the order the model writes them."""
    mods = available(names)
    items = {"anyOf": [module_schema(m) for m in mods]} if mods else {"type": "object"}
    return {
        "type": "object",
        "properties": {
            "modules": {"type": "array", "items": items, "maxItems": MAX_MODULES},
            "agent": {"type": "string", "enum": list(AGENT_MODES)},
            "needs_web": {"type": "boolean"},
        },
        "required": ["modules", "agent", "needs_web"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------- validation of what the model wrote

_CODE = re.compile(r"^[A-Za-z]{3}$")
_BAD_CHARS = re.compile(r"[\[\]{}<>|\\\n\r\t\"]")


def _clean_str(v) -> str | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if not isinstance(v, str):
        return None
    if _BAD_CHARS.search(v):  # a line break or markup: a paste or an injection, never a name
        return None
    v = " ".join(v.split()).strip(" ?!.,;:'")
    if not v or len(v) > MAX_STR:
        return None
    return v


def check_args(name: str, args) -> tuple[dict | None, str]:
    """(clean args, '') or (None, why). Unknown keys are dropped; a wrong type, a missing required argument or an
    over-long string makes the whole module invalid (never guessed)."""
    m = BY_NAME.get(name)
    if m is None:
        return None, "unknown module"
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, "args is not an object"
    out: dict = {}
    for k, a in m.args.items():
        if k not in args or args[k] in (None, "", []):
            if a.required:
                return None, f"missing {k}"
            continue
        v = args[k]
        if a.type == "num":
            if isinstance(v, str):
                try:
                    v = float(v.replace(" ", "").replace(" ", "").replace(",", "."))
                except ValueError:
                    return None, f"{k} is not a number"
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 < v < 1e13):
                return None, f"{k} is not a positive number"
            out[k] = int(v) if float(v).is_integer() else float(v)
        elif a.type == "enum":
            v = str(v).strip().lower()
            if v not in a.choices:
                return None, f"{k} not in {a.choices}"
            out[k] = v
        elif a.type == "list":
            items = v if isinstance(v, list) else [v]
            clean = [c for c in (_clean_str(x) for x in items) if c]
            if not clean or len(clean) != len(items) or len(clean) > a.max_items:
                return None, f"{k} is not a short list of names"
            out[k] = clean
        else:
            c = _clean_str(v)
            if c is None:
                return None, f"{k} is not a short string"
            out[k] = c
    if name == "convert_currency":
        for k in ("from", "to"):
            if not _CODE.match(out[k]):
                from birds.harness import intents

                code = intents.currency_code(out[k])
                if not code:
                    return None, f"{k} is not a currency"
                out[k] = code
            out[k] = out[k].upper()
        if out["from"] == out["to"]:
            return None, "same currency"
    return out, ""
