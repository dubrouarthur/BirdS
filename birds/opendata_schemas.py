"""Schemas of the open-data tools (birds/harness/tools/opendata), appended to ``birds.tools.EXTRA_TOOLS``.

Like the other widget tools they are offered only when the harness routes them in (birds/harness/opendata_intents),
so an ordinary turn keeps the trained tool block byte for byte. Tiny and flat: at most 3 string/number arguments.
Pure data, no import from the harness (birds.tools imports this module).
"""

from __future__ import annotations


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_S = {"type": "string"}

OPENDATA_SCHEMAS: list[dict] = [
    _fn(
        "work_calendar",
        "Public holidays and working days (France and its zones from calendrier.api.gouv.fr, other countries from "
        "Nager.Date): the holidays of a year or month with the number of working days, the weekday of a date, or "
        "the date N working days after a date.",
        {
            "period": {**_S, "description": "A year (2027), a month (2027-05) or a date (2027-04-20)."},
            "zone": {
                **_S,
                "description": "Optional: metropole (default), alsace-moselle, a DOM, or a country, e.g. DE.",
            },
            "add_days": {"type": "number", "description": "Optional: working days to add to the date."},
        },
        ["period"],
    ),
    _fn(
        "lookup_entity",
        "An entity card from Wikipedia and Wikidata: short summary, picture and key facts of a company, a country, "
        "a city, an organisation or a concept.",
        {"name": {**_S, "description": "What to look up, e.g. Airbus, Portugal."}},
        ["name"],
    ),
    _fn(
        "get_statistics",
        "Draw an official statistics series as a line chart (Eurostat, World Bank, INSEE): unemployment, inflation, "
        "GDP, GDP growth, population, electricity prices for businesses, exports, business start-ups.",
        {
            "indicator": {**_S, "description": "e.g. chômage, inflation, PIB, population."},
            "places": {**_S, "description": "Countries or French communes, comma separated (default France)."},
            "since": {**_S, "description": "Optional: first year (2015) or a number of months (24m)."},
        },
        ["indicator"],
    ),
    _fn(
        "find_tenders",
        "Find open French public calls for tenders on the BOAMP by keywords, optionally in a département or region.",
        {
            "query": {**_S, "description": "Keywords of the contract, e.g. nettoyage de locaux."},
            "where": {**_S, "description": "Optional: département (59, Nord) or région (Bretagne)."},
            "days": {"type": "number", "description": "Optional: published within this many days (default 30)."},
        },
        ["query"],
    ),
    _fn(
        "find_papers",
        "Find scholarly works (OpenAlex) or check a DOI (Crossref): title, authors, year, venue, citations, link.",
        {
            "query": {**_S, "description": "Topic, title words or a DOI."},
            "order": {"type": "string", "enum": ["relevance", "cited", "recent"], "description": "Optional order."},
            "source": {"type": "string", "enum": ["openalex", "crossref"], "description": "Optional source."},
        },
        ["query"],
    ),
    _fn(
        "find_commune",
        "A French commune card (INSEE code, postal codes, population, département) or a French postal address "
        "normalised by the Base Adresse Nationale.",
        {"name": {**_S, "description": "A commune name (Roubaix) or a postal address."}},
        ["name"],
    ),
]
OPENDATA_NAMES = [t["function"]["name"] for t in OPENDATA_SCHEMAS]
OPENDATA_EXAMPLES = {
    "work_calendar": '{"period": "2027-05", "zone": "metropole"}',
    "lookup_entity": '{"name": "Airbus"}',
    "get_statistics": '{"indicator": "chômage", "places": "France, Allemagne", "since": "2015"}',
    "find_tenders": '{"query": "nettoyage de locaux", "where": "59"}',
    "find_papers": '{"query": "batteries sodium-ion", "order": "recent"}',
    "find_commune": '{"name": "Roubaix"}',
}
# what the settings panel says about each tool (birds.web.server.tools_info)
OPENDATA_TEXT = {
    "work_calendar": (
        "Jours fériés et jours ouvrés (calendrier.api.gouv.fr, Nager.Date)",
        "Public holidays and working days (calendrier.api.gouv.fr, Nager.Date)",
    ),
    "lookup_entity": ("Fiches Wikipédia et Wikidata", "Wikipedia and Wikidata cards"),
    "get_statistics": (
        "Statistiques officielles en graphique (Eurostat, Banque mondiale, Insee)",
        "Official statistics as charts (Eurostat, World Bank, INSEE)",
    ),
    "find_tenders": ("Appels d'offres publics (BOAMP)", "French public tenders (BOAMP)"),
    "find_papers": ("Publications scientifiques (OpenAlex, Crossref)", "Scholarly works (OpenAlex, Crossref)"),
    "find_commune": (
        "Communes et adresses (geo.api.gouv.fr, Base Adresse Nationale)",
        "Communes and addresses (geo.api.gouv.fr, national address base)",
    ),
}
CHART_TOOLS = {"get_statistics"}  # draw into answer.charts: make_chart is withdrawn for that turn
