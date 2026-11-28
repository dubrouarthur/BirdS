"""Trigger bench: does Bird offer or start the right rich content for realistic phrasings?

Run: .venv/bin/python -I scripts/trigger_bench.py  (no network, no model). Prints misses and a score per family.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from birds.canvas import intents as canvas_intents  # noqa: E402
from birds.harness import clock, crew, followup, intents, when  # noqa: E402
from birds.harness.agent import (  # noqa: E402
    _previous_answer,
    chart_ask,
    chart_call,
    detect_lang,
    figures_in,
    route,
)
from birds.web.widgets import event_widget  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_maps  # noqa: E402  (maps: 200 realistic asks + 60 office prompts, 30 + 15 held out)

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
    # a person addressed before the place (« à Julie qui … ») is never the place
    ("Réponds à Julie qui me demande s'il fera beau à Nice ce week-end", "Nice"),
    ("Dis à Paul qu'il fera beau à Lyon demain ?", "Lyon"),
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
    # a reply or a message to write: the weather words are in the text handed over, not asked of Bird
    "Réponds à ce message : « Salut, tu viens à Nantes vendredi ? Il paraît qu'il va pleuvoir. »",
    "Écris un SMS à ma femme : je rentre tard, il neige à Grenoble",
    "Relis ce message : il va pleuvoir à Lyon demain, prends ton parapluie",
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
    ("une visio entre Londres et Singapour demain ?", ["Londres", "Singapour"]),
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
    "J'ai un point avec Nice entre 10h et 11h",
    "Fais le point entre l'équipe de Paris et celle de Lyon sur le projet",
    "point avec Londres entre 10h et 11h",
    "call avec Montréal entre 9h et 10h",
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


# ---------------------------------------------------------------- trigger audit: realistic phrasings per family
# Stricter than the lists above: a "yes" must START the rich content (the harness pre-call, args set: the model was
# never trained on these tools, an offer alone draws nothing), and a "no" must not even offer it.
CHART_YES2 = [
    "fais moi un graphique des ventes : janvier 120, fevrier 135, mars 160, avril 150",
    "tu peux me faire un camembert avec : marketing 40%, RH 25%, IT 35%",
    "graphique en barres : 2021 100, 2022 120, 2023 130",
    "CA 2022 : 1,2 M€, 2023 : 1,5 M€, 2024 : 1,9 M€. Fais un graphique",
    "nombre de tickets par semaine : S1 45, S2 52, S3 61, S4 58 — sous forme de courbe",
    "répartition des effectifs : 45 % CDI, 30 % CDD, 25 % intérim, en camembert svp",
    "represente graphiquement la repartition : cadres 30 %, employes 50 %, ouvriers 20 %",
    "tu peux mettre ces chiffres en graphique ?",
    "mets ça en graphique",
    "fais-en un camembert",
    "tu peux le mettre en courbe ?",
    "refais le en barres",
    "la population de Paris depuis 2012",
    "la population de Lyon ces 10 dernieres annees",
    "le chiffre d'affaires de LVMH sur les 5 dernières années",
    "progression des ventes en ligne en France de 2015 à 2024",
    "historique du prix du baril de petrole",
    "le smic depuis 10 ans",
    "evolution du chomage en france depuis 2010",
    "comment a evolue le prix du gaz entre 2020 et 2024 ?",
    "le cac 40 depuis 2015",
    "make a pie chart: rent 1200, food 400, transport 150",
    "can you graph this for me",
    "how has the population of london changed since 2000?",
    "population of france from 2000 to 2020",
    "diagramme des parts de marche : Apple 28%, Samsung 22%, Xiaomi 14%, autres 36%",
    "fais une courbe de l'inflation en France sur 10 ans",
]
CHART_NO2 = [
    "redige une charte graphique pour notre startup",
    "explique-moi la courbe en j des investissements",
    "notre courbe d'apprentissage sur le nouvel outil est lente, des conseils ?",
    "quelle carte graphique acheter pour de la 3D ?",
    "fais un diagramme de Gantt du projet",
    "dessine un diagramme de flux pour le processus de commande",
    "fais un diagramme de séquence UML",
    "je suis dans l'entreprise depuis 2019, aide-moi à rédiger ma demande d'augmentation",
    "rédige un mail : le client est en retard de paiement depuis 2023",
    "la tendance mode de cet hiver ?",
    "quelles sont les tendances du marketing digital en 2026 ?",
    "l'evolution de carriere d'un comptable",
    "comment evoluer vers un poste de manager ?",
    "c'est quoi un histogramme ?",
    "comment faire un graphique dans Excel ?",
    "le designer a envoyé la nouvelle identité graphique, tu peux rédiger un mail de remerciement ?",
    "calcule la TVA sur 1 500 € HT",
    "fais un tableau des taches de la semaine",
    # a table asked for, figures given: a table, never a chart (found in the app with the model router)
    "Mets en forme ce tableau : Paris 12, Lyon 8, Marseille 5",
    "présente ces chiffres sous forme de tableau : Q1 40, Q2 55, Q3 61",
    "format this table: Berlin 7, Madrid 4, Rome 3",
]
# the user's own figures in these asks: the harness draws them (exact rows, type named)
CHART_FIGURES = {
    "fais moi un graphique des ventes : janvier 120, fevrier 135, mars 160, avril 150": ("line", 4),
    "tu peux me faire un camembert avec : marketing 40%, RH 25%, IT 35%": ("pie", 3),
    "graphique en barres : 2021 100, 2022 120, 2023 130": ("bar", 3),
    "CA 2022 : 1,2 M€, 2023 : 1,5 M€, 2024 : 1,9 M€. Fais un graphique": ("line", 3),
    "nombre de tickets par semaine : S1 45, S2 52, S3 61, S4 58 — sous forme de courbe": ("line", 4),
    "répartition des effectifs : 45 % CDI, 30 % CDD, 25 % intérim, en camembert svp": ("pie", 3),
    "represente graphiquement la repartition : cadres 30 %, employes 50 %, ouvriers 20 %": ("pie", 3),
    "make a pie chart: rent 1200, food 400, transport 150": ("pie", 3),
    "diagramme des parts de marche : Apple 28%, Samsung 22%, Xiaomi 14%, autres 36%": ("pie", 4),
}
MAP_YES2 = [
    "ou est la gare de lyon",
    "c'est où le musée d'Orsay ?",
    "où est l'hôtel de ville de Lyon ?",
    "où se trouve la Banque de France",
    "adresse de la Banque de France à Lyon",
    "les parkings de aix",
    "où sont les pharmacies de Nantes",
    "ou est nantes",
    "où se trouve clermont-ferrand",
    "c'est où vierzon ?",
    "where is lyon",
    "carte de la bretagne",
    "montre-moi Lyon sur une carte",
    "situe nantes sur une carte",
    "où est située la tour Eiffel ?",
    "c'est où exactement Toussus-le-Noble ?",
    "bonjour, pourriez-vous m'indiquer où se trouve la gare de Bordeaux Saint-Jean ?",
    "est-ce que tu peux me dire où est la gare Montparnasse",
    "dis-moi où se trouve la tour Eiffel",
    "je voudrais l'adresse de la mairie de Lyon",
    "what's the address of the Louvre museum",
    "des hôtels à proximité du palais des congrès",
    "comment aller à la tour Eiffel depuis la gare de Lyon",
    "how to get to Orly from Paris",
    "itinéraire Lyon Grenoble",
    "trajet paris marseille",
    "trouve moi un hotel pas cher a lyon",
    "y a t il une boulangerie pres de la gare de rennes",
    "je cherche un coworking a bordeaux svp",
    "pharmacie de garde a toulouse",
    "hotel a lyon part dieu",
    "directions from London to Oxford",
    "une station service a cote de l'aeroport de nice",
    "où se trouve le 10 rue de la paix 75002 paris ?",
]
MAP_NO2 = [
    "où est la différence entre SAS et SARL ?",
    "where is the value in this deal",
    "où est le problème ?",
    "où est l'intérêt de faire ça",
    "ou est sophie",
    "où est passée ma commande ?",
    "c'est où que je change le mot de passe ?",
    "où est Jean ?",
    "where is John?",
    "ou en est le dossier client",
    "où est mon fichier excel",
    "ou est le rapport Q3",
    "fais-moi une carte de visite",
    "un plan de table pour le mariage",
    "quelle est l'adresse ip du serveur",
    "where is the meeting tomorrow?",
    "locate the bug in this function",
    "où se trouve l'erreur dans ce code",
    "où se situe le point mort ?",
    "c'est où le pot de départ de Julie ?",
    "quel est le meilleur trajet de formation pour un manager",
    "où se trouve le bouton enregistrer",
    "on en est où sur la facture ?",
]
# what the map must look for (query, near): a named landmark stays whole, a route goes to its destination
MAP_ARGS = {
    "ou est la gare de lyon": ("gare de lyon", None),
    "c'est où le musée d'Orsay ?": ("musée d'Orsay", None),
    "où est l'hôtel de ville de Lyon ?": ("hôtel de ville de Lyon", None),
    "où se trouve la Banque de France": ("Banque de France", None),
    "les parkings de aix": ("parking", "aix"),
    "comment aller à la tour Eiffel depuis la gare de Lyon": ("tour Eiffel", "gare de Lyon"),
    "how to get to Orly from Paris": ("Orly", "Paris"),
    "des hôtels à proximité du palais des congrès": ("hotel", "palais des congrès"),
    "où est située la tour Eiffel ?": ("tour Eiffel", None),
    "c'est où exactement Toussus-le-Noble ?": ("Toussus-le-Noble", None),
}
COMPANY_FX_YES = [
    "fiche de l'entreprise Doctolib",
    "fiche entreprise doctolib",
    "qui dirige Michelin ?",
    "qui dirige la société Decathlon",
    "c'est quoi le siren de Free ?",
    "siren 552 100 554",
    "verifie le siren 732 829 320 stp",
    "siret 55210055400013",
    "donne moi les infos sur la société Back Market",
    "chiffre d'affaires de Leroy Merlin",
    "quel est le chiffre d'affaires de la société Ornikar ?",
    "le CA de Carrefour en 2024",
    "peux-tu me trouver le kbis de la société Alan",
    "infos sur notre fournisseur Manutan",
    "infos sur l'entreprise blablacar stp",
    "qui sont les dirigeants de Qonto ?",
    "numero de tva de la societe Malt",
    "combien de salariés chez Doctolib",
    "look up the company Mistral AI",
    "who runs Danone?",
    "120 $ en euros",
    "combien vaut 1 000 CHF",
    "combien vaut 1 000 CHF en euros",
    "taux USD/EUR",
    "taux de change euro dollar",
    "convertis 2500 euros en dollars",
    "250 livres en euros stp",
    "ca fait combien 300 dollars en euros",
    "1,5 M$ en euros",
    "how much is 50 GBP in EUR?",
    "convert 100 usd to eur",
    "quel est le cours du dollar aujourd'hui",
    "500 yens ça fait combien en euros ?",
    "combien font 1200 francs suisses en euro",
    "le taux euro/livre",
    "j'ai une facture de 3 400 USD, ça fait combien en euros ?",
    "convertir 80 euros en dollars canadiens",
    "taux de change eur usd du jour",
]
COMPANY_FX_NO = [
    "fiche de poste pour un commercial",
    "présente notre entreprise en 3 lignes",
    "qu'est-ce que la société civile immobilière ?",
    "le produit coûte 120 €",
    "convertis ce fichier en PDF",
    "convert this docx to pdf",
    "convertis ce texte en majuscules",
    "notre CA 2024 est de 1,2 M€, rédige un commentaire",
    "rédige un mail à notre fournisseur",
    "qui dirige la réunion de demain ?",
    "le prix est de 45 dollars, c'est cher ?",
    "combien vaut un brevet ?",
    "quel est le cours de l'action LVMH",
    "explique ce qu'est un numéro SIREN",
    "comment trouver le siret d'une entreprise ?",
    "mon numéro de téléphone est 06 12 34 56 78",
    "facture n° 123456789",
    "le taux de TVA en France",
    "la société générale a publié ses résultats",
    "quel est le CA de Janvier ?",
    "dirigeants de PME : 5 conseils",
    "le prix est de 30 €/mois",
    "taux d'intérêt du livret A",
]
FX_ARGS = {
    "convertir 80 euros en dollars canadiens": ("EUR", "CAD"),
    "combien vaut 1 000 CHF": ("CHF", "EUR"),
    "le taux euro/livre": ("EUR", "GBP"),
    "500 yens ça fait combien en euros ?": ("JPY", "EUR"),
}
EVENT_YES = [
    "cale une réunion avec Paul jeudi à 14h",
    "cale une reunion avec paul jeudi a 14h",
    "peux-tu planifier un rdv avec le client mardi prochain à 10h30 ?",
    "Réunion avec Sophie demain 15h",
    "rdv chez le dentiste vendredi à 9h",
    "ajoute dans mon agenda un déjeuner avec Marc le 3 décembre à 12h30",
    "mets dans mon calendrier un point avec l'équipe lundi à 9h",
    "organise une visio avec le fournisseur le 12/12 de 14h à 15h",
    "prévois un entretien avec la candidate mercredi 10h",
    "bloque un créneau pour la réunion budget le 2 décembre de 9h à 11h",
    "programme un call avec Julien demain à 17h stp",
    "fixe un rendez-vous avec le comptable le 5 décembre à 11h",
    "je voudrais planifier un séminaire le 20 janvier 2027",
    "schedule a meeting with John next Tuesday at 3pm",
    "book a lunch with the sales team on December 4th at noon",
    "add a call with Anna to my calendar tomorrow at 10am",
    "pose un rdv avec Mme Durand le 28/11 à 16h",
    "Peux tu caler un point avec Karim jeudi 14h ?",
    "rdv client samedi 10h",
    "note dans mon agenda : visio avec Lyon mardi 11h",
    "cale moi un rdv avec le banquier apres-demain a 9h",
    "prends rdv chez le garagiste mercredi à 8h30",
    "cale une réunion pour jeudi 14h",
    "programme un call pour vendredi 11h",
    "peux-tu mettre une réunion avec la direction le 1er décembre à 10h dans mon agenda ?",
    "ajoute au calendrier la réunion de jeudi 14h avec Paul",
    "crée un événement dans mon agenda pour jeudi 14h",
    "génère un fichier ics pour la réunion de jeudi 14h",
    "fais-moi un .ics pour le rdv de vendredi 10h",
    "add the meeting with Paul on Friday at 2pm to my calendar",
    "cale une réunion aujourd'hui à 16h",
]
EVENT_NO = [
    "rédige le compte rendu de la réunion de lundi",
    "annule la réunion de jeudi à 14h",
    "décale le rdv de demain à 16h",
    "comment organiser une réunion efficace ?",
    "résume la réunion d'hier",
    "fais le point sur les ventes d'aujourd'hui",
    "prépare l'ordre du jour de la réunion de mardi",
    "quelle est la date de la prochaine réunion ?",
    "merci pour la réunion de ce matin",
    "écris un mail de remerciement après le rendez-vous de mardi",
    "how do I schedule a meeting in Outlook?",
    "cancel tomorrow's meeting at 3pm",
    "fais une présentation pour la réunion de lundi 10h",
    "recherche les actualités de la réunion du G20 demain",
    "programme une fonction python qui calcule les jours fériés",
    "quelle formation choisir pour apprendre Excel ?",
    "ajoute un point à l'ordre du jour de la réunion de jeudi",
    "explique-moi le format ics",
    "comment ajouter une réunion à mon agenda Outlook ?",
    "quel événement a lieu à Paris ce week-end ?",
    "montre-moi une photo de la tour Eiffel",
]
# the slot the card must show (now = Monday 23 November 2026, 10:00 Paris): never all-day when a time is written
EVENT_SLOTS = {
    "cale une réunion pour jeudi 14h": "2026-11-26 14:00",
    "programme un call pour vendredi 11h": "2026-11-27 11:00",
    "crée un événement dans mon agenda pour jeudi 14h": "2026-11-26 14:00",
    "ajoute au calendrier la réunion de jeudi 14h avec Paul": "2026-11-26 14:00",
}
OFFICE_AGENT_YES = [
    "Compare les offres de ces trois fournisseurs et rédige un mail de recommandation : Devis 1 – Alpha 12 000 €, "
    "Devis 2 – Beta 10 500 €, Devis 3 – Gamma 11 200 €",
    "Compare ces devis et rédige un mail de recommandation :\nDevis 1 – Alpha : 12 000 €\nDevis 2 – Beta : 10 500 €\n"
    "Devis 3 – Gamma : 11 200 €",
    "compare ces offres et fais un rapport :\n1) Alpha 12 000 € HT\n2) Beta 10 500 € HT\n3) Gamma 11 200 € HT",
    "Compare les offres et écris un mail de reco : Offre A : Alpha 12 000 €, Offre B : Beta 10 500 €",
    "quel est le meilleur devis ? redige un mail a mon boss pour justifier\nDevis 1 – Alpha Copieurs : 420 € HT par "
    "mois\nDevis 2 – Beta Bureautique : 390 € HT par mois",
    "Compare these quotes and draft an email recommending the best one:\nOffer A – Alpha 12 000 €\nOffer B – Beta "
    "10 500 €",
    "Peux-tu comparer ces offres et me rédiger une note de synthèse avec ta recommandation ?\nOffre 1 : Alpha 12 000 € "
    "HT\nOffre 2 : Beta 10 500 € HT",
    "Fais le compte rendu de cette réunion avec le tableau des actions :\nPrésents : Marie Dupont, Julien Martin, "
    "Sophie Leroy\n1. Julien relance le sous-traitant avant vendredi.\n2. Sophie organise la visite le 20/11.\n3. Marie "
    "envoie le point au client lundi.",
    "fais moi un compte-rendu propre avec qui fait quoi\nPrésents : Marie Dupont, Julien Martin, Sophie Leroy\nJulien "
    "relance le fournisseur avant le 15/11. Sophie prépare le budget pour le 20/11.",
    "Write the minutes of this meeting with the action items\nParticipants : Anne Vernet, Bruno Caron\nBruno sends the "
    "quote by Friday. Anne books the room for 3 March.",
    "Prépare une présentation de 6 slides sur le télétravail en France depuis 2019 avec des chiffres sourcés",
    "fais moi une presentation sur le marche des vehicules electriques en france avec des chiffres recents",
    "Peux-tu préparer un powerpoint sur l'évolution du chômage des jeunes depuis 2015, avec les statistiques de l'INSEE ?",
    "fais un deck de 5 diapos sur les prix de l'energie en europe en 2025",
    "Make a 6-slide deck on the EV market in Europe with recent figures and sources",
    "prepare des slides sur le marché du cloud souverain en France avec des données chiffrées récentes",
    "J'ai besoin d'une présentation sur l'inflation en France depuis 2020 avec les chiffres officiels",
    "Fais-moi un diaporama sur la cybersécurité des PME : statistiques 2025, coûts moyens d'une attaque",
    "Bonjour, pourriez-vous me préparer une présentation de 8 diapositives sur l'évolution du marché immobilier à Lyon "
    "depuis 2018, avec des chiffres ?",
    "presentation 6 slides sur le teletravail depuis 2019 chiffres sources",
    "Fais une présentation de 6 slides sur le marché du vélo électrique en France avec des chiffres",
    "prépare des slides sur les chiffres clés du e-commerce en France",
    "fais une presentation chiffrée sur le marché de la cybersécurité",
    "fais un powerpoint sur le marché des ERP en France avec des statistiques",
    "Prépare un deck de présentation de notre offre pour un client, avec le marché, la concurrence et les prix",
]
OFFICE_AGENT_NO = [
    "Bonjour",
    "merci, c'est parfait !",
    "Rédige un mail court pour décaler la réunion",
    "écris un mail a Paul pour lui dire que je serai en retard demain",
    "Peux-tu rédiger un mail de relance pour la facture 2025-114 ?",
    "fais un mail de remerciement à l'équipe pour le séminaire",
    "Fais une présentation de 5 slides sur notre nouvelle charte qualité",
    "crée un tableur avec les colonnes nom, prénom, email",
    "Fais un document Word avec le règlement intérieur de la cantine",
    "Combien font 17 % de 3 450 € ?",
    "Explique la différence entre CDD et CDI",
    "c'est quoi le meilleur CRM pour une PME ?",
    "Comment ajouter une diapo dans PowerPoint ?",
    "quel est le prix moyen d'un copieur multifonction ?",
    "ajoute une diapo sur les chiffres 2025 à la présentation",
    "Compare Excel et Google Sheets",
    "résume ce document en 5 points",
    "Rédige un mail à Sophie pour lui envoyer le compte rendu de la réunion d'hier",
    "Peux-tu me recommander un bon logiciel de compta ?",
    "traduis ce mail en anglais : Bonjour, je vous remercie pour votre devis de 12 000 €.",
    "Fais une présentation de 5 slides avec ces chiffres : CA 2023 1,2 M€, 2024 1,5 M€",
    "fais une presentation avec nos chiffres 2025 : CA 3,2 M€, marge 12 %, 45 salariés",
    "Rédige un mail à Sophie pour lui envoyer le compte rendu\nPrésents : Marie Dupont, Julien Martin",
    "Traduis ce texte en anglais\nDevis 1 – Alpha : 12 000 €\nDevis 2 – Beta : 10 500 €",
]
# ---------------------------------------------------------------- small modules (« card »): the user's own data
CARD_YES = [  # (ask with its data, the kind the parsers must hint)
    ("Fais une frise chronologique : 2015 création à Lyon, 2018 premier client export, 2021 levée de fonds", "timeline"),
    ("frise : 2019 création, 2021 levée de fonds, 2024 ouverture de Lille", "timeline"),
    ("Make a timeline: 2016 founded, 2019 first export, 2023 Series A", "timeline"),
    ("Compare ces offres :\n| Offre | Prix | Délai |\n|---|---|---|\n| A | 120 € | 4 h |\n| B | 95 € | 8 h |", "matrix"),
    ("Transforme en liste de tâches :\n- appeler le fournisseur\n- envoyer le devis\n- relancer Paul", "tasks"),
    ("fais une checklist : réserver la salle, envoyer l'invitation, commander le traiteur", "tasks"),
    ("Pour et contre du télétravail : pour : moins de trajets, plus de calme ; contre : isolement, réunions longues",
     "proscons"),
    ("avantages et inconvénients :\n+ rapide\n+ pas cher\n- fragile\n- bruyant", "proscons"),
    ("Fais une fiche de chiffres clés : CA 2025 : 1,2 M€ ; marge : 18 % ; effectif : 45 salariés", "figures"),
    ("key figures: revenue: 3.4 M€; margin: 12 %; headcount: 80", "figures"),
    ("Fais un glossaire :\nRGPD : règlement général sur la protection des données\nDPO : délégué à la protection des "
     "données", "glossary"),
    ("mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 %", "calc"),
    ("combien font 17 % de 3 450 € ?", "calc"),
    ("prix TTC de 1 200 € HT avec une TVA à 20 %", "calc"),
    ("calcule la marge sur un produit vendu 120 € acheté 80 €", "calc"),
    ("donne-moi les sources de ta réponse", "sources"),
]
CARD_NO = [  # the words of a card without its data, or another request: no card
    "quels sont les avantages du vélo électrique ?",
    "fais une frise de l'histoire de France",
    "quels sont les chiffres clés du marché du vélo en France ?",
    "compare l'iPhone 16 et le Pixel 9",
    "fais un glossaire du RGPD",
    "rédige un mail à Paul pour la réunion de lundi",
    "résume ce document en 5 points",
    "fais une présentation de 6 diapos sur le télétravail",
    "explique la différence entre CDD et CDI",
    "quelles sont les tâches d'un chef de projet ?",
    "le pour et le contre de la semaine de quatre jours ?",
    "Bonjour",
    "écris une fonction Python qui trie une liste",
    "what are the pros and cons of remote work?",
    "c'est quoi un glossaire ?",
]

# the exact calculator reads the figures in the user's language (« 1,200 » is 1200 in English, 1.2 in French)
CALC_VALUES_YES = [  # (ask, lang, text the computed facts must contain)
    ("What is the monthly payment on a 300,000 € loan over 25 years at 4%?", "en", "Monthly payment: 1,583.51 €"),
    ("What is 15% of 1,200?", "en", "15% of 1,200: 180."),
    ("Bought at 1,000 €, sold at 1,500 €, what is the margin?", "en", "Margin: 500 €"),
    ("Price incl. VAT of 1,200 € excl. VAT at 20%?", "en", "1,440 €"),
    ("mensualité d'un prêt de 1.250.000 € sur 25 ans à 4 %", "fr", "6\u202f597,96\u202f€"),
    ("mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 %", "fr", "1\u202f159,92\u202f€"),
    ("combien font 50 % de 1,5 ?", "fr", "0,75"),
]
CALC_VALUES_NO = [  # figures without a sum to do: no calculator card, in English too
    ("We grew revenue to 1,200,000 € this year.", "en"),
    ("Send the 1,500 € invoice to Paul.", "en"),
    ("The loan committee meets on 12 March.", "en"),
]

# ---------------------------------------------------------------- follow-ups, pictures, and realistic phrasings
# a short follow-up re-asks the previous turn's rich result (its context comes from the server memo, followup.py)
_W = {"tool": "get_weather", "args": {"place": "Lyon", "day": "demain"}}
_P = {"tool": "find_places", "args": {"query": "restaurant", "near": "gare de Lyon"}}
_PW = {"tool": "find_places", "args": {"query": "tour Eiffel"}}
_F = {"tool": "convert_currency", "args": {"from": "EUR", "to": "USD", "amount": 100}}
_C = {"tool": "clock", "args": {"cities": ["Tokyo"], "mode": "time"}}
_CO = {"tool": "find_company", "args": {"name": "Michelin"}}
_CHART = "chart"  # the previous answer showed a chart
FOLLOWUP_YES = [  # (previous context, follow-up, the call it must start)
    (_W, "et à Paris ?", ("get_weather", {"place": "Paris", "day": "demain"})),
    (_W, "et Tokyo ?", ("get_weather", {"place": "Tokyo", "day": "demain"})),
    (_W, "et après-demain ?", ("get_weather", {"place": "Lyon", "day": "après-demain"})),
    (_W, "et samedi à Nice ?", ("get_weather", {"place": "Nice", "day": "samedi"})),
    (_W, "pareil pour Bordeaux", ("get_weather", {"place": "Bordeaux", "day": "demain"})),
    (_W, "what about tomorrow?", ("get_weather", {"place": "Lyon", "day": "tomorrow"})),
    (_W, "et des restaurants autour ?", ("find_places", {"query": "restaurant", "near": "Lyon"})),
    (_P, "et à Lyon ?", ("find_places", {"query": "restaurant", "near": "Lyon"})),
    (_P, "et des hôtels ?", ("find_places", {"query": "hotel", "near": "gare de Lyon"})),
    (_PW, "et des restaurants autour ?", ("find_places", {"query": "restaurant", "near": "tour Eiffel"})),
    (_PW, "et le Louvre ?", ("find_places", {"query": "Louvre"})),
    (_PW, "et la météo là-bas ?", ("get_weather", {"place": "tour Eiffel"})),
    (_F, "et en livres ?", ("convert_currency", {"from": "EUR", "to": "GBP", "amount": 100})),
    (_F, "et 500 ?", ("convert_currency", {"from": "EUR", "to": "USD", "amount": 500.0})),
    (_F, "et en yens", ("convert_currency", {"from": "EUR", "to": "JPY", "amount": 100})),
    (_C, "et Sydney ?", ("clock", ["Sydney"])),
    (_C, "et à New York ?", ("clock", ["New York"])),
    (_CO, "et Danone ?", ("find_company", {"name": "Danone"})),
    (_CHART, "en camembert plutôt", ("chart", "pie")),
    (_CHART, "et en courbe ?", ("chart", "line")),
    (_CHART, "plutôt en barres", ("chart", "bar")),
]
OFFICE_NO = [  # ordinary office prompts: no rich content at all, alone or right after a rich result
    # a mail whose content names a deck, a report or a table (a clause of the mail, not a second deliverable)
    "Rédige un mail qui annonce une présentation au comité jeudi",
    "Prépare un mail pour demander un rapport d'activité à Julie",
    "Écris un mail pour demander à Paul de m'envoyer un tableau Excel",
    "Écris un mail au client pour lui présenter un tableau de nos tarifs",
    "Rédige une réponse à ce mail : pouvez-vous me faire une présentation du projet ?",
    "rédige un mail de relance pour la facture 2024-118",
    "Ajoute 12 rue de la Paix à mon CV.",
    "résume ce compte rendu en 5 points",
    "traduis ce paragraphe en anglais",
    "quel est le délai de préavis pour une démission ?",
    "prépare l'ordre du jour de la réunion de lundi",
    "améliore l'image de marque de notre PME",
    "le climat de l'équipe est tendu, des conseils ?",
    "la courbe d'apprentissage d'Excel est raide",
    "comment rédiger une offre d'emploi attractive ?",
    "fais-moi un tableau des congés de l'équipe",
    "quelle est la différence entre CDD et CDI ?",
    "écris un post LinkedIn sur notre nouveau produit",
    "peux-tu relire ce contrat ?",
    "où en est le dossier Martin ?",
    "il faut faire le point sur le budget marketing",
    "donne-moi 5 idées de team building",
    "quelles sont les étapes d'un recrutement ?",
    "explique-moi la TVA intracommunautaire",
    "la tendance est au télétravail, qu'en penses-tu ?",
    "la photo de profil de mon compte Teams ne s'affiche pas",
    "convertis ce document Word en PDF",
    "réunion annulée demain, préviens l'équipe",
    "quel est le taux de TVA sur la restauration ?",
    "combien coûte un salarié au SMIC pour l'employeur ?",
    "mets à jour le planning de la semaine",
    "c'est quoi un KPI ?",
    "calcule la marge sur un produit vendu 120 € acheté 80 €",
    "liste les risques du projet Atlas",
    "il faut améliorer l'image de l'entreprise auprès des jeunes",
    "quel temps de réponse pour le support client ?",
    "quelles sont les prévisions de vente pour 2027 ?",
    "la météo du projet est au vert",
    "crée une image de couverture pour la newsletter",
    "mets une photo de l'équipe dans le document",
    "quelle image donner à nos clients ?",
    "comment insérer une photo dans Word ?",
    "quel est le décalage entre le budget et le réel ?",
    "le cours de formation Excel commence quand ?",
    "et maintenant rédige le mail",
    "merci !",
    "et pour la réunion ?",
    "et le projet ?",
    "ok",
    "et à Lyon, combien de salariés ?",
    # « je cherche / je recherche » is « I am looking for / I want to understand », not a web search
    "Je cherche à comprendre la différence entre CDD et CDI.",
    "Je recherche un stagiaire en marketing, rédige l'annonce.",
    "Je recherche les causes possibles d'une baisse de CA, donne-moi des pistes.",
    # « une formule Excel » asks for a formula, not a spreadsheet; a how-to question asks for no file
    "Je cherche une formule Excel pour additionner une colonne si la cellule voisine vaut Oui.",
    "comment faire un tableau croisé dynamique ?",
    # a link to include is content, not a page to read
    "Ajoute ce lien à ma signature de mail : https://www.linkedin.com/in/test",
    # a code example that shows a call is the answer, not a call
    "Écris un script Python qui envoie un mail avec smtplib.",
    "Donne-moi un exemple de JSON pour un appel de fonction de recherche web.",
]
FOLLOWUP_NO = [(prev, q) for prev in (_W, _P, _PW, _F, _C, _CO, _CHART) for q in OFFICE_NO]
IMAGES_YES = [  # (ask, the subject searched)
    ("montre-moi une photo de la tour Eiffel", "tour Eiffel"),
    ("à quoi ressemble le Mont-Saint-Michel ?", "Mont-Saint-Michel"),
    ("show me a picture of a koala", "koala"),
    ("Montre moi des photos de koalas", "koalas"),
    ("des images de Lyon", "Lyon"),
    ("What does the Eiffel Tower look like", "Eiffel Tower"),
    ("show me what the Burj Khalifa looks like", "Burj Khalifa"),
    ("trouve-moi une image du Taj Mahal pour ma présentation", "Taj Mahal"),
    ("j'aimerais voir des photos de Kyoto", "Kyoto"),
    ("j'aimerais voir à quoi ressemble Marrakech", "Marrakech"),
    ("tu peux me montrer une image de la Joconde ?", "Joconde"),
    ("montre-moi une photo du pont du Gard", "pont du Gard"),
    ("à quoi ressemble la cathédrale de Strasbourg ?", "cathédrale de Strasbourg"),
    ("show me photos of the Grand Canyon", "Grand Canyon"),
    ("des photos du château de Chambord stp", "château de Chambord"),
    ("image de la Grande Muraille de Chine", "Grande Muraille de Chine"),
    ("montre une image d'un panda roux", "panda roux"),
    ("can you find me a picture of the Golden Gate Bridge?", "Golden Gate Bridge"),
]
IMAGES_NO = [
    "image de marque de notre entreprise",
    "comment améliorer l'image de l'entreprise ?",
    "droit à l'image des salariés",
    "l'image de la société s'est dégradée",
    "génère une image de chat",
    "insère une photo de la tour Eiffel dans la présentation",
    "montre-moi les photos de la soirée",
    "une photo de Marie Dupont",
    "à quoi ressemble un bon CV ?",
    "à quoi ressemble une journée type chez Google",
    "photo de profil LinkedIn : conseils",
    "une image vaut mille mots",
    "images de synthèse : quel logiciel ?",
    "show me pictures of our team",
    "décris cette image",
    "ajoute une image dans la diapo 3",
    "l'image du service client s'est améliorée",
    "faut-il une photo sur un CV ?",
    # writing about a picture: a caption is text (found in the app with the model router)
    "Peux-tu rédiger la légende d une photo de la tour Eiffel pour notre newsletter ?",
    "écris une légende pour notre photo du Mont-Saint-Michel sur Instagram",
    "write a caption for a photo of the Golden Gate Bridge",
]
REALISTIC_YES = [  # (phrasing, family it must START): realistic asks found missing or fixed in this round
    ("prévisions pour Lille demain matin", "get_weather"),
    ("what's the weather like in Madrid this weekend?", "get_weather"),
    ("forecast for Berlin on Monday", "get_weather"),
    ("quelle météo à Bordeaux jeudi ?", "get_weather"),
    ("doit-on prendre un parapluie à Rennes demain ?", "get_weather"),
    ("risque de neige à Clermont-Ferrand samedi ?", "get_weather"),
    ("il va faire froid à Strasbourg demain ?", "get_weather"),
    ("where is the nearest pharmacy to the Louvre?", "find_places"),
    ("la pharmacie la plus proche du Louvre", "find_places"),
    ("the closest ATM to Times Square", "find_places"),
    ("y a-t-il une boulangerie près de la gare Saint-Lazare ?", "find_places"),
    ("trouve un parking à côté du Zénith de Nantes", "find_places"),
    ("hôtels près du Palais des congrès de Lyon", "find_places"),
    ("any good restaurants near the Colosseum?", "find_places"),
    ("je cherche un coworking à Bordeaux", "find_places"),
    ("show me hotels around Gare du Nord", "find_places"),
    ("10 000 yens ça fait combien ?", "convert_currency"),
    ("50 dollars c'est combien en euros ?", "convert_currency"),
    ("le taux euro dollar aujourd'hui", "convert_currency"),
    ("convertis 2 500 € en francs suisses", "convert_currency"),
    ("1 200 GBP en EUR stp", "convert_currency"),
    ("combien valent 200 francs suisses ?", "convert_currency"),
    ("fiche entreprise de la société Alan", "find_company"),
    ("qui est le dirigeant de BlaBlaCar ?", "find_company"),
    ("numéro SIRET de la société Qonto", "find_company"),
    ("on est à quelle heure à Los Angeles ?", "clock"),
    ("quelle heure est-il à Saint-Denis ?", "clock"),
    ("quel décalage avec Sydney ?", "clock"),
    ("best time to call Tokyo from Paris", "clock"),
    ("programmer une formation le 15 janvier", "event"),
    ("réserve une salle pour la formation le 12 janvier", "event"),
    ("planifie un call avec le fournisseur le 2 décembre à 11h", "event"),
    ("fixe un rendez-vous avec Maître Durand jeudi 16h", "event"),
    ("fais un histogramme : Q1 40, Q2 55, Q3 61, Q4 70", "chart"),
    ("plot this: Jan 10, Feb 14, Mar 9, Apr 17", "chart"),
]
CHART_HOWTO_NO = [  # questions ABOUT charts: no make_chart offered, nothing drawn
    "comment faire un graphique dans Excel ?",
    "je voudrais savoir comment insérer un graphique dans Word",
    "tuto pour faire une courbe sur Excel",
    "quel graphique choisir pour montrer une répartition ?",
    "Quel type de graphique pour des données temporelles ?",
    "Peux-tu m'expliquer comment tracer une courbe de tendance dans Excel ?",
    "définition d'un diagramme de Pareto",
    "étapes pour créer un graphique croisé dynamique",
    "montre-moi comment faire un graphique dans Excel",
    "which chart should I use for market share?",
    "dans quel cas utiliser un camembert plutôt qu'un histogramme ?",
]

# Studies named as a deliverable (étude comparative, dossier de veille, benchmark, note de synthèse sourcée): a
# "yes" routes to the researched document (Activé, or Auto once its flag is on); a "no" never does, even with the
# flag on (an office request with a study word that is not a study of what is out there).
STUDY_YES = [
    "Fais une étude comparative des 3 principaux CRM du marché avec un tableau et une recommandation",
    "Rédige un rapport sur la transition énergétique des PME françaises avec des chiffres récents et des sources",
    "Fais un dossier de veille sur l'IA générative en entreprise en 2026 : tendances, chiffres, risques",
    "Fais un benchmark des outils de visioconférence du marché pour une PME de 50 personnes",
    "Prépare une note de synthèse sur la réforme de la facturation électronique 2026 avec les sources officielles",
    "Rédige une étude de marché sur les box de repas livrées en France avec des chiffres",
    "Fais une veille concurrentielle sur les logiciels de paie pour PME",
    "Write a comparative study of the main project management tools on the market",
    "j'ai besoin d'un benchmark des solutions de signature électronique du marché",
    "peux-tu me faire un dossier de veille sur la cybersécurité des PME en 2026 ?",
]
STUDY_NO = [
    "Rédige une note de synthèse sur la réunion d'hier",
    "Fais un rapport d'activité du mois de novembre",
    "Rédige un rapport d'incident pour la panne de ce matin",
    "Fais un benchmark de nos fournisseurs actuels",
    "Rédige une note de synthèse sur les principaux points du contrat",
    "Fais une note de synthèse sur les tendances de nos ventes",
    "Le bureau d'études doit me rendre le plan, rédige un mail de relance",
    "Range ce dossier de veille dans le drive",
    "Qu'est-ce qu'un benchmark ?",
    "Comment faire une veille efficace ?",
    "Écris un rapport sur nos résultats 2025 : CA 3,2 M€, marge 12 %",
    "Rédige une note de veille pour l'équipe à partir de ces liens que je t'envoie demain",
    "Fais un mail pour présenter le benchmark à l'équipe",
    "Rédige un mail court au client pour lui envoyer le livre blanc",
    "c'est quoi le meilleur CRM du marché ?",
    "Quels sont les principaux concurrents de Salesforce ?",
    "Rédige un rapport de stage sur mon alternance",
    "Fais un rapport sur l'avancement du projet ERP",
    "Rédige le rapport annuel de l'association",
    "fais une synthèse de ce document",
]
CANVAS_YES = [  # (ask, the canvas it must open): a creation ask, the content written beside the chat
    ("Fais une présentation de 6 slides sur le télétravail", "deck"),
    ("prépare des slides sur le marché du cloud", "deck"),
    ("make a pitch deck for our startup", "deck"),
    ("une présentation sur le vélo, 5 slides", "deck"),
    ("Fais une présentation sur le plan vélo de l'entreprise", "deck"),
    ("Peux-tu me faire une présentation sur la RSE pour le comité de lundi ?", "deck"),
    ("prépare-moi pour lundi une présentation sur nos résultats", "deck"),
    ("Crée un diaporama pour l'accueil des nouveaux arrivants", "deck"),
    ("Can you make a short deck about our new product?", "deck"),
    ("Rédige un rapport sur la sécurité informatique", "doc"),
    ("Fais le compte rendu de cette réunion", "doc"),
    ("Rédige une note de synthèse sur la sobriété numérique au bureau", "doc"),
    ("Écris un cahier des charges pour la refonte de l'intranet", "doc"),
    ("Write a report on remote work in small companies", "doc"),
    ("Rédige une proposition commerciale pour un client dans la logistique", "doc"),
    ("crée une landing page pour une boulangerie", "code"),
    ("fais une page HTML avec un formulaire de contact", "code"),
    ("fais un logo svg pour Bird", "code"),
    ("écris un script python qui renomme des fichiers", "code"),
    ("Code un mini-jeu de morpion en JavaScript", "code"),
    ("dessine le schéma du processus de recrutement", "diagram"),
    ("draw a flowchart of the onboarding process", "diagram"),
    ("Fais un organigramme de l'équipe commerciale", "diagram"),
]
CANVAS_NO = [  # ordinary office prompts and questions about a document: never a canvas
    "Peux-tu me dire ce que contient ce document ?",
    "Je dois faire une présentation orale demain, des conseils pour le stress ?",
    "Prépare un discours de 2 minutes pour le pot de départ de Marie",
    "Fais une liste des documents à fournir pour un dossier de retraite",
    "Prépare un brief pour le photographe en 3 lignes",
    "Écris la politique de remboursement en deux phrases pour ma réponse au client",
    "Peux-tu vérifier ce rapport ?",
    "Peux-tu comparer ces deux documents ?",
    "Peux-tu extraire les dates de ce document ?",
    "Peux-tu reprendre les idées de ce document en 5 points ?",
    "Peux-tu m aider avec ma présentation de demain ?",
    "Fais une liste des slides à revoir",
    "Rédige une réponse au rapport du CSE",
    "Write a reply to the report from finance",
    "Comment faire une bonne présentation ?",
    "Comment ajouter une diapo dans PowerPoint ?",
    "Présente-moi l'entreprise Airbus",
    "résume ce document en 5 points",
    "écris une fonction Python qui trie une liste",
    "rédige un mail pour envoyer la présentation à Paul",
    "traduis ce rapport en anglais",
    "quelle est la différence entre un rapport et une note ?",
    "Peux-tu relire mon rapport et corriger les fautes ?",
    "Que dit ce document sur les congés ?",
    "Dans ce rapport, quels sont les chiffres clés ?",
    "Peux-tu me donner ton avis sur ma présentation ?",
    "Ce document est-il conforme au RGPD ?",
    "Est-ce que ce rapport mentionne le budget ?",
    "J'ai besoin d'aide pour comprendre ce document",
    "Il me faut le résumé de ce rapport pour ce soir",
    "Can you check this report for typos?",
    "Can you tell me what this document says about pricing?",
    "Peux-tu lister les risques cités dans ce rapport ?",
    "Pourrais-tu analyser cette présentation ?",
    "Fais-moi un résumé du document joint",
    "Ma présentation dure combien de temps idéalement ?",
    "Quelle police utiliser pour un rapport professionnel ?",
    "Prépare les minutes de la réunion en trois lignes",
    "Écris un guide en une phrase pour se connecter au wifi",
    "Rédige la procédure en deux lignes pour le client",
    "Fais une liste de questions pour l'entretien",
    "Peux-tu trouver les incohérences dans ce document ?",
    "Le rapport de Paul est en retard, rédige-lui un message",
    "Combien de slides pour une présentation de 10 minutes ?",
]
# office prompts that ask for a script: no office file and no tool call to run (OFFICE_NO), but the code canvas is the
# right place to write it, like « écris un script python qui renomme des fichiers » above
# an artifact is open (a deck): (words, panel shown) the canvas must take as an edit of it
CANVAS_EDIT_YES = [
    ("Ajoute une diapositive sur les coûts", True),
    ("Ajoute une diapositive sur les coûts", False),
    ("supprime la slide 3", False),
    ("remplace l'image de la slide 3", False),
    ("Change le titre de la présentation", False),
    ("plus court", True),
    ("Change le titre", True),
    ("raccourcis la conclusion", True),
]
# … and ordinary messages it must leave to the chat, the panel shown or not
CANVAS_EDIT_NO = [
    (q, shown)
    for q in (
        "Améliore le style de ce mail avant que je l'envoie : Bonjour Paul, je te relance pour la facture de mars, "
        "peux-tu me dire où en est le paiement ?",
        "Résume ce paragraphe en trois points : le télétravail réduit les trajets, améliore la concentration et "
        "change l'organisation des équipes.",
        "Change le titre de ma réunion de demain en « Point budget »",
        "Corrige les fautes de ce texte : je vous remercie pour votre retour, je reviendrais vers vous demain.",
        "Mets un rappel dans mon agenda lundi à 9h",
    )
    for shown in (True, False)
] + [
    ("Mets ces chiffres dans un graphique : janvier 120, février 135, mars 160", False),
    ("Change le titre", False),
    ("plus court", False),
]
CANVAS_CODE_FROM_OFFICE = [("Écris un script Python qui envoie un mail avec smtplib.", "code")]
CANVAS_OFFICE_NO = [q for q in OFFICE_NO if q not in dict(CANVAS_CODE_FROM_OFFICE)]
NOW = datetime(2026, 11, 23, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))


def chart_offered(q: str) -> bool:
    return "make_chart" not in route(q)


def chart_touched(q: str) -> bool:
    return chart_offered(q) or chart_ask(q)


def chart_drawn(q: str) -> bool:
    """The harness draws the user's figures with the right type and every row."""
    want = CHART_FIGURES.get(q)
    if want is None:
        return True
    got = figures_in(q)
    return bool(got) and chart_call(q, got, "fr")["type"] == want[0] and len(got[1]) == want[1]


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


