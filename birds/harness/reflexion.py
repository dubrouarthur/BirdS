"""Mode Réflexion: how long Bird thinks before answering, as five birds, and what it checks before it answers.

    Colibri · Instantané   no reasoning, immediate answer (greetings, simple questions, rewording)
    Hirondelle · Rapide    short reasoning (emails, summaries, most tasks)
    Faucon · Précis        standard reasoning, then a self-check (calculations, comparisons, code)
    Chouette · Approfondi  long reasoning, self-check, then the model re-reads its draft (analyses, hard problems)
    Albatros · Endurance   long tasks: the Mode Agent team when the request is one, else Chouette with more time

« Auto » lets Bird choose: ONE short call (≤ 16 output tokens, temperature 0, schema-enforced when the endpoint
supports it, the same detection as the router) whose answer is ``{"level": "faucon"}``. It runs at the same time as
the router call, so it costs no extra wall time on a remote endpoint. The hand-written ``hint_level`` is only the
fallback (in-process client, endpoint too slow, unreadable answer), never the primary decider.

What each level really changes, measured on Bird S 4B (vLLM, 28/11/2026, docs/HARNESS.md § 14):

- the reasoning budget: ``think_chars`` characters of reasoning (≈ 2.4 characters per token on this model), the
  generation's ``max_tokens`` raised by as much; past the budget the reasoning is CLOSED, not thrown away: the
  harness keeps what was reasoned, writes « budget reached, answering now » in the reasoning and the model answers
  from there (budget forcing). A reasoning that loops is cut at the loop and closed the same way;
- the self-check (``checks`` rounds): every « a × b = c » written in the answer is recomputed by the harness, and a
  request with several questions or a list of points is checked point by point; anything wrong or missing goes
  back to the model in ONE reminder that names it (« 14,90 × 24 = 357,60, not 375,60 »), and the model rewrites;
- the review (Chouette, Albatros): one more generation in which the model re-reads its draft against the request
  and answers « OK » or the corrected text.

``summary`` turns the reasoning into three or four readable lines for the interface (extractive: the model's own
sentences, never invented). Nothing here sends anything to the browser: the server builds the ``reflexion`` field
of the answer event from ``Run.reflexion``.
"""

from __future__ import annotations

import ast
import json
import logging
import math
import operator
import re
import time
import unicodedata
from dataclasses import dataclass, field

log = logging.getLogger("bird.reflexion")

CHARS_PER_TOKEN = 2.4  # measured on Bird S 4B (349 characters for 144 tokens, French arithmetic, 28/11/2026)


@dataclass(frozen=True)
class Level:
    key: str
    bird: dict
    label: dict
    thinking: bool
    think_chars: int  # reasoning budget, in characters
    checks: int  # self-check rounds before the answer is accepted
    review: bool = False  # the model re-reads its draft once
    endurance: bool = False  # Albatros: the Mode Agent team, longer run

    @property
    def think_tokens(self) -> int:
        """Extra output tokens for the reasoning: the answer keeps the configured ``max_tokens`` on top."""
        return int(math.ceil(self.think_chars / CHARS_PER_TOKEN)) + 64 if self.thinking else 0

    def name(self, lang: str) -> str:
        lg = "en" if lang == "en" else "fr"
        return f"{self.bird[lg]} · {self.label[lg]}"


LEVELS: dict[str, Level] = {
    "colibri": Level("colibri", {"fr": "Colibri", "en": "Hummingbird"}, {"fr": "Instantané", "en": "Instant"},
                     thinking=False, think_chars=0, checks=0),
    "hirondelle": Level("hirondelle", {"fr": "Hirondelle", "en": "Swallow"}, {"fr": "Rapide", "en": "Quick"},
                        thinking=True, think_chars=1500, checks=0),
    "faucon": Level("faucon", {"fr": "Faucon", "en": "Falcon"}, {"fr": "Précis", "en": "Precise"},
                    thinking=True, think_chars=4000, checks=1),
    "chouette": Level("chouette", {"fr": "Chouette", "en": "Owl"}, {"fr": "Approfondi", "en": "Deep"},
                      thinking=True, think_chars=9000, checks=2, review=True),
    "albatros": Level("albatros", {"fr": "Albatros", "en": "Albatross"}, {"fr": "Endurance", "en": "Endurance"},
                      thinking=True, think_chars=12000, checks=2, review=True, endurance=True),
}  # fmt: skip
KEYS = tuple(LEVELS)
CHOICES = ("auto", *KEYS)
AUTO_LEVELS = ("colibri", "hirondelle", "faucon", "chouette")  # Albatros is the team's (crew.decide), never guessed

