"""Deterministic reading of a market ask (get_quote, birds/harness/tools/opendata/finance.py): a HINT for the model
router and the fallback when it does not answer, never the decision when it does (birds/harness/opendata_route.py).

Says yes only when a listed instrument (``markets.py``) is named together with a market word: « cours de l'action
LVMH », « le CAC 40 sur 5 ans », « compare LVMH et Hermès », « bitcoin sur 1 an », « évolution de l'euro dollar
sur 6 mois ». Stays silent on the known look-alikes: « cours » as a lesson (« cours de piano »), « action » as a task
(« plan d'action », « quelles actions mener chez Airbus »), the price of a product (« prix de l'iPhone »), a
definition or a how-to (« c'est quoi le bitcoin ? »), a piece of writing about the market, the user's own
portfolio. Pure functions, no I/O.
"""

from __future__ import annotations

import re

from birds.harness.intents import Intent
from birds.harness.tools.opendata.finance import range_of
from birds.harness.tools.opendata.markets import AMBIGUOUS, find_all, fold, fx_pair

# a market word next to the instrument: these are enough for a share named without ambiguity
_MARKET = re.compile(
    r"\b(?:cours|cotations?|cot[ée]e?s?|bourse|boursi\w+|indices?|titres?|stocks?|share\s+prices?|shares?|"
    r"stock\s+prices?|ticker|valeurs?|vaut|valait|prix\s+(?:du|de\s+l'|de\s+la|of)|price|cl[ôo]tur\w*|s[ée]ance|"
    r"performance|perf|[ée]volution|historique|history|graphique|graph|courbe|chart|compar\w*|versus|vs|base\s+100|"
    r"hausse|baisse|monte|descend|chute|gagn[ée]|perdu|niveau|points?|aujourd'hui|today|en\s+ce\s+moment|"
    r"market|march[ée]s?\s+financiers?)\b", re.I)  # fmt: skip
# the strong ones: an ambiguous name (Orange, Apple, Total, Vinci…) counts only next to one of these
_STRONG = re.compile(r"\b(?:cours\s+(?:de\s+l'action|de\s+bourse|boursiers?)|cours\s+(?:de\s+|d'|du\s+)(?-i:(?=[A-Z]))|"
                     r"cotations?|cot[ée]e?s?|en\s+bourse|"
                     r"l'action|actions?\s+(?=[A-Z])|titres?\s+(?=[A-Z])|stocks?|share\s+prices?|stock\s+prices?|"
                     r"shares?\s+of|ticker|base\s+100)", re.I)  # fmt: skip
# a lesson, a task, a product: « cours » and « action » that are not the market
_LESSON = re.compile(r"\bcours\s+(?:de|d')\s*(?:piano|guitare|chant|danse|yoga|maths?|math[ée]matiques|fran[cç]ais|"
                     r"anglais|langue|cuisine|dessin|natation|tennis|conduite|histoire|g[ée]o\w*|physique|chimie|"
                     r"code|informatique|programmation|soutien|rattrapage|sport|th[ée][âa]tre|musique|danse)\b|"
                     r"\b(?:au|en|un|le|mon|ton|son|du)\s+cours\s+(?:de\s+)?(?:la\s+)?(?:journ[ée]e|semaine|ann[ée]e|"
                     r"r[ée]union|projet|mois|conversation)\b|\ben\s+cours\b|\bau\s+cours\s+(?:de|du|des)\b", re.I)  # fmt: skip
_TASK = re.compile(r"\bplan\s+d'actions?\b|\bactions?\s+(?:[àa]\s+(?:mener|faire|pr[ée]voir)|correctives?|"
                   r"commerciales?|marketing|prioritaires?|concr[èe]tes?)\b|\b(?:quelles?|les)\s+actions?\s+"
                   r"(?:mener|faire|engager|lancer|pour)\b|\baction\s+items?\b|\bcall\s+to\s+action\b|"
                   r"\btake\s+action\b|\bactions?\s+(?:to\s+take|plan)\b", re.I)  # fmt: skip
_PRODUCT = re.compile(r"\b(?:iphone|ipad|macbook|airpods|watch|galaxy|pixel|kindle|prime|abonnement|forfait|"
                      r"livraison|produits?|article|commande|billet|vol|subscription|delivery|order)\b", re.I)  # fmt: skip
_DELIVERABLE = re.compile(r"\b(?:r[ée]dig\w*|[ée]cri(?:s|re|vez|t)\b|mail|e-mail|courriel|lettre|traduis\w*|"
                          r"traduire|reformule\w*|r[ée]sum\w*|pr[ée]sentation|diapo\w*|slides?|deck|document|rapport|"
                          r"report|note\s+de|article\s+sur|draft|write|compose|programme\w*|fonction|script|python|"
                          r"javascript|sql|formule|formula|macro|vba|code|api|excel|tableur|spreadsheet|translat\w*|"
                          r"summari[sz]\w*|proofread\w*|rewrit\w*|corrige\w*|pr[ée]pare\s+un\s+cours)\b", re.I)  # fmt: skip
_HOWTO = re.compile(r"\b(?:comment\s+(?:fonctionne|marche|acheter|investir|lire|calculer|ça\s+marche)|how\s+(?:do|to|"
                    r"does|can)|pourquoi|why|explique\w*|explain|qu'est-ce\s+qu|c'est\s+quoi|what\s+is|what's|"
                    r"que\s+signifie|d[ée]finition|define|histoire\s+(?:de|du)|history\s+of|qui\s+a\s+(?:cr[ée]{2}|"
                    r"invent[ée])|who\s+(?:created|invented))\b", re.I)  # fmt: skip
