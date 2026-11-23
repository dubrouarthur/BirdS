"""Trigger audit, company and currency: register questions about a named company and source-only conversions are
pre-called; file conversions and questions about the register itself offer nothing."""

from __future__ import annotations

import pytest

from birds.harness import intents


def _args(text):
    got = intents.detect(text)
    return got[0].args if got else None


@pytest.mark.parametrize(
    "text,frm,to",
    [
        ("convertir 80 euros en dollars canadiens", "EUR", "CAD"),
        ("convertis 100 dollars en livres turques", "USD", "TRY"),
        ("convertis 2500 euros en dollars", "EUR", "USD"),  # the generic word still works
        ("250 livres en euros stp", "GBP", "EUR"),
    ],
)
def test_a_specific_currency_wins_over_the_generic_word(text, frm, to):
    got = intents.fx(text)
    assert got.args["from"] == frm and got.args["to"] == to


@pytest.mark.parametrize(
    "text,args",
    [
        ("combien vaut 1 000 CHF", {"from": "CHF", "to": "EUR", "amount": 1000.0}),
        ("500 yens ça fait combien en euros ?", {"from": "JPY", "to": "EUR", "amount": 500.0}),
        ("j'ai une facture de 3 400 USD, ça fait combien en euros ?", {"from": "USD", "to": "EUR", "amount": 3400.0}),
        ("quel est le cours du dollar aujourd'hui", {"from": "USD", "to": "EUR"}),
        ("le taux euro/livre", {"from": "EUR", "to": "GBP"}),
    ],
)
def test_conversions_with_the_target_later_or_implied(text, args):
    assert intents.fx(text).args == args


@pytest.mark.parametrize(
    "text",
    [
        "le cours du dollar depuis 2020",
        "combien vaut 100 € en 2026",
        "combien vaut un brevet ?",
        "le prix est de 45 dollars",
    ],
)
def test_no_conversion_without_a_clear_ask(text):
    got = intents.fx(text)
    assert got is None or got.args is None


@pytest.mark.parametrize(
    "text", ["convertis ce fichier en PDF", "convert this docx to pdf", "convertis ce texte en majuscules"]
)
def test_a_file_or_text_conversion_offers_no_currency_tool(text):
    assert intents.detect(text) == []


def test_a_conversion_word_with_money_is_still_offered():
    got = intents.fx("convertis 100 euros")
    assert got is not None and got.tool == "convert_currency" and got.args is None


@pytest.mark.parametrize(
    "text,name",
    [
        ("qui dirige Michelin ?", "Michelin"),
        ("qui dirige la société Decathlon", "Decathlon"),
        ("c'est quoi le siren de Free ?", "Free"),
        ("chiffre d'affaires de Leroy Merlin", "Leroy Merlin"),
        ("quel est le chiffre d'affaires de la société Ornikar ?", "Ornikar"),
        ("le CA de Carrefour en 2024", "Carrefour"),
        ("qui sont les dirigeants de Qonto ?", "Qonto"),
        ("numero de tva de la societe Malt", "Malt"),
        ("combien de salariés chez Doctolib", "Doctolib"),
        ("who runs Danone?", "Danone"),
        ("fiche entreprise doctolib", "doctolib"),
        ("infos sur l'entreprise blablacar stp", "blablacar"),
    ],
)
def test_register_questions_about_a_named_company_are_pre_called(text, name):
    assert _args(text) == {"name": name}


@pytest.mark.parametrize(
    "text",
    [
        "qui dirige la réunion de demain ?",
        "quel est le CA de Janvier ?",
        "le CA de 2024",
        "chiffre d'affaires de Q3",
        "le CA de notre filiale",
        "dirigeants de PME : 5 conseils",
        "notre CA 2024 est de 1,2 M€, rédige un commentaire",
        "fiche de poste pour un commercial",
        "rédige une fiche produit",
    ],
)
def test_no_company_call_for_ordinary_words(text):
    assert intents.company(text) is None


@pytest.mark.parametrize("text", ["explique ce qu'est un numéro SIREN", "comment trouver le siret d'une entreprise ?"])
def test_a_question_about_the_register_offers_nothing(text):
    assert intents.company(text) is None
