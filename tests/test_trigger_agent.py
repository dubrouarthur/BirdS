"""Trigger audit, Mode Agent Auto: short offers or an attendee list written right after the request are material
of their own (compare_write, minutes_actions); a deck on a public market with figures is researched; a deck built on
the user's own figures is not."""

from __future__ import annotations

import pytest

from birds.harness import crew_checks as cc
from birds.harness.crew import decide, split_request

INLINE = (
    "Compare les offres de ces trois fournisseurs et rédige un mail de recommandation : Devis 1 – Alpha 12 000 €, "
    "Devis 2 – Beta 10 500 €, Devis 3 – Gamma 11 200 €"
)


def test_offers_on_one_line_are_split_into_material():
    instr, pasted = split_request(INLINE)
    assert instr.endswith("recommandation") and cc.offer_names(pasted) == ["Alpha", "Beta", "Gamma"]


@pytest.mark.parametrize(
    "text,recipe",
    [
        (INLINE, "compare_write"),
        ("compare ces offres et fais un rapport :\n1) Alpha 12 000 € HT\n2) Beta 10 500 € HT\n3) Gamma 11 200 € HT",
         "compare_write"),
        ("Compare these quotes and draft an email recommending the best one:\nOffer A – Alpha 12 000 €\n"
         "Offer B – Beta 10 500 €", "compare_write"),
        ("quel est le meilleur devis ? redige un mail a mon boss pour justifier\nDevis 1 – Alpha Copieurs : 420 € HT "
         "par mois\nDevis 2 – Beta Bureautique : 390 € HT par mois", "compare_write"),
        ("Fais le compte rendu de cette réunion avec le tableau des actions :\nPrésents : Marie Dupont, Julien Martin, "
         "Sophie Leroy\n1. Julien relance le sous-traitant avant vendredi.\n2. Sophie organise la visite le 20/11.",
         "minutes_actions"),
        ("Write the minutes of this meeting with the action items\nParticipants : Anne Vernet, Bruno Caron\nBruno "
         "sends the quote by Friday. Anne books the room for 3 March.", "minutes_actions"),
        ("Fais une présentation de 6 slides sur le marché du vélo électrique en France avec des chiffres",
         "deck_research"),
        ("prépare des slides sur les chiffres clés du e-commerce en France", "deck_research"),
        ("fais une presentation chiffrée sur le marché de la cybersécurité", "deck_research"),
    ],
)  # fmt: skip
def test_auto_starts_the_team(text, recipe):
    assert decide(text).recipe == recipe


@pytest.mark.parametrize(
    "text",
    [
        "Fais une présentation de 5 slides avec ces chiffres : CA 2023 1,2 M€, 2024 1,5 M€",
        "fais une presentation avec nos chiffres 2025 : CA 3,2 M€, marge 12 %, 45 salariés",
        "Traduis ce texte en anglais\nDevis 1 – Alpha : 12 000 €\nDevis 2 – Beta : 10 500 €",
        "Rédige un mail à Sophie pour lui envoyer le compte rendu\nPrésents : Marie Dupont, Julien Martin",
        "Fais une présentation de 5 slides sur notre nouvelle charte qualité",
        "Voici mon planning : lundi réunion, mardi formation",
    ],
)
def test_auto_stays_single_agent(text):
    assert decide(text).recipe is None
