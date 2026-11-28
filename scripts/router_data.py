"""The trigger bench (scripts/trigger_bench.py) as a labelled dataset for the model router, its scoring, and a
scripted stand-in for a 4B router (plumbing tests and ``router_eval.py --fake``).

Each item: {"family", "text", "history", "label": "yes" | "no", "expect": {"tool", "args"} | None,
"tools": the family's modules (a "no" must start none of them), "agent": True for the agent families}.
Labels come from the bench lists only: a "yes" names the module (and, where the bench does, its arguments), a "no"
forbids the family's modules (``OFFICE_NO`` in the follow-up and realistic families forbids every rich module).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import trigger_bench as B  # noqa: E402

from birds.harness import catalog, clock, followup  # noqa: E402
from birds.harness import router as R  # noqa: E402

RICH = tuple(m.name for m in catalog.MODULES if m.kind != catalog.HINT)
_REALISTIC = {"chart": "make_chart", "event": "event"}


# Tasks on pasted text: what the parsers read inside the quoted text is content, not a request. Router families only:
# the parsers fire on most of the "no" items (a known limit of the regex path), so they stay off the trigger bench.
PASTED_NO = [
    "Résume ce mail : « Bonjour, la réunion de demain est maintenue. Météo à Lyon demain : pluie, prenez un "
    "parapluie. Cordialement »",
    "Analyse ce verbatim client : « l'horloge de la salle de réunion à New York retarde »",
    "Traduis en anglais : « Rendez-vous jeudi à 14h au restaurant Le Florian à Lyon, il fera beau »",
    "Corrige les fautes : « la reunion de lundi a Marseille est reporter, la météo a Marseille demain est mauvaise »",
    "Reformule ce message : « 100 euros en dollars, ça fait combien maintenant ? demande le client »",
    'Summarize this email: "Hi team, the weather in London tomorrow looks bad, so the offsite moves to Friday"',
    "Résume ce compte rendu : « Point client chez Michelin à Clermont-Ferrand, quelle heure est-il à Tokyo pour le "
    "call »",
    "Analyse ce verbatim : « je cherche une pharmacie près de la gare de Lyon et rien n est indiqué »",
]
PASTED_YES = [  # (ask, the module its own instruction starts)
    ("Corrige : « je vais au restaurant demain soir avec Paul » et trouve-moi un restaurant à Lyon", "find_places"),
    ('Proofread: "see you at the office tomorrow morning, team" and show me restaurants near Gare du Nord',
     "find_places"),
    ("Corrige : « on se voit demain au bureau pour le point » et quelle heure est-il à Tokyo ?", "clock"),
]  # fmt: skip


def _history(prev) -> list[dict] | None:
    """The conversation a follow-up comes after: the previous turn's memo, as the server writes it."""
    if prev is None:
        return None
    if prev == B._CHART:
        return list(B._CHART_HISTORY)
    tool, args = prev["tool"], prev["args"]
    ask = {
        "get_weather": "météo à Lyon demain",
        "find_places": "restaurants près de la gare de Lyon" if args.get("near") else "où est la tour Eiffel ?",
        "convert_currency": "100 euros en dollars",
        "clock": "quelle heure est-il à Tokyo",
        "find_company": "qui dirige Michelin ?",
    }[tool]
    memo = followup.memo_part({"tool": tool, "args": args}, "fr")
    return [{"role": "user", "content": ask}, {"role": "assistant", "content": f"Voilà.\n\n[Mémo de ce tour — {memo}]"}]


def _item(family, text, label, tools, expect=None, history=None, agent=False) -> dict:
    return {"family": family, "text": text, "history": history, "label": label, "expect": expect,
            "tools": list(tools), "agent": agent}  # fmt: skip


