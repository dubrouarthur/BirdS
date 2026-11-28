"""Demo scenarios of the small modules (no model): the REAL code on recorded inputs, labelled as a demo.

* Deep research: ``birds.harness.research.Research`` itself, its checks, its widgets and its team board, on three
  fictional example pages (example.org, example.net, example.com) and a scripted model that makes the mistakes a small
  model makes (a paraphrased quote, a figure not in its quote, an invented figure in the report). What reaches the
  answer is what the real checks kept.
* Calculator: ``birds.harness.calc`` on the user's own words (exact results; the sentence is written by code).
* Timeline, comparison matrix, checklist: ``birds.harness.modules.from_words`` on the user's own message.
"""

from __future__ import annotations

import json
import time

from birds.harness import calc, modules
from birds.harness.agent import Hooks, Step
from birds.harness.crew import decide

_PAGES = {
    "https://example.org/hydrogene-filiere": (
        "La filière hydrogène en région (exemple)",
        "Dans ce scénario fictif, la Région Exemple a lancé en 2023 un plan de 40 millions d'euros pour l'hydrogène "
        "renouvelable, piloté par l'agence Énergie Exemple.\n"
        "La société HydroNord a signé en 2022 un partenariat avec le groupe Volta Industrie pour une usine "
        "d'électrolyse sur le port.\n"
        "La start-up Lysa produit de l'hydrogène à partir d'éolien depuis 2021, selon ce document d'exemple.",
    ),
    "https://example.net/electrolyseurs": (
        "Électrolyseurs : le marché (exemple)",
        "Le fabricant ÉlectroLys a ouvert en 2024 un atelier de 120 salariés à Ville-Exemple, d'après cette page "
        "fictive.\n"
        "Le groupe Volta Industrie détient une participation dans la société Mobilis H2 depuis 2019, selon son "
        "rapport annuel fictif.\n"
        "La filière de l'exemple vise 2 gigawatts d'électrolyse installés en 2030, un objectif jugé ambitieux.",
    ),
    "https://example.com/mobilite-h2": (
        "Mobilité hydrogène (exemple)",
        "Mobilis H2 exploite à Ville-Exemple une flotte de 80 taxis à hydrogène en 2025, la plus grande de la "
        "région fictive.\n"
        "HydroNord fournit l'hydrogène des stations de Mobilis H2 depuis 2023, selon ce texte d'exemple.\n"
        "Le coût de l'hydrogène renouvelable reste deux à trois fois supérieur à celui de l'hydrogène fossile.",
    ),
    "https://example.edu/budget-region": (
        "Budget régional de l'hydrogène (exemple)",
        "Selon ce budget fictif, la Région Exemple a consacré en 2023 un plan de 45 millions d'euros à l'hydrogène "
        "renouvelable, un montant revu à la hausse.\n"
        "Le plan régional de l'hydrogène renouvelable est piloté par l'agence Énergie Exemple depuis 2023.\n"
        "Les stations de Mobilis H2 sont approvisionnées par HydroNord depuis 2023, d'après ce document d'exemple.",
    ),
}
_N = {u: i for i, u in enumerate(_PAGES, 1)}


