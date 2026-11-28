"""Open-data families of the trigger bench (scripts/trigger_bench.py) and of the router dataset (router_data.py).

- ``OPENDATA_YES``: (ask, tool, arguments the call must carry): holidays and working days, entity cards, official
  statistics, public tenders, scholarly works, communes and addresses, FR and EN;
- ``OPENDATA_NO``: near misses: the same words in a piece of writing, a how-to, a definition, the user's own data;
- ``OPENDATA_ROUTER_YES``: clear asks the parsers do not see (a router-only family, like ``pasted``): the model
  is measured on them, the regex path is not (it says nothing, which is safe).

Arguments are compared accent- and case-folded; an argument not listed is not checked.
"""

from __future__ import annotations

from datetime import date

TODAY = date(2026, 11, 23)  # the bench's fixed day (trigger_bench.NOW)

OPENDATA_YES = [
    # holidays and working days (calendrier.api.gouv.fr, Nager.Date)
    ("quels sont les jours fériés en 2027 ?", "work_calendar", {"period": "2027", "zone": "metropole"}),
    ("jours fériés de mai 2027", "work_calendar", {"period": "2027-05"}),
    ("liste des jours fériés 2026", "work_calendar", {"period": "2026"}),
    ("combien de jours ouvrés en mai 2027 ?", "work_calendar", {"period": "2027-05"}),
    ("combien de jours ouvrés entre le 1er et le 31 mars 2027", "work_calendar", {"period": "2027-03"}),
    ("le 14 juillet 2027 tombe quel jour ?", "work_calendar", {"period": "2027-07-14"}),
    ("le 11 novembre est-il férié ?", "work_calendar", {}),
    ("J+30 ouvrés à partir du 3 décembre", "work_calendar", {"add_days": 30}),
    ("date limite à 15 jours ouvrés du 20 décembre", "work_calendar", {"add_days": 15}),
    ("jours fériés en Alsace-Moselle 2026", "work_calendar", {"zone": "alsace-moselle"}),
    ("jours fériés en Guadeloupe en 2027", "work_calendar", {"zone": "guadeloupe"}),
    ("quels sont les jours fériés en Belgique cette année ?", "work_calendar", {"zone": "BE"}),
    ("jours fériés en Espagne 2027", "work_calendar", {"zone": "ES", "period": "2027"}),
    ("public holidays in Germany in 2027", "work_calendar", {"zone": "DE", "period": "2027"}),
    ("bank holidays in the UK in 2027", "work_calendar", {"zone": "GB", "period": "2027"}),
    ("is May 1st 2027 a public holiday?", "work_calendar", {"period": "2027-05-01"}),
    ("how many working days in June 2027?", "work_calendar", {"period": "2027-06"}),
    # entity cards (Wikipedia, Wikidata)
    ("c'est quoi Airbus ?", "lookup_entity", {"name": "Airbus"}),
    ("c'est quoi l'OCDE ?", "lookup_entity", {"name": "OCDE"}),
    ("qu'est-ce que la Banque de France ?", "lookup_entity", {"name": "Banque de France"}),
    # official statistics (Eurostat, World Bank, INSEE)
    ("évolution du chômage en France depuis 2015", "get_statistics", {"indicator": "unemployment", "since": "2015"}),
    ("le chômage en France et en Allemagne depuis 2010", "get_statistics",
     {"indicator": "unemployment", "places": "France, Allemagne"}),
    ("inflation en zone euro depuis 2020", "get_statistics", {"indicator": "inflation"}),
    ("inflation en France ces 5 dernières années", "get_statistics", {"indicator": "inflation", "places": "France"}),
    ("PIB de la France et du Japon depuis 2000", "get_statistics", {"indicator": "gdp", "places": "France, Japon"}),
    ("la croissance du PIB en France depuis 2015", "get_statistics", {"indicator": "gdp_growth"}),
    ("taux de chômage en Italie depuis 2012", "get_statistics", {"indicator": "unemployment", "places": "Italie"}),
    ("courbe du taux de chômage en Espagne", "get_statistics", {"indicator": "unemployment", "places": "Espagne"}),
    ("exportations de la France depuis 2010", "get_statistics", {"indicator": "exports"}),
    ("population de Roubaix depuis 1968", "get_statistics", {"indicator": "population", "places": "Roubaix"}),
    ("évolution de la population de Nantes", "get_statistics", {"indicator": "population", "places": "Nantes"}),
    ("GDP of Germany since 2000", "get_statistics", {"indicator": "gdp", "places": "Allemagne"}),
    ("unemployment in Spain and Portugal since 2010", "get_statistics", {"indicator": "unemployment"}),
    # public tenders (BOAMP)
    ("appels d'offres nettoyage de locaux dans le Nord", "find_tenders", {"query": "nettoyage de locaux", "where": "59"}),
    ("marchés publics informatique en Bretagne", "find_tenders", {"query": "informatique", "where": "Bretagne"}),
    ("trouve des appels d'offres pour de la maintenance d'ascenseurs", "find_tenders",
     {"query": "maintenance d'ascenseurs"}),
    ("appels d'offres BOAMP travaux de voirie Gironde", "find_tenders", {"query": "travaux de voirie", "where": "33"}),
    ("marchés publics de restauration collective dans le Rhône", "find_tenders",
     {"query": "restauration collective", "where": "69"}),
    ("cherche un appel d'offres pour une mission de conseil RH", "find_tenders", {"query": "mission de conseil RH"}),
    ("public tenders for cleaning services in France", "find_tenders", {"query": "cleaning services"}),
    # scholarly works (OpenAlex, Crossref)
    ("articles scientifiques sur les batteries sodium-ion", "find_papers", {"query": "batteries sodium-ion"}),
    ("publications récentes sur le microbiote intestinal", "find_papers",
     {"query": "microbiote intestinal", "order": "recent"}),
    ("articles les plus cités sur le deep learning", "find_papers", {"query": "deep learning", "order": "cited"}),
    ("publications sur l'apprentissage fédéré", "find_papers", {"query": "apprentissage fédéré"}),
    ("vérifie ce DOI 10.1038/nature14539", "find_papers", {"query": "10.1038/nature14539"}),
    ("DOI 10.1126/science.aaa8415", "find_papers", {"query": "10.1126/science.aaa8415"}),
    ("find papers on CRISPR gene editing", "find_papers", {"query": "CRISPR gene editing"}),
    # communes and addresses (geo.api.gouv.fr, Base Adresse Nationale)
    ("code postal de Roubaix", "find_commune", {"name": "Roubaix"}),
    ("codes postaux de Marseille", "find_commune", {"name": "Marseille"}),
    ("quel est le code INSEE de Bordeaux ?", "find_commune", {"name": "Bordeaux"}),
    ("code INSEE de Saint-Denis", "find_commune", {"name": "Saint-Denis"}),
    ("quelles communes s'appellent Saint-Martin ?", "find_commune", {"name": "Saint-Martin"}),
    ("population de Lille", "find_commune", {"name": "Lille"}),
    ("normalise cette adresse : 20 av de segur paris", "find_commune", {"name": "20 av de segur paris"}),
    ("vérifie l'adresse 8 bd du port 95000 cergy", "find_commune", {"name": "8 bd du port 95000 cergy"}),
    ("postcode of Roubaix", "find_commune", {"name": "Roubaix"}),
]  # fmt: skip

