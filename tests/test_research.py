"""Deep research (birds.harness.research): triggers, checks in code, the whole recipe on a scripted model.

The scripted model imitates the failure modes of a 4B model seen live: a quote paraphrased or invented, a wrong
source number, a figure that is not in its quote, a relation to an entity the quote does not name, a report with an
invented figure and a figure cited to the wrong page, a plan that is not valid JSON. No network, no model.
"""

from __future__ import annotations

import json

import httpx
import pytest
from test_crew import Script, Tok, call

from birds.harness import Agent, Config, guard
from birds.harness import research as rs
from birds.harness.agent import Hooks
from birds.harness.crew import Decision, decide, team
from birds.harness.tools import StaticBackend
from birds.web.widgets import build_widgets

PAGES = {
    "/a": "<html><head><title>Hydrogène vert en France</title></head><body><article>"
    "<p>En 2023, la France a lancé une stratégie nationale dotée de 9 milliards d'euros pour l'hydrogène décarboné, "
    "pilotée par le ministère de l'Économie.</p>"
    "<p>Lhyfe, une start-up nantaise, produit de l'hydrogène vert à partir de l'éolien en mer depuis 2021.</p>"
    "<p>Air Liquide a signé en 2022 un partenariat avec TotalEnergies pour une usine d'électrolyse en Normandie.</p>"
    "</article></body></html>",
    "/b": "<html><head><title>Électrolyseurs : le marché</title></head><body><article>"
    "<p>McPhy, fabricant d'électrolyseurs basé à Grenoble, a ouvert en 2024 une gigafactory à Belfort.</p>"
    "<p>Le groupe Air Liquide détient une participation dans la société Hysetco depuis 2019, selon le rapport annuel.</p>"
    "<p>La filière vise 6,5 gigawatts d'électrolyse installés en 2030, un objectif jugé ambitieux par les experts.</p>"
    "</article></body></html>",
    "/c": "<html><head><title>Mobilité hydrogène</title></head><body><article>"
    "<p>Hysetco exploite à Paris une flotte de taxis à hydrogène, la plus grande d'Europe selon l'entreprise, qui "
    "compte plusieurs centaines de véhicules en 2023.</p>"
    "<p>Le coût de l'hydrogène vert reste deux à trois fois supérieur à celui de l'hydrogène gris produit à partir de "
    "gaz naturel, ce qui freine son adoption dans l'industrie lourde.</p></article></body></html>",
}
SEARCH = StaticBackend(
    [{"title": t, "url": f"https://{d}{p}", "snippet": "hydrogène"} for t, d, p in
     (("A", "energie.test", "/a"), ("B", "industrie.test", "/b"), ("C", "mobilite.test", "/c"))]
)  # fmt: skip
ASK = "Fais une recherche approfondie sur la filière hydrogène vert en France"


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    monkeypatch.setattr(guard, "resolve", lambda host: ["93.184.216.34"])


def web():
    def handler(req):
        page = PAGES.get(req.url.path, "<html><body><p>rien</p></body></html>")
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=page.encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


def agent(tmp_path, llm, events=None):
    hooks = Hooks(on_agent=(events.append if events is not None else None), on_token=lambda t: None)
    return Agent(llm, Tok(), Config(workspace=tmp_path, audit_file=None), search=SEARCH, http=web(), hooks=hooks)