MAX_TOKENS = 16
BUDGET_S = 2.5
MAX_MESSAGE_CHARS = 600
STOP = ["<|im_end|>", "<|endoftext|>", "\n\n"]
PREFIX = '{"level":"'


def normalize(value, default: str = "auto") -> str:
    """A level key or « auto » from what a client sent (``thinking: true`` from an older client → Hirondelle)."""
    if isinstance(value, bool):
        return "hirondelle" if value else "colibri"
    v = str(value or "").strip().lower()
    v = {"on": "hirondelle", "off": "colibri", "true": "hirondelle", "false": "colibri"}.get(v, v)
    return v if v in CHOICES else default


def level(key: str) -> Level:
    return LEVELS.get(key) or LEVELS["hirondelle"]


# ---------------------------------------------------------------- Auto: the model decides


def schema() -> dict:
    return {
        "type": "object",
        "properties": {"level": {"type": "string", "enum": list(AUTO_LEVELS)}},
        "required": ["level"],
        "additionalProperties": False,
    }


_GUIDE = {
    "fr": (
        'Tu choisis combien Bird réfléchit avant de répondre à ce message. Réponds en JSON : {"level": …}.\n'
        "colibri : réponse immédiate, sans réflexion (salutation, merci, question simple, reformulation, traduction "
        "courte, fait connu).\n"
        "hirondelle : réflexion courte (mail, résumé, explication, conseil, idées, la plupart des tâches).\n"
        "faucon : réflexion avec vérification (calcul, chiffres, pourcentages, comparaison chiffrée, code, logique, "
        "dates).\n"
        "chouette : longue réflexion et relecture (analyse en plusieurs étapes, stratégie, problème difficile, "
        "démonstration, décision à arguments multiples).\n"
        "Exemples :"
    ),
    "en": (
        'You choose how long Bird thinks before answering this message. Answer in JSON: {"level": …}.\n'
        "colibri: immediate answer, no reasoning (greeting, thanks, simple question, rewording, short translation, "
        "known fact).\n"
        "hirondelle: short reasoning (email, summary, explanation, advice, ideas, most tasks).\n"
        "faucon: reasoning with a check (calculation, figures, percentages, numeric comparison, code, logic, dates).\n"
        "chouette: long reasoning and review (multi-step analysis, strategy, hard problem, proof, decision with many "
        "arguments).\n"
        "Examples:"
    ),
}
_SHOTS = {
    "fr": (
        ("bonjour !", "colibri"),
        ("traduis « bonne journée » en anglais", "colibri"),
        ("rédige un mail pour décaler la réunion de jeudi à vendredi", "hirondelle"),
        ("résume ce compte rendu en cinq points", "hirondelle"),
        ("3 devis : 1 250 €, 980 € et 1 410 € HT, lequel est le moins cher TTC à 20 % ?", "faucon"),
        ("écris une fonction Python qui calcule la moyenne pondérée", "faucon"),
        ("analyse les risques et les bénéfices de passer l'équipe à la semaine de quatre jours", "chouette"),
    ),
    "en": (
        ("hi there", "colibri"),
        ("what is the capital of Canada?", "colibri"),
        ("draft an email to move Thursday's meeting to Friday", "hirondelle"),
        ("summarize these notes in five bullet points", "hirondelle"),
        ("a plan costs $14.90 a month or $149 a year: which is cheaper over two years, and by how much?", "faucon"),
        ("write a SQL query for the top 5 customers by revenue", "faucon"),
        ("analyze the trade-offs of moving our whole team to a four-day week", "chouette"),
    ),
}


def messages(text: str, lang: str = "fr") -> list[dict]:
    """[system, user]: the guide and fixed examples (static prefix, reused by the endpoint's cache), then the turn.
    The examples sit in the system message so a training record built from these messages has one assistant turn
    to learn (scripts/build_tools_mix.py, task « reflexion »)."""
    lg = "en" if lang == "en" else "fr"
    sep = ": " if lg == "en" else " : "
    shots = "\n".join(f"Message{sep}{q} → " + json.dumps({"level": a}) for q, a in _SHOTS[lg])
    msg = " ".join((text or "").split())[:MAX_MESSAGE_CHARS]
    return [{"role": "system", "content": _GUIDE[lg] + "\n" + shots}, {"role": "user", "content": f"Message{sep}{msg}"}]


