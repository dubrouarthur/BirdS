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

import bench_finance as FI  # noqa: E402
import bench_opendata as OD  # noqa: E402
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


def _rich_but_calc(q: str) -> list[str]:
    """Every rich module, except the calculator card for an ask it computes: « calcule la marge sur un produit vendu
    120 € acheté 80 € » is an office prompt with no chart or map, and a ``card(calc)`` yes of the cards family."""
    from birds.harness import calc

    return [t for t in RICH if t != "card"] if calc.detect(q) is not None else list(RICH)


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
    # a category near a town (« supermarchés à Saint-Cloud »): the category, in the user's words or as the OSM key
    out += [_item("maps_category", q, "yes", ["find_places"], {"tool": "find_places", "args": {"query": k, "near": n}})
            for q, k, n, _ in B.bench_maps.MAPS_CATEGORY]  # fmt: skip
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
    out += [_item("followups", q, "no", _rich_but_calc(q), None, _history(prev)) for prev, q in B.FOLLOWUP_NO]
    for q, fam in B.REALISTIC_YES:
        tool = _REALISTIC.get(fam, fam)
        out.append(_item("realistic", q, "yes", [tool], {"tool": tool, "args": {}}))
    out += [_item("realistic", q, "no", _rich_but_calc(q)) for q in B.OFFICE_NO]
    out += [_item("cards", q, "yes", ["card"], {"tool": "card", "args": {"kind": k}}) for q, k in B.CARD_YES]
    out += [_item("cards", q, "no", ["card"]) for q in B.CARD_NO]
    out += [_item("pasted", q, "yes", [t], {"tool": t, "args": {}}) for q, t in PASTED_YES]
    out += [_item("pasted", q, "no", RICH) for q in PASTED_NO]
    od = [m.name for m in catalog.MODULES if m.family == "opendata"]
    out += [_item("opendata", q, "yes", od, {"tool": t, "args": a}) for q, t, a in OD.OPENDATA_YES]
    out += [_item("opendata", q, "no", od) for q in OD.OPENDATA_NO]
    out += [_item("opendata_router", q, "yes", od, {"tool": t, "args": a}) for q, t, a in OD.OPENDATA_ROUTER_YES]
    fi = ["get_quote"]
    out += [_item("finance", q, "yes", fi, {"tool": "get_quote", "args": a}) for q, a in FI.FINANCE_YES]
    out += [_item("finance", q, "no", fi) for q in FI.FINANCE_NO]
    out += [_item("finance_router", q, "yes", fi, {"tool": "get_quote", "args": a}) for q, a in FI.FINANCE_ROUTER_YES]
    for fam, yes, no in (("agent", B.AGENT_YES, B.AGENT_NO), ("office_agent", B.OFFICE_AGENT_YES, B.OFFICE_AGENT_NO),
                         ("agent_study", B.STUDY_YES, B.STUDY_NO)):  # fmt: skip
        out += [_item(fam, q, "yes", [], None, agent=True) for q in yes]
        out += [_item(fam, q, "no", [], None, agent=True) for q in no]
    out += use_tools_items()
    return out


def _turn(ask: str, answer: str) -> list[dict]:
    return [{"role": "user", "content": ask}, {"role": "assistant", "content": answer}]


