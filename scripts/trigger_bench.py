"""Trigger bench: does Bird offer or start the right rich content for realistic phrasings?

Run: .venv/bin/python -I scripts/trigger_bench.py  (no network, no model). Prints misses and a score per family.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from birds.harness import clock, crew, intents, when  # noqa: E402
from birds.harness.agent import chart_ask, chart_call, detect_lang, figures_in, route  # noqa: E402
from birds.web.widgets import event_widget  # noqa: E402

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
    ):
        ok, n = bench(*args)
        total[0] += ok
        total[1] += n
    print(f"total: {total[0]}/{total[1]}")