def map_started(q: str) -> bool:
    """A map is searched for by the harness itself, with the right query when the bench names it."""
    got = next((i for i in intents.detect(q, False, "fr") if i.tool == "find_places" and i.args), None)
    if got is None:
        return False
    want = MAP_ARGS.get(q)
    return want is None or (got.args.get("query"), got.args.get("near")) == want


def company_fx_started(q: str) -> bool:
    got = next((i for i in intents.detect(q, False, "fr") if i.tool in ("find_company", "convert_currency")), None)
    if got is None or not got.args:
        return False
    want = FX_ARGS.get(q)
    return want is None or (got.args.get("from"), got.args.get("to")) == want


def company_fx_touched(q: str) -> bool:
    return any(i.tool in ("find_company", "convert_currency") for i in intents.detect(q, False, "fr"))


def event_card(q: str) -> bool:
    card = event_widget(q, NOW, detect_lang(q))
    if card is None:
        return False
    want = EVENT_SLOTS.get(q)
    got = when.event_ask(q, NOW, detect_lang(q)) or when.parse(q, NOW, detect_lang(q))
    return want is None or (got is not None and f"{got['start']:%Y-%m-%d %H:%M}" == want and not got["all_day"])


def agent_on(q: str) -> bool:
    return bool(crew.decide(q, mode="auto", lang="fr").recipe)