# Bird uses its tools instead of refusing (docs/HARNESS.md § 19): a misspelt name is a card under its right name, and
# « une image » after a topic is a picture of that topic. Router eval cases and training examples at once.
TYPO_YES = [
    ("qui est jaques chirac", "Jacques Chirac"), ("c'est qui simone veille ?", "Simone Veil"),
    ("qui était charles de gaule", "Charles de Gaulle"), ("parle-moi de leonard de vinci", "Léonard de Vinci"),
    ("who is barak obama", "Barack Obama"), ("who was winston churchil", "Winston Churchill"),
]  # fmt: skip
PICTURE_FOLLOWUP_YES = [
    ("parle-moi du lynx boréal", "Le lynx boréal est le plus grand félin d'Europe.", "une image", "lynx boréal"),
    ("raconte-moi l'histoire de la cathédrale de Chartres", "Elle fut rebâtie après 1194.", "tu as une photo ?",
     "cathédrale de Chartres"),
    ("c'est quoi un axolotl ?", "Un amphibien du Mexique qui garde ses branchies.", "montre-moi à quoi il ressemble",
     "axolotl"),
    ("tell me about the Matterhorn", "A 4,478 m peak on the Swiss-Italian border.", "a picture?", "Matterhorn"),
]  # fmt: skip
PICTURE_FOLLOWUP_NO = [  # a picture ask with nothing to picture, or an image to make: no search
    ("écris un poème sur l'automne", "Les feuilles tombent…", "génère une image pour l'illustrer"),
    ("aide-moi à rédiger mon CV", "Voici une structure.", "je mets une photo ?"),
]  # fmt: skip


def use_tools_items() -> list[dict]:
    out = [_item("typo_entity", q, "yes", ["lookup_entity"], {"tool": "lookup_entity", "args": {"name": n}})
           for q, n in TYPO_YES]  # fmt: skip
    out += [_item("picture_followup", m, "yes", ["images"], {"tool": "images", "args": {"subject": s}},
                  history=_turn(q, a)) for q, a, m, s in PICTURE_FOLLOWUP_YES]  # fmt: skip
    out += [_item("picture_followup", m, "no", ["images"], history=_turn(q, a)) for q, a, m in PICTURE_FOLLOWUP_NO]
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
    if call.tool == "get_statistics" and want.get("indicator"):  # the parser's key or the model's word, same series
        from birds.harness.tools.opendata.stats import indicator_of

        if indicator_of(str(call.args.get("indicator", "")), loose=True) != want["indicator"]:
            return False
        want = {k: v for k, v in want.items() if k != "indicator"}
    if call.tool == "work_calendar" and "zone" in want:
        from birds.harness.tools.opendata.calendar import zone_of

        if zone_of(str(call.args.get("zone") or "metropole")) != zone_of(want["zone"]):
            return False
        want = {k: v for k, v in want.items() if k != "zone"}
    if call.tool == "find_tenders" and "where" in want:
        from birds.harness.tools.opendata.places_fr import where

        if where(str(call.args.get("where", "")))[1] != where(want["where"])[1]:
            return False
        want = {k: v for k, v in want.items() if k != "where"}
    if call.tool == "get_quote":  # the same instruments, whatever their spelling or order
        return FI.args_match(call.args, want)
    if call.tool == "clock" and "cities" in want:
        return _cities(call) == want["cities"]
    if call.tool == "find_places" and want:
        from birds.harness.tools.places import category

        q = call.args.get("query", "")
        same_kind = (category(q) or ("",))[0] == want["query"]  # « supermarché » is the category « supermarket »
        return (same_kind or _same(q, want["query"])) and _same(
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
    drawn = ("get_statistics", "get_quote")  # official figures or market prices drawn from the source itself
    if exp["tool"] == "make_chart":  # a trend of official figures drawn from the source itself is that chart
        fired += [c for c in decision.modules if c.tool in drawn]
    hit = [c for c in fired if not exp["tool"] or c.tool == exp["tool"] or (exp["tool"] == "make_chart"
                                                                            and c.tool in drawn)]
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
                    "convert_currency": {"from": "USD", "to": "EUR"},
                    "work_calendar": {"period": "2027"}, "lookup_entity": {"name": it["text"].split()[-1]},
                    "get_statistics": {"indicator": "gdp"}, "find_tenders": {"query": it["text"].split()[-1]},
                    "find_papers": {"query": it["text"].split()[-1]},
                    "find_commune": {"name": it["text"].split()[-1]},
                    "get_quote": {"symbols": "CAC 40"}}.get(tool, {})  # fmt: skip
            return json.dumps({"modules": [{"tool": tool, "args": args}], "agent": "auto", "needs_web": False})
        return json.dumps({"modules": [], "agent": "auto", "needs_web": False})  # a missed module


