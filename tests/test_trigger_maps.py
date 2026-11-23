"""Trigger audit, maps: a named landmark is looked up whole, a route goes to its destination, a town typed in
lowercase or after a polite lead-in still gets a map, and abstract « où est … » questions never reach the geocoder."""

from __future__ import annotations

import pytest

from birds.harness import intents


def _call(text):
    got = intents.places(text)
    return got and got.args and (got.args, got.mode)


@pytest.mark.parametrize(
    "text,query",
    [
        ("où est la gare de Lyon ?", "gare de Lyon"),
        ("ou est la gare de lyon", "gare de lyon"),
        ("c'est où le musée d'Orsay ?", "musée d'Orsay"),
        ("où est l'hôtel de ville de Lyon ?", "hôtel de ville de Lyon"),
        ("où se trouve la gare de l'Est", "gare de l'Est"),
    ],
)
def test_a_singular_landmark_is_one_place_not_a_kind_in_a_town(text, query):
    assert _call(text) == ({"query": query}, "where")


@pytest.mark.parametrize(
    "text,args,mode",
    [
        ("où sont les pharmacies de Nantes", {"query": "pharmacy", "near": "Nantes"}, "near"),
        ("où se situent les parkings de aix", {"query": "parking", "near": "aix"}, "near"),
        ("les parkings de aix", {"query": "parking", "near": "aix"}, "near"),
        ("pharmacie de garde a toulouse", {"query": "pharmacy", "near": "toulouse"}, "near"),
        ("un parking proche de l'Opéra de Lyon", {"query": "parking", "near": "Opéra de Lyon"}, "near"),
    ],
)
def test_a_plural_kind_in_a_town_is_still_a_near_search(text, args, mode):
    assert _call(text) == (args, mode)


@pytest.mark.parametrize(
    "text,query",
    [
        ("où se trouve la Banque de France", "Banque de France"),
        ("adresse de la Banque de France à Lyon", "Banque de France à Lyon"),
        ("où se trouve l'hôtel de la Paix à Genève", "hôtel de la Paix à Genève"),
    ],
)
def test_a_named_place_starting_with_a_kind_noun_is_looked_up_whole(text, query):
    assert _call(text) == ({"query": query}, "where")


@pytest.mark.parametrize(
    "text",
    [
        "où est la différence entre SAS et SARL ?",
        "where is the value in this deal",
        "où est le problème ?",
        "où est l'intérêt de faire ça",
        "ou est sophie",
        "où est passée ma commande ?",
        "c'est où que je change le mot de passe ?",
        "c'est où demain ?",
    ],
)
def test_abstract_or_personal_targets_are_not_places(text):
    assert intents.places(text) is None


@pytest.mark.parametrize(
    "text,args",
    [
        ("comment aller à la tour Eiffel depuis la gare de Lyon", {"query": "tour Eiffel", "near": "gare de Lyon"}),
        ("how to get to Orly from Paris", {"query": "Orly", "near": "Paris"}),
        ("how do i get to the airport from the city center", {"query": "airport", "near": "city center"}),
        ("itinéraire Lyon Grenoble", {"query": "Grenoble", "near": "Lyon"}),
        ("trajet paris marseille", {"query": "marseille", "near": "paris"}),
    ],
)
def test_routes_go_to_the_destination_from_the_start(text, args):
    assert _call(text) == (args, "route")


@pytest.mark.parametrize(
    "text", ["trajet domicile travail", "quel est le meilleur trajet de formation pour un manager"]
)
def test_bare_trajet_needs_two_places(text):
    assert not _call(text)


@pytest.mark.parametrize(
    "text,query",
    [
        ("ou est nantes", "nantes"),
        ("où se trouve clermont-ferrand", "clermont-ferrand"),
        ("c'est où vierzon ?", "vierzon"),
        ("where is lyon", "lyon"),
        ("carte de la bretagne", "bretagne"),
        ("montre-moi Lyon sur une carte", "Lyon"),
        ("situe nantes sur une carte", "nantes"),
    ],
)
def test_a_town_in_lowercase_or_an_explicit_map_gets_a_map(text, query):
    assert _call(text) == ({"query": query}, "where")


