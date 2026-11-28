"""Market family of the trigger bench (scripts/trigger_bench.py) and of the router dataset (router_data.py).

- ``FINANCE_YES``: (ask, arguments the get_quote call must carry): shares, indices, crypto-assets, currency pairs,
  history ranges, comparisons, FR and EN; and the asks the quote card itself offers (period chips, « compare … »);
- ``FINANCE_NO``: the look-alikes: « cours » as a lesson, « action » as a task, the price of a product, a company's
  accounts, a definition or a how-to, a piece of writing about the market, the user's own portfolio;
- ``FINANCE_ROUTER_YES``: clear asks the parser does not see (router-only, like ``opendata_router``).

``symbols`` is compared as a set of instruments (« LVMH, Hermès » = « Hermès, LVMH »); other arguments folded.
"""

from __future__ import annotations

FINANCE_YES = [
    # shares
    ("cours de l'action LVMH", {"symbols": "LVMH"}),
    ("graphique du cours de LVMH sur 1 an", {"symbols": "LVMH", "range": "1y"}),
    ("compare LVMH et Hermès", {"symbols": "LVMH, Hermès"}),
    ("compare LVMH et Hermès sur 5 ans", {"symbols": "LVMH, Hermès", "range": "5y"}),
    ("LVMH vs Hermès vs Kering sur 5 ans", {"symbols": "LVMH, Hermès, Kering", "range": "5y"}),
    ("combien vaut l'action Airbus ?", {"symbols": "Airbus"}),
    ("cours de bourse de TotalEnergies", {"symbols": "TotalEnergies"}),
    ("l'action L'Oréal sur 6 mois", {"symbols": "L'Oréal", "range": "6m"}),
    ("évolution de l'action Sanofi depuis un an", {"symbols": "Sanofi", "range": "1y"}),
    ("cours de l'action Orange sur 5 ans", {"symbols": "Orange"}),
    ("Nvidia en bourse", {"symbols": "Nvidia"}),
    ("Schneider Electric : cours et évolution sur 1 mois", {"symbols": "Schneider Electric", "range": "1m"}),
    ("où en est le titre BNP Paribas ?", {"symbols": "BNP Paribas"}),
    ("dois-je acheter des actions Airbus ?", {"symbols": "Airbus"}),
    ("dois-je acheter du bitcoin maintenant ?", {"symbols": "Bitcoin"}),  # live 28/11: answered « consultez un site »
    ("est-ce le moment d'investir dans Nvidia ?", {"symbols": "Nvidia"}),
    ("should I buy ethereum now?", {"symbols": "Ethereum"}),
    ("cours de MC.PA", {"symbols": "LVMH"}),
    ("stock price of Apple", {"symbols": "Apple"}),
    ("Apple share price over 5 years", {"symbols": "Apple", "range": "5y"}),
    ("compare Microsoft and Nvidia stock over a year", {"symbols": "Microsoft, Nvidia", "range": "1y"}),
    ("Tesla stock this month", {"symbols": "Tesla", "range": "1m"}),
    # indices
    ("le CAC 40 aujourd'hui", {"symbols": "CAC 40"}),
    ("le CAC 40 sur 5 ans", {"symbols": "CAC 40", "range": "5y"}),
    ("courbe du DAX sur 6 mois", {"symbols": "DAX", "range": "6m"}),
    ("compare le CAC 40 et le DAX sur un an", {"symbols": "CAC 40, DAX", "range": "1y"}),
    ("how is the DAX doing today?", {"symbols": "DAX"}),
    ("Nikkei 225 over the past year", {"symbols": "Nikkei 225", "range": "1y"}),
    ("le FTSE 100 cette année", {"symbols": "FTSE 100", "range": "1y"}),
    # crypto-assets
    ("cours du bitcoin", {"symbols": "Bitcoin"}),
    ("bitcoin sur 1 an", {"symbols": "Bitcoin", "range": "1y"}),
    ("prix du bitcoin en dollars", {"symbols": "Bitcoin"}),  # the currency is read from the words by the tool
    ("compare bitcoin et ethereum", {"symbols": "Bitcoin, Ethereum"}),
    ("combien vaut l'ether en ce moment ?", {"symbols": "Ethereum"}),
    ("bitcoin price over the last 6 months", {"symbols": "Bitcoin", "range": "6m"}),
    ("évolution du solana ce mois-ci", {"symbols": "Solana", "range": "1m"}),
    # currency pairs (ECB reference rates)
    ("évolution de l'euro dollar sur 6 mois", {"symbols": "EUR/USD", "range": "6m"}),
    ("historique EUR/USD sur 1 an", {"symbols": "EUR/USD", "range": "1y"}),
    ("le dollar sur un an", {"symbols": "EUR/USD", "range": "1y"}),
    ("courbe de la livre sterling face à l'euro depuis 6 mois", {"symbols": "GBP/EUR", "range": "6m"}),
    ("graphique du yen sur 5 ans", {"symbols": "EUR/JPY", "range": "5y"}),
    # the card's own asks (continuity): each one draws the updated chart
    ("cours de LVMH sur 5 ans", {"symbols": "LVMH", "range": "5y"}),
    ("cours de LVMH et Hermès sur 1 an", {"symbols": "LVMH, Hermès", "range": "1y"}),
    ("compare le cours de LVMH avec le CAC 40", {"symbols": "LVMH, CAC 40"}),
    ("cours de L'Oréal sur 1 mois", {"symbols": "L'Oréal", "range": "1m"}),
    ("CAC 40 sur 1 an", {"symbols": "CAC 40", "range": "1y"}),
    ("Bitcoin et Ethereum sur 1 mois", {"symbols": "Bitcoin, Ethereum", "range": "1m"}),
    ("compare Bitcoin avec Ethereum", {"symbols": "Bitcoin, Ethereum"}),
    ("EUR/USD sur 1 an", {"symbols": "EUR/USD", "range": "1y"}),
    ("Apple stock over 5 years", {"symbols": "Apple", "range": "5y"}),
    ("compare Apple stock with Microsoft", {"symbols": "Apple, Microsoft"}),
    # router-only at first, the parser sees them too
    ("comment se porte Hermès en bourse depuis janvier ?", {"symbols": "Hermès", "range": "1y"}),
    ("LVMH a-t-il plus progressé qu'Hermès cette année ?", {"symbols": "LVMH, Hermès"}),
    ("donne-moi la cotation de Safran", {"symbols": "Safran"}),
    ("ether vs bitcoin, lequel a le plus monté sur 6 mois ?", {"symbols": "Ethereum, Bitcoin", "range": "6m"}),
]