# ---------------------------------------------------------------- the data planner (birds/harness/analysis/planner.py)
# Fixed cases on tests/fixtures/data/ventes.csv: (id, message, previous spec or None, gold, charts accepted).
# gold None = no computation; otherwise the query keys that must match (by/pivot may be swapped for a cross-tab,
# "filter" = (column, value) of one filter). ``LIVE_8`` are the 8 prompts of the live before/after (docs/HARNESS.md).
_PREV_REGION = {"analysis": {"op": "aggregate", "measure": "CA (€)", "agg": "sum", "by": "Région", "sort": "desc"},
                "chart": "bar", "version": 1}  # fmt: skip
_PREV_QTY = {"analysis": {"op": "aggregate", "measure": "Quantité", "agg": "mean", "by": "Région", "sort": "desc"},
             "chart": "bar", "version": 1}  # fmt: skip
DATA_PLAN = [
    ("units_seller", "Quel commercial a vendu le plus d'unités ?", None,
     {"op": "aggregate", "measure": "Quantité", "agg": "sum", "by": "Commercial"}, {"bar", "hbar", "auto"}),
    ("moving_avg", "CA mensuel avec une moyenne mobile sur 3 mois", None,
     {"op": "aggregate", "measure": "CA (€)", "time": "Date", "period": "month", "window": 3},
     {"combo", "line", "area", "auto"}),
    ("pivot", "CA par région et par produit", None,
     {"op": "aggregate", "measure": "CA (€)", "agg": "sum", "by": "Région", "pivot": "Produit"},
     {"stacked", "heatmap", "bar", "auto"}),
    ("top_filter", "Les 5 clients qui rapportent le plus dans le Sud", None,
     {"op": "aggregate", "measure": "CA (€)", "by": "Client", "top": 5, "filter": ("Région", "Sud")},
     {"hbar", "bar", "auto"}),
    ("pct_change", "Évolution du CA d'un trimestre à l'autre, en %", None,
     {"op": "aggregate", "measure": "CA (€)", "time": "Date", "period": "quarter", "change": True},
     {"combo", "line", "bar", "auto"}),
    ("compare_by", "Compare 2024 et 2025 par produit", None,
     {"op": "compare", "measure": "CA (€)", "by": "Produit", "years": [2024, 2025]}, {"bar", "hbar", "auto"}),
    ("share", "Quelle part du CA fait chaque produit ?", None,
     {"op": "aggregate", "measure": "CA (€)", "by": "Produit", "share": True}, {"donut", "auto"}),
    ("summary_no", "Résume ce fichier en deux phrases", None, None, set()),
    # held out of the live run (rules and scripted checks only)
    ("followup_pie", "plutôt en camembert", _PREV_REGION,
     {"op": "aggregate", "measure": "CA (€)", "by": "Région", "share": True}, {"donut"}),
    ("followup_top", "garde seulement les 3 premières", _PREV_REGION,
     {"op": "aggregate", "measure": "CA (€)", "by": "Région", "top": 3}, {"bar", "hbar", "auto"}),
    ("mean_price", "Prix unitaire moyen par produit", None,
     {"op": "aggregate", "measure": "Prix unitaire (€)", "agg": "mean", "by": "Produit"}, {"bar", "hbar", "auto"}),
    ("corr", "Y a-t-il un lien entre la remise et la quantité ?", None,
     {"op": "corr", "x": {"Remise", "Quantité"}, "y": {"Remise", "Quantité"}}, {"scatter", "auto"}),
    ("mail_no", "Rédige un mail à Paul pour lui présenter ce fichier", None, None, set()),
    ("en_monthly", "monthly revenue in 2025", None,
     {"op": "aggregate", "measure": "CA (€)", "time": "Date", "period": "month", "filter": ("Date", 2025)},
     {"line", "area", "bar", "combo", "auto"}),
    # the « Par {colonne} » chip: the category changes, the measure and the aggregation stay
    ("followup_by", "Par Produit", _PREV_QTY, {"op": "aggregate", "measure": "Quantité", "agg": "mean", "by": "Produit"},
     {"bar", "hbar", "auto"}),
    ("followup_by_en", "By Commercial", _PREV_QTY,
     {"op": "aggregate", "measure": "Quantité", "agg": "mean", "by": "Commercial"}, {"bar", "hbar", "auto"}),
    # the table is already in the conversation (an analysis was shown) and the message is about something else: no
    # computation (review 28/11/2026: each of these became « Total CA (€) » and replaced the model's answer)
    ("earlier_canberra", "Quelle est la population de Canberra ?", _PREV_REGION, None, set()),
    ("earlier_maths", "Combien font 17 x 23 ?", _PREV_REGION, None, set()),
    ("earlier_price", "Combien coûte un abonnement Bird ?", _PREV_REGION, None, set()),
    ("earlier_en", "What is the total population of France?", _PREV_REGION, None, set()),
    ("earlier_advice", "Quelle est la meilleure façon de présenter ce fichier à mon chef ?", _PREV_REGION, None, set()),
    ("earlier_leave", "Combien de jours de congés me reste-t-il ?", _PREV_REGION, None, set()),
]  # fmt: skip
LIVE_8 = ("units_seller", "moving_avg", "pivot", "top_filter", "pct_change", "compare_by", "share", "summary_no")


