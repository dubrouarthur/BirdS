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


def test_build_widgets_adds_the_users_modules():
    got = build_widgets([], TABLE, "fr", NOW, b"x")
    assert [w["type"] for w in got] == ["matrix"]