def _claims(n: int) -> list[dict]:
    c = {
        1: [
            {"source": 1, "claim": "La Région Exemple a lancé en 2023 un plan de 40 millions d'euros pour l'hydrogène "
             "renouvelable", "quote": "la Région Exemple a lancé en 2023 un plan de 40 millions d'euros pour "
             "l'hydrogène renouvelable, piloté par l'agence Énergie Exemple", "date": "2023",
             "entities": [{"name": "Région Exemple", "type": "lieu"}, {"name": "Énergie Exemple", "type": "organisation"}],
             "relations": [{"from": "Énergie Exemple", "to": "Région Exemple", "label": "pilote le plan de"}]},
            {"source": 1, "claim": "HydroNord a signé en 2022 un partenariat avec Volta Industrie",
             "quote": "La société HydroNord a signé en 2022 un partenariat avec le groupe Volta Industrie", "date": "2022",
             "entities": [{"name": "HydroNord", "type": "organisation"}, {"name": "Volta Industrie", "type": "organisation"}],
             "relations": [{"from": "HydroNord", "to": "Volta Industrie", "label": "partenariat"}]},
            # a paraphrase that is not in the page (a small model's habit): the check drops it
            {"source": 1, "claim": "Lysa est le leader national", "quote": "Lysa est le leader national de l'hydrogène",
             "entities": [{"name": "Lysa", "type": "organisation"}]},
        ],
        2: [
            {"source": 2, "claim": "ÉlectroLys a ouvert en 2024 un atelier de 120 salariés à Ville-Exemple",
             "quote": "Le fabricant ÉlectroLys a ouvert en 2024 un atelier de 120 salariés à Ville-Exemple",
             "date": "2024", "entities": [{"name": "ÉlectroLys", "type": "organisation"},
                                          {"name": "Ville-Exemple", "type": "lieu"}],
             "relations": [{"from": "ÉlectroLys", "to": "Ville-Exemple", "label": "atelier à"}]},
            {"source": 2, "claim": "Volta Industrie détient une participation dans Mobilis H2 depuis 2019",
             "quote": "Le groupe Volta Industrie détient une participation dans la société Mobilis H2 depuis 2019",
             "date": "2019", "entities": [{"name": "Volta Industrie", "type": "organisation"},
                                          {"name": "Mobilis H2", "type": "organisation"}],
             "relations": [{"from": "Volta Industrie", "to": "Mobilis H2", "label": "actionnaire de"}]},
            # a figure that is not in its quote: dropped
            {"source": 2, "claim": "La filière vise 5 gigawatts en 2030",
             "quote": "La filière de l'exemple vise 2 gigawatts d'électrolyse installés en 2030", "date": "2030"},
        ],
        3: [
            {"source": 3, "claim": "Mobilis H2 exploite une flotte de 80 taxis à hydrogène à Ville-Exemple en 2025",
             "quote": "Mobilis H2 exploite à Ville-Exemple une flotte de 80 taxis à hydrogène en 2025", "date": "2025",
             "entities": [{"name": "Mobilis H2", "type": "organisation"}, {"name": "Ville-Exemple", "type": "lieu"}],
             "relations": [{"from": "Mobilis H2", "to": "Ville-Exemple", "label": "taxis à"}]},
            {"source": 3, "claim": "HydroNord fournit l'hydrogène des stations de Mobilis H2 depuis 2023",
             "quote": "HydroNord fournit l'hydrogène des stations de Mobilis H2 depuis 2023", "date": "2023",
             "entities": [{"name": "HydroNord", "type": "organisation"}, {"name": "Mobilis H2", "type": "organisation"}],
             "relations": [{"from": "HydroNord", "to": "Mobilis H2", "label": "fournit"}]},
        ],
        4: [
            # another site, another amount for the same plan the same year: a contradiction, shown as such
            {"source": 4, "claim": "La Région Exemple a consacré en 2023 un plan de 45 millions d'euros à l'hydrogène "
             "renouvelable", "quote": "la Région Exemple a consacré en 2023 un plan de 45 millions d'euros à "
             "l'hydrogène renouvelable", "date": "2023",
             "entities": [{"name": "Région Exemple", "type": "lieu"}]},
            # the same fact as page 3 on another site: corroborated
            {"source": 4, "claim": "HydroNord approvisionne les stations de Mobilis H2 depuis 2023",
             "quote": "Les stations de Mobilis H2 sont approvisionnées par HydroNord depuis 2023", "date": "2023",
             "entities": [{"name": "HydroNord", "type": "organisation"}, {"name": "Mobilis H2", "type": "organisation"}],
             "relations": [{"from": "HydroNord", "to": "Mobilis H2", "label": "fournit"}]},
        ],
    }  # fmt: skip
    return c[n]