def decision_json(key: str) -> str:
    return json.dumps({"level": key}, separators=(",", ":"))


# The FALLBACK only (no model to ask, or it failed): a few cues, never the primary decider when the model answered.
_CALC = re.compile(
    r"\d\s*(?:[+×*/÷=]|\bx\s*\d|%)|\d[\d  .,]*\s*(?:€|\$|£|euros?|dollars?|k€|HT|TTC)\b|"
    r"\b(?:combien|calcul\w*|total\w*|moyenne|pourcentage|compar\w*|lequel|laquelle|rentab\w*|moins cher|plus cher|"
    r"how much|how many|calculat\w*|average|percent\w*|cheaper|which (?:is|one))\b",
    re.I,
)
_CODE = re.compile(r"```|\b(?:code|fonction|function|python|javascript|typescript|sql|regex|bug|script)\b", re.I)
_DEEP = re.compile(
    r"\b(?:analys\w*|analy[sz]e|strat[ée]gi\w*|strategy|d[ée]montr\w*|prove|risques?|risks?|trade-?offs?|"
    r"avantages et (?:les )?inconv[ée]nients|pros and cons|plan d'action|diagnostic|impacts?|sc[ée]narios?)\b",
    re.I,
)
_SMALL = re.compile(
    r"^\s*(?:bonjour|salut|coucou|merci|hello|hi|hey|thanks?|thank you|ok|d'accord|super|parfait|bonne (?:journée|soirée)|"
    r"qui es-tu|who are you)\b",
    re.I,
)


def hint_level(text: str) -> str:
    t = " ".join((text or "").split())
    words = len(t.split())
    if _SMALL.match(t) and words <= 8:
        return "colibri"
    deep = bool(_DEEP.search(t)) and words >= 8
    if _CALC.search(t) or _CODE.search(t):
        return "chouette" if deep and words >= 30 else "faucon"
    if deep:
        return "chouette"
    return "colibri" if words <= 4 and "?" not in t else "hirondelle"


@dataclass
class Choice:
    level: str
    source: str  # user | model | hint (fallback) | crew (the team ran: Albatros) | resume
    seconds: float = 0.0
    usage: dict | None = None
    why: str = ""  # fallback reason

    def meta(self) -> dict:
        return {"level": self.level, "source": self.source, "seconds": round(self.seconds, 3), "why": self.why}


def parse(raw: str, prefix: str = "") -> str:
    """The level the model wrote, or '' (any of the five names, a JSON object, or the prefix completed)."""
    s = (raw or "").strip()
    s = re.sub(r"^<think>.*?</think>\s*", "", s, flags=re.S)
    if prefix and not s.startswith("{"):
        s = prefix + s
    try:
        obj = json.loads(s[s.find("{") : s.rfind("}") + 1]) if "{" in s and "}" in s else None
    except ValueError:
        obj = None
    if isinstance(obj, dict) and str(obj.get("level", "")).strip().lower() in AUTO_LEVELS:
        return str(obj["level"]).strip().lower()
    m = re.search(r"\b(colibri|hirondelle|faucon|chouette)\b", s.lower())
    return m.group(1) if m else ""


def decide(llm, tok, text: str, *, lang: str = "fr", budget: float = BUDGET_S, cache_salt: str | None = None,
           structured: str | None = None) -> Choice:  # fmt: skip
    """One short call: the level for this message. Never raises; falls back on ``hint_level``."""
    from birds.harness import router
    from birds.harness.llm import EndpointError
    from birds.render import prompt as render_prompt

    t0 = time.monotonic()
    if not router.probeable(llm):
        return Choice(hint_level(text), "hint", 0.0, None, "no_endpoint")
    try:
        kind = router.structured_kind(llm, deadline=t0 + budget) if structured is None else structured
        p = render_prompt(tok, messages(text, lang), [], False) + ("" if kind else PREFIX)
        extra = {"temperature": 0, **router.structured_extra(kind, schema())}
        if cache_salt:
            extra["cache_salt"] = cache_salt
        out = llm.generate(p, MAX_TOKENS, STOP, deadline=t0 + budget, extra=extra)
    except EndpointError as e:
        return Choice(hint_level(text), "hint", time.monotonic() - t0, None, e.kind)
    except Exception as e:  # a client bug must never break the turn
        return Choice(hint_level(text), "hint", time.monotonic() - t0, None, type(e).__name__)
    seconds = time.monotonic() - t0
    usage = {k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds", "busy_seconds",
                                      "cached_tokens", "finish_reason") if k in out}  # fmt: skip
    got = parse(out.get("text") or "", "" if kind else PREFIX)
    if not got:
        return Choice(hint_level(text), "hint", seconds, usage, "invalid")
    if seconds > budget * 1.5:
        return Choice(hint_level(text), "hint", seconds, usage, "over_budget")
    return Choice(got, "model", seconds, usage)