_CHART_HISTORY = [
    {"role": "user", "content": "le CA par trimestre"},
    {"role": "assistant", "content": "Voilà.\n\n[Mémo de ce tour — graphique affiché : « CA » (bar) colonnes T / CA — "
     "T1 120 ; T2 135 ; T3 150]"},
]  # fmt: skip


def _follow(prev, q):
    """What a follow-up starts: ("chart", type) | ("clock", [cities]) | (tool, args) | None."""
    if prev == _CHART:
        if not followup.chart_retype(q):
            return None
        rows = figures_in(_previous_answer(_CHART_HISTORY))
        return ("chart", chart_call(q, rows, "fr")["type"]) if rows else None
    if intents.detect(q, False, "fr") and any(i.args for i in intents.detect(q, False, "fr")):
        return None  # a complete ask of its own is read as itself
    got = followup.resolve(q, prev, "fr")
    if got is None:
        return None
    if got.tool == "clock":
        found = clock.detect(got.args["text"])
        return ("clock", [c["fr"] for c in found["cities"]]) if found else None
    return (got.tool, got.args)


def followup_ok(item) -> bool:
    prev, q, want = item
    return _follow(prev, q) == want


def followup_touched(item) -> bool:
    prev, q = item[:2]
    return _follow(prev, q) is not None