_REPORT = {
    "title": "La filière hydrogène de la Région Exemple",
    "summary": "Dans ce scénario fictif, la Région Exemple finance l'hydrogène renouvelable par un plan de 40 millions "
    "d'euros [1]. Un petit réseau d'industriels s'organise autour de HydroNord, Volta Industrie et Mobilis H2 [1].",
    "sections": [
        {"heading": "Financements publics", "text": "Le plan régional lancé en 2023 est doté de 40 millions d'euros "
         "[2]. Il doit créer 3 000 emplois [1]. L'agence Énergie Exemple pilote ce plan [1]."},
        {"heading": "Industriels et liens", "text": "HydroNord a signé un partenariat avec Volta Industrie en 2022 "
         "[1]. Volta Industrie détient une participation dans Mobilis H2 [2], que HydroNord fournit en hydrogène "
         "depuis 2023 [3]. ÉlectroLys a ouvert un atelier de 120 salariés en 2024 [2]."},
        {"heading": "Usages", "text": "Mobilis H2 exploite une flotte de 80 taxis à hydrogène en 2025 [3]. Le coût "
         "de l'hydrogène renouvelable reste deux à trois fois supérieur à celui de l'hydrogène fossile [3]."},
    ],
    "comparison": {"columns": ["Acteur", "Activité", "Depuis"],
                   "rows": [["HydroNord", "fournit l'hydrogène des stations de Mobilis H2", "2023"],
                            ["ÉlectroLys", "atelier de 120 salariés", "2024"],
                            ["Mobilis H2", "flotte de 80 taxis à hydrogène", "2025"]]},
}  # fmt: skip


class _Tok:
    def apply_chat_template(self, messages, tools=None, enable_thinking=False, tokenize=False,
                            add_generation_prompt=False):  # fmt: skip
        return json.dumps({"tools": [t["function"]["name"] for t in tools or []], "messages": messages},
                          ensure_ascii=False)  # fmt: skip


def _call(name: str, **args) -> str:
    params = "".join(f"<parameter={k}>\n{v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}\n</parameter>\n"
                     for k, v in args.items())  # fmt: skip
    return f"<tool_call>\n<function={name}>\n{params}</function>\n</tool_call>"


class _Scripted:
    """The scripted model of the demo: one answer per specialist, short pauses (scaled by the demo's delay)."""

    def __init__(self, pause):
        self.pause = pause

    def generate(self, prompt, max_tokens, stop, *, on_token=None, **_):
        p = json.loads(prompt)
        tools, user = p["tools"], p["messages"][-1]["content"]
        if tools == ["plan_search"]:  # Mode Agent's search planning, as in production
            out = _call("plan_search", sub_questions=[
                {"question": "Quels financements publics soutiennent la filière ?",
                 "query": "financement hydrogène Région Exemple"},
                {"question": "Quels industriels, et comment sont-ils liés ?", "query": "industriels hydrogène filière"},
                {"question": "Quels usages concrets aujourd'hui ?", "query": "mobilité hydrogène taxis filière"}])  # fmt: skip
            self.pause(0.9)
        elif tools == ["record_claims"]:
            mine = [n for n in (1, 2, 3, 4) if f"[{n}] " in user]
            out = _call("record_claims", claims=[c for n in mine for c in _claims(n)])
            self.pause(0.8 + 0.9 * min(mine or [1]))  # the readers finish one after the other: the graph grows
        elif tools == ["write_report"]:
            out = _call("write_report", **_REPORT)
            self.pause(2.0)
        else:
            out = "…"
        if on_token:
            on_token(out[:40])
        return {"text": out, "prompt_tokens": len(prompt) // 4, "completion_tokens": len(out) // 4, "seconds": 0.5,
                "busy_seconds": 0.5}  # fmt: skip


def research_match(text: str, request) -> bool:
    if getattr(request, "agent", "auto") == "off" or request.images or request.attachments:
        return False
    return decide(text, mode=getattr(request, "agent", "auto") or "auto").recipe == "deep_research"


