"""Deterministic reading of the user's own words: places, company, currency (birds.harness.intents)."""

import pytest

from birds.harness import intents

PLACES = [
    ("Restaurants près de la gare de Lyon", {"query": "restaurant", "near": "gare de Lyon"}, "near"),
    (
        "Trouve-moi une pharmacie à côté de la place de la Nation",
        {"query": "pharmacy", "near": "place de la Nation"},
        "near",
    ),
    ("des hôtels autour de la gare Part-Dieu", {"query": "hotel", "near": "gare Part-Dieu"}, "near"),
    ("un parking proche de l'Opéra de Lyon", {"query": "parking", "near": "Opéra de Lyon"}, "near"),
    ("Hotels near the Eiffel Tower", {"query": "hotel", "near": "Eiffel Tower"}, "near"),
    ("coffee shops close to King's Cross", {"query": "cafe", "near": "King's Cross"}, "near"),
    ("Où se trouve la tour Eiffel ?", {"query": "tour Eiffel"}, "where"),
    ("Où est le siège de l'Unesco ?", {"query": "siège de l'Unesco"}, "where"),
    ("Where is the Louvre?", {"query": "Louvre"}, "where"),
    ("Donne-moi une carte de Bordeaux", {"query": "Bordeaux"}, "where"),
    ("Quelle est l'adresse de la mairie de Nantes ?", {"query": "mairie de Nantes"}, "where"),
    ("Itinéraire de la gare de Lyon à la tour Eiffel", {"query": "tour Eiffel", "near": "gare de Lyon"}, "route"),
    ("Comment aller au Mont-Saint-Michel ?", {"query": "Mont-Saint-Michel"}, "route"),
    (
        "Compare ces 3 sites pour notre nouvelle agence : Lyon Part-Dieu, Lille Europe, Nantes",
        {"query": "Lyon Part-Dieu ; Lille Europe ; Nantes"},
        "list",
    ),
    ("Mets sur une carte nos agences : Rennes, Brest et Quimper", {"query": "Rennes ; Brest ; Quimper"}, "list"),
    (
        "Quelle est l'adresse de notre client au 20 avenue de Ségur à Paris ? Fais-moi un plan d'accès.",
        {"query": "20 avenue de Ségur Paris"},
        "address",
    ),
]

NOT_PLACES = [
    "Où en est le projet Alpha ?",
    "Quelle est l'adresse mail de Paul ?",
    "Ma carte graphique chauffe",
    "Fais-moi un plan d'action pour le lancement",
    "Rédige un business plan",
    "Où se trouve le bouton d'export ?",
    "Comment ajouter une carte dans PowerPoint ?",
    "Résume ce document",
    "Écris un mail à Paul",
    "Quelle est l'adresse IP du serveur ?",
    "C'est quoi un plan comptable ?",
    "Where is the settings menu?",
    "Fais une présentation sur nos ventes",
    "Où est le fichier budget.xlsx ?",
]


# office questions whose object is a document, a meeting or a person: no place intent at all (never geocoded)
NO_PLACE_INTENT = [
    "Où est le contrat de Paul Martin ?",
    "Donne-moi l'adresse de Jean Dupont, mon collègue",
    "Adresse de facturation du client Dupont ?",
    "Where is the Q3 report?",
    "c'est où la réunion de demain ?",
    "where does John Smith live",
    "Où habite Marie Durand ?",
    "Où est Paul ?",
    "Où sont les fichiers de la compta ?",
    "Comment aller à l'essentiel dans une présentation ?",
    "Situe le contexte de cette réunion",
    "Où est la réunion de demain ?",
    "Où sont les dossiers du client ?",
    "Restaurants près de chez Paul",
]


@pytest.mark.parametrize("text", NO_PLACE_INTENT)
def test_documents_meetings_and_people_are_not_places(text):
    assert intents.places(text) is None
    assert not [i for i in intents.detect(text) if i.tool == "find_places"]


@pytest.mark.parametrize("text", ["Où se trouve Lyon ?", "Situe Brest sur une carte", "Where is New York?"])
def test_proper_nouns_are_places(text):
    got = intents.places(text)
    assert got is not None and got.args and got.mode == "where"


@pytest.mark.parametrize("text", ["Où est montmartre la nuit ?", "c'est où le meilleur coin pour un pique-nique"])
def test_vague_targets_are_only_offered(text):
    got = intents.places(text)
    assert got is not None and got.args is None


# ordinary office phrasing: no extra tool offered at all (the trained tool block stays byte for byte)
NO_TOOL = [
    "Fais-moi un plan pour la présentation du budget 2027",
    "Fais-moi un plan de la note : introduction, constat, propositions",
    "Rédige une réponse polie à un fournisseur qui augmente ses prix de 8 %",
    "Le restaurant d'entreprise ferme à 14h, préviens l'équipe",
    "Qui est le fournisseur d'électricité le moins cher ?",
    "Notre entreprise recrute : rédige l'annonce",
]


@pytest.mark.parametrize("text", NO_TOOL)
def test_common_office_words_offer_no_tool(text):
    assert intents.detect(text) == []