def images_ok(q) -> bool:
    text, subject = q if isinstance(q, tuple) else (q, None)
    got = intents.images(text)
    return bool(got) and (subject is None or got.args["query"] == subject)


def _started(q: str, family: str) -> bool:
    if family == "clock":
        found = clock.detect(q)
        return bool(found and found["cities"])
    if family == "event":
        return event_widget(q, NOW, detect_lang(q)) is not None
    if family == "chart":
        return chart_offered(q) and chart_ask(q) and figures_in(q) is not None
    return any(i.tool == family and i.args for i in intents.detect(q, False, "fr"))


def realistic_ok(item) -> bool:
    return _started(*item)


def anything(q: str) -> bool:
    """Any rich content at all: an intent (even only offered), a clock, an event card, a chart offer, pictures."""
    return bool(intents.detect(q, False, "fr") or clock.detect(q) or event_widget(q, NOW, detect_lang(q))
                or chart_offered(q) or intents.images(q))  # fmt: skip
def study_routed(q: str) -> bool:
    flipped = {**crew.RECIPES, "doc_research": {**crew.RECIPES["doc_research"], "auto": True}}
    return crew.decide(q, mode="on").recipe == "doc_research" and crew.decide(q, recipes=flipped).recipe == "doc_research"


def study_touched(q: str) -> bool:
    flipped = {**crew.RECIPES, "doc_research": {**crew.RECIPES["doc_research"], "auto": True}}
    return crew.decide(q, mode="on").recipe == "doc_research" or bool(crew.decide(q, recipes=flipped).recipe)