def demo_research(run) -> None:
    """The real deep research recipe on the recorded example pages: events, checks and widgets as in production."""
    from birds.harness import Agent, Config
    from birds.harness.research import Research
    from birds.web.backends import step_event
    from birds.web.crew_web import on_agent

    t, lang, ctx = run.t, run.lang, run.ctx
    words = next((m["content"] for m in reversed(run.req.messages) if m["role"] == "user"), "")
    base = run.steps
    emit = on_agent(ctx, lang, lambda: base, lambda i, s, lg: step_event(
        i, s.tool, s.arguments, "error" if s.error else "done", t("Page lue (exemple)", "Page read (example)")
        if s.tool == "read_page" else t("3 résultats (exemple)", "3 results (example)"), s.seconds))  # fmt: skip

    def on(ev):
        if ev.get("type") == "agent_start":
            ev = {**ev, "demo": t("scénario de démonstration", "demo scenario")}
        emit(ev)

    import tempfile
    from pathlib import Path

    agent = Agent(_Scripted(run.pause), _Tok(), Config(workspace=Path(tempfile.gettempdir()), audit_file=None),
                  hooks=Hooks(on_agent=on, on_token=lambda _t: None))  # fmt: skip

    class DemoResearch(Research):
        def _tool(self, lane, name, args, *, forced=None, index=None):  # the recorded pages instead of the network
            if index is None:
                index = self._announce(lane, name, args)
            run.pause(0.5 if name == "read_page" else 0.7)
            if name == "web_search":  # each query finds the example pages in its own order
                items = list(_PAGES.items())
                k = sum(map(ord, str(args.get("query")))) % len(items)
                items = items[k:] + items[:k]
                text = "Résultats (exemple) :\n" + "\n".join(f"{i}. {ti}\n   {u}" for i, (u, (ti, _)) in
                                                                enumerate(items, 1))  # fmt: skip
            else:
                u = str(args.get("url"))
                title, body = _PAGES.get(u, ("", ""))
                text = f"URL: {u}\nTitle: {title}\n\n{body}"
                run.bytes += len(body)
            step = Step(generation=0, tool=name, arguments=args, result=text[:200], seconds=0.4, chars=len(text))
            with self.lock:
                self.steps.append((index, step))
            self._emit({"kind": "tool_end", "index": index, "step": step, "agent": lane})
            return index, step, text, None

    d = decide(words, mode=getattr(run.req, "agent", "auto") or "auto")
    team = DemoResearch(agent, d, lang=lang)
    out = team.run(words, words)
    run.steps += len(out.steps)
    head = t("**Scénario de démonstration** (aucun modèle ne tourne ici ; pages et acteurs fictifs) : voici ce que "
             "fait la recherche approfondie, vérifications comprises.\n\n",
             "**Demo scenario** (no model runs here; fictional pages and players): this is what deep research does, "
             "checks included.\n\n")  # fmt: skip
    sources = [{"n": i, "title": _PAGES[u][0], "url": u} for i, u in enumerate(out.sources, 1)]
    run.finish(head + out.answer, sources=sources, widgets=out.widgets)


def calc_match(text: str, request) -> bool:
    return not request.attachments and not request.images and calc.detect(text) is not None


def demo_calc(run) -> None:
    words = next((m["content"] for m in reversed(run.req.messages) if m["role"] == "user"), "")
    w, _ = calc.facts_for(words, run.lang)
    main = next((r for r in w["rows"] if r.get("main")), w["rows"][0])
    run.finish(run.t(f"**{main['label'].rstrip(' =')}** : {main['value']}. Le détail est dans la fiche ci-dessous ; "
                     "changez une valeur pour recalculer.",
                     f"**{main['label'].rstrip(' =')}**: {main['value']}. The detail is in the card below; change a "
                     "value to recompute."), widgets=[w])  # fmt: skip


def modules_match(text: str, request) -> list[dict]:
    if request.images:
        return []
    return modules.cards(text, "en" if request.lang == "en" else "fr")  # the parsers' guess: the demo has no router


def demo_modules(run, found: list[dict]) -> None:
    kinds = {w["type"] for w in found}
    names = {"timeline": run.t("la frise", "the timeline"), "matrix": run.t("le tableau comparatif", "the comparison"),
             "checklist": run.t("la liste de tâches", "the task list"),
             "proscons": run.t("les avantages et inconvénients", "the pros and cons"),
             "figures": run.t("les chiffres clés", "the key figures"), "glossary": run.t("le glossaire", "the glossary")}  # fmt: skip
    what = ", ".join(names[k] for k in names if k in kinds)
    time.sleep(0)
    run.finish(run.t(f"**Scénario de démonstration** : voici {what}, construit(e) à partir de vos données "
                     "uniquement.", f"**Demo scenario**: here is {what}, built from your data only."), widgets=found)  # fmt: skip