OPENDATA_NO = [
    "rédige un mail pour prévenir l'équipe que le bureau est fermé le jour férié",
    "comment calculer les jours ouvrés dans Excel ?",
    "écris une formule Excel pour compter les jours ouvrés",
    "le pont de l'Ascension, on le pose ou pas ?",
    "fais une note sur la politique de congés et les jours fériés",
    "explique la différence entre jours ouvrés et jours ouvrables",
    "fais un tableau des jours de congés de l'équipe",
    "planifie une réunion le lundi de Pâques",
    "c'est quoi un KPI ?",
    "c'est quoi le chômage partiel ?",
    "c'est quoi un code NAF ?",
    "c'est quoi notre politique de télétravail ?",
    "qui est le meilleur candidat pour le poste ?",
    "qu'est-ce qu'un appel d'offres ?",
    "comment répondre à un appel d'offres ?",
    "rédige le mémoire technique pour l'appel d'offres de nettoyage",
    "aide-moi à rédiger notre réponse au marché public de la mairie",
    "nos chiffres de ventes depuis 2015",
    "graphique de nos ventes : janvier 120, février 135, mars 160",
    "comment calculer le taux d'inflation ?",
    "explique-moi le PIB",
    "rédige un article de blog sur l'inflation",
    "le taux de chômage des jeunes, tu peux m'en parler dans un paragraphe pour mon rapport ?",
    "écris un article sur le télétravail pour notre newsletter",
    "fais une présentation sur les publications de l'équipe",
    "résume cet article scientifique",
    "traduis le résumé de cette publication",
    "mets à jour l'adresse de facturation du client",
    "corrige l'adresse dans la signature de mon mail",
    "Corrige l'adresse 10 rue de Rivoli Paris dans le courrier",
    "la population cible de notre campagne marketing",
    "quelle est la population de notre fichier clients ?",
    "how do I count working days in Google Sheets?",
    "write an email telling the team about the bank holiday",
    "what is a call for tenders?",
    "what is inflation?",
    "draft a cover letter for a research position",
    "summarize this paper for me",
    "what's our churn rate since 2020?",
    # the user's own figures: never an official France series in their place (no country named either)
    "inflation de mes loyers depuis 2020",
    "le chômage dans mon équipe depuis 2015",
    "exportations de notre PME depuis 2010",
    "Inflation des salaires dans l'équipe depuis 2020",
    "the unemployment rate in my team since 2015",
    "le chômage depuis 2015",
]