# ---------------------------------------------------------------- reasoning: budget forcing, loops, summary

CLOSE = {
    "think_budget": {
        "fr": "(Budget de réflexion atteint : je m'arrête là et je réponds avec ce que j'ai établi.)",
        "en": "(Reasoning budget reached: I stop here and answer with what I have established.)",
    },
    "repetition": {
        "fr": "(Je tourne en rond : je m'arrête et je réponds avec ce que j'ai établi.)",
        "en": "(I am going round in circles: I stop and answer with what I have established.)",
    },
}


def kept_reasoning(text: str) -> str:
    """The reasoning worth keeping from a cut generation: without the opening tag and the unfinished sentence."""
    s = (text or "").replace("<think>", "").rstrip()
    end = max(s.rfind(". "), s.rfind(".\n"), s.rfind("\n"), s.rfind(" ; "), s.rfind("? "), s.rfind("! "))
    if end > len(s) * 0.5:
        s = s[: end + 1]
    return s.rstrip()


def close_text(text: str, reason: str, lang: str) -> str:
    """What follows the rendered prompt when the reasoning is closed: the kept reasoning, the note, the end tag."""
    note = CLOSE.get(reason, CLOSE["think_budget"])["en" if lang == "en" else "fr"]
    kept = kept_reasoning(text)
    return (kept + "\n" if kept else "") + note + "\n</think>\n\n"


_SENT = re.compile(r"(?<=[.!?:])\s+(?=[A-ZÀ-ÖØ-Ý0-9«(\"])|\n+")
_FILLER = re.compile(
    r"^(?:ok(?:ay)?|bon|alors|donc|hmm+|euh|voyons|let me|let's|alright|so|well|first|d'abord|je dois|i need to|"
    r"the user|l'utilisateur)\b",
    re.I,
)


def summary(reasoning: str, lang: str = "fr", n: int = 4) -> list[str]:
    """Up to ``n`` short lines of the model's own reasoning: the sentences that carry figures or conclusions first,
    in their original order. Extractive only: nothing is rewritten, so nothing is invented."""
    from birds.harness import guard

    text = guard.redact(re.sub(r"</?think>", "", reasoning or ""))
    parts = [" ".join(p.split()).strip(" -•*") for p in _SENT.split(text)]
    parts = [p for p in parts if 12 <= len(p) and not p.startswith(tuple(CLOSE_NOTES))]
    parts = [p for p in parts if not (_FILLER.match(p) and not re.search(r"\d", p))]  # « Bon, voyons. »
    if not parts:
        return []

    def score(i: int, p: str) -> float:
        s = 0.0
        s += 2.0 if re.search(r"\d", p) else 0.0
        s += 1.5 if re.search(r"=|→|donc|so |therefore|conclu|au total|in total|soit |reste|le moins|the cheapest", p,
                              re.I) else 0.0  # fmt: skip
        s -= 1.5 if _FILLER.match(p) else 0.0
        s += 0.8 if i == 0 else 0.0
        s += 0.6 if i == len(parts) - 1 else 0.0
        return s

    ranked = sorted(range(len(parts)), key=lambda i: (-score(i, parts[i]), i))[:n]
    out = []
    for i in sorted(ranked):
        p = parts[i]
        out.append(p if len(p) <= 180 else p[:177].rsplit(" ", 1)[0] + "…")
    return out


CLOSE_NOTES = tuple(v for d in CLOSE.values() for v in d.values())

# ---------------------------------------------------------------- self-check: calculations and asked points