def canvas_opened(item) -> bool:
    q, kind = item
    return canvas_intents.ask(q) == kind


def canvas_touched(q) -> bool:
    return bool(canvas_intents.ask(q))


def canvas_edited(item) -> bool:
    q, shown = item
    return canvas_intents.edit_ask(q, "deck", shown=shown)


def calc_value(item) -> bool:
    """The calculator card fired and its exact facts contain the expected figure (NO items: it did not fire)."""
    from birds.harness import calc

    q, lang, want = (*item, None) if len(item) == 2 else item
    w, facts = calc.facts_for(q, lang)
    return bool(w) and (want is None or want in facts)


def card_kind(q):
    """The parsers' hint for the small modules (router.regex_decision), with the data there."""
    from birds.harness import router

    q, kind = q if isinstance(q, tuple) else (q, None)
    got = router.regex_decision(q).get("card")
    return bool(got) and (kind is None or got.args["kind"] == kind)


def bench(name: str, yes: list[str], no: list[str], fn, touched=None) -> tuple[int, int]:
    miss = [q for q in yes if not fn(q)]
    false = [q for q in no if (touched or fn)(q)]
    for q in miss:
        print(f"  MISS  [{name}] " + str(q).replace("\n", " / "))
    for q in false:
        print(f"  FALSE [{name}] " + str(q).replace("\n", " / "))
    ok = len(yes) - len(miss) + len(no) - len(false)
    print(f"{name}: {ok}/{len(yes) + len(no)}  (missed {len(miss)}/{len(yes)}, false {len(false)}/{len(no)})")
    return ok, len(yes) + len(no)


