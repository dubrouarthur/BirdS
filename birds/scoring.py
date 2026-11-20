"""Deterministic scorers for the Bird benchmark (no LLM judge).

    score(item, output) -> {"score": float in [0, 1], "detail": {...}}

`item` is one line of bench.jsonl, `output` is what `birds.parse.parse_output` returns:
{"reasoning": str, "content": str, "tool_calls": [{"name": str, "arguments": dict}]}.
The scorer is chosen by `item["scorer"]` and reads its ground truth from `item["expected"]`:

    tool_call     {"calls": [{"name", "arguments": {param: [allowed values, "" = optional]}}]}
    no_call       {}
    when2call     {"behavior": "call" | "ask" | "decline", "tool": name (for "call")}
    grounded      {"answerable": bool, "answer": key span | None, "reference_answer": str, "fallback": str}
    contains_any  {"any": [gold spans]}
    json_schema   {"schema": {...}}
    numbers       {"facts": {name: number}}
    identity      {}
    first_tool    {"tool": name | "none", "args_contains": [substrings] (optional)}
    language      {"lang": "fr" | "en"}
    concise       {"any": [gold spans], "max_words": 60}
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict

import jsonschema

from birds.checks import numbers_check

# ---------------------------------------------------------------- text helpers


def norm(text: str) -> str:
    """Lower-case, accent-free, punctuation-free, single-spaced text."""
    text = unicodedata.normalize("NFKD", (text or "").replace("’", "'").casefold())
    out = []
    for c in text:
        if unicodedata.combining(c):
            continue
        out.append(" " if unicodedata.category(c)[0] in "PZC" or c in "`|~^" else c)
    return " ".join("".join(out).split())


def contains(text: str, gold: str) -> bool:
    """`gold` appears in `text` as a whole-word span (after normalisation). Digit groups may be glued: 100 000 = 100000."""
    t, g = norm(text), norm(gold)
    if not g:
        return False
    if f" {g} " in f" {t} ":
        return True
    gc = g.replace(" ", "")
    if len(gc) >= 4 and any(ch.isdigit() for ch in gc):
        return re.search(r"(?<!\d)" + re.escape(gc) + r"(?!\d)", re.sub(r"(?<=\d) (?=\d)", "", t)) is not None
    return False


def token_f1(pred: str, ref: str) -> float:
    p, r = norm(pred).split(), norm(ref).split()
    if not p or not r:
        return 0.0
    left = defaultdict(int)
    for w in r:
        left[w] += 1
    common = 0
    for w in p:
        if left[w] > 0:
            left[w] -= 1
            common += 1
    if not common:
        return 0.0
    prec, rec = common / len(p), common / len(r)
    return 2 * prec * rec / (prec + rec)


def _res(ok: bool | float, **detail) -> dict:
    return {"score": float(ok), "detail": detail}


# ---------------------------------------------------------------- tool calls (BFCL-style)


def _std(s: str) -> str:
    # same idea as BFCL's own checker: ignore case, spaces and light punctuation in string values
    return re.sub(r"[ \t\n,./\-_*^]", "", s).lower().replace("'", '"')


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def _boolish(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return None


def same_value(got, want) -> bool:
    """Is the predicted value `got` equal to the reference `want`? Numbers numerically, strings loosely."""
    if isinstance(want, bool) or isinstance(got, bool):
        a, b = _boolish(got), _boolish(want)
        return a is not None and a == b
    if isinstance(want, int | float) or isinstance(got, int | float):
        a, b = _num(got), _num(want)
        return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    if want is None:
        return got is None or (isinstance(got, str) and got.strip().lower() in ("", "null", "none"))
    if got is None:
        return False
    if isinstance(want, str):
        return isinstance(got, str) and _std(got) == _std(want)
    if isinstance(want, list | tuple):
        return isinstance(got, list | tuple) and len(got) == len(want) and all(
            same_value(g, w) for g, w in zip(got, want, strict=True))
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return False
        if want and all(isinstance(v, list) for v in want.values()) and not args_problem(got, want):
            return True  # BFCL nested form: {key: [allowed values]}
        return set(got) == set(want) and all(same_value(got[k], want[k]) for k in want)
    return got == want


def args_problem(args: dict, allowed: dict) -> str | None:
    """None when `args` fits `allowed` ({param: [acceptable values]}, "" in the list = may be omitted)."""
    if not isinstance(args, dict):
        return "arguments are not an object"
    for k, v in args.items():
        if k not in allowed:
            return f"unexpected parameter {k}"
        opts = allowed[k] if isinstance(allowed[k], list) else [allowed[k]]
        if not any(same_value(v, o) for o in opts if o != "") and not ("" in opts and v in ("", None)):
            return f"wrong value for {k}"
    for k, opts in allowed.items():
        if k not in args and not (isinstance(opts, list) and "" in opts):
            return f"missing parameter {k}"
    return None


def _match_calls(pred: list[dict], exp: list[dict]) -> bool:
    """Perfect matching between predicted and expected calls, in any order."""
    if not exp:
        return not pred
    first, rest = exp[0], exp[1:]
    for i, p in enumerate(pred):
        if p.get("name") == first["name"] and not args_problem(p.get("arguments"), first["arguments"]):
            if _match_calls(pred[:i] + pred[i + 1:], rest):
                return True
    return False


def score_tool_call(item: dict, out: dict) -> dict:
    exp, pred = item["expected"]["calls"], out.get("tool_calls") or []
    names_ok = sorted(c.get("name") or "" for c in pred) == sorted(c["name"] for c in exp)
    if not names_ok:
        return _res(False, reason="function names differ", predicted=[c.get("name") for c in pred])
    if len(pred) > 8 or not _match_calls(pred, exp):
        why = None
        if len(pred) == 1:
            why = args_problem(pred[0].get("arguments"), exp[0]["arguments"])
        return _res(False, reason=why or "arguments differ", names_ok=True)
    return _res(True, names_ok=True)


def score_no_call(item: dict, out: dict) -> dict:
    calls = out.get("tool_calls") or []
    return _res(not calls, predicted=[c.get("name") for c in calls])


_QMARK = re.compile(r"[?？]")


def score_when2call(item: dict, out: dict) -> dict:
    """call: first call has the right name; ask: no call and a question; decline: no call, some text, no question."""
    exp, calls, text = item["expected"], out.get("tool_calls") or [], (out.get("content") or "").strip()
    asked = bool(_QMARK.search(text))
    got = "call" if calls else "ask" if asked else "decline" if text else "empty"
    ok = got == exp["behavior"] and (got != "call" or calls[0].get("name") == exp.get("tool"))
    return _res(ok, behavior=got, expected=exp["behavior"])


def score_first_tool(item: dict, out: dict) -> dict:
    exp, calls = item["expected"], out.get("tool_calls") or []
    got = calls[0].get("name") if calls else "none"
    if got != exp["tool"]:
        return _res(False, predicted=got, expected=exp["tool"])
    blob = json.dumps(calls[0].get("arguments"), ensure_ascii=False).lower() if calls else ""
    missing = [s for s in exp.get("args_contains") or [] if s.lower() not in blob]
    return _res(not missing, predicted=got, missing_args=missing)


# ---------------------------------------------------------------- grounded QA / extraction

_REFUSAL = re.compile("|".join([
    # French
    r"pas (?:pu )?trouve", r"ne contien\w+ pas", r"ne contien\w+ aucun", r"pas d information", r"aucune information",
    r"aucune (?:mention|indication|precision)", r"ne (?:le |la |les |en )?mentionn\w+ (?:pas|aucun)",
    r"ne (?:le |la |les )?precis\w+ pas", r"ne (?:le |la |les )?indiqu\w+ pas", r"ne (?:le |la |les )?fourni\w+ pas",
    r"ne (?:le |la |les )?donn\w+ pas", r"n (?:est|y est|en est|est nulle part) (?:pas |nullement )?(?:mentionn|precis|indiqu|fourni|communiqu|specifi)",
    r"n est pas (?:disponible|present)", r"ne figure\w* (?:pas|nulle)", r"ne perme\w+ pas de", r"impossible de (?:repondre|determiner|le dire)",
    r"je ne (?:sais|peux) pas (?:repondre|le dire|le determiner|vous|te)?", r"pas (?:de|la) reponse", r"ne dispose\w* pas",
    r"n apparai\w+ pas", r"pas en mesure de",
    # English
    r"not contain", r"no information", r"(?:cannot|can t|could not|couldn t|can not|unable to|did not|didn t|not) find",
    r"(?:does|do|did)(?: not|n t) (?:mention|specify|state|provide|say|include|give|indicate|list|cover|address)",
    r"not (?:mentioned|stated|specified|provided|given|indicated|listed|available|included|covered|addressed)",
    r"no mention", r"(?:cannot|can t|unable to|not able to|can not) (?:answer|determine|be determined|say|tell)",
    r"not enough information", r"insufficient information", r"(?:not|isn t|aren t) (?:in|found in|present in|part of) the (?:provided |given )?(?:document|context|text|source)",
    r"i don t know", r"no (?:answer|data|details?|figure|indication) ",
]))


def is_refusal(text: str) -> bool:
    """Does the answer say that the information is not in the documents?"""
    return bool(_REFUSAL.search(norm(text) + " "))


def score_grounded(item: dict, out: dict) -> dict:
    exp, text = item["expected"], out.get("content") or ""
    declined = is_refusal(text)
    if not exp["answerable"]:
        return _res(declined, answerable=False, declined=declined)
    f1 = token_f1(text, exp.get("reference_answer") or exp.get("answer") or "")
    span = bool(exp.get("answer")) and contains(text, exp["answer"])
    return _res((f1 >= 0.3 or span) and not declined, answerable=True, declined=declined, f1=round(f1, 3), span=span)


def score_contains_any(item: dict, out: dict) -> dict:
    text = out.get("content") or ""
    hit = next((g for g in item["expected"]["any"] if contains(text, g)), None)
    return _res(hit is not None, matched=hit)


_FILLERS = ("excellente question", "bonne question", "great question", "good question", "certainly!", "bien sûr !",
            "bien sûr!", "as an ai", "en tant qu'ia", "en tant qu'intelligence artificielle", "absolument !", "absolutely!")


def score_concise(item: dict, out: dict) -> dict:
    exp, text = item["expected"], (out.get("content") or "").strip()
    low = " ".join(text.lower().replace("’", "'").split())
    hit = next((g for g in exp["any"] if contains(text, g)), None)
    words = len(text.split())
    filler = next((f for f in _FILLERS if f in low), None)
    ok = hit is not None and words <= exp.get("max_words", 60) and filler is None
    return _res(ok, matched=hit, words=words, filler=filler)


_FENCE = re.compile(r"```[a-zA-Z0-9_-]*\s*\n?(.*?)```", re.S)


def extract_json(text: str):
    """Parsed JSON value from an answer (optionally inside a ``` fence); raises ValueError otherwise."""
    text = (text or "").strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    elif text.startswith("```"):  # opening fence never closed (truncated answer)
        text = text.split("\n", 1)[-1].strip()
    return json.loads(text)


def score_json_schema(item: dict, out: dict) -> dict:
    schema = item["expected"]["schema"]
    try:
        inst = extract_json(out.get("content") or "")
    except ValueError:
        return _res(False, reason="not valid JSON")
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    try:
        err = next(iter(cls(schema).iter_errors(inst)), None)
    except Exception as e:  # unresolvable $ref and the like
        return _res(False, reason=f"schema error: {type(e).__name__}")
    return _res(err is None, reason=None if err is None else err.message[:200])


def score_numbers(item: dict, out: dict) -> dict:
    r = numbers_check(out.get("content") or "", item["expected"]["facts"])
    return {"score": float(r["score"]), "detail": {"missing": r["missing"], "checked": r["checked"]}}


# ---------------------------------------------------------------- identity

_OTHER = (r"(?:qwen|tongyi|chat ?gpt|gpt|openai|claude|anthropic|gemini|bard|google|alibaba|llama|meta ai|mistral|"
          r"deepseek|copilot|microsoft|grok)(?![a-zà-ÿ])")
_COMPANY = r"(?:openai|alibaba(?: cloud)?|anthropic|google(?: deepmind)?|deepmind|meta|microsoft|mistral(?: ai)?|deepseek|qwen|tongyi)"
_SELF = re.compile(r"\b(?:je suis|i am|i'm|je m'appelle|my name is|mon nom est|on m'appelle|call me|appelez-moi|appelle-moi)\b"
                   r"([^.,;:!?\n()—–]{0,60})")
_SAFE = re.compile(r"\b(?:bird|not|pas|ni|non|no|neither|nor|built|based|construit|bas[ée]e?|fond[ée]e?|issue?|d[ée]riv[ée]e?|derived|"
                   r"from|partir|top|fine-?tun\w*|sp[ée]cialis\w*|specialis\w*|specializ\w*|adapt\w*|powered|propuls\w*|rather|plut[oô]t|"
                   r"instead|unlike|contrairement)\b")
_MADE = r"(?:cré|cre|développ|developp|conç|conc|entra[iî]n|fabriqu|built|made|trained|designed|released)\w*"
_MADE_BY = re.compile(
    r"\b(?:i was|i am|i'm|i have been|i've been|j'ai été|je suis|j'ai ete)\s+(?:\w+\s+){0,2}?" + _MADE
    + r"\s+(?:by|par|chez|at)\s+(?:(?:the|l'|la|le|les|team|équipe|société|company|entreprise|of|de|d')\s*){0,3}" + _COMPANY + r"\b"
    r"|\b" + _COMPANY + r"\s+(?:qui\s+)?m'(?:a|ont)\s+" + _MADE
    + r"|\b" + _COMPANY + r"\s+(?:has\s+|have\s+|who\s+|that\s+)?" + _MADE + r"\s+me\b"
    r"|\b(?:my (?:creator|developer|maker)s?|mon (?:créateur|concepteur|développeur)|mes (?:créateurs|concepteurs))\s+(?:is|are|est|sont)\s+(?:\w+\s+){0,2}?"
    + _COMPANY + r"\b")


def identity_violation(text: str) -> str | None:
    """The fragment where the model takes another identity or another maker, else None."""
    low = " ".join((text or "").lower().replace("’", "'").replace("*", "").replace("_", " ").split())
    for m in _SELF.finditer(low):
        tail = m.group(1)
        if re.search(r"\b" + _OTHER, tail) and not _SAFE.search(tail):
            return m.group(0).strip()
    m = _MADE_BY.search(low)
    return m.group(0).strip() if m else None


def score_identity(item: dict, out: dict) -> dict:
    text = out.get("content") or ""
    named = re.search(r"\bbird\b", text, re.I) is not None
    bad = identity_violation(text)
    return _res(named and bad is None, says_bird=named, violation=bad)


# ---------------------------------------------------------------- language

_FR = frozenset("le la les des du de un une et est en que qui pour dans pas vous nous je il elle sur au aux avec ce cette ces "
                "sont votre vos notre nos se ne par ou mais être avoir à voici très sa ses mon mes leur leurs si comme tout "
                "fait peut ont été l j qu n y dont où afin chez entre aussi cela ainsi donc bonjour merci cordialement".split())
_EN = frozenset("the of and to is in that for it with as was are be this have from or by not you we your our will can at an i if "
                "please thanks thank hi hello here there has would should their they been but which regards dear my do does "
                "what when how these those its about into than then so also best".split())
_WORD = re.compile(r"[a-zàâäçéèêëîïôöùûüœ]+")


def detect_lang(text: str) -> tuple[str | None, int, int]:
    """('fr' | 'en' | None, french hits, english hits) from stop-word counts."""
    words = _WORD.findall((text or "").lower().replace("’", "'"))
    fr, en = sum(w in _FR for w in words), sum(w in _EN for w in words)
    if fr + en < 2:
        return None, fr, en
    ratio = fr / (fr + en)
    return ("fr" if ratio >= 0.6 else "en" if ratio <= 0.4 else None), fr, en


def score_language(item: dict, out: dict) -> dict:
    lang, fr, en = detect_lang(out.get("content") or "")
    return _res(lang == item["expected"]["lang"], detected=lang, fr=fr, en=en)


# ---------------------------------------------------------------- dispatch and aggregation

SCORERS = {
    "tool_call": score_tool_call, "no_call": score_no_call, "when2call": score_when2call, "first_tool": score_first_tool,
    "grounded": score_grounded, "contains_any": score_contains_any, "json_schema": score_json_schema,
    "numbers": score_numbers, "identity": score_identity, "language": score_language, "concise": score_concise,
}


def score(item: dict, output: dict) -> dict:
    """Score one parsed model output against one benchmark item."""
    r = SCORERS[item["scorer"]](item, output or {})
    r["score"] = min(1.0, max(0.0, float(r["score"])))
    return r


def aggregate(results: list[dict]) -> dict:
    """Mean score per suite and per language, plus macro-averages over suites.

    Each result needs "suite", "lang" and "score". `overall` is the macro-average over the main suites;
    the `*_think` copies are reported apart in `overall_think` so they do not count twice.
    """
    def mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    by_suite, by_lang = defaultdict(list), defaultdict(list)
    for r in results:
        by_suite[r["suite"]].append(float(r["score"]))
        by_lang[r["lang"]].append(float(r["score"]))
    suites = {s: {"n": len(v), "score": mean(v)} for s, v in sorted(by_suite.items())}
    main = [v["score"] for s, v in suites.items() if not s.endswith("_think")]
    think = [v["score"] for s, v in suites.items() if s.endswith("_think")]
    return {
        "n": len(results),
        "suites": suites,
        "langs": {k: {"n": len(v), "score": mean(v)} for k, v in sorted(by_lang.items())},
        "overall": mean(main),
        "overall_think": mean(think),
    }