_NUM = r"(?:\d{1,3}(?:[   ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
_UNIT = r"(?:\s?(?:%|€|\$|£|k€|M€|EUR|USD|euros?|h|min|km|kg|m²|m2|ans?|mois|jours?|days?|months?|years?))?"
_OP = r"\s*(?:[+×*/÷]|(?<=\s)[x−–-](?=\s))\s*"
_EQ = re.compile(
    rf"(?<![\w.,])(?P<expr>\(?{_NUM}{_UNIT}(?:{_OP}\(?{_NUM}{_UNIT}\)?){{1,6}})\s*=\s*(?P<res>-?{_NUM})(?P<runit>{_UNIT})(?![\d])"
)
_PCT_OF = re.compile(rf"(?<![\w.,])(?P<p>{_NUM})\s?%\s+(?:de|du|des|of)\s+(?P<b>{_NUM}){_UNIT}\s*=\s*(?P<res>{_NUM})")
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _num(s: str) -> float | None:
    from birds.harness import intents

    s = s.strip().replace(" ", " ").replace(" ", " ")
    if re.fullmatch(r"\d+\.\d{1,2}", s):  # « 14.90 »: a decimal point, never thousands, in a calculation
        return float(s)
    return intents.parse_amount(s)


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    raise ValueError("unsupported")


def _decimals(s: str) -> int:
    m = re.search(r"[.,](\d+)$", s.strip())
    return len(m.group(1)) if m and not re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s.strip()) else 0


def fmt(value: float, lang: str = "fr", decimals: int | None = None) -> str:
    d = decimals if decimals is not None else (0 if abs(value - round(value)) < 1e-9 else 2)
    s = f"{value:,.{d}f}"
    return s.replace(",", " ").replace(".", ",") if lang != "en" else s


_TOKEN = re.compile(rf"(?P<num>{_NUM})(?P<unit>{_UNIT})|(?P<op>[+×*/÷x\-])|(?P<par>[()])|\s+")


def _python(expr: str) -> str | None:
    """« 14,90 € × 24 » -> "14.9 * 24.0"; a percentage operand of × or ÷ is divided by 100; None when the expression
    holds something else (a percentage added to an amount is a raise, never judged)."""
    out, pos, toks = [], 0, []
    for m in _TOKEN.finditer(expr):
        if m.start() != pos:
            return None
        pos = m.end()
        if m.group("num"):
            toks.append(("num", m.group("num"), "%" in (m.group("unit") or "")))
        elif m.group("op"):
            toks.append(("op", {"×": "*", "x": "*", "÷": "/"}.get(m.group("op"), m.group("op")), False))
        elif m.group("par"):
            toks.append(("par", m.group("par"), False))
    if pos != len(expr):
        return None
    for i, (kind, val, pct) in enumerate(toks):
        if kind != "num":
            out.append(val)
            continue
        v = _num(val)
        if v is None:
            return None
        if pct:
            near = [toks[j][1] for j in (i - 1, i + 1) if 0 <= j < len(toks) and toks[j][0] == "op"]
            if any(o in "+-" for o in near):
                return None
            v /= 100
        out.append(repr(v))
    return " ".join(out)


def _left_to_right(py: str) -> str:
    """The same operations, read in writing order: « 3 + 4 * 2 » -> « ((3 + 4) * 2) »."""
    parts = py.split()
    acc = parts[0]
    for i in range(1, len(parts) - 1, 2):
        acc = f"({acc} {parts[i]} {parts[i + 1]})"
    return acc


