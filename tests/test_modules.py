"""Small modules (birds.harness.modules): matrix, checklist, timeline from the user's data or the harness's work."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from test_crew import ASK_NOTES, Script, make_agent

from birds.harness import crew_checks as cc
from birds.harness import modules as m
from birds.harness.crew import Brief, Crew, decide
from birds.web.widgets import build_widgets

NOW = datetime(2026, 11, 27, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))
TABLE = ("Compare ces offres :\n| Offre | Prix mensuel | Délai | Note |\n|---|---|---|---|\n| A | 120 € | 4 h | 4,5 |\n"
         "| B | 95 € | 8 h | 4,1 |\n| C | 140 € | 2 h | 4,8 |")  # fmt: skip


def test_matrix_marks_the_best_value_only_when_the_direction_is_certain():
    w = m.from_words(TABLE)[0]
    assert w["type"] == "matrix" and w["columns"] == ["Offre", "Prix mensuel", "Délai", "Note"]
    assert w["best"] == {"1": [1], "2": [2], "3": [2]}  # cheapest B, fastest C, best rated C
    w2 = m.matrix(["Offre", "Couleur"], [["A", "rouge"], ["B", "bleu"]], title="x")
    assert w2["best"] == {}


def test_tsv_and_semicolon_tables_are_read():
    assert m.table_in("a\tb\n1\t2\n3\t4") == (["a", "b"], [["1", "2"], ["3", "4"]])
    assert m.table_in("Nom;Prix\nX;3\nY;4")[0] == ["Nom", "Prix"]
    assert m.table_in("pas de tableau ici") is None


def test_matrix_from_the_harness_costs_has_the_verdict():
    offers = [
        {"name": "InfoServ", "monthly_items": [{"amount": 1450, "qty": 1}], "one_off": [{"amount": 2000}], "months": 36,
         "sla_hours": 4},
        {"name": "Nexa", "monthly_items": [{"amount": 19, "qty": 85}], "months": 24, "sla_hours": 8},
    ]  # fmt: skip
    costs = cc.compute_offers(offers, {"sla_hours": 4, "budget_year": 20000})
    w = m.matrix_from_costs(costs, "fr")
    assert w["verdict"] == 0 and w["rows"][0][0] == "InfoServ" and w["rows"][1][-1].startswith("non")
    assert w["origin"] == "harness" and "4" not in w["best"]


def test_checklist_from_minutes_and_from_the_users_list(tmp_path):
    crew = Crew(make_agent(tmp_path, Script(lambda *a: "")), decide(ASK_NOTES))
    b = Brief(tool="make_document", instr=ASK_NOTES,
              actions=[{"owner": "Thomas Petit", "action": "Planning révisé", "due": "avant le 21/10"},
                       {"owner": "Julie Moreau", "action": "Nettoyer les doublons", "due": "31/10"}])  # fmt: skip
    got = crew._modules(b)
    assert [w["type"] for w in got] == ["checklist"] and got[0]["items"][0]["owner"] == "Thomas Petit"
    w = m.from_words(
        "Transforme en liste de tâches :\n- appeler le fournisseur\n- [x] envoyer le devis\n- relancer Paul"
    )
    assert [i["done"] for i in w[0]["items"]] == [False, True, False]


def test_timeline_from_dated_lines():
    w = m.from_words("Fais une frise chronologique :\n- mars 2021 : levée de fonds\n- 2019 : création\n- 2024 : Lille")
    assert [e["key"] for e in w[0]["events"]] == ["2019", "2021-03", "2024"]


@pytest.mark.parametrize("q", [
    "rédige un mail pour la réunion de 2024", "compare le télétravail et le présentiel",
    "quelle est la chronologie de la révolution française ?", "fais une checklist pour un déménagement",
    "résume ce document en 5 points", "compare ces deux devis", "qu'est-ce qu'une to-do list ?",
])  # fmt: skip
def test_no_module_without_the_users_data(q):
    assert m.from_words(q) == []


# ------------------------------------------------------------------ the « card » module: the router decides


class _Once:
    def __init__(self, text):
        self.text, self.prompts = text, []

    def generate(self, prompt, max_tokens, stop, **_):
        self.prompts.append(prompt)
        return {"text": self.text, "prompt_tokens": 10, "completion_tokens": 10, "seconds": 0.01}


def _run(tmp_path, monkeypatch, words, decision):
    """One agent turn with the router's decision forced (None: the router is off and the parsers decide)."""
    from test_calc import Tok

    from birds.harness import Agent, Config
    from birds.harness import router as R
    from birds.harness.agent import Hooks

    monkeypatch.setattr(R, "plan_turn", lambda *a, **k: R.Plan(decision))
    a = Agent(_Once("Voilà."), Tok(), Config(workspace=tmp_path, audit_file=None), hooks=Hooks())
    run = a.run(words, lang="fr")
    return [w["type"] for w in build_widgets(run.steps, "", "fr", NOW, b"x", extra=run.widgets)]


