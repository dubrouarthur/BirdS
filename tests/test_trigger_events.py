"""Trigger audit, events: « pour jeudi 14h » keeps its time, and an .ics ask, « mettre … dans mon agenda »,
« ajoute au calendrier » and « crée un événement » get the event card."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from birds.harness import when
from birds.web.widgets import event_widget

NOW = datetime(2026, 11, 23, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))  # a Monday


@pytest.mark.parametrize(
    "text,start,end",
    [
        ("cale une réunion pour jeudi 14h", "2026-11-26 14:00", "15:00"),
        ("programme un call pour vendredi 11h", "2026-11-27 11:00", "12:00"),
        ("planifie un rdv avec Paul pour demain 9h", "2026-11-24 09:00", "10:00"),
        ("réunion jeudi pour 2h à 14h", "2026-11-26 14:00", "16:00"),  # a real duration is still read
    ],
)
def test_pour_before_a_day_is_not_a_duration(text, start, end):
    got = when.parse(text, NOW, "fr")
    assert not got["all_day"] and f"{got['start']:%Y-%m-%d %H:%M}" == start and f"{got['end']:%H:%M}" == end


@pytest.mark.parametrize(
    "text,lang",
    [
        ("cale une réunion pour jeudi 14h", "fr"),
        ("programme un call pour vendredi 11h", "fr"),
        ("génère un fichier ics pour la réunion de jeudi 14h", "fr"),
        ("fais-moi un .ics pour le rdv de vendredi 10h", "fr"),
        ("ajoute au calendrier la réunion de jeudi 14h avec Paul", "fr"),
        ("peux-tu mettre une réunion avec la direction le 1er décembre à 10h dans mon agenda ?", "fr"),
        ("crée un événement dans mon agenda pour jeudi 14h", "fr"),
        ("cree un evenement dans mon agenda vendredi 9h reunion equipe", "fr"),
        ("add the meeting with Paul on Friday at 2pm to my calendar", "en"),
    ],
)
def test_these_asks_get_an_event_card(text, lang):
    card = event_widget(text, NOW, lang)
    assert card is not None and not when.event_ask(text, NOW, lang)["all_day"]


@pytest.mark.parametrize(
    "text",
    [
        "explique-moi le format ics",
        "comment ajouter une réunion à mon agenda Outlook ?",
        "ajoute un point à l'ordre du jour de la réunion de jeudi",
        "mets à jour l'agenda de la réunion",
        "quel événement a lieu à Paris ce week-end ?",
        "crée un événement jeudi",  # a weak word with no time
    ],
)
def test_no_card_for_these(text):
    assert event_widget(text, NOW, "fr") is None