def data_judge(plan: dict | None, gold: dict | None, charts: set[str]) -> dict:
    """{"ok": the right analysis, "chart_ok": an accepted chart (or no computation when none is due)}."""
    if gold is None:
        return {"ok": plan is None, "chart_ok": plan is None}
    if plan is None:
        return {"ok": False, "chart_ok": False}
    q = plan["query"]
    ok = True
    for k, v in gold.items():
        if k == "filter":
            col, val = v
            ok &= any(f.get("col") == col and (str(f.get("value")).lower() == str(val).lower()
                      or (isinstance(f.get("value"), list) and str(val) in map(str, f["value"])))
                      for f in q.get("filters") or [])  # fmt: skip
        elif k in ("by", "pivot") and "pivot" in gold:
            ok &= {q.get("by"), q.get("pivot")} == {gold["by"], gold["pivot"]}
        elif isinstance(v, set):
            ok &= q.get(k) in v
        else:
            ok &= q.get(k) == v
    return {"ok": bool(ok), "chart_ok": (plan.get("chart") or "auto") in charts}


# ---------------------------------------------------------------- Mode Réflexion (birds/harness/reflexion.py)
# The level decision of « Auto »: (message, levels accepted). Held out of the training templates of
# build_tools_mix.py (checked by tests/test_tools_mix.py), measured by scripts/reflexion_eval.py --levels.
REFLEXION_LEVELS = [
    ("salut, ça va ?", {"colibri"}),
    ("merci beaucoup, c'est parfait", {"colibri"}),
    ("quelle est la capitale de l'Australie ?", {"colibri", "hirondelle"}),
    ("écris un mail à mon équipe pour annoncer la fermeture du bureau vendredi", {"hirondelle"}),
    ("résume ce texte en trois points : le télétravail progresse dans les PME françaises depuis 2020", {"hirondelle"}),
    ("donne-moi cinq idées de titres pour un article sur la sobriété numérique", {"hirondelle"}),
    ("une remise de 12 % sur 1 450 € HT puis la TVA à 20 %, ça donne combien TTC ?", {"faucon", "chouette"}),
    ("écris une requête SQL qui compte les commandes par client en 2025", {"faucon"}),
    ("analyse les forces et faiblesses d'une stratégie d'abonnement pour un logiciel de paie", {"chouette"}),
    ("thanks, that's all", {"colibri"}),
    ("draft a short reply to accept the invitation for Tuesday", {"hirondelle"}),
    ("if a team of 7 bills 520 dollars a day each, what is the cost of a 3-week project?", {"faucon", "chouette"}),
]

