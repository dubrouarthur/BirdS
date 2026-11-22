"""Day and time in the user's own words (birds.harness.when). Fixed 'now': Sunday 22 November 2026, 10:00 Paris."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from birds.harness.when import parse

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 11, 22, 10, 0, tzinfo=PARIS)  # a Sunday

CASES = [
    # text, lang, start, end (None: all day)
    ("réunion demain à 14h", "fr", "2026-11-23T14:00", "2026-11-23T15:00"),
    ("rdv aujourd'hui à 16h30", "fr", "2026-11-22T16:30", "2026-11-22T17:30"),
    ("après-demain 9h", "fr", "2026-11-24T09:00", "2026-11-24T10:00"),
    ("jeudi prochain à 14h", "fr", "2026-11-26T14:00", "2026-11-26T15:00"),
    ("jeudi à 14h", "fr", "2026-11-26T14:00", "2026-11-26T15:00"),
    ("dimanche à 10h", "fr", "2026-11-29T10:00", "2026-11-29T11:00"),  # said on a Sunday: next week
    ("lundi en huit", "fr", "2026-11-30T00:00", None),
    ("mardi de la semaine prochaine 9h", "fr", "2026-11-24T09:00", "2026-11-24T10:00"),
    ("dans 3 jours à 9h", "fr", "2026-11-25T09:00", "2026-11-25T10:00"),
    ("le 3 décembre à 14h", "fr", "2026-12-03T14:00", "2026-12-03T15:00"),
    ("le 3 déc. à 14h", "fr", "2026-12-03T14:00", "2026-12-03T15:00"),
    ("le 1er mars", "fr", "2027-03-01T00:00", None),  # no year, already past this year? no: March 2027 is next
    ("le 15 janvier 2027 à 10h", "fr", "2027-01-15T10:00", "2027-01-15T11:00"),
    ("le 10 novembre", "fr", "2027-11-10T00:00", None),  # past without a year: next year
    ("le 03/12 de 14h à 15h30", "fr", "2026-12-03T14:00", "2026-12-03T15:30"),
    ("12/03 à 9h", "fr", "2027-03-12T09:00", "2027-03-12T10:00"),  # day first in French
    ("12/03 at 9 am", "en", "2026-12-03T09:00", "2026-12-03T10:00"),  # month first in English
    ("03/12/2026 14h-15h", "fr", "2026-12-03T14:00", "2026-12-03T15:00"),
    ("2026-12-03 à 14:30", "fr", "2026-12-03T14:30", "2026-12-03T15:30"),
    ("le 25 décembre à midi", "fr", "2026-12-25T12:00", "2026-12-25T13:00"),
    ("visio dimanche 10h30 pendant 1h30", "fr", "2026-11-29T10:30", "2026-11-29T12:00"),
    ("point vendredi 9h pendant 30 min", "fr", "2026-11-27T09:00", "2026-11-27T09:30"),
    ("call lundi 11h 45 min", "fr", "2026-11-23T11:00", "2026-11-23T11:45"),
    ("déjeuner mercredi", "fr", "2026-11-25T00:00", None),  # no time: all day, never a guessed noon
    ("dîner samedi de 20h à 23h", "fr", "2026-11-28T20:00", "2026-11-28T23:00"),
    ("soirée vendredi de 22h à 1h", "fr", "2026-11-27T22:00", "2026-11-28T01:00"),
    ("meeting next Monday at 2pm", "en", "2026-11-23T14:00", "2026-11-23T15:00"),
    ("meeting next Monday at 2pm for 30 minutes", "en", "2026-11-23T14:00", "2026-11-23T14:30"),
    ("call tomorrow at 9:15", "en", "2026-11-23T09:15", "2026-11-23T10:15"),
    ("lunch the day after tomorrow at noon", "en", "2026-11-24T12:00", "2026-11-24T13:00"),
    ("December 3rd 2-3pm", "en", "2026-12-03T14:00", "2026-12-03T15:00"),
    ("Dec 3 at 10 am", "en", "2026-12-03T10:00", "2026-12-03T11:00"),
    ("3 December 2026 at 4pm", "en", "2026-12-03T16:00", "2026-12-03T17:00"),
    ("this Sunday at 6pm", "en", "2026-11-22T18:00", "2026-11-22T19:00"),
    ("on Friday from 2pm to 3:30pm", "en", "2026-11-27T14:00", "2026-11-27T15:30"),
    ("in 2 days at 8am for an hour", "en", "2026-11-24T08:00", "2026-11-24T09:00"),
    ("today", "en", "2026-11-22T00:00", None),
    ("réunion le 29 mars 2026 à 10h", "fr", "2026-03-29T10:00", "2026-03-29T11:00"),  # DST day, explicit year
    ("formation le 28 mars 2027 à 9h", "fr", "2027-03-28T09:00", "2027-03-28T10:00"),  # DST change day
    ("atelier le 31 octobre 2027 à 15h", "fr", "2027-10-31T15:00", "2027-10-31T16:00"),
    ("séminaire le 2 janvier", "fr", "2027-01-02T00:00", None),  # year rollover
    ("rdv le 31 décembre à 18h", "fr", "2026-12-31T18:00", "2026-12-31T19:00"),
    ("demain de 9h à 9h", "fr", "2026-11-23T09:00", "2026-11-23T10:00"),  # empty range: default hour
    ("demain minuit", "fr", "2026-11-23T00:00", "2026-11-23T01:00"),
    ("Mardi à 8h15", "fr", "2026-11-24T08:15", "2026-11-24T09:15"),
]

NONE = [
    "fais le point sur le budget",
    "organise une réunion avec Paul",
    "en deux semaines",
    "réunion à 14h",
    "le 31/02",
    "2 sept personnes",
    "",
]


@pytest.mark.parametrize("text,lang,start,end", CASES)
def test_parse(text, lang, start, end):
    got = parse(text, NOW, lang)
    assert got is not None, text
    assert got["start"].strftime("%Y-%m-%dT%H:%M") == start
    if end is None:
        assert got["all_day"]
    else:
        assert not got["all_day"] and got["end"].strftime("%Y-%m-%dT%H:%M") == end


@pytest.mark.parametrize("text", NONE)
def test_no_day_no_card(text):
    assert parse(text, NOW, "fr") is None


def test_offsets_follow_dst_and_default_duration_is_said():
    winter = parse("le 3 décembre à 14h", NOW, "fr")
    summer = parse("le 3 juin à 14h", NOW, "fr")
    assert winter["start"].utcoffset().total_seconds() == 3600 and summer["start"].utcoffset().total_seconds() == 7200
    assert winter["assumptions"] == ["default_duration"]
    assert parse("demain de 14h à 15h", NOW, "fr")["assumptions"] == []


def test_matched_words_in_order():
    assert parse("visio dimanche 10h30 pendant 1h30", NOW, "fr")["matched"] == "dimanche 10h30 pendant 1h30"


# ---------------------------------------------------------------- is it an ask to put an event in the diary?

from birds.harness.when import event_ask  # noqa: E402

EVENT_ASKS = [
    "Organise une réunion avec Paul jeudi prochain à 14h",
    "Cale un déjeuner avec l'équipe le 25 décembre à midi",
    "Planifie un point avec Marie demain à 9h30",
    "Ajoute à mon agenda la visio de lundi à 11h",
    "Schedule a meeting with Anna on Friday at 3pm",
    "rdv chez le client samedi à 10h",
    "Écris un mail à Paul pour caler une réunion jeudi à 14h",
]
NOT_EVENT_ASKS = [
    "Rédige le compte rendu de la réunion de jeudi : présents Paul et Marie ; décisions : budget validé",
    "Écris un mail pour annuler la réunion de demain avec Paul",
    "Le séminaire du 12 mars s'est bien passé, merci à tous",
    "Prépare les slides pour le meeting de lundi",
    "Fais une présentation pour le séminaire de vendredi",
    "Quels documents apporter à l'entretien annuel de vendredi ?",
    "Rédige une invitation au webinaire du 3 décembre",
    "Prépare l'ordre du jour de la réunion de lundi",
    "Où est la réunion de demain ?",
    "Reporte la réunion de jeudi à vendredi",
    "Envoie un remerciement pour le déjeuner d'hier",
    "Write the minutes of Monday's meeting",
    "Cancel tomorrow's call with John",
    "réunion demain",
]


@pytest.mark.parametrize("text", EVENT_ASKS)
def test_event_asks(text):
    assert event_ask(text, NOW, "en" if text.startswith(("Schedule",)) else "fr") is not None, text


@pytest.mark.parametrize("text", NOT_EVENT_ASKS)
def test_documents_about_meetings_and_past_meetings_are_not_event_asks(text):
    assert event_ask(text, NOW, "fr") is None and event_ask(text, NOW, "en") is None
