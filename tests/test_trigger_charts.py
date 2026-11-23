"""Trigger audit, charts: the user's own figures are read whole, the type they name is used, a follow-up charts the
previous answer, and diagrams, dates or trend words alone never pass for a chart ask."""

from __future__ import annotations

import pytest

from birds.harness import Agent, Config, FakeClient
from birds.harness.agent import NO_CHART, chart_ask, chart_call, figures_in, route, trend_ask


class Tok:
    def apply_chat_template(self, messages, tools=None, tokenize=False, add_generation_prompt=True, **kw):
        return "\n".join(str(m.get("content")) for m in messages)


def _rows(text):
    got = figures_in(text)
    return got and (got[1], got[2])


def test_a_decimal_value_is_never_split_and_keeps_its_unit(tmp_path):
    ask = "CA 2022 : 1,2 M€, 2023 : 1,5 M€, 2024 : 1,9 M€. Fais un graphique"
    assert _rows(ask) == ([["2022", "1,2"], ["2023", "1,5"], ["2024", "1,9"]], "M€")
    run = Agent(FakeClient(["Le CA progresse."]), Tok(), Config(workspace=tmp_path)).run(ask, lang="fr")
    chart = run.charts[0]
    assert [r[1] for r in chart["rows"]] == [1.2, 1.5, 1.9] and chart["source"] == "request"


def test_the_last_pair_before_a_dash_or_text_is_kept():
    rows, _ = _rows("nombre de tickets par semaine : S1 45, S2 52, S3 61, S4 58 — sous forme de courbe")
    assert [r[0] for r in rows] == ["S1", "S2", "S3", "S4"]


@pytest.mark.parametrize(
    "text,rows",
    [
        ("graphique en barres : 2021 100, 2022 120, 2023 130", [["2021", "100"], ["2022", "120"], ["2023", "130"]]),
        ("fais un camembert : 2022 40, 2023 35, 2024 25", [["2022", "40"], ["2023", "35"], ["2024", "25"]]),
        ("trace la courbe du CA 2021 120k 2022 150k 2023 180k", [["2021", "120"], ["2022", "150"], ["2023", "180"]]),
        (
            "fais un graphique : Paris 12 500, Lyon 8 300, Nice 4 100",
            [["Paris", "12500"], ["Lyon", "8300"], ["Nice", "4100"]],
        ),
    ],
)
def test_year_labelled_pairs_and_thousands(text, rows):
    assert _rows(text)[0] == rows


@pytest.mark.parametrize(
    "text,labels,unit",
    [
        (
            "répartition des effectifs : 45 % CDI, 30 % CDD, 25 % intérim, en camembert svp",
            ["CDI", "CDD", "intérim"],
            "%",
        ),
        ("budget : 45 % salaires, 30 % loyers, 25 % divers - fais un camembert", ["salaires", "loyers", "divers"], "%"),
        ("fais un graphique : 120 en janvier, 135 en février, 160 en mars", ["janvier", "février", "mars"], ""),
    ],
)
def test_number_first_pairs(text, labels, unit):
    rows, got_unit = _rows(text)
    assert [r[0] for r in rows] == labels and got_unit == unit


def test_two_figures_in_a_sentence_are_still_not_a_chart():
    assert figures_in("Le budget est de 12 000 € et la marge de 31 %.") is None


@pytest.mark.parametrize(
    "text,rows,unit",
    [
        (
            "fais un graphique de la population : Paris 2,1 millions, Lyon 0,5 millions, Marseille 0,87 millions",
            [["Paris", "2,1"], ["Lyon", "0,5"], ["Marseille", "0,87"]],
            "M",
        ),
        ("fais une courbe : T1 1,25 M, T2 1,4 M, T3 1,6 M", [["T1", "1,25"], ["T2", "1,4"], ["T3", "1,6"]], "M"),
        (
            "fais un histogramme du CA : Nord 1,2 Md, Sud 0,9 Md, Est 0,7 Md",
            [["Nord", "1,2"], ["Sud", "0,9"], ["Est", "0,7"]],
            "Md",
        ),
        (
            "le budget est de 1,5 million, fais un graphique : salaires 0,8 million, loyers 0,4 million, "
            "divers 0,3 million",
            [["salaires", "0,8"], ["loyers", "0,4"], ["divers", "0,3"]],
            "M",
        ),
    ],
)
def test_a_decimal_before_a_magnitude_word_is_read_whole(tmp_path, text, rows, unit):
    assert _rows(text) == (rows, unit)
    run = Agent(FakeClient(["Voici."]), Tok(), Config(workspace=tmp_path)).run(text, lang="fr")
    assert [r[1] for r in run.charts[0]["rows"]] == [float(r[1].replace(",", ".")) for r in rows]


@pytest.mark.parametrize(
    "text,kind",
    [
        ("nombre de tickets par semaine : S1 45, S2 52, S3 61, S4 58 — sous forme de courbe", "line"),
        ("graphique en barres : 2021 : 100, 2022 : 120, 2023 : 130", "bar"),
        ("histogramme des ventes : janvier 120, fevrier 135, mars 160", "bar"),
        ("fais un camembert : 2022 40, 2023 35, 2024 25", "pie"),
        ("graphique des ventes : janvier 120, février 135, mars 160", "line"),  # nothing named: time labels
    ],
)
def test_the_type_the_user_names_wins(text, kind):
    assert chart_call(text, figures_in(text), "fr")["type"] == kind