def test_a_lowercase_phrase_with_an_article_stays_an_offer():
    got = intents.places("Où est montmartre la nuit ?")
    assert got is not None and got.args is None


@pytest.mark.parametrize(
    "text,query",
    [
        (
            "bonjour, pourriez-vous m'indiquer où se trouve la gare de Bordeaux Saint-Jean ?",
            "gare de Bordeaux Saint-Jean",
        ),
        ("est-ce que tu peux me dire où est la gare Montparnasse", "gare Montparnasse"),
        ("dis-moi où se trouve la tour Eiffel", "tour Eiffel"),
        ("je voudrais l'adresse de la mairie de Lyon", "mairie de Lyon"),
        ("what's the address of the Louvre museum", "Louvre museum"),
    ],
)
def test_polite_lead_ins_are_stripped(text, query):
    assert _call(text) == ({"query": query}, "where")


@pytest.mark.parametrize(
    "text,args,mode",
    [
        ("où est située la tour Eiffel ?", {"query": "tour Eiffel"}, "where"),
        ("c'est où exactement Toussus-le-Noble ?", {"query": "Toussus-le-Noble"}, "where"),
        ("ou est situee la ville de Lens", {"query": "Lens"}, "where"),
        ("des hôtels à proximité du palais des congrès", {"query": "hotel", "near": "palais des congrès"}, "near"),
    ],
)
def test_filler_words_stay_out_of_the_geocoder_query(text, args, mode):
    assert _call(text) == (args, mode)


def test_a_legal_question_keeps_the_web_and_calls_no_map():
    assert intents.detect("où est la différence entre SAS et SARL ?") == []


@pytest.mark.parametrize(
    "text",
    [
        "carte de vœux pour nos clients",
        "carte des vins pour le séminaire",
        "carte de crédit perdue, que faire ?",
        "carte de séjour d'un salarié étranger : quelles démarches ?",
    ],
)
def test_a_card_that_is_not_a_map_calls_nothing(text):
    assert intents.detect(text) == []


@pytest.mark.parametrize(
    "text,query", [("carte de Lyon", "Lyon"), ("carte de l'Europe", "Europe"), ("carte de la bretagne", "bretagne")]
)
def test_a_map_of_a_place_is_still_drawn(text, query):
    assert _call(text) == ({"query": query}, "where")


@pytest.mark.parametrize("text", ["où est Excel ?", "où est Teams ?", "ou est outlook", "where is Excel?"])
def test_office_software_is_never_a_place(text):
    assert intents.places(text) is None


@pytest.mark.parametrize("text", ["où est Dupont ?", "où est Martin ?", "carte du réseau commercial"])
def test_an_unknown_lone_name_or_a_lowercase_phrase_is_only_offered(text):
    got = intents.places(text)
    assert got is not None and got.args is None


def test_a_capitalised_known_town_still_gets_a_map():
    assert _call("où est Biarritz") == ({"query": "Biarritz"}, "where")


@pytest.mark.parametrize("text", ["les restaurants du coin", "les hôtels du centre"])
def test_a_kind_near_an_unnamed_spot_is_only_offered(text):
    got = intents.places(text)
    assert got is not None and got.args is None


@pytest.mark.parametrize("text", ["trajet client fournisseur", "itinéraire marketing digital", "itinéraire client idéal"])
def test_a_customer_journey_is_not_a_route(text):
    assert not _call(text)


@pytest.mark.parametrize(
    "text,args",
    [
        ("trajet vierzon -> bourges", {"query": "bourges", "near": "vierzon"}),
        ("trajet roanne → vichy", {"query": "vichy", "near": "roanne"}),
    ],
)
def test_an_arrow_joins_two_stops(text, args):
    assert _call(text) == (args, "route")


@pytest.mark.parametrize("text", ["mets ça sur la carte", "ajoute ce point sur la carte", "mets les sur la carte"])
def test_a_pointer_put_on_the_map_is_only_offered(text):
    got = intents.places(text)
    assert got is not None and got.args is None


def test_a_verb_before_a_town_on_the_map_is_dropped():
    assert _call("Mets Lyon sur la carte") == ({"query": "Lyon"}, "where")