def items() -> list[dict]:
    out: list[dict] = []
    for fam, yes, no in (("charts", B.CHART_YES, B.CHART_NO), ("charts+", B.CHART_YES2, B.CHART_NO2)):
        out += [_item(fam, q, "yes", ["make_chart"], {"tool": "make_chart", "args": {}}) for q in yes]
        out += [_item(fam, q, "no", ["make_chart"]) for q in no]
    out += [_item("chart_howto", q, "no", ["make_chart"]) for q in B.CHART_HOWTO_NO]
    out += [_item("maps", q, "yes", ["find_places"], {"tool": "find_places", "args": {}}) for q in B.MAP_YES]
    out += [_item("maps", q, "no", ["find_places"]) for q in B.MAP_NO]
    for q in B.MAP_YES2:
        want = B.MAP_ARGS.get(q)
        args = {} if want is None else {"query": want[0], **({"near": want[1]} if want[1] else {})}
        out.append(_item("maps+", q, "yes", ["find_places"], {"tool": "find_places", "args": args}))
    out += [_item("maps+", q, "no", ["find_places"]) for q in B.MAP_NO2]
    out += [_item("weather", q, "yes", ["get_weather"], {"tool": "get_weather", "args": {"place": p}})
            for q, p in B.WEATHER_YES]  # fmt: skip
    out += [_item("weather", q, "no", ["get_weather"]) for q in B.WEATHER_NO]
    out += [_item("clock", q, "yes", ["clock"], {"tool": "clock", "args": {"cities": c}}) for q, c in B.CLOCK_YES]
    out += [_item("clock", q, "no", ["clock"]) for q in B.CLOCK_NO]
    cf = ["find_company", "convert_currency"]
    for q in B.COMPANY_FX_YES:
        want = B.FX_ARGS.get(q)
        exp = (
            {"tool": "convert_currency", "args": {"from": want[0], "to": want[1]}} if want else {"tool": "", "args": {}}
        )
        out.append(_item("company_fx", q, "yes", cf, exp))
    out += [_item("company_fx", q, "no", cf) for q in B.COMPANY_FX_NO]
    out += [_item("events", q, "yes", ["event"], {"tool": "event", "args": {}}) for q in B.EVENT_YES]
    out += [_item("events", q, "no", ["event"]) for q in B.EVENT_NO]
    out += [_item("images", q, "yes", ["images"], {"tool": "images", "args": {"subject": s}}) for q, s in B.IMAGES_YES]
    out += [_item("images", q, "no", ["images"]) for q in B.IMAGES_NO]
    for prev, q, want in B.FOLLOWUP_YES:
        tool, val = want
        if tool == "chart":
            exp = {"tool": "make_chart", "args": {"type": val}}
        elif tool == "clock":
            exp = {"tool": "clock", "args": {"cities": val}}
        else:
            exp = {"tool": tool, "args": val}
        out.append(_item("followups", q, "yes", [exp["tool"]], exp, _history(prev)))
    out += [_item("followups", q, "no", RICH, None, _history(prev)) for prev, q in B.FOLLOWUP_NO]
    for q, fam in B.REALISTIC_YES:
        tool = _REALISTIC.get(fam, fam)
        out.append(_item("realistic", q, "yes", [tool], {"tool": tool, "args": {}}))
    out += [_item("realistic", q, "no", RICH) for q in B.OFFICE_NO]
    out += [_item("pasted", q, "yes", [t], {"tool": t, "args": {}}) for q, t in PASTED_YES]
    out += [_item("pasted", q, "no", RICH) for q in PASTED_NO]
    for fam, yes, no in (("agent", B.AGENT_YES, B.AGENT_NO), ("office_agent", B.OFFICE_AGENT_YES, B.OFFICE_AGENT_NO),
                         ("agent_study", B.STUDY_YES, B.STUDY_NO)):  # fmt: skip
        out += [_item(fam, q, "yes", [], None, agent=True) for q in yes]
        out += [_item(fam, q, "no", [], None, agent=True) for q in no]
    return out


# ---------------------------------------------------------------- scoring


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return R.fold(str(a)) == R.fold(str(b))


def _cities(call) -> list[str]:
    got = clock.detect(R.clock_text(call))
    return [c["fr"] for c in got["cities"]] if got else []


def args_ok(call, expect: dict) -> bool:
    want = expect.get("args") or {}
    if call.tool == "clock" and "cities" in want:
        return _cities(call) == want["cities"]
    if call.tool == "find_places" and want:
        return _same(call.args.get("query", ""), want["query"]) and _same(
            call.args.get("near", ""), want.get("near", "")
        )
    return all(k in call.args and _same(call.args[k], v) for k, v in want.items())


def judge(decision, item) -> dict:
    """{"pred": the family fired, "ok": the item is right (tool and, where labelled, arguments)}."""
    if item["agent"]:
        pred = decision.agent == "on"
        return {"pred": pred, "ok": pred == (item["label"] == "yes"), "args": True}
    fired = [c for c in decision.modules if c.tool in item["tools"]]
    if item["label"] == "no":
        return {"pred": bool(fired), "ok": not fired, "args": True}
    exp = item["expect"]
    hit = [c for c in fired if not exp["tool"] or c.tool == exp["tool"]]
    good = bool(hit) and args_ok(hit[0], exp)
    return {"pred": bool(hit), "ok": good, "args": good or not hit}


def summarise(rows: list[dict]) -> dict:
    """Per family: accuracy, precision, recall (a 'yes' counts as found only with the right arguments)."""
    fams: dict[str, dict] = {}
    for r in rows:
        f = fams.setdefault(r["family"], {"n": 0, "ok": 0, "tp": 0, "fp": 0, "fn": 0, "wrong_args": 0})
        f["n"] += 1
        f["ok"] += r["ok"]
        if r["label"] == "yes":
            f["tp"] += r["ok"]
            f["fn"] += not r["ok"]
            f["wrong_args"] += r["pred"] and not r["ok"]
        else:
            f["fp"] += r["pred"]
    for f in fams.values():
        f["accuracy"] = round(f["ok"] / f["n"], 3) if f["n"] else None
        f["precision"] = round(f["tp"] / (f["tp"] + f["fp"]), 3) if f["tp"] + f["fp"] else None
        f["recall"] = round(f["tp"] / (f["tp"] + f["fn"]), 3) if f["tp"] + f["fn"] else None
    return fams


