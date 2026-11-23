"""Trigger gaps closed at the root: chart how-tos, unlabelled code fences, event titles and dates, Saint-Denis."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from birds.harness import clock, geo, when
from birds.harness.agent import chart_ask, chart_howto, route
from birds.web.tidy import code_checks
from birds.web.widgets import event_widget

NOW = datetime(2026, 11, 23, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))
FENCE = "```"


@pytest.mark.parametrize(
    "text",
    [
        "comment faire un graphique dans Excel ?",
        "Comment créer un camembert sous PowerPoint",
        "how do I make a chart in Google Sheets?",
        "je voudrais savoir comment insérer un graphique dans Word",
        "tuto pour faire une courbe sur Excel",
        "quel graphique choisir pour montrer une répartition ?",
        "Quel type de graphique pour des données temporelles ?",
        "Peux-tu m'expliquer comment tracer une courbe de tendance dans Excel ?",
        "définition d'un diagramme de Pareto",
        "quelle est la différence entre un histogramme et un diagramme en barres ?",
        "étapes pour créer un graphique croisé dynamique",
        "montre-moi comment faire un graphique dans Excel",
        "which chart should I use for market share?",
    ],
)
def test_chart_how_tos_get_no_chart_tool(text):
    assert chart_howto(text) and "make_chart" in route(text) and not chart_ask(text)


@pytest.mark.parametrize(
    "text",
    [
        "fais un graphique des ventes : janvier 120, février 135, mars 160",
        "fais un graphique des ventes et explique la tendance",
        "trace la courbe et explique comment la lire",
        "comment représenter ça en graphique : T1 120, T2 135, T3 150 ?",
        "fais un camembert de la répartition des dépenses",
    ],
)
def test_chart_requests_stay_requests(text):
    assert not chart_howto(text) and "make_chart" not in route(text)


def test_unlabelled_fences_are_checked_when_they_read_as_json_or_python():
    blocks = ['{"a": 1, "b": [1, 2]}', "def f(x):\n    return x +", "for i in range(3):\n    print(i)",
              "SELECT * FROM t;", "const a = {b: 1};", "{ a: 1 }", "Bonjour Paul,\nMerci pour ton retour.",
              "Total = 120 €\nTVA = 24 €", "[1] Source : INSEE"]  # fmt: skip
    got = {c["i"]: c for c in code_checks("\n".join(f"{FENCE}\n{b}\n{FENCE}" for b in blocks))}
    assert sorted(got) == [0, 1, 2]
    assert got[0]["lang"] == "json" and got[0]["ok"] and got[0]["sniffed"]
    assert got[1]["lang"] == "python" and got[1]["kind"] == "error" and got[1]["line"] == 2
    assert got[2]["lang"] == "python" and got[2]["ok"]
    labelled = code_checks(f"{FENCE}python\nx = 1\n{FENCE}")
    assert labelled and "sniffed" not in labelled[0]


@pytest.mark.parametrize(
    "text,lang,title",
    [
        ("réunion avec Paul apres-demain à 10h", "fr", "Réunion avec Paul"),
        ("meeting with John to discuss the budget tomorrow at 3pm", "en", "Meeting with John"),
        ("déjeuner avec Marie chez Flo jeudi à 12h30", "fr", "Déjeuner avec Marie"),
        ("réunion avec l'équipe dans la salle B jeudi à 14h", "fr", "Réunion avec l'équipe"),
    ],
)
def test_event_titles_stop_before_day_and_place_words(text, lang, title):
    assert event_widget(text, NOW, lang)["title"] == title


@pytest.mark.parametrize(
    "text,day",
    [
        ("programmer une formation le 15 janvier", "2027-01-15"),
        ("peux-tu programmer une formation le 15 janvier ?", "2027-01-15"),
        ("Programmer une formation sécurité le 15/01", "2027-01-15"),
        ("planifie un atelier le 3 mars 2027", "2027-03-03"),
    ],
)
def test_a_planned_session_with_a_full_date_is_a_whole_day_card(text, day):
    w = event_widget(text, NOW, "fr")
    assert w and w["all_day"] and w["start"].startswith(day)


@pytest.mark.parametrize(
    "text",
    [
        "le programme de la formation du 15 janvier",
        "fais le point sur la formation du 15 janvier",
        "la formation du 15 janvier est annulée",
        "programmer une formation demain",  # no full date: a weak word stays without a card
    ],
)
def test_no_card_for_a_formation_that_is_only_mentioned(text):
    assert event_widget(text, NOW, "fr") is None or when.event_ask(text, NOW, "fr") is None


@pytest.mark.parametrize(
    "text,zone",
    [
        ("quelle heure est-il à Saint-Denis ?", "Europe/Paris"),
        ("quelle heure est-il à St Denis", "Europe/Paris"),
        ("quelle heure est-il à Saint-Denis de la Réunion ?", "Indian/Reunion"),
        ("heure locale à Saint-Denis (La Réunion)", "Indian/Reunion"),
        ("décalage horaire avec Saint-Denis, Réunion", "Indian/Reunion"),
        ("quelle heure est-il à la Réunion ?", "Indian/Reunion"),
    ],
)
def test_saint_denis_alone_is_the_town_near_paris(text, zone):
    assert [c["zone"] for c in clock.detect(text)["cities"]] == [zone]


def test_geocoder_reads_saint_denis_as_seine_saint_denis_unless_reunion_is_said():
    assert geo.disambiguate("Saint-Denis", "météo à Saint-Denis demain") == "Saint-Denis, Seine-Saint-Denis"
    assert geo.disambiguate("St Denis", "") == "Saint-Denis, Seine-Saint-Denis"
    assert geo.disambiguate("Saint-Denis", "météo à Saint-Denis de la Réunion") == "Saint-Denis"
    assert geo.disambiguate("Saint-Denis-de-Pile", "") == "Saint-Denis-de-Pile"
    assert geo.disambiguate("Lyon", "") == "Lyon"