def test_built_in_example_prompts_offer_no_extra_tool():
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "birds" / "web" / "static" / "i18n.js").read_text(encoding="utf-8")
    prompts = re.findall(r'"ex\.[\w.]+\.prompt":\s*"((?:[^"\\]|\\.)*)"', js)
    assert len(prompts) >= 8
    for p in prompts:
        assert intents.detect(p) == [], p


@pytest.mark.parametrize("text,args,mode", PLACES)
def test_place_asks_are_prefilled(text, args, mode):
    got = intents.places(text)
    assert got is not None and got.args == args and got.mode == mode


@pytest.mark.parametrize("text", NOT_PLACES)
def test_place_look_alikes_are_ignored(text):
    got = intents.places(text)
    assert got is None or got.args is None
    assert not [i for i in intents.detect(text) if i.args and i.tool == "find_places"]


def test_deictic_follow_up_is_only_offered():
    got = intents.places("Et des hôtels près de là ?")
    assert got is not None and got.tool == "find_places" and got.args is None


def test_attachment_address_is_never_prefilled():
    text = "Fais un plan d'accès pour le 20 avenue de Ségur 75007 Paris"
    assert intents.detect(text)[0].args
    found = intents.detect(text, attached=True)
    assert found and found[0].args is None


def test_split_near_for_a_model_call():
    assert intents.split_near("restaurants près de la gare de Lyon") == ("restaurant", "gare de Lyon")
    assert intents.split_near("tour Eiffel") is None


# ---------------------------------------------------------------- company


@pytest.mark.parametrize(
    "digits,valid",
    [("383474814", True), ("383474815", False), ("38347481400100", True), ("732829320", True), ("123456789", False)],
)
def test_luhn(digits, valid):
    assert intents.luhn(digits) is valid


@pytest.mark.parametrize(
    "text,name",
    [
        ("SIREN 383474814 : c'est quelle entreprise et où est son siège ?", "383474814"),
        ("siren 383 474 814", "383474814"),
        ("le SIRET 383 474 814 00100 est-il actif ?", "38347481400100"),
        ("Donne-moi la fiche de la société Airbus", "Airbus"),
        ("Infos sur l'entreprise Michelin", "Michelin"),
        ("Quelle est l'adresse de notre client Dupont SA ?", "Dupont SA"),
        ("Qui est le fournisseur Schneider Electric ?", "Schneider Electric"),
        ("Tell me about the company Danone", "Danone"),
        ("coordonnées de la société Orange", "Orange"),
    ],
)
def test_company_asks_are_prefilled(text, name):
    got = intents.company(text)
    assert got is not None and got.args == {"name": name}


@pytest.mark.parametrize(
    "text",
    ["la société est en croissance", "SIREN 383474815 ?", "Combien coûte une société en 2026 ?", "Écris un poème"],
)
def test_company_negatives_are_not_prefilled(text):
    got = intents.company(text)
    assert got is None or got.args is None


def test_company_wins_over_places():
    found = intents.detect("Quelle est l'adresse de la société Airbus ?")
    assert found[0].tool == "find_company" and found[0].args == {"name": "Airbus"}
    assert any(i.tool == "find_places" and i.args is None for i in found)


# ---------------------------------------------------------------- currency


@pytest.mark.parametrize(
    "text,args,keep_web",
    [
        ("Convertis 1 200 dollars en euros", {"from": "USD", "to": "EUR", "amount": 1200.0}, False),
        ("Quel est le taux de change euro livre sterling ?", {"from": "EUR", "to": "GBP"}, False),
        ("combien font 50 € en francs suisses", {"from": "EUR", "to": "CHF", "amount": 50.0}, False),
        ("1,5 M$ en euros", {"from": "USD", "to": "EUR", "amount": 1_500_000.0}, False),
        ("how much is 300 GBP in USD", {"from": "GBP", "to": "USD", "amount": 300.0}, False),
        ("EUR/USD", {"from": "EUR", "to": "USD"}, False),
        ("12.50 USD to JPY", {"from": "USD", "to": "JPY", "amount": 12.5}, False),
        ("€1200 in dollars", {"from": "EUR", "to": "USD", "amount": 1200.0}, False),
        ("évolution du taux de change euro dollar depuis 2020", {"from": "EUR", "to": "USD"}, True),
        ("1.200,50 euros en yens", {"from": "EUR", "to": "JPY", "amount": 1200.5}, False),
    ],
)
def test_fx_asks(text, args, keep_web):
    got = intents.fx(text)
    assert got is not None and got.args == args and got.keep_web is keep_web


@pytest.mark.parametrize("text", ["50 balles en euros", "Le dollar est-il fort ?", "Écris un mail à Paul"])
def test_fx_negatives(text):
    got = intents.fx(text)
    assert got is None or got.args is None


def test_parse_amount():
    assert intents.parse_amount("1 200") == 1200
    assert intents.parse_amount("1,5 M") == 1_500_000
    assert intents.parse_amount("12.50") == 12.5
    assert intents.parse_amount("1.200,50") == 1200.5
    assert intents.parse_amount("abc") is None


def test_ordinary_turns_have_no_intent():
    for text in ["Écris un mail de relance à Paul", "Résume ce texte", "Fais une présentation de 4 slides"]:
        assert intents.detect(text) == []