if __name__ == "__main__":
    total = [0, 0]
    for args in (
        ("charts", CHART_YES, CHART_NO, chart_offered),
        ("maps", MAP_YES, MAP_NO, map_detected),
        ("weather", WEATHER_YES, WEATHER_NO, weather_called),
        ("clock", CLOCK_YES, CLOCK_NO, clock_shown),
        ("agent", AGENT_YES, AGENT_NO, agent_on),
        ("charts+", CHART_YES2, CHART_NO2, lambda q: chart_offered(q) and chart_drawn(q), chart_touched),
        ("maps+", MAP_YES2, MAP_NO2, map_started, map_detected),
        ("company_fx", COMPANY_FX_YES, COMPANY_FX_NO, company_fx_started, company_fx_touched),
        ("events", EVENT_YES, EVENT_NO, event_card),
        ("office_agent", OFFICE_AGENT_YES, OFFICE_AGENT_NO, agent_on),
        ("followups", FOLLOWUP_YES, FOLLOWUP_NO, followup_ok, followup_touched),
        ("images", IMAGES_YES, IMAGES_NO, images_ok),
        ("realistic", REALISTIC_YES, OFFICE_NO, realistic_ok, anything),
        ("chart_howto", [], CHART_HOWTO_NO, chart_touched),
        ("agent_study", STUDY_YES, STUDY_NO, study_routed, study_touched),
        ("maps_real", bench_maps.MAPS_REAL, bench_maps.MAPS_OFFICE_NO, bench_maps.correct, bench_maps.detected),
        ("maps_heldout", bench_maps.MAPS_HELDOUT, bench_maps.MAPS_HELDOUT_NO, bench_maps.correct, bench_maps.detected),
        ("canvas", CANVAS_YES + CANVAS_CODE_FROM_OFFICE, CANVAS_NO + CANVAS_OFFICE_NO, canvas_opened, canvas_touched),
        ("canvas_edit", CANVAS_EDIT_YES, CANVAS_EDIT_NO, canvas_edited),
        ("cards", CARD_YES, CARD_NO, card_kind),
        ("calc_values", CALC_VALUES_YES, CALC_VALUES_NO, calc_value),
    ):
        ok, n = bench(*args)
        total[0] += ok
        total[1] += n
    print(f"total: {total[0]}/{total[1]}")