# The fixed set of calculations and comparisons (before / after, scripts/reflexion_eval.py --calc): the figures a
# right answer must contain (spaces and the decimal mark ignored; any one of the forms listed per figure), and, for a
# comparison, the wrong winner it must not name ({"not": pattern}: « Février a le meilleur taux » fails).
REFLEXION_CALC = [
    ("calc_sub", "Un abonnement coûte 14,90 € par mois, ou 149 € par an. Sur deux ans, lequel est le moins cher et "
     "de combien ?", [["59,60", "59,6"], ["annuel", "an"],
     {"not": r"mensuel\w*\s+(?:est|revient)\s+(?:donc\s+)?(?:le\s+)?moins cher"}]),
    ("calc_vat", "Un produit coûte 80 € HT. On applique une remise de 15 %, puis la TVA à 20 %. Quel est le prix "
     "TTC ?", [["81,60", "81,6"]]),
    ("cmp_quotes", "Trois devis HT : 1 250 €, 980 € et 1 410 €. Lequel est le moins cher, et quel est l'écart avec "
     "le plus cher ?", [["980"], ["430"]]),
    ("calc_fuel", "Une voiture consomme 6,5 L aux 100 km et l'essence coûte 1,85 € le litre. Combien coûte un trajet "
     "de 420 km ?", [["50,51", "50,50", "50,5"]]),
    ("calc_salary", "Salaire brut de 2 800 € par mois, cotisations salariales de 22 %. Donne :\n1. le net mensuel\n"
     "2. le net annuel sur 12 mois", [["2184", "2 184"], ["26208", "26 208"]]),
    ("cmp_offers", "Offre A : 1 200 € par an plus 15 € par utilisateur et par mois. Offre B : 40 € par utilisateur "
     "et par mois. Pour 5 utilisateurs sur un an, laquelle est la moins chère et de combien ?",
     [["2100", "2 100"], ["2400", "2 400"], ["300"], {"not": r"offre b\W{0,3}(?:est|revient)\s+(?:la\s+)?moins ch"}]),
    ("calc_compound", "10 000 € placés à 3 % par an, intérêts composés : combien après 3 ans ?",
     [["10927,27", "10 927,27", "10927,3", "10 927,3"]]),
    ("cmp_rates", "Janvier : 2 300 visites et 69 ventes. Février : 3 100 visites et 81 ventes. Quel mois a le "
     "meilleur taux de conversion, et quels sont les deux taux ?", [["janvier"], ["3 %", "3%", "3,0", "3,00"],
                                                                   ["2,61", "2,6 "],
     {"not": r"f[ée]vrier\W{0,3}(?:a|affiche|pr[ée]sente)\s+(?:donc\s+)?le\s+meilleur|meilleur taux.{0,25}f[ée]vrier"}]),
]  # fmt: skip


def calc_ok(answer: str, wants: list[list[str]]) -> tuple[bool, int]:
    """(every figure present, how many). Thin spaces and non-breaking spaces read as spaces; « 2 184 » = « 2184 »."""
    a = " ".join((answer or "").replace(" ", " ").replace("\xa0", " ").lower().split())
    squeezed = a.replace(" ", "")
    hit = 0
    for forms in wants:
        if isinstance(forms, dict):
            hit += not re.search(forms["not"], a, re.I)
        else:
            hit += any(w.lower() in a or w.lower().replace(" ", "") in squeezed for w in forms)
    return hit == len(wants), hit