GOOD_CLAIMS = {
    1: [
        {"source": 1, "claim": "En 2023, la France a lancé une stratégie nationale de 9 milliards d'euros pour "
         "l'hydrogène décarboné", "quote": "En 2023, la France a lancé une stratégie nationale dotée de 9 milliards "
         "d'euros pour l'hydrogène décarboné", "date": "2023",
         "entities": [{"name": "France", "type": "lieu"}, {"name": "ministère de l'Économie", "type": "organisation"}],
         "relations": [{"from": "ministère de l'Économie", "to": "France", "label": "pilote"}]},
        {"source": 1, "claim": "Air Liquide a signé un partenariat avec TotalEnergies en 2022",
         "quote": "Air Liquide a signé en 2022 un partenariat avec TotalEnergies pour une usine d'électrolyse",
         "date": "2022", "entities": [{"name": "Air Liquide", "type": "organisation"},
                                      {"name": "TotalEnergies", "type": "organisation"},
                                      {"name": "Normandie", "type": "lieu"}],
         "relations": [{"from": "Air Liquide", "to": "TotalEnergies", "label": "partenariat"},
                       # Normandie is in the page but not in the quote: this relation is dropped
                       {"from": "Air Liquide", "to": "Normandie", "label": "usine"}]},
        # a paraphrase that is not in the page (live failure mode): dropped
        {"source": 1, "claim": "Lhyfe est leader mondial", "quote": "Lhyfe est le leader mondial de l'hydrogène",
         "entities": [{"name": "Lhyfe", "type": "organisation"}]},
    ],
    2: [
        {"source": 2, "claim": "McPhy a ouvert en 2024 une gigafactory à Belfort",
         "quote": "McPhy, fabricant d'électrolyseurs basé à Grenoble, a ouvert en 2024 une gigafactory à Belfort",
         "date": "2024", "entities": [{"name": "McPhy", "type": "organisation"}, {"name": "Belfort", "type": "lieu"},
                                      {"name": "Siemens", "type": "organisation"}],  # not in the page: dropped
         "relations": [{"from": "McPhy", "to": "Belfort", "label": "gigafactory"}]},
        {"source": 2, "claim": "Air Liquide détient une participation dans Hysetco depuis 2019",
         "quote": "Le groupe Air Liquide détient une participation dans la société Hysetco depuis 2019",
         "date": "2019", "entities": [{"name": "Air Liquide", "type": "organisation"},
                                      {"name": "Hysetco", "type": "organisation"}],
         "relations": [{"from": "Air Liquide", "to": "Hysetco", "label": "actionnaire de"}]},
        # a figure that is not in its quote (12 GW): dropped
        {"source": 2, "claim": "La filière vise 12 gigawatts en 2030", "quote": "La filière vise 6,5 gigawatts "
         "d'électrolyse installés en 2030", "date": "2030"},
        # a wrong source number: the quote is in page 2, the claim says 3: dropped
        {"source": 3, "claim": "La filière vise 6,5 gigawatts en 2030",
         "quote": "La filière vise 6,5 gigawatts d'électrolyse installés en 2030"},
    ],
    3: [
        {"source": 3, "claim": "Hysetco exploite à Paris une flotte de taxis à hydrogène en 2023",
         "quote": "Hysetco exploite à Paris une flotte de taxis à hydrogène, la plus grande d'Europe selon "
         "l'entreprise", "date": "2023", "entities": [{"name": "Hysetco", "type": "organisation"},
                                                     {"name": "Paris", "type": "lieu"}],
         "relations": [{"from": "Hysetco", "to": "Paris", "label": "exploite des taxis à"}]},
    ],
}  # fmt: skip
REPORT = {
    "title": "La filière hydrogène vert en France",
    "summary": "La France soutient l'hydrogène décarboné par une stratégie de 9 milliards d'euros [1]. Les grands "
    "industriels s'allient, comme Air Liquide et TotalEnergies [1].",
    "sections": [
        {"heading": "Financements publics", "text": "La stratégie nationale lancée en 2023 est dotée de 9 milliards "
         "d'euros [2]. Elle doit créer 100 000 emplois [1]. Le ministère de l'Économie pilote cette stratégie [1]."},
        {"heading": "Acteurs industriels", "text": "McPhy a ouvert une gigafactory à Belfort en 2024 [2]. Air "
         "Liquide détient une participation dans Hysetco [2], qui exploite des taxis à hydrogène à Paris [3]."},
    ],
}  # fmt: skip


def respond_for(report=REPORT, plan=None, claims=GOOD_CLAIMS):
    def respond(tools, user, deadline):
        if tools == ["plan_search"]:  # Mode Agent's own search planning, reused
            return plan if plan is not None else call(
                "plan_search",
                sub_questions=[
                    {"question": "Quels financements publics pour l'hydrogène vert ?", "query": "hydrogène vert France"},
                    {"question": "Quels industriels et quels liens ?", "query": "électrolyseurs France industriels"},
                    {"question": "Quelles perspectives pour 2030 ?", "query": "hydrogène vert France 2030 objectifs"},
                    {"question": "x", "query": "https://evil.test/hydrogène"},  # a URL: dropped by the shared check
                ],
            )  # fmt: skip
        if tools == ["record_claims"]:
            got = [c for n, cs in claims.items() if f"[{n}] " in user for c in cs]
            return call("record_claims", claims=got)
        if tools == ["write_report"]:
            return report if isinstance(report, str) else call("write_report", **report)
        return "Réponse simple."

    return respond