# the user's own holdings or company: not a market quote
_OWN = re.compile(r"\b(?:mes|mon|ma|nos|notre|my|our)\s+(?:actions?|portefeuille|placements?|titres?|stock-?options?|"
                  r"bsp?ce|pea|shares?|portfolio|investissements?|entreprise|soci[ée]t[ée]|bo[iî]te)\b|"
                  r"\b(?:portefeuille|portfolio)\b", re.I)  # fmt: skip
# the members of an index, its history or its rules: an article, not a price
_INDEX_FACTS = re.compile(r"\b(?:composition|compos[ée]|membres?|entreprises?\s+(?:du|de)|soci[ée]t[ée]s\s+(?:du|de)|"
                          r"liste\s+des|entr[ée]e?\s+dans|int[èe]gr\w+|rejoin\w+|sort\w*\s+du|r[èe]gles?|cr[ée]{2}\s+en|"
                          r"companies\s+in|members\s+of|constituents?)\b", re.I)  # fmt: skip
_FX_HISTORY = re.compile(r"\b(?:[ée]volution|historique|history|courbe|graphique|graph|chart|tendance|trend|"
                         r"variation|depuis|sur\s+(?:\d+|un|une|six|cinq)\s+(?:mois|ans?|semaines)|over\s+(?:the\s+)?"
                         r"(?:past|last)?\s*(?:\d+|a|one|six|five)?\s*(?:months?|years?)|this\s+year|cette\s+ann[ée]e|"
                         r"base\s+100)\b", re.I)  # fmt: skip
# a company's accounts or headcount, not its share price (« le CA d'Airbus depuis 2015 »: official figures or the web)
_ACCOUNTS = re.compile(r"\b(?:chiffres?\s+d'affaires|(?-i:CA)|ventes|r[ée]sultats?|b[ée]n[ée]fices?|pertes|marges?|"
                       r"effectifs?|salari[ée]s|employ[ée]s|emplois|revenue|sales|profits?|earnings|headcount|"
                       r"employees|dividendes?|dividends?|dette|debt|capital\s+social|actionnaires?|shareholders?|"
                       r"si[èe]ge|dirigeants?|pdg|ceo|siren|siret|adresse)\b", re.I)  # fmt: skip
_COMPARE = re.compile(r"\b(?:compar\w*|versus|vs\.?|contre|face\s+[àa]|par\s+rapport\s+[àa]|against)\b", re.I)


def _clean(text: str) -> str:
    t = " ".join(str(text or "").replace("’", "'").split())
    return re.sub(r"^(?:bonjour|bonsoir|salut|hello|hi)\b[\s,!]*", "", t, flags=re.I)


def quote(text: str, lang: str = "fr") -> Intent | None:
    """The get_quote call these words ask for, or None. ``Intent(tool, None)`` is never returned: a market word
    without a listed instrument is left to the model (it may still pick the module, or answer in words)."""
    t = _clean(text)
    if not t or len(t) > 220 or _DELIVERABLE.search(t) or _HOWTO.search(t) or _OWN.search(t):
        return None
    if _LESSON.search(t) and not _STRONG.search(t):
        return None
    insts = find_all(t)
    args: dict = {}
    rng = range_of(t)
    if not insts:
        fx = fx_pair(_fx_words(t)) if _FX_HISTORY.search(t) else None
        if fx is None:
            return None
        args = {"symbols": fx.symbol}
        if rng:
            args["range"] = rng
        return Intent("get_quote", args, keep_web=False, mode="history")  # wins over the day's conversion
    if _TASK.search(t) and not re.search(r"\b(?:cours|bourse|cotation|stock|share)", t, re.I):
        return None
    if _PRODUCT.search(t) and not _STRONG.search(t):
        return None  # « prix d'un iPhone chez Apple »: a product, not the share
    if _ACCOUNTS.search(t) and not _STRONG.search(t):
        return None  # « le chiffre d'affaires d'Airbus », « compare les effectifs de LVMH et Hermès »
    kinds = {i.kind for i in insts}
    words = {fold(t)}
    strong = bool(_STRONG.search(t))
    market = bool(_MARKET.search(t))
    for i in insts:
        named = [a for a in i.aliases if re.search(rf"(?<![\w]){re.escape(a)}(?![\w])", next(iter(words)))]
        if named and all(a in AMBIGUOUS for a in named) and not strong:
            return None  # « une orange », « le total », « Apple a sorti un iPhone »: not the share
    if kinds <= {"index"}:
        if _INDEX_FACTS.search(t) and not strong:
            return None
        if not (market or rng or len(t.split()) <= 5):
            return None
    elif kinds <= {"crypto"}:
        if not (market or rng or len(t.split()) <= 4):
            return None
    elif not (strong or market or rng or (len(insts) >= 2 and _COMPARE.search(t))):
        return None
    if len(insts) >= 2 and not (_COMPARE.search(t) or market or rng or re.search(r"\bet\b|\band\b|,", t)):
        return None
    args = {"symbols": ", ".join(i.name for i in insts)}
    if rng:
        args["range"] = rng
    if re.search(r"\b(?:en|in)\s+(?:dollars?|usd)\b", t, re.I) and kinds <= {"crypto"}:
        args["currency"] = "USD"
    return Intent("get_quote", args, keep_web=False)


def _fx_words(t: str) -> str:
    """« évolution de l'euro face au dollar sur 6 mois » → « euro dollar »: only the currency words remain."""
    from birds.harness import intents

    words = re.findall(r"[A-Za-zÀ-ÿ]+(?:/[A-Za-z]{3})?", t)
    keep = []
    for w in words:
        if "/" in w:
            return w
        if intents.currency_code(w) and w.lower() not in ("en", "de", "a", "le", "la", "sur", "mois", "an", "ans"):
            keep.append(w)
    return " ".join(keep)