def calc_errors(text: str, lang: str = "fr") -> tuple[int, list[dict]]:
    """(calculations checked, wrong ones [{expr, shown, right}]) in ``text``. Only « a op b … = c » with explicit
    numbers is read; « ≈ » and words are never judged. A result off by less than its own rounding is right."""
    checked, wrong = 0, []
    plain = text.replace("−", "-").replace("–", "-")
    plain = re.sub(r"\*\*|__|`", "", plain)  # « = **357,60 €** »: Markdown emphasis around a result
    for m in _EQ.finditer(plain):
        expr, res = m.group("expr"), m.group("res")
        if expr.count("(") != expr.count(")"):
            continue
        if re.match(rf"{_OP}\(?\d", plain[m.end() :]):
            continue  # « 1 200 + 15 × 60 = 1 200 + 900 = 2 100 »: an intermediate step, not a result
        py = _python(expr)
        shown = _num(res.lstrip("-"))
        if py is None or shown is None:
            continue
        try:
            right = _eval(ast.parse(py, mode="eval"))
            # « 3 + 4 × 2 = 14 » written left to right without brackets: not judged as an error either way
            flat = _eval(ast.parse(_left_to_right(py), mode="eval")) if "(" not in py else right
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError, RecursionError):
            continue
        shown = -shown if res.startswith("-") else shown
        if "%" in (m.group("runit") or "") and "%" not in expr:
            right, flat = right * 100, flat * 100  # « 69 ÷ 2 300 = 3 % »: a ratio written as a percentage
        checked += 1
        tol = max(0.5 * 10 ** (-_decimals(res)) + 1e-9, abs(right) * 0.001)
        if abs(right - shown) > tol and abs(flat - shown) > tol:
            exact = abs(right - round(right)) < 1e-9
            wrong.append({"expr": " ".join(expr.split()), "shown": res,
                          "right": fmt(right, lang, _decimals(res) if _decimals(res) or exact else 2)})  # fmt: skip
    for m in _PCT_OF.finditer(plain):
        p, b, shown = _num(m.group("p")), _num(m.group("b")), _num(m.group("res"))
        if None in (p, b, shown):
            continue
        right, checked = p * b / 100, checked + 1
        if abs(right - shown) > max(0.5 * 10 ** (-_decimals(m.group("res"))) + 1e-9, abs(right) * 0.001):
            wrong.append({"expr": f"{m.group('p')} % de {m.group('b')}" if lang != "en" else
                          f"{m.group('p')}% of {m.group('b')}", "shown": m.group("res"),
                          "right": fmt(right, lang, _decimals(m.group("res")) or None)})  # fmt: skip
    return checked, wrong


_STOP = frozenset(
    """le la les un une des du de d l et ou en au aux a à ce cet cette ces mon ma mes ton ta tes son sa ses notre nos
    votre vos leur leurs je tu il elle on nous vous ils elles me te se y est sont sera être avoir fait faire pour par
    sur dans avec sans plus moins tres très bien aussi quel quelle quels quelles quoi comment combien pourquoi quand
    est-ce qu que qui dont donne donner dis dire peux peut pouvez veux voudrais merci stp svp the a an of to in on for
    and or is are be with what which how why when who does do can could would should please me my your our their it
    this that these those tell give make also then""".split()
)
_ASK_LINE = re.compile(r"^\s*(?:\d{1,2}[.)]|[-•*]|[a-h]\))\s+(.+)$", re.M)


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").replace("’", "'").casefold())
    return "".join(c for c in t if not unicodedata.combining(c))


def asked_points(request: str) -> list[str]:
    """The points of a request that asks several things: numbered or bulleted lines, else two questions or more.
    [] for a request that asks one thing (nothing to check point by point)."""
    req = request or ""
    lines = [m.group(1).strip() for m in _ASK_LINE.finditer(req)]
    if len(lines) >= 2:
        return lines[:8]
    qs = [q.strip() for q in re.findall(r"[^?.!\n]{6,}\?", req)]
    return qs[:8] if len(qs) >= 2 else []