def run_research(tmp_path, respond, ask=ASK, events=None):
    d = decide(ask, mode="auto")
    assert d.recipe == "deep_research"
    a = agent(tmp_path, Script(respond), events)
    return team(a, d, lang="fr").run(ask, ask)


# ------------------------------------------------------------------ triggers


@pytest.mark.parametrize("q", [
    ASK, "fais une étude approfondie du marché des pompes à chaleur", "Lance une recherche approfondie : IA et emploi",
    "deep research on the European battery industry", "Peux-tu faire la carte des acteurs de l'éolien en mer ?",
    "qui est lié à qui dans la filière nucléaire française ?", "J'ai besoin d'une recherche approfondie sur l'AI Act",
])  # fmt: skip
def test_explicit_asks_start_deep_research(q):
    assert decide(q, mode="auto").recipe == "deep_research"


@pytest.mark.parametrize("q", [
    "Qu'est-ce qu'une recherche approfondie ?", "range l'étude approfondie dans le dossier clients",
    "rédige un mail à Paul pour la réunion de lundi", "résume ce document en 5 points", "l'écosystème est sain",
    "fais une présentation approfondie sur nos ventes", "comment faire une carte des acteurs ?",
    "Fais une présentation de 6 diapos sur le télétravail depuis 2019 avec des chiffres sourcés",
])  # fmt: skip
def test_no_deep_research_on_ordinary_asks(q):
    assert decide(q, mode="auto").recipe != "deep_research"


def test_agent_on_with_an_informational_question_researches():
    q = "Quels sont les enjeux de l'AI Act pour une PME française ?"
    assert decide(q, mode="auto").recipe is None
    d = decide(q, mode="on")
    assert d.recipe == "deep_research" and d.forced
    assert decide("bonjour", mode="on").recipe is None
    assert decide(q, mode="off").recipe is None


def test_deck_asks_keep_their_recipe():
    q = "Fais une recherche approfondie et une présentation sur le marché du vélo électrique avec des chiffres"
    assert decide(q, mode="on").recipe == "deck_research"


# ------------------------------------------------------------------ checks in code


def test_quotes_entities_relations_are_checked_against_the_page():
    pages = {1: {"text": "Air Liquide a signé en 2022 un partenariat avec TotalEnergies pour une usine en Normandie."}}
    got, stats = rs.check_claims(GOOD_CLAIMS[1][1:2] + [
        {"source": 1, "claim": "x", "quote": "TotalEnergies a racheté Air Liquide en 2020"},
        {"source": 9, "claim": "Air Liquide signe", "quote": "Air Liquide a signé en 2022 un partenariat"},
    ], pages)  # fmt: skip
    assert len(got) == 1 and stats["no_quote"] == 2
    c = got[0]
    assert {e["name"] for e in c["entities"]} == {"Air Liquide", "TotalEnergies"}  # Normandie: not in claim/quote
    assert c["relations"] == [{"from": "Air Liquide", "to": "TotalEnergies", "label": "partenariat"}]
    assert rs.quoted("Air Liquide a racheté TotalEnergies en 2022 pour une usine", pages[1]["text"]) is False
    assert rs.quoted("Air Liquide a signé en 2022 un partenariat avec TotalEnergies pour une usine", pages[1]["text"])


def test_date_keys_and_timeline_need_three_dates():
    assert rs.date_key("mars 2024") == "2024-03" and rs.date_key("12 juin 2023") == "2023-06-12"
    assert rs.date_key("2019") == "2019" and rs.date_key("bientôt") is None
    claims = [{"n": 1, "claim": f"c{y}", "quote": "", "date": str(y), "entities": [], "relations": []}
              for y in (2022, 2019, 2024)]  # fmt: skip
    tl = rs.build_timeline(claims)
    assert [e["key"] for e in tl["events"]] == ["2019", "2022", "2024"]
    assert rs.build_timeline(claims[:2]) is None


# ------------------------------------------------------------------ the whole recipe