# ---------------------------------------------------------------- a scripted stand-in for Bird S 4B


def oracle(item) -> dict:
    """The decision the labels call for, as the router would write it."""
    mods = []
    exp = item["expect"]
    if item["label"] == "yes" and exp and not exp["tool"]:  # company_fx without labelled args: the parser's call
        base = R.regex_decision(item["text"], history=item["history"])
        mods = [c.as_dict() for c in base.modules if c.tool in item["tools"]][:1]
        return {"modules": mods, "agent": "auto", "needs_web": False}
    if item["label"] == "yes" and exp and exp["tool"]:
        args = dict(exp["args"])
        if exp["tool"] == "make_chart":
            args = {k: v for k, v in args.items() if k == "type"}
        if exp["tool"] == "find_places" and not args:  # the bench names no query: the parser's, else the words
            got = R.regex_decision(item["text"]).get("find_places")
            args = dict(got.args) if got else {"query": item["text"].split(" les ", 1)[-1].strip(" ?")[:80]}
        mods.append({"tool": exp["tool"], "args": args})
    agent = "on" if item["agent"] and item["label"] == "yes" else "auto"
    return {"modules": mods, "agent": agent, "needs_web": False}


_MSG = re.compile(r"(?:^|\n)Message ?: (?P<m>[^\n]*?)(?:<\|im_end\|>|\n|$)")
_HINTS = re.compile(r"(?:^|\n)(?:Indices|Hints) ?: (?P<h>[^\n]*)")


class Imitator:
    """A fake endpoint that answers router prompts like a small model would: the labelled decision most of the time,
    and, deterministically by the hash of the message, the mistakes seen with small models: broken JSON, prose
    around it, a made-up argument, a false trigger on a "no", a missed module. Not a measure of the real model:
    it proves the plumbing (parsing, validation, veto, fallback) holds on every bench phrasing."""

    def __init__(self, dataset: list[dict], *, error_every: int = 6, structured: str = ""):
        self.by_text = {}
        for it in dataset:
            self.by_text.setdefault(" ".join(it["text"].split())[: R.MAX_MESSAGE_CHARS], it)
        self.error_every, self.router_structured, self.prompts = error_every, structured, []

    def generate(self, prompt: str, max_tokens: int, stop, **kw) -> dict:
        self.prompts.append(prompt)
        tail = prompt.rsplit("<|im_start|>user", 1)[-1]
        m = _MSG.search(tail)
        it = self.by_text.get(m.group("m").strip() if m else "")
        if it is None:
            text = json.dumps({"modules": [], "agent": "auto", "needs_web": False})
        else:
            text = json.dumps(self._answer(it), ensure_ascii=False)
            h = int(hashlib.sha1(it["text"].encode()).hexdigest(), 16)
            if self.error_every and h % self.error_every == 0:
                text = self._mistake(it, text, h)
        if prompt.endswith(R.PREFIX) and text.startswith(R.PREFIX):
            text = text[len(R.PREFIX) :]  # the harness wrote the start of the object
        return {"text": text, "prompt_tokens": len(prompt) // 4, "completion_tokens": len(text) // 4, "seconds": 0.05}

    def _answer(self, it) -> dict:
        return oracle(it)

    def _mistake(self, it, text: str, h: int) -> str:
        kind = (h // 7) % 4
        if kind == 0:
            return text[: max(10, len(text) // 2)]  # cut off: repaired, or a fallback
        if kind == 1:
            return "Voici ma décision : " + text + " Bonne journée !"
        if kind == 2 and it["label"] == "yes" and it["expect"] and it["expect"]["tool"] in ("get_weather", "images"):
            key = "place" if it["expect"]["tool"] == "get_weather" else "subject"
            return json.dumps({"modules": [{"tool": it["expect"]["tool"], "args": {key: "Zanzibar"}}],
                               "agent": "auto", "needs_web": False})  # fmt: skip
        if it["label"] == "no" and it["tools"]:
            tool = it["tools"][0]
            args = {"get_weather": {"place": it["text"].split()[-1]}, "find_places": {"query": it["text"].split()[-1]},
                    "clock": {"cities": [it["text"].split()[-1]]}, "images": {"subject": it["text"].split()[-1]},
                    "make_chart": {}, "event": {}, "find_company": {"name": it["text"].split()[-1]},
                    "convert_currency": {"from": "USD", "to": "EUR"}}.get(tool, {})  # fmt: skip
            return json.dumps({"modules": [{"tool": tool, "args": args}], "agent": "auto", "needs_web": False})
        return json.dumps({"modules": [], "agent": "auto", "needs_web": False})  # a missed module
