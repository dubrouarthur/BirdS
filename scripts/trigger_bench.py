"""Trigger bench: does Bird offer or start the right rich content for realistic phrasings?

Run: .venv/bin/python -I scripts/trigger_bench.py  (no network, no model). Prints misses and a score per family.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from birds.harness import clock, crew, intents  # noqa: E402
from birds.harness.agent import route  # noqa: E402

CHART_YES = [
    "fais un graphique des ventes : janvier 120, février 135, mars 160",
    "montre-moi l'évolution du chômage en France depuis 2015",
    "la population de Paris évolue comment depuis 2012 ?",
    "trace la courbe du CA 2021 120k 2022 150k 2023 180k",
    "visualise ces chiffres : Nord 30 %, Sud 45 %, Est 25 %",
    "compare en barres les budgets 2024 et 2025",
    "un camembert de la répartition des dépenses",
    "peux-tu représenter graphiquement ces données",
    "histogramme des notes de satisfaction",
    "show me a chart of revenue by quarter",
    "plot the inflation in France over the last 10 years",
    "quelle est la tendance des prix de l'immobilier à Lyon ?",
    "fais un diagramme de la part de marché des 3 concurrents",
    "graphe des visites mensuelles du site",
    "dessine-moi une courbe de croissance",
    "mets ça sous forme de graphique",
    "en image s'il te plaît, sous forme de barres",
    "compare l'évolution du PIB de la France et de l'Allemagne depuis 2000",
]
CHART_NO = [
    "rédige un mail à Paul pour la réunion de lundi",
    "quelle est la charte graphique de notre marque ?",
    "explique-moi la courbe en J",
    "résume ce document en 5 points",
    "traduis ce texte en anglais",
    "écris une fonction Python qui trie une liste",
]
MAP_YES = [
    "où est la tour Eiffel ?",
    "ou es la boutique du pilote a toussus",
    "où se situent les parkings de aix",
    "restaurants près de la gare de Lyon",
    "trouve-moi une pharmacie à Nantes",
    "adresse de la mairie de Bordeaux",
    "c'est où le siège d'Airbus ?",
    "montre-moi sur une carte les agences de Lyon, Marseille et Lille",
    "itinéraire pour aller à la gare Montparnasse",
    "quels hôtels y a-t-il autour de l'aéroport de Nice ?",
    "where is the Louvre?",
    "coffee shops near Times Square",
    "localise le stade de France",
    "je cherche un garage à Versailles",
    "y a-t-il un parking près de la place Bellecour ?",
]
MAP_NO = [
    "où en est le projet ?",
    "où est le contrat de Paul Martin ?",
    "quelle est l'adresse mail du support ?",
    "fais une carte mentale de mes idées",
    "un plan d'action pour le trimestre",
    "ma carte graphique chauffe, que faire ?",
    "où est passé mon fichier ?",
]
WEATHER_YES = [  # (phrase, the place the harness must pre-call get_weather with)
    ("météo à Lyon demain", "Lyon"),
    ("il va pleuvoir à Nantes ?", "Nantes"),
    ("quel temps pour jeudi à Lille", "Lille"),
    ("weather in London tomorrow", "London"),
    ("Quel temps fera-t-il à Paris ce week-end ?", "Paris"),
    ("meteo bordeaux", "bordeaux"),
    ("prévisions météo pour Strasbourg cette semaine", "Strasbourg"),
    ("est-ce qu'il pleut à Brest en ce moment", "Brest"),
    ("va-t-il neiger à Chamonix samedi ?", "Chamonix"),
    ("il fait beau à Nice ?", "Nice"),
    ("do I need an umbrella in Paris tomorrow?", "Paris"),
    ("will it rain in Berlin on Friday?", "Berlin"),
    ("la météo de Marseille pour demain stp", "Marseille"),
    ("quelle température à Toulouse demain ?", "Toulouse"),
    ("réunion jeudi à Lille, il va pleuvoir ?", "Lille"),
    ("météo à la gare de Lyon ce soir", "gare de Lyon"),
]
WEATHER_NO = [
    "le climat social est tendu, que faire ?",
    "fais-moi la météo des marchés",
    "comment réduire le temps de réponse du serveur ?",
    "il fait beau ce projet",
    "la météo sociale de l'entreprise",
    "quel est le temps de trajet entre Lyon et Paris ?",
    "une pluie de critiques sur le projet",
    "sales forecast for Q3",
    "règle la température du modèle à 0,7",
    "rédige un mail à Paul pour la réunion de lundi",
    "en même temps, il faut finir le budget",
    "Quel temps de livraison pour un colis vers Lyon ?",
    "Quel temps de préparation pour le dossier Martin ?",
    "Quel temps faut-il pour traiter une commande ?",
    "Quel temps de validation pour les notes de frais ?",
    "Quel temps de cuisson pour un rôti ?",
    "Il pleut des bugs en production depuis la mise à jour",
    "Il neige des tickets au support ce matin",
    "Le parapluie de garantie couvre-t-il notre filiale de Lille ?",
    "Je veux un parapluie publicitaire avec notre logo pour le salon de Lyon",
    "Le projet Météo à Toulouse est en retard",
    "les prévisions météo du chiffre d'affaires",
    "Draft an email about the weather station product launch in Berlin",
]
CLOCK_YES = [  # (phrase, cities the card must show besides the user's)
    ("quelle heure est-il à New York", ["New York"]),
    ("décalage horaire avec Tokyo", ["Tokyo"]),
    ("trouve un créneau commun Paris Montréal Singapour pour une réunion", ["Paris", "Montréal", "Singapour"]),
    ("what time is it in Sydney?", ["Sydney"]),
    ("time difference between Paris and Los Angeles", ["Paris", "Los Angeles"]),
    ("il est quelle heure à Dubaï ?", ["Dubaï"]),
    ("quel est le décalage horaire entre Londres et Singapour ?", ["Londres", "Singapour"]),
    ("quand appeler nos collègues de São Paulo ?", ["São Paulo"]),
    ("best time for a meeting between London and New York", ["Londres", "New York"]),
    ("heure locale à Bombay", ["Bombay"]),
    ("décalage horaire avec les États-Unis", ["Washington"]),
    ("fuseau horaire de Montréal", ["Montréal"]),
    ("quel créneau pour la réunion avec Tokyo ?", ["Tokyo"]),  # « la réunion » is a meeting, not the island
    ("décalage horaire avec New York pour la réunion de lundi", ["New York"]),
    ("quelle heure est-il à la Réunion ?", ["Saint-Denis (La Réunion)"]),
]
CLOCK_NO = [
    "à quelle heure est la réunion ?",
    "heure de pointe à Paris, quel itinéraire ?",
    "trouve un créneau commun avec Paul et Marie",
    "quelle heure pour le déjeuner avec Paul ?",
    "combien d'heures sup ce mois-ci ?",
    "mets un rappel à 14h",
    "time management tips for managers",
    "trouve un créneau pour une réunion à Lyon",
    "combien d'heures de vol entre Paris et Tokyo ?",
    "Trouve un créneau avec Lyon pour la réunion budget",
]
AGENT_YES = [
    "Prépare une présentation de 6 slides sur le télétravail en France depuis 2019 avec des chiffres sourcés",
    "Fais une étude comparative des 3 principaux CRM du marché avec un tableau et une recommandation",
    "Rédige un rapport sur la transition énergétique des PME françaises avec des chiffres récents et des sources",
    "Compare les offres de ces trois fournisseurs et rédige un mail de recommandation : Devis 1 – Alpha 12 000 €, "
    "Devis 2 – Beta 10 500 €, Devis 3 – Gamma 11 200 €",
    "Fais un dossier de veille sur l'IA générative en entreprise en 2026 : tendances, chiffres, risques",
    "Prépare un deck de présentation de notre offre pour un client, avec le marché, la concurrence et les prix",
]
AGENT_NO = [
    "Bonjour",
    "Rédige un mail court pour décaler la réunion",
    "Combien font 17 % de 3 450 € ?",
    "Explique la différence entre CDD et CDI",
    "Traduis ce paragraphe en anglais",
]


def chart_offered(q: str) -> bool:
    return "make_chart" not in route(q)


def map_detected(q: str) -> bool:
    return any(i.tool == "find_places" for i in intents.detect(q, False, "fr"))


def weather_called(q) -> bool:
    """YES items: pre-called with the expected place. NO items: no get_weather at all (not even offered)."""
    text, place = q if isinstance(q, tuple) else (q, None)
    found = [i for i in intents.detect(text, False, "fr") if i.tool == "get_weather"]
    if place is None:
        return bool(found)
    return bool(found and found[0].args and found[0].args["place"] == place)


def clock_shown(q) -> bool:
    """YES items: a clock card with exactly these cities (in order). NO items: no clock card."""
    text, cities = q if isinstance(q, tuple) else (q, None)
    found = clock.detect(text)
    card = clock.card(found, datetime(2026, 11, 23, 9, 30, tzinfo=ZoneInfo("Europe/Paris")), "fr") if found else None
    if cities is None:
        return bool(card)
    return bool(card) and [c["fr"] for c in found["cities"]] == cities


def agent_on(q: str) -> bool:
    return bool(crew.decide(q, mode="auto", lang="fr").recipe)


def bench(name: str, yes: list[str], no: list[str], fn) -> tuple[int, int]:
    miss = [q for q in yes if not fn(q)]
    false = [q for q in no if fn(q)]
    for q in miss:
        print(f"  MISS  [{name}] {q}")
    for q in false:
        print(f"  FALSE [{name}] {q}")
    ok = len(yes) - len(miss) + len(no) - len(false)
    print(f"{name}: {ok}/{len(yes) + len(no)}  (missed {len(miss)}/{len(yes)}, false {len(false)}/{len(no)})")
    return ok, len(yes) + len(no)


if __name__ == "__main__":
    bench("charts", CHART_YES, CHART_NO, chart_offered)
    bench("maps", MAP_YES, MAP_NO, map_detected)
    bench("weather", WEATHER_YES, WEATHER_NO, weather_called)
    bench("clock", CLOCK_YES, CLOCK_NO, clock_shown)
    bench("agent", AGENT_YES, AGENT_NO, agent_on)