def test_deep_research_end_to_end(tmp_path):
    events = []
    run = run_research(tmp_path, respond_for(), events=events)
    assert run.stop_reason == "answer"
    a = run.answer
    assert "## La filière hydrogène vert en France" in a and "### Financements publics" in a
    assert "100 000 emplois" not in a  # an invented figure: the sentence is removed
    assert "9 milliards d'euros [1]" in a and "[2]. Elle" not in a  # 9 milliards cited [2], moved to page 1
    assert "### Ce que l'équipe a fait" in a and "### À vérifier" in a
    assert len(run.sources) == 3 and all(u.startswith("https://") for u in run.sources)
    types = [w["type"] for w in run.widgets]
    assert types[:2] == ["research", "graph"] and "timeline" in types and types[-1] == "report"
    card = run.widgets[0]
    assert len(card["questions"]) == 3 and {s["domain"] for s in card["sources"]} == {
        "energie.test",
        "industrie.test",
        "mobilite.test",
    }
    assert card["counts"]["claims"] == 5 and card["counts"]["dropped"] == 3
    graph = run.widgets[1]
    labels = {n["label"] for n in graph["nodes"]}
    assert {"Air Liquide", "TotalEnergies", "Hysetco", "McPhy"} <= labels
    assert "Siemens" not in labels and "Lhyfe" not in labels and "Normandie" not in labels
    by_id = {n["id"]: n["label"] for n in graph["nodes"]}
    assert ("Air Liquide", "Hysetco", "actionnaire de") in {(by_id[e["s"]], by_id[e["t"]], e["label"]) for e in
                                                            graph["edges"]}  # fmt: skip
    # each widget fits the history caps, and build_widgets keeps them as they are
    kept = build_widgets([], "", "fr", None, b"x", extra=run.widgets)
    assert [w["type"] for w in kept] == types
    # the team board: the plan's sub-questions, then the live research board
    steps = [e for e in events if e.get("type") == "agent_step"]
    assert any(e.get("questions") for e in steps if e["id"] == "planificateur")
    boards = [e for e in events if e.get("type") == "agent_research"]
    assert [q["query"] for q in boards[0]["questions"]] == ["hydrogène vert France", "électrolyseurs France industriels",
                                                            "hydrogène vert France 2030 objectifs"]  # fmt: skip
    assert {q["status"] for q in boards[0]["questions"]} == {"open"}
    phases = [b["phase"] for b in boards]
    assert phases.index("search") < phases.index("read") < phases.index("extract") < phases.index("write")
    assert phases[-1] == "done"
    # sources arrive one by one: reading, then kept
    statuses = [{s["domain"]: s["status"] for s in b["sources"]} for b in boards]
    assert any(st.get("energie.test") == "reading" for st in statuses) and statuses[-1]["energie.test"] == "kept"
    # the graph grows during the extraction (each extractor's claims), never with an unverified relation
    grow = [len((b["graph"] or {}).get("nodes", [])) for b in boards if b["phase"] == "extract"]
    assert grow and grow == sorted(grow) and grow[-1] >= 4
    last = boards[-1]
    assert last["claims"]["checked"] == 5 and last["claims"]["seen"] == 8
    assert any(q["status"] == "resolved" for q in last["questions"])
    assert all(len(json.dumps(b, ensure_ascii=False)) <= 14_000 for b in boards)
    done = [e for e in events if e.get("type") == "agent_done"][-1]
    assert done["ok"] and done["recipe"] == "deep_research" and done["calls"] <= 6


def test_broken_plan_and_broken_report_still_give_a_sourced_report(tmp_path):
    run = run_research(tmp_path, respond_for(report="Voici le rapport : la filière va bien.", plan='{"sub_questions": ['))
    a = run.answer
    assert "rapport écrit par le code" in a
    assert "[1]" in a and "[2]" in a
    assert run.widgets[0]["type"] == "research" and run.widgets[0]["questions"]  # code-written sub-questions


def test_no_verified_claim_falls_back_honestly(tmp_path):
    bad = {n: [{**c, "quote": "rien de tout cela"} for c in cs] for n, cs in GOOD_CLAIMS.items()}
    run = run_research(tmp_path, respond_for(claims=bad))
    assert not run.widgets or run.widgets[0]["type"] != "graph"
    assert "graph" not in json.dumps([w.get("type") for w in run.widgets])