def _decided(*kinds):
    from birds.harness import router as R

    return R.Decision([R.Call("card", {"kind": k}) for k in kinds], "off", False, "model")


TIMELINE = "Fais une frise chronologique : 2015 création à Lyon, 2018 premier client export, 2021 levée de fonds"


def test_the_router_decides_the_card_and_the_user_data_fills_it(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, TABLE, _decided("matrix")) == ["matrix"]
    assert _run(tmp_path, monkeypatch, TIMELINE, _decided("timeline")) == ["timeline"]
    # the parsers would build a matrix here, but the router decided none: no card
    assert _run(tmp_path, monkeypatch, TABLE, _decided()) == []
    # the router decides a timeline, the words hold no three dates: nothing is invented
    assert _run(tmp_path, monkeypatch, "fais une frise de l'histoire de France", _decided("timeline")) == []
    # the router off: the parsers' guess is the fallback (as before the router)
    assert _run(tmp_path, monkeypatch, TABLE, None) == ["matrix"]
    loan = "mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 %"
    assert _run(tmp_path, monkeypatch, loan, _decided("calc")) == ["calc"]
    assert _run(tmp_path, monkeypatch, loan, _decided()) == []
    assert _run(tmp_path, monkeypatch, loan, None) == ["calc"]


def test_pros_cons_key_figures_and_glossary_from_the_users_words():
    pc = m.card("proscons", "Pour et contre du télétravail : pour : moins de trajets, plus de calme ; contre : "
                "isolement, réunions plus longues")  # fmt: skip
    assert pc["pros"] == ["moins de trajets", "plus de calme"] and pc["cons"] == ["isolement", "réunions plus longues"]
    assert m.card("proscons", "les avantages du vélo") is None  # no listed points: no card
    pc2 = m.card("proscons", "Avantages et inconvénients :\n+ rapide\n+ pas cher\n- fragile")
    assert pc2["pros"] == ["rapide", "pas cher"] and pc2["cons"] == ["fragile"]
    fig = m.card("figures", "Fais une fiche de chiffres clés : CA 2025 : 1,2 M€ ; marge : 18 % ; effectif : 45 salariés")
    assert [(x["label"], x["value"]) for x in fig["items"]] == [("CA 2025", "1,2 M€"), ("marge", "18 %"),
                                                                ("effectif", "45 salariés")]  # fmt: skip
    assert m.card("figures", "quels sont les chiffres clés du marché ?") is None  # the market's: a search, not a card
    gl = m.card("glossary", "Fais un glossaire :\nRGPD : règlement général sur la protection des données\nDPO : "
                "délégué à la protection des données")  # fmt: skip
    assert [x["term"] for x in gl["items"]] == ["DPO", "RGPD"]
    one = "Fais un glossaire : RGPD : règlement général sur la protection des données ; CNIL : commission nationale"
    assert [x["term"] for x in m.card("glossary", one)["items"]] == ["CNIL", "RGPD"]  # one line: the ask is no term
    assert [w["type"] for w in m.cards(one, "fr")] == ["glossary"]
    assert m.source_cards([], "fr") is None and m.source_cards(["https://a.test"], "fr")["n"] == 1
    assert m.asked_kinds("donne-moi les sources de ta réponse") == ["sources"]


def test_the_parsers_hint_a_card_only_with_the_data():
    from birds.harness import router as R

    assert R.regex_decision(TIMELINE).get("card").args == {"kind": "timeline"}
    assert R.regex_decision("fais une frise de l'histoire de France").get("card") is None
    assert R.regex_decision("rédige un mail à Paul pour la réunion de lundi").get("card") is None