# clear asks the parsers miss: router-only (router_data family "opendata_router"), never on the regex bench
OPENDATA_ROUTER_YES = [
    ("quand tombe l'Ascension en 2027 ?", "work_calendar", {"period": "2027"}),
    ("fiche Wikipédia du Portugal", "lookup_entity", {"name": "Portugal"}),
    ("présente-moi l'Unesco en quelques lignes avec sa fiche", "lookup_entity", {"name": "Unesco"}),
    ("tell me about the Eiffel Tower", "lookup_entity", {"name": "Eiffel Tower"}),
    ("prix de l'électricité pour les entreprises en France depuis 2018", "get_statistics",
     {"indicator": "electricity", "places": "France", "since": "2018"}),
    ("créations d'entreprises en France ces deux dernières années", "get_statistics", {"indicator": "creations"}),
    ("y a-t-il des marchés publics de formation bureautique en ce moment ?", "find_tenders",
     {"query": "formation bureautique"}),
    ("quelles recherches récentes sur la pompe à chaleur ?", "find_papers", {"query": "pompe à chaleur"}),
    ("dans quel département est Vierzon ?", "find_commune", {"name": "Vierzon"}),
]  # fmt: skip


def _fold(v) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("'", " ").split())


def args_match(got: dict, want: dict) -> bool:
    return all(k in got and _fold(got[k]) == _fold(v) for k, v in want.items())


def started(item) -> bool:
    """The open-data parser starts the expected call (tool and the listed arguments)."""
    from birds.harness import opendata_intents

    q, tool, want = item
    found = opendata_intents.detect(q, False, "en" if _en(q) else "fr", today=TODAY)
    return bool(found and found[0].args and found[0].tool == tool and args_match(found[0].args, want))


def touched(q: str) -> bool:
    """Any open-data call started (a "no" must start none)."""
    from birds.harness import opendata_intents

    return any(i.args for i in opendata_intents.detect(q, False, "en" if _en(q) else "fr", today=TODAY))


def _en(q: str) -> bool:
    from birds.harness.agent import detect_lang

    return detect_lang(q) == "en"