def test_pasted_text_is_the_only_source(tmp_path):
    text = ("Fais la carte des acteurs de ce texte :\n\n" + "Le groupe Air Liquide détient une participation dans la "
            "société Hysetco depuis 2019, selon le rapport annuel. Hysetco exploite à Paris une flotte de taxis à "
            "hydrogène. " * 1 + "\n" + "x" * 650)  # fmt: skip

    def respond(tools, user, deadline):
        if tools == ["record_claims"]:
            return call("record_claims", claims=[GOOD_CLAIMS[2][1] | {"source": 1}])
        if tools == ["write_report"]:
            return call("write_report", **{"title": "Acteurs", "summary": "Air Liquide détient une participation "
                        "dans Hysetco [1].", "sections": [{"heading": "Liens", "text": "Air Liquide détient une "
                        "participation dans la société Hysetco depuis 2019 [1]."}]})  # fmt: skip
        raise AssertionError(f"no plan and no search with pasted text: {tools}")

    d = decide(text, mode="auto")
    assert d.recipe == "deep_research"
    llm = Script(respond)
    a = agent(tmp_path, llm)
    run = team(a, d, lang="fr").run(text, text)
    assert run.sources == [] and "vos documents comme seules sources" in run.answer
    assert not any(s.tool == "web_search" for s in run.steps)


def test_decision_object_for_team_factory(tmp_path):
    a = agent(tmp_path, Script(lambda *a: "x"))
    assert type(team(a, Decision("deep_research"))).__name__ == "Research"
    assert type(team(a, Decision("generic"))).__name__ == "Crew"


# ------------------------------------------------------------------ the full report, cross-checks, comparison


def test_the_report_widget_holds_sentences_citations_sources_and_confidence(tmp_path):
    run = run_research(tmp_path, respond_for())
    rep = next(w for w in run.widgets if w["type"] == "report")
    assert rep["title"] == "La filière hydrogène vert en France"
    assert [s["heading"] for s in rep["sections"]] == ["Financements publics", "Acteurs industriels"]
    first = rep["sections"][0]["sents"][0]
    assert first["c"] == [1] and "[" not in first["t"] and "9 milliards" in first["t"]  # moved from [2] to [1]
    assert not any("100 000" in x["t"] for s in rep["sections"] for x in s["sents"])  # removed, never shown
    assert {s["n"]: s["cited"] for s in rep["sources"]} == {1: True, 2: True, 3: True}
    assert all(c["conf"] in ("high", "medium", "low") for c in rep["claims"]) and len(rep["claims"]) == 5
    assert all(c["q"] for c in rep["claims"])  # each claim keeps its quote (the bubble shows it)
    values = [f["value"] for f in rep["figures"]]
    assert "9 milliards d'euros" in values
    assert len(json.dumps(rep, ensure_ascii=False)) <= 16_000
    assert build_widgets([], "", "fr", None, b"x", extra=[rep])[0]["type"] == "report"


def test_cross_check_corroborates_across_sites_and_flags_contradictions():
    from birds.harness import research_report as rr

    pages = [{"n": 1, "domain": "a.test"}, {"n": 2, "domain": "b.test"}, {"n": 3, "domain": "a.test"},
             {"n": 4, "domain": "c.test"}]  # fmt: skip
    claims = [
        {"n": 1, "claim": "Le télétravail concerne 26 % des salariés du privé en 2023", "quote": "26 % des salariés "
         "du privé télétravaillent en 2023", "date": "2023"},
        {"n": 2, "claim": "En 2023, 26 % des salariés du privé pratiquent le télétravail", "quote": "26 % des "
         "salariés du privé pratiquent le télétravail en 2023", "date": "2023"},
        {"n": 4, "claim": "Le télétravail concerne 31 % des salariés du privé en 2023", "quote": "31 % des salariés "
         "du privé télétravaillent en 2023", "date": "2023"},
        # the same site again: never a corroboration
        {"n": 3, "claim": "Le télétravail concerne 26 % des salariés du privé en 2023 selon la Dares", "quote": "x",
         "date": "2023"},
        {"n": 2, "claim": "Les cadres sont les plus nombreux à télétravailler", "quote": "les cadres sont les plus "
         "nombreux", "date": ""},
    ]  # fmt: skip
    out, contra = rr.cross_check(claims, pages)
    assert 2 in out[0]["also"] and 3 not in out[0]["also"]
    assert out[2]["conf"] == "low" and 1 in out[2]["against"] and 2 in out[2]["against"]
    assert contra and {contra[0]["a"]["value"], contra[0]["b"]["value"]} == {"26 %", "31 %"}
    assert out[4]["conf"] == "medium" and not out[4]["also"]
    figs = rr.key_figures(out)  # one tile per value: 26 % once, 31 % once, both marked as disputed
    assert sorted(f["value"] for f in figs) == ["26 %", "31 %"] and {f["conf"] for f in figs} == {"low"}
    alone, _ = rr.cross_check([dict(claims[0]), dict(claims[1])], pages)
    assert [c["conf"] for c in alone] == ["high", "high"] and rr.key_figures(alone)[0]["conf"] == "high"