def _keys(point: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9'-]*", _fold(point))
    return {w for w in words if (len(w) >= 4 or w.isdigit()) and w not in _STOP}


def missing_points(request: str, answer: str) -> tuple[int, list[str]]:
    """(points asked, points the answer never touches). A point is touched when one of its own words (or a word of
    the same stem, or one of its numbers) is in the answer. Words every point shares say nothing and are ignored."""
    points = asked_points(request)
    if not points:
        return 0, []
    keys = [_keys(p) for p in points]
    common = set.intersection(*keys) if keys else set()
    body = _fold(answer)
    words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", body))
    stems = {w[:5] for w in words if len(w) >= 5}
    out = []
    for p, k in zip(points, keys, strict=True):
        own = k - common
        if not own:
            continue
        if not any(w in words or (len(w) >= 5 and w[:5] in stems) for w in own):
            out.append(p)
    return len(points), out


@dataclass
class Verdict:
    calcs: int = 0
    calc_wrong: list[dict] = field(default_factory=list)
    points: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.calc_wrong and not self.missing

    def as_dict(self) -> dict:
        return {"calcs": self.calcs, "calc_wrong": len(self.calc_wrong), "points": self.points,
                "missing": len(self.missing)}  # fmt: skip


def verify(request: str, answer: str, reasoning: str = "", lang: str = "fr") -> Verdict:
    """The harness's own checks of an answer. A wrong calculation in the reasoning counts only when its wrong result
    reached the answer (« 14,90 × 24 = 375,60 » thought, « 375,60 € » written)."""
    n, wrong = calc_errors(answer, lang)
    rn, rwrong = calc_errors(reasoning, lang) if reasoning else (0, [])
    seen = {w["expr"] for w in wrong}
    for w in rwrong:
        if w["expr"] not in seen and re.search(rf"(?<![\d,.]){re.escape(w['shown'])}(?![\d])", answer):
            wrong.append(w)
            seen.add(w["expr"])
    points, missing = missing_points(request, answer)
    return Verdict(n + (rn if rwrong else 0), wrong, points, missing)


def nudge(v: Verdict, lang: str = "fr") -> str:
    """ONE reminder naming everything to fix. English, like the harness's other reminders; the answer stays in the
    user's language."""
    parts = ["Self-check before you answer."]
    if v.calc_wrong:
        parts.append(
            "These calculations are wrong, recomputed by the harness: "
            + "; ".join(f"{w['expr']} = {w['right']} (not {w['shown']})" for w in v.calc_wrong[:4])
            + ". Correct them and every figure that depends on them."
        )
    if v.missing:
        parts.append("The request also asks, and your answer does not address: "
                     + "; ".join(f"« {p[:120]} »" for p in v.missing[:4]) + ".")  # fmt: skip
    parts.append(
        "Write your full answer again, corrected, in the user's language"
        + (" (French)" if lang != "en" else "")
        + ". Do not mention this check."
    )
    return " ".join(parts)


REVIEW = (
    "Re-read your answer once against the request: redo each calculation, check that every point asked is "
    "answered and that nothing is invented. If everything is right, reply with exactly: OK. Otherwise write the "
    "full corrected answer, in the user's language, without mentioning this review."
)


def review_kept(draft: str, reply: str) -> tuple[str, bool]:
    """(answer, changed) after the model's review: « OK » keeps the draft; a full rewrite replaces it; a short or
    empty reply keeps the draft (a review never shortens an answer to a stub)."""
    r = (reply or "").strip()
    if not r or re.fullmatch(r"(?i)\W*ok\W*(?:[.!]|\s.{0,40})?", r) or r.upper().startswith("OK\n") and len(r) < 60:
        return draft, False
    if len(r) < 0.4 * len(draft or ""):
        return draft, False
    return r, r.strip() != (draft or "").strip()


def label_line(key: str, lang: str = "fr") -> str:
    """« Bird a pris son vol en Faucon » / « Bird took flight as a Falcon »."""
    lv = level(key)
    return f"Bird took flight as a {lv.bird['en']}" if lang == "en" else f"Bird a pris son vol en {lv.bird['fr']}"


def public(info: dict | None, lang: str = "fr") -> dict | None:
    """The ``reflexion`` field of the answer event: plain data for the interface (no prompt text, no hidden
    reasoning beyond the extractive summary, which the user's own reasoning panel shows anyway)."""
    if not info or info.get("level") not in LEVELS:
        return None
    lv = LEVELS[info["level"]]
    checks = info.get("checks") or {}
    return {
        "level": lv.key,
        "bird": lv.bird["en" if lang == "en" else "fr"],
        "label": lv.label["en" if lang == "en" else "fr"],
        "auto": bool(info.get("auto")),
        "source": str(info.get("source") or ""),
        "line": label_line(lv.key, lang),
        "think_chars": int(info.get("think_chars") or 0),
        "budget_chars": lv.think_chars,
        "cut": info.get("cut"),  # None | "think_budget" | "repetition"
        "summary": [str(s) for s in (info.get("summary") or [])][:4],
        "checks": {
            "calcs": int(checks.get("calcs") or 0),
            "calc_wrong": int(checks.get("calc_wrong") or 0),
            "points": int(checks.get("points") or 0),
            "missing": int(checks.get("missing") or 0),
        },
        "corrected": bool(info.get("corrected")),
        "reviewed": bool(info.get("reviewed")),
        "review_changed": bool(info.get("review_changed")),
        "seconds": round(float(info.get("seconds") or 0.0), 2),
    }