# ---------------------------------------------------------------- next steps (birds/harness/nextsteps.py)
# Fixed answers and what Bird's next steps must do with them: (id, lang, request, answer, expectation).
# ``none``: no suggestion at all; ``words``: every suggestion names one of these (the options of Bird's question,
# rephrased as the user's answer); ``not``: no suggestion matches this pattern (Bird's voice, an impossible action).
# Held out of the training templates of build_tools_mix.py (tests/test_tools_mix.py), measured live by
# scripts/followups_eval.py --cases and offline by tests/test_nextsteps.py (the validation part).
NEXTSTEPS_CASES = [
    ("slide_ask", "fr", "fais une diapo sur notre offre de conseil",
     "Voici la diapositive « Notre offre de conseil ». Souhaitez-vous que je vous aide à intégrer des images "
     "spécifiques ou à structurer la diapositive visuellement ?",
     {"words": ["image", "structur", "bloc", "visuel"], "not": r"(?i)^(?:vous aide|à structurer|oui)"}),
    ("format_ask", "fr", "j'ai besoin de présenter le budget 2027 au comité",
     "Je peux vous préparer ce support. Souhaitez-vous un mail, une note ou un tableau ?",
     {"words": ["mail", "note", "tableau"], "not": r"(?i)^(?:un mail|une note|un tableau)$"}),
    ("length_ask", "fr", "explique-moi la TVA intracommunautaire",
     "La TVA intracommunautaire s'applique aux échanges entre entreprises de l'UE… Voulez-vous la version "
     "courte ou la version détaillée avec un exemple chiffré ?",
     {"words": ["court", "détaill", "exemple"]}),
    ("hello", "fr", "bonjour", "Bonjour ! Comment puis-je vous aider aujourd'hui ?", {"none": True}),
    ("thanks", "fr", "merci beaucoup", "Avec plaisir ! N'hésitez pas si vous avez besoin d'autre chose.", {"none": True}),
    ("info_needed", "en", "draft an email to a client to postpone our meeting",
     "I need the client's name and the new date before I can draft it. Could you share them?",
     {"not": r"(?i)^(?:provide|share|give)"}),
    ("mail_done", "fr", "rédige un mail pour relancer la facture 2024-118",
     "Objet : Relance – facture 2024-118. Bonjour, sauf erreur de notre part, la facture 2024-118 reste impayée…",
     {"not": r"(?i)\b(?:envoie|envoyer|valide)\b"}),
    ("offsite_en", "en", "help me plan a team offsite",
     "Here is a one-day outline: morning workshop, lunch, afternoon hike. Would you like a budget or a "
     "sample invitation?",
     {"words": ["budget", "invitation"]}),
    # the review of the 28/11 live set: user facts, invented origins or assumptions, routes, generic steps
    ("facts_asked", "fr", "aide-moi à préparer mon entretien de fin d'année",
     "Bien sûr. Pour commencer, pouvez-vous me donner vos principales réalisations de l'année et vos objectifs ?",
     {"not": r"(?i)\b(?:liste|donne|indique|rappelle)[- ]?(?:moi )?mes (?:r[ée]alisations|accomplissements|objectifs)"}),
    ("map_museum", "fr", "où se trouve le musée des Confluences ?",
     "Le musée des Confluences est au 86 quai Perrache, 69002 Lyon. Le lien « Itinéraire » de la carte donne "
     "l'accès.",
     {"not": r"(?i)itin[ée]raire|trajet|m[ée]tro|bus|tram|tarif|prix|avis|depuis la gare|traduis"}),
    ("weather_city", "fr", "quel temps à Toulouse demain ?",
     "Demain à Toulouse : ensoleillé, 6 à 15 °C, pas de pluie, vent faible.",
     {"not": r"(?i)traduis|anglais|carte|semaine derni[èe]re|hier|raccourcis|r[ée]sum"}),
    ("sales_trend", "fr", "nos ventes : T1 80, T2 95, T3 90. Quelle tendance ?",
     "Les ventes montent de T1 à T2 (+18,8 %) puis reculent légèrement au T3 (-5,3 %).",
     {"not": r"(?i)en supposant|hypoth[èe]se|si les ventes (?:baissent|montent)|\d+ ?% de (?:baisse|hausse)"}),
]  # fmt: skip


def nextsteps_ok(items: list[dict], expect: dict) -> bool:
    """Is a list of suggestions what ``expect`` (a NEXTSTEPS_CASES expectation) asks for?"""
    if expect.get("none"):
        return not items
    if expect.get("not") and any(re.search(expect["not"], f"{x['label']} {x['prompt']}") for x in items):
        return False
    words = expect.get("words")
    if words:
        return bool(items) and all(any(w in (x["label"] + " " + x["prompt"]).lower() for w in words) for x in items)
    return True