def test_scale_words_are_part_of_the_value_never_compared_on_their_first_letters():
    from birds.harness import research_report as rr

    assert rr.figures_of("1,2 million d'euros")[0][1:] == (1_200_000.0, "eur")
    assert rr.figures_of("1,2 milliard d'euros")[0][1:] == (1_200_000_000.0, "eur")
    assert rr.figures_of("9 Md€")[0][1:] == rr.figures_of("9 milliards d'euros")[0][1:] == (9e9, "eur")
    assert rr.figures_of("45 M€")[0][1:] == rr.figures_of("45 millions d'euros")[0][1:]
    pages = [{"n": 1, "domain": "a.fr"}, {"n": 2, "domain": "b.fr"}]
    s = "Le marché français de l'hydrogène vert représente {} d'euros en 2023."
    claims = [{"n": 1, "claim": s.format("1,2 million"), "quote": "x"},
              {"n": 2, "claim": s.format("1,2 milliard"), "quote": "x"}]  # fmt: skip
    out, contra = rr.cross_check(claims, pages)
    assert out[0]["also"] == [] and out[1]["also"] == [] and "high" not in {c["conf"] for c in out}
    assert contra and {contra[0]["a"]["value"], contra[0]["b"]["value"]} == {"1,2 million d'euros",
                                                                             "1,2 milliard d'euros"}  # fmt: skip
    same = [{"n": 1, "claim": s.format("45 millions"), "quote": "x"},
            {"n": 2, "claim": "Le marché français de l'hydrogène vert représente 45 M€ en 2023.", "quote": "x"}]
    out, contra = rr.cross_check(same, pages)
    assert [c["conf"] for c in out] == ["high", "high"] and not contra


@pytest.mark.parametrize(
    "a, b",
    [  # two scopes, both true: « chiffres différents », never a contradiction, confidence kept
        ("Le taux de chômage en France atteint 7,3 % en 2023 selon l'Insee.",
         "Le taux de chômage des jeunes en France atteint 17,3 % en 2023 selon la Dares."),
        ("Le télétravail concerne 26 % des salariés en 2023.", "Le télétravail concerne 52 % des cadres en 2023."),
        ("Les ventes de pompes à chaleur ont baissé de 30 % en 2024 en France.",
         "Les ventes de pompes à chaleur air-eau ont baissé de 45 % en 2024 en France."),
    ],
)  # fmt: skip
def test_different_scopes_are_different_figures_not_a_contradiction(a, b):
    from birds.harness import research_report as rr

    pages = [{"n": 1, "domain": "a.fr"}, {"n": 2, "domain": "b.fr"}]
    out, contra = rr.cross_check([{"n": 1, "claim": a, "quote": "x"}, {"n": 2, "claim": b, "quote": "x"}], pages)
    assert not contra and [c["conf"] for c in out] == ["medium", "medium"]
    assert out[0]["differs"] == [2] and out[1]["differs"] == [1] and not out[0]["against"]
    w = rr.report_widget(title="t", summary=[], sections=[], pages=[{"n": 1, "title": "a", "domain": "a.fr"}],
                         consulted=[], claims=out, figures=[], contradictions=contra, questions=[], counts={})  # fmt: skip
    assert w["claims"][0]["differs"] == [2]