# « no » items of other families that ARE market asks (« quel est le cours de l'action LVMH » forbids a company card
# or a conversion, not the quote): left out of finance_cross, and not repeated here (one label per phrasing)
OTHER_FAMILIES_YES = {"quel est le cours de l'action LVMH"}

FINANCE_NO = [
    # « cours » as a lesson, a course, a moment
    "cours de piano à Lyon le samedi",
    # another asset named after a listed coin: never that coin's card (merge-core verification, 28/11/2026)
    "cours du Bitcoin Cash", "cours de l'Ethereum Classic", "combien vaut le Wrapped Bitcoin", "Bitcoin Gold price",
    "je cherche un cours d'anglais en ligne",
    "prépare un cours sur la bourse pour des lycéens",
    "au cours de la réunion, Paul a parlé d'Airbus",
    "le projet est en cours chez Airbus",
    "cours de maths sur les pourcentages",
    # « action » as a task
    "plan d'action commercial pour 2027",
    "quelles actions mener chez Airbus pour fidéliser le client ?",
    "liste des actions correctives après l'audit",
    "what action items came out of the Tesla meeting?",
    # the price of a product
    "prix de l'iPhone 16",
    "combien coûte un abonnement Netflix ?",
    "prix d'un MacBook Air chez Apple",
    "Amazon livraison gratuite à partir de combien ?",
    # a company's accounts, register or people (not the share)
    "chiffre d'affaires de LVMH en 2024",
    "compare les effectifs de LVMH et Hermès",
    "qui dirige Airbus ?",
    "siège social de TotalEnergies",
    "graphique du CA de Carrefour depuis 2015",
    # definitions, how-tos, writing about the market
    "c'est quoi le bitcoin ?",
    "comment fonctionne la bourse ?",
    "explique-moi le CAC 40",
    "qu'est-ce qu'une action en bourse ?",
    "rédige un article sur le cours du bitcoin",
    "écris un mail au client sur la baisse du CAC 40",
    "résume cet article sur Nvidia",
    "how do I buy Apple shares?",
    "composition du CAC 40",
    "quelles entreprises sont dans le CAC 40 ?",
    # the user's own holdings or company
    "mes actions LVMH ont baissé, que faire ?",
    "mon portefeuille d'actions",
    "nos stock-options chez Airbus",
    # common words that are also names
    "le total des ventes du mois",
    "une orange pressée le matin",
    "Apple a présenté un nouvel iPhone",
    "la météo des marchés à Lyon",
    "fais un graphique du CA : T1 120, T2 135,5",
    "le cours de la Seine à Paris",
    "le cours de la réunion a changé",
]

# clear asks the parser misses: router-only (router_data family "finance_router"), never on the regex bench
FINANCE_ROUTER_YES = [
    ("Safran, ça monte ou ça baisse ?", {"symbols": "Safran"}),
    ("et Apple, ça a pris combien depuis l'été ?", {"symbols": "Apple"}),
    ("is Nvidia up or down this week?", {"symbols": "Nvidia"}),
]


def _fold(v) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("'", " ").split())


def same_symbols(got, want) -> bool:
    """The same set of instruments (names, tickers or pairs resolved through markets.py)."""
    from birds.harness.tools.opendata import finance

    try:
        a = {i.key for i in finance.instruments_of({"symbols": got})}
        b = {i.key for i in finance.instruments_of({"symbols": want})}
    except Exception:
        return False
    return a == b


def args_match(got: dict, want: dict) -> bool:
    for k, v in want.items():
        if k not in got:
            return False
        if k == "symbols":
            if not same_symbols(got[k], v):
                return False
        elif _fold(got[k]) != _fold(v):
            return False
    return True


def _lang(q: str) -> str:
    from birds.harness.agent import detect_lang

    return "en" if detect_lang(q) == "en" else "fr"


def started(item) -> bool:
    """The market parser starts the expected get_quote call (and only that one)."""
    from birds.harness import opendata_intents

    q, want = item
    found = opendata_intents.detect(q, False, _lang(q))
    return bool(found and found[0].args and found[0].tool == "get_quote" and args_match(found[0].args, want))


def touched(q: str) -> bool:
    """Any get_quote call started (a "no" must start none)."""
    from birds.harness import opendata_intents

    return any(i.tool == "get_quote" and i.args for i in opendata_intents.detect(q, False, _lang(q)))