def test_refais_le_en_barres_uses_the_named_type():
    data = (["Année", "CA"], [["2021", "1"], ["2022", "2"], ["2023", "3"]], "")
    assert chart_call("refais le en barres", data, "fr")["type"] == "bar"


TABLE = "Voici le CA :\n\n| Trimestre | CA (k€) |\n|---|---|\n| T1 | 120 |\n| T2 | 135 |\n| T3 | 150 |\n| T4 | 160 |"
MEMO = (
    "D'accord.\n\n[Mémo de ce tour] graphique affiché : « CA » (bar, k€) colonnes Trimestre / CA — T1 120 ; "
    "T2 135 ; T3 150 ; T4 160"
)


@pytest.mark.parametrize(
    "ask,previous,kind",
    [
        ("mets ça en graphique", TABLE, "line"),
        ("fais-en un camembert", TABLE, "pie"),
        ("tu peux le mettre en courbe ?", MEMO, "line"),
        ("refais le en barres", MEMO, "bar"),
        ("make it a chart", TABLE, "line"),
    ],
)
def test_a_follow_up_charts_the_previous_answer(tmp_path, ask, previous, kind):
    history = [{"role": "user", "content": "le CA par trimestre"}, {"role": "assistant", "content": previous}]
    run = Agent(FakeClient(["D'accord, voici le graphique."]), Tok(), Config(workspace=tmp_path)).run(
        ask, lang="fr", history=history
    )
    assert run.charts and run.charts[0]["type"] == kind and len(run.charts[0]["rows"]) == 4
    assert run.steps[0].tool == "make_chart" and run.answer != NO_CHART["fr"]


def test_a_follow_up_without_history_draws_nothing_by_itself(tmp_path):
    llm = FakeClient(["Quels chiffres voulez-vous représenter ?"])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("mets ça en graphique", lang="fr")
    assert not run.charts


@pytest.mark.parametrize(
    "text",
    [
        "dessine un diagramme de flux pour le processus de commande",
        "fais un diagramme de Gantt du projet",
        "fais un diagramme de séquence UML",
        "make a gantt chart for the project",
    ],
)
def test_diagrams_without_figures_are_not_chart_asks(text):
    assert not chart_ask(text) and "make_chart" in route(text)


def test_a_flow_diagram_answer_is_kept(tmp_path):
    answer = "Voici le diagramme de flux : Commande → Validation → Préparation → Expédition."
    run = Agent(FakeClient([answer]), Tok(), Config(workspace=tmp_path)).run(
        "dessine un diagramme de flux pour le processus de commande", lang="fr"
    )
    assert run.answer == answer and not run.charts


TREND_YES = [
    "la population de Paris depuis 2012",
    "la population de Lyon ces 10 dernieres annees",
    "le chiffre d'affaires de LVMH sur les 5 dernières années",
    "progression des ventes en ligne en France de 2015 à 2024",
    "historique du prix du baril de petrole",
    "le smic depuis 10 ans",
    "evolution du chomage en france depuis 2010",
    "comment a evolue le prix du gaz entre 2020 et 2024 ?",
    "le cac 40 depuis 2015",
    "how has the population of london changed since 2000?",
    "population of france from 2000 to 2020",
    "quelle est la tendance des prix de l'immobilier à Lyon ?",
]
TREND_NO = [
    "je suis dans l'entreprise depuis 2019, aide-moi à rédiger ma demande d'augmentation",
    "rédige un mail : le client est en retard de paiement depuis 2023",
    "la tendance mode de cet hiver ?",
    "quelles sont les tendances du marketing digital en 2026 ?",
    "l'evolution de carriere d'un comptable",
    "comment evoluer vers un poste de manager ?",
]


@pytest.mark.parametrize("text", TREND_YES)
def test_trend_questions_offer_a_chart(text):
    assert trend_ask(text) and "make_chart" not in route(text)


@pytest.mark.parametrize("text", TREND_NO)
def test_a_year_or_a_trend_word_alone_is_not_a_trend_question(text):
    assert not trend_ask(text) and "make_chart" in route(text)


def test_a_bullet_answer_to_a_raise_letter_is_not_charted(tmp_path):
    answer = "Points à mettre en avant :\n- Ancienneté : 5 ans\n- Projets menés : 12\n- Objectifs atteints : 95 %"
    run = Agent(FakeClient([answer]), Tok(), Config(workspace=tmp_path)).run(
        "je suis dans l'entreprise depuis 2019, aide-moi à rédiger ma demande d'augmentation", lang="fr"
    )
    assert not run.charts and run.answer == answer


@pytest.mark.parametrize(
    "text",
    [
        "tu peux mettre ces chiffres en graphique ?",
        "peux-tu mettre ça sous forme de graphique",
        "can you graph this for me",
        "tu peux le mettre en courbe ?",
    ],
)
def test_mettre_and_you_graph_are_chart_verbs(text):
    assert chart_ask(text)


@pytest.mark.parametrize("text", ["mets à jour le tableau des congés", "passe-moi le mail de Paul"])
def test_mettre_and_passer_alone_are_not_chart_asks(text):
    assert not chart_ask(text)