def test_the_same_subject_with_another_verb_stays_a_contradiction():
    from birds.harness import research_report as rr

    pages = [{"n": 1, "domain": "a.fr"}, {"n": 2, "domain": "b.fr"}]
    a = "La Région Exemple a lancé en 2023 un plan de 40 millions d'euros pour l'hydrogène renouvelable"
    b = "La Région Exemple a consacré en 2023 un plan de 45 millions d'euros à l'hydrogène renouvelable"
    out, contra = rr.cross_check([{"n": 1, "claim": a, "quote": "x"}, {"n": 2, "claim": b, "quote": "x"}], pages)
    assert len(contra) == 1 and [c["conf"] for c in out] == ["low", "low"] and not out[0]["differs"]

def test_the_writers_comparison_is_kept_only_with_sourced_figures():
    from birds.harness import research_report as rr

    pages = [{"n": 1, "domain": "a.test", "text": "McPhy et Lhyfe sont deux acteurs. McPhy emploie 300 salariés."},
             {"n": 2, "domain": "b.test", "text": "Lhyfe emploie 120 salariés et produit depuis 2021."}]  # fmt: skip
    claims = [{"n": 1, "claim": "McPhy emploie 300 salariés", "quote": "McPhy emploie 300 salariés"},
              {"n": 2, "claim": "Lhyfe emploie 120 salariés", "quote": "Lhyfe emploie 120 salariés"}]  # fmt: skip
    raw = {"columns": ["Acteur", "Salariés", "Chiffre d'affaires"],
           "rows": [["McPhy", "300", "45 M€"], ["Lhyfe", "120", "12 M€"], ["Siemens", "90 000", "70 Md€"]]}  # fmt: skip
    w, blanked = rr.check_comparison(raw, claims, pages)
    assert w["type"] == "matrix" and w["origin"] == "sources"
    assert [r[0] for r in w["rows"]] == ["McPhy", "Lhyfe"]  # Siemens is in no page read
    assert w["rows"][0] == ["McPhy", "300", "—"] and blanked == 2  # the turnover is in no quote
    assert rr.check_comparison({"columns": ["a"], "rows": []}, claims, pages)[0] is None
    assert rr.check_comparison("pas du JSON", claims, pages)[0] is None


def test_research_comparison_reaches_the_widgets(tmp_path):
    report = {**REPORT, "comparison": {"columns": ["Acteur", "Fait"], "rows": [["McPhy", "gigafactory en 2024"],
                                                                               ["Hysetco", "taxis à Paris"]]}}  # fmt: skip
    run = run_research(tmp_path, respond_for(report=report))
    m = next(w for w in run.widgets if w["type"] == "matrix")
    assert [r[0] for r in m["rows"]] == ["McPhy", "Hysetco"]


def test_the_plan_cards_exclusions_and_preferences_steer_the_reading(tmp_path):
    from birds.harness import crew_plan

    d = decide(ASK, mode="auto")
    plan = crew_plan.make_plan(d, ASK, "fr")
    plan, _ = crew_plan.apply_edits(plan, {"exclude": ["industrie.test"]})
    events = []
    a = agent(tmp_path, Script(respond_for()), events)
    run = team(a, d, lang="fr", plan=plan).run(ASK, ASK)
    reads = [s.arguments["url"] for s in run.steps if s.tool == "read_page"]
    assert reads and not any("industrie.test" in u for u in reads)


def test_the_subject_drops_the_colon_after_the_tasks_name(tmp_path):
    a = agent(tmp_path, Script(lambda *x: "x"))
    q = "Recherche approfondie : l'AI Act et ses obligations pour une PME française"
    t = team(a, decide(q, mode="auto"), lang="fr")
    t.instr = q
    assert not t._subject().startswith(":") and "AI Act" in t._subject()


def test_the_shared_query_check_reads_word_forms_and_acronyms():
    from birds.harness.crew import checked_sub_questions

    req = "Recherche approfondie : l'AI Act et ses obligations pour une PME française"
    got = checked_sub_questions({"sub_questions": [
        {"question": "Risques ?", "query": "risques juridiques AI Act PME France"},  # seen live, once rejected
        {"question": "Recettes ?", "query": "recette de la tarte aux pommes"},
    ]}, req)  # fmt: skip
    assert [q for _, q in got] == ["risques juridiques AI Act PME France"]
