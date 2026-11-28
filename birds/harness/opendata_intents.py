"""Deterministic reading of the user's OWN words for the open-data tools (birds/harness/tools/opendata).

Bird S 4B was never trained on these tools, so the harness decides, as birds/harness/intents.py does for places,
companies, rates and weather: a confident parser returns the call itself (``Intent.args``), run before the first
generation; nothing is guessed from the model's text. Each parser says yes only on a clear ask and stays silent on
ordinary office prompts (« rédige un mail… », « comment calculer… », « c'est quoi un KPI ? »): see
scripts/trigger_bench.py (families opendata_*) and tests/test_opendata.py. Pure functions, no I/O.
"""

from __future__ import annotations

import re
from datetime import date

from birds.harness.intents import FIRST_NAMES, Intent, known_place
from birds.harness.tools.opendata import calendar as cal
from birds.harness.tools.opendata import countries
from birds.harness.tools.opendata.commune import looks_like_address
from birds.harness.tools.opendata.places_fr import where as fr_where
from birds.harness.tools.opendata.stats import indicator_of
from birds.opendata_schemas import CHART_TOOLS, OPENDATA_NAMES

OWN_ANSWER = set(OPENDATA_NAMES)  # the card answers: web tools withdrawn unless the words ask for the web


def own(prefill) -> bool:
    return bool(prefill is not None and prefill.tool in OWN_ANSWER)


def withdraw(prefill) -> set[str]:
    """Tools to withdraw for this turn: a statistics chart is already drawn, so no second make_chart."""
    return {"make_chart"} if prefill is not None and prefill.tool in CHART_TOOLS else set()


def _clean(text: str) -> str:
    t = " ".join(str(text or "").replace("’", "'").split())
    return re.sub(r"^(?:bonjour|bonsoir|salut|hello|hi)\b[\s,!]*", "", t, flags=re.I)


# a piece of writing, a file, code or a how-to: the data is context there, never a card of its own
_DELIVERABLE = re.compile(
    r"\b(?:r[ée]dig\w*|[ée]cri(?:s|re|vez|t)\b|mail|e-mail|courriel|courrier|lettre|traduis\w*|traduire|reformule\w*|"
    r"r[ée]sum\w*|pr[ée]sentation|diapo\w*|slides?|pptx|powerpoint|deck|document|docx|rapport|report|note de|"
    r"tableur|excel|xlsx|spreadsheet|feuille de calcul|draft|write|compose|programme\w*|fonction|script|"
    r"code(?!\s+(?:postal|insee|naf|ape|commune))|python|"
    r"javascript|sql|formule|formula|macro|vba|api\b|tableau|table)\b",
    re.I,
)
_HOWTO = re.compile(
    r"\b(?:comment|how (?:do|to|can|should)|pourquoi|why|explique\w*|explain|d[ée]finition|define|qu'est-ce qu|"
    r"c'est quoi|what is|what's|que signifie|what does)\b",
    re.I,
)


# ---------------------------------------------------------------- calendar (holidays, working days)

_HOLIDAY = re.compile(r"\bjours?\s+f[ée]ri[ée]s?\b|\bf[ée]ri[ée]s?\b|\bpublic holidays?\b|\bbank holidays?\b|"
                      r"\bholidays?\s+in\b|\bnational holidays?\b", re.I)  # fmt: skip
_WORKDAYS = re.compile(r"\bjours?\s+ouvr(?:[ée]s?|ables?)\b|\bouvr[ée]s\b|\bworking days?\b|\bbusiness days?\b|"
                       r"\bwork days?\b|\bweekdays\b", re.I)  # fmt: skip
_MONTH = (r"janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|"
          r"january|february|march|april|may|june|july|august|september|october|november|december")  # fmt: skip
_DATE = (rf"(?:(?:le\s+|the\s+)?(?:1er|\d{{1,2}})\s+(?:{_MONTH})(?:\s+(?:19|20)\d\d)?|(?:{_MONTH})\s+\d{{1,2}}"
         rf"(?:st|nd|rd|th)?(?:,?\s+(?:19|20)\d\d)?|\d{{1,2}}/\d{{1,2}}(?:/(?:\d{{4}}|\d{{2}}))?|(?:19|20)\d\d-\d\d-\d\d)")  # fmt: skip
_RX_DATE = re.compile(_DATE, re.I)
_RX_MONTH_YEAR = re.compile(rf"\b(?:en\s+|in\s+|de\s+|du mois de\s+|pour\s+|for\s+)?({_MONTH})(?:\s+((?:19|20)\d\d))?\b",
                            re.I)  # fmt: skip
_RX_YEAR = re.compile(r"\b((?:19|20)\d\d)\b")
_RX_PLUS = re.compile(r"\b[jJ]\s*\+\s*(\d{1,3})\b(?:\s*(?:jours?\s+)?ouvr\w*)?|\b(\d{1,3})\s+(?:jours?\s+ouvr\w*|"
                      r"working days?|business days?)", re.I)  # fmt: skip
_RX_FROM = re.compile(rf"\b(?:[àa]\s+partir\s+du|[àa]\s+compter\s+du|apr[èe]s\s+le|depuis\s+le|du|from|after|starting)\s+"
                      rf"(?P<d>{_DATE})", re.I)  # fmt: skip
_RX_WEEKDAY = re.compile(
    rf"(?P<d>{_DATE})\s+(?:tombe|tombera|est|sera|c'est)\s+(?:un\s+)?quel\s+jour|quel\s+jour\s+(?:tombe|tombera|est|"
    rf"sera)\s+(?P<d2>{_DATE})|what\s+day\s+(?:is|does|will)\s+(?P<d3>{_DATE})|(?P<d4>{_DATE})\s+(?:est-il|est-ce|"
    rf"sera-t-il|c'est)\s+(?:un\s+jour\s+)?f[ée]ri[ée]|is\s+(?P<d5>{_DATE})\s+a\s+(?:public\s+|bank\s+)?holiday|"
    rf"(?P<d6>{_DATE})\s+(?:est\s+)?f[ée]ri[ée]\s*\?",
    re.I,
)
_NOT_CALENDAR = re.compile(r"\b(?:pose[rz]?|prendre|prends|cong[ée]s?\s+pay[ée]s|rtt|cale|planifie|organise|"
                           r"r[ée]union|rdv|rendez-vous|meeting|majoration|pay[ée]s?\s+double|travaill[ée]|"
                           r"heures?\s+sup|salaire)\b", re.I)  # fmt: skip


def _zone_words(t: str) -> str:
    f = cal.fold(t)
    for w in sorted(cal._ZONE_WORDS, key=len, reverse=True):
        if w in ("france", "metropole") or len(w) < 4:
            continue
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", f):
            return cal._ZONE_WORDS[w]
    for w in sorted(cal._COUNTRY_WORDS, key=len, reverse=True):
        if len(w) <= 2:
            if re.search(r"(?<![\w-])" + w.upper() + r"(?![\w-])", t):
                return cal._COUNTRY_WORDS[w]
            continue
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", f):
            return cal._COUNTRY_WORDS[w]
    return "metropole"


def _iso(d: str, today: date) -> str:
    try:
        kind, y, m, day = cal.parse_period(re.sub(r"^(?:le|the)\s+", "", d.strip(), flags=re.I), today)
    except Exception:  # noqa: BLE001 - not a date this reader knows
        return ""
    return day.isoformat() if day else ""


def calendar(text: str, lang: str = "fr", today: date | None = None) -> Intent | None:
    """« combien de jours ouvrés en mai 2027 », « jours fériés 2027 en Alsace-Moselle », « J+15 ouvrés à partir du
    20 avril », « le 8 mai tombe quel jour », « le 6 janvier est-il férié en Espagne ? »."""
    today = today or cal.today_paris()
    t = _clean(text)
    if not t or len(t) > 220 or _DELIVERABLE.search(t) or re.search(
            r"\b(?:comment|how (?:to|do|can)|diff[ée]rence|d[ée]finition|signifi\w*|veut dire|c'est quoi|qu'est-ce|"
            r"what is|what's the difference)\b", t, re.I):  # fmt: skip
        return None
    hol, work, plus = _HOLIDAY.search(t), _WORKDAYS.search(t), _RX_PLUS.search(t)
    wd = _RX_WEEKDAY.search(t)
    if not (hol or work or plus or wd):
        return None
    if _NOT_CALENDAR.search(t) and not (plus or wd):
        return None  # « pose un congé le 8 mai », « réunion le jour férié »: an event or an HR question
    zone = _zone_words(t)
    if plus and (work or re.search(r"\b[jJ]\s*\+", t)):
        n = int(plus.group(1) or plus.group(2))
        m = _RX_FROM.search(t)
        start = _iso(m.group("d"), today) if m else ""
        if not start and re.search(r"\b(?:dans|in|d'ici|from today|aujourd'hui|from now)\b", t, re.I):
            start = today.isoformat()
        if start and 0 < n <= cal.MAX_ADD:
            return Intent("work_calendar", {"period": start, "zone": zone, "add_days": n}, keep_web=False)
        return None  # « nos délais sont de 5 jours ouvrés »: no date to count from
    if wd:
        d = next(g for g in (wd.group(k) for k in ("d", "d2", "d3", "d4", "d5", "d6")) if g)
        iso = _iso(d, today)
        return Intent("work_calendar", {"period": iso, "zone": zone}, keep_web=False) if iso else None
    if not (hol or work):
        return None
    # « combien de jours ouvrés en mai 2027 », « jours fériés de décembre »: a month; else a year (this one)
    mm = _RX_MONTH_YEAR.search(t)
    year_m = _RX_YEAR.search(t)
    if re.search(r"\b(?:ce mois|this month)\b", t, re.I):
        period = f"{today.year}-{today.month:02d}"
    elif re.search(r"\b(?:le mois prochain|next month)\b", t, re.I):
        period = f"{today.year + (today.month == 12)}-{today.month % 12 + 1:02d}"
    elif mm and not (mm.group(1).lower() == "mai" and re.search(r"\b8\s+mai|1er\s+mai\b", t, re.I) and hol):
        mo = cal._MONTH_WORDS.get(cal.fold(mm.group(1)))
        y = int(mm.group(2)) if mm.group(2) else (int(year_m.group(1)) if year_m else
                                                  (today.year if mo >= today.month else today.year + 1))  # fmt: skip
        period = f"{y}-{mo:02d}"
    elif year_m:
        period = year_m.group(1)
    elif re.search(r"\b(?:l'an prochain|l'ann[ée]e prochaine|next year)\b", t, re.I):
        period = str(today.year + 1)
    else:
        period = str(today.year)
    if work and not re.search(r"\b(?:combien|nombre|how many|count|compte|calcul\w*|liste|quels?|quelles?|y a-t-il|"
                              r"en\s+(?:" + _MONTH + r")|\d{4})\b", t, re.I):  # fmt: skip
        return None  # « on travaille en jours ouvrés » is a statement, not an ask
    if hol and not work and not (t.rstrip().endswith("?") or re.search(
            r"\b(?:quels?|quelles?|liste|combien|calendrier|dates?|which|list|when|how many|(?:19|20)\d\d|"
            r"l'an(?:n[ée]e)? prochaine?|cette ann[ée]e|next year|this year)\b|^(?:les\s+)?jours\s+f[ée]ri[ée]s(?:\s+(?:en|de|du|des|à|au|in|pour)\b|\s*(?:19|20)\d\d|\s*$)|"
            r"^public holidays",
            t, re.I)):  # fmt: skip
        return None
    return Intent("work_calendar", {"period": period, "zone": zone}, keep_web=False)


# ---------------------------------------------------------------- statistics (charts of real series)

_CHART_CUE = re.compile(
    r"\b(?:graphiques?|graphe|courbes?|en graphique|chart|graph|plot|visualis\w*|diagramme)\b", re.I
)
_COMPARE = re.compile(r"\b(?:vs\.?|versus|contre|compar\w*|et|and)\b", re.I)
_SINCE_YEAR = re.compile(
    r"\b(?:depuis|since|from|de|entre|between|d[ée]but)\s+(?:l'an\s+|the year\s+)?((?:19|20)\d\d)\b", re.I
)
_SINCE_N = re.compile(r"\b(?:sur|over|depuis|ces|les|the last|the past|last|past|des)\s+(\d{1,2})\s+(?:derni[èe]res\s+)?"
                      r"(ans|ann[ée]es|years|mois|months|derniers mois)\b", re.I)  # fmt: skip
_CREATIONS_ASK = re.compile(r"\bcombien\s+d'entreprises\s+(?:ont\s+[ée]t[ée]\s+)?cr[ée]{2}e?s|\bnombre\s+de\s+cr[ée]ations\s+"
                            r"d'entreprises|\bhow many (?:businesses|companies) (?:were )?(?:created|started)", re.I)  # fmt: skip
_BUSINESS = re.compile(
    r"\b(?:entreprises?|professionnels?|pros?|industriels?|business(?:es)?|companies|non-household)\b", re.I
)
_TOWN_OF = re.compile(r"\b(?i:population|habitants)\s+(?i:de|d'|du|of|à|a|in)\s*(?i:la\s+ville\s+de\s+)?"
                      r"(?P<t>[A-ZÀ-Ý][\w'-]+(?:\s+(?:sur|en|le|la|les|de|du|lès|sous)\s+[A-ZÀ-Ý][\w'-]+|"
                      r"\s+[A-ZÀ-Ý][\w'-]+){0,2})")  # fmt: skip
_FOREIGN_CITY = re.compile(r"\b(?:london|londres|berlin|madrid|rome|new york|tokyo|bruxelles|brussels|gen[èe]ve|"
                           r"montr[ée]al|barcelone|barcelona|milan|amsterdam|lisbonne|lisbon|munich|vienne|prague|"
                           r"dubai|duba[iï]|singapour|singapore|shanghai|p[ée]kin|beijing|sydney|los angeles|chicago)\b", re.I)  # fmt: skip


_RANKING = re.compile(r"\b(?:(?:des|les|de\s+nos|of\s+the)\s+(?:\d+\s+)?(?:plus\s+(?:grand|petit|peupl)\w*\s+)?(?:villes|communes|"
                      r"r[ée]gions|d[ée]partements|pays|entreprises|capitales|m[ée]tropoles|agences|cities|countries|"
                      r"regions)|top\s+\d+|classement|ranking|largest|biggest|plus\s+grandes?|plus\s+peupl[ée]e?s)\b", re.I)  # fmt: skip


def _since_of(t: str, today: date) -> str:
    m = _SINCE_N.search(t)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        return f"{n}m" if unit.startswith(("mois", "month", "derniers mois")) else f"{n}y"
    m = _SINCE_YEAR.search(t)
    if m and int(m.group(1)) <= today.year:
        return m.group(1)
    return ""


def statistics(text: str, lang: str = "fr", today: date | None = None) -> Intent | None:
    """« évolution du chômage en France depuis 2015 », « PIB Allemagne vs France », « population de Lille sur 10
    ans », « inflation dans la zone euro sur 24 mois en graphique », « combien d'entreprises créées l'an dernier »."""
    from birds.harness.agent import figures_in, trend_ask  # the same readings as the chart router

    today = today or date.today()
    t = _clean(text)
    if not t or len(t) > 240 or _DELIVERABLE.search(t) or _HOWTO.search(t):
        return None
    key = indicator_of(t)
    if not key or _RANKING.search(t) or figures_in(t):
        return None  # « la population des 3 plus grandes villes »: a ranking, not one series per place
    if key == "electricity" and not _BUSINESS.search(t):
        return None  # households' tariffs are another dataset, not drawn here
    places = countries.find(t)
    since = _since_of(t, today)
    trend = trend_ask(t) or bool(_CHART_CUE.search(t)) or bool(since) or bool(_SINCE_YEAR.search(t))
    compare = len(places) >= 2 and bool(_COMPARE.search(t))
    if key == "creations":
        if not (trend or _CREATIONS_ASK.search(t)):
            return None
        return Intent("get_statistics", {"indicator": key, "places": "France", "since": since}, keep_web=False)
    if key == "electricity":
        names = [countries.name(c, "fr") for c in places if countries.in_eurostat(c)] or ["France"]
        return Intent("get_statistics", {"indicator": key, "places": ", ".join(names), "since": since}, keep_web=False)
    if not (trend or compare):
        return None
    if not places:
        m = _TOWN_OF.search(t)
        if key == "population" and m:
            town = m.group("t").strip(" '-")
            if _FOREIGN_CITY.search(town) or cal.fold(town) in FIRST_NAMES:
                return None
            return Intent("get_statistics", {"indicator": key, "places": town, "since": since}, keep_web=False)
        if _FOREIGN_CITY.search(t):
            return None  # « la population de Londres depuis 2000 »: no series for a foreign city
        if key == "population" and re.search(r"\b(?:de|du|des|of|à|in)\s+[a-zà-ÿ]{3,}", t) and not re.search(
                r"\b(?:fran[cç]ais|france)\b", t, re.I):  # fmt: skip
            return None  # « la population de lyon » typed in lowercase: unclear, leave it to the chart router
        places = ["FR"]
    names = ", ".join(countries.name(c, "fr") for c in places[:5])
    return Intent("get_statistics", {"indicator": key, "places": names, "since": since}, keep_web=False)


# ---------------------------------------------------------------- entity card (Wikipedia + Wikidata)

_RX_WHAT = re.compile(
    r"^(?:et\s+)?(?:c'est\s+quoi|qu'est-ce\s+que(?:\s+c'est\s+que)?|qu'est\s+ce\s+que|what\s+is|what's|who\s+are)\s+"
    r"(?P<x>.{2,60}?)\s*\??$",
    re.I,
)
_RX_SHEET = re.compile(
    r"^(?:(?:donne|fais|montre|affiche|pr[ée]pare)(?:-moi|\s+moi)?\s+)?(?:une\s+|la\s+)?(?:fiche|carte\s+d'identit[ée]|"
    r"pr[ée]sentation\s+rapide)\s+(?:pays\s+(?:(?:sur|de|du|des|d'|pour)\s*)?|(?:sur|de|du|des|d'|pour)\s*)(?P<x>[^(?!,:]{2,60}?)\s*(?:\(.*\))?\s*\??$",
    re.I,
)
_RX_FACT = re.compile(
    r"\b(?:quelle\s+est\s+la\s+|c'est\s+quoi\s+la\s+|la\s+)?(?:capitale|monnaie|devise|langue\s+officielle|superficie|"
    r"chef\s+de\s+l'[ée]tat|pr[ée]sident|capital|currency|official\s+language)\s+(?:de\s+la|de\s+l'|du|des|de|d'|of)\s*"
    r"(?P<x>[\w' -]{3,40}?)\s*\??$",
    re.I,
)
_GENERIC = re.compile(
    r"^(?:un|une|des|les|mon|ma|mes|ton|ta|tes|notre|nos|votre|vos|ce|cet|cette|ces|ça|ca|a|an|the|my|our|your|"
    r"le\s+meilleur|la\s+meilleure|le\s+mieux|la\s+diff[ée]rence|le\s+probl[èe]me|la\s+proc[ée]dure|le\s+plus)\b",
    re.I,
)


def _proper(x: str) -> str:
    """The name of a thing, or '' (a common noun, a person's first name, a sentence)."""
    x = x.strip(" '\"«»?.!")
    x = re.sub(r"\s+(?:exactement|en bref|en r[ée]sum[ée]|stp|svp|please|au juste)$", "", x, flags=re.I)
    if not x or _GENERIC.match(x) or len(x.split()) > 5 or re.search(r"(?i:\b(?:d'une?|un|une|des)\b)", x):
        return ""  # « le DOI d'un article », « le rôle d'une DRH »: a concept, not a named thing
    core = re.sub(r"^(?:le|la|les|l'|the)\s*", "", x, flags=re.I)
    if not core:
        return ""
    if countries.find(core) or (known_place(core) and " " not in core):
        return core
    if not core[:1].isupper() or core.lower() in FIRST_NAMES:
        return ""
    words = core.split()
    if len(words) == 2 and words[0].lower() in FIRST_NAMES:
        return ""  # « Marie Dupont »: a person, maybe a colleague; never looked up
    if re.search(r"\b(?:projet|project|dossier|client|fichier|file|r[ée]union|meeting|[ée]quipe|team)\b", core, re.I):
        return ""
    return core


def entity(text: str, lang: str = "fr") -> Intent | None:
    """« C'est quoi Airbus ? », « fiche sur le Portugal (capitale, population, monnaie) », « capitale du Kenya »."""
    t = _clean(text)
    if not t or len(t) > 160 or _DELIVERABLE.search(t):
        return None
    for rx in (_RX_SHEET, _RX_WHAT, _RX_FACT):
        m = rx.match(t) if rx is not _RX_FACT else rx.search(t)
        if not m:
            continue
        x = _proper(m.group("x"))
        if rx is _RX_FACT and not countries.find(x):
            continue  # « la capitale de notre réseau »: only a country's facts
        if rx is _RX_SHEET and re.search(r"\b(?:entreprise|soci[ée]t[ée]|poste|paie|produit|client|fournisseur)\b",
                                         m.group("x"), re.I):  # fmt: skip
            return None  # « fiche de poste », « fiche entreprise X »: a job sheet or the company register
        if x:
            return Intent("lookup_entity", {"name": x}, keep_web=False)
    return None


# ---------------------------------------------------------------- public tenders (BOAMP)

_TENDER = re.compile(r"\b(?:appels?\s+d'offres?|\bAO\b|march[ée]s\s+publics?|march[ée]\s+public|consultations?\s+"
                     r"publiques?|commande\s+publique|boamp|public\s+tenders?|tenders?|calls?\s+for\s+tenders?)\b", re.I)  # fmt: skip
_TENDER_NO = re.compile(r"\b(?:r[ée]pon\w+|candidat\w*|m[ée]moire\s+technique|dce|dossier|lettre|offre\s+de\s+prix|"
                        r"remport\w*|gagn\w*|perdu|rejet\w*|attribu\w*|code\s+de\s+la\s+commande|seuils?|r[ée]glement\w*|"
                        r"proc[ée]dures?|formation|respond|bid\s+for|write)\b", re.I)  # fmt: skip
_TENDER_ASK = re.compile(r"\b(?:trouve|cherche|liste|montre|affiche|quels?|quelles?|y\s+a-t-il|y\s+a\s+t\s+il|il\s+y\s+a|"
                         r"des|derniers|r[ée]cents|nouveaux|veille|find|list|show|any|latest|new|recent)\b", re.I)  # fmt: skip
_TOPIC = re.compile(r"(?:\b(?:en|de|pour|sur|concernant|dans\s+le\s+domaine\s+(?:du|de\s+la|de\s+l')|in|for|on)\s+|"
                    r"(?:appels?\s+d'offres?|march[ée]s?\s+publics?|tenders?|\bAO\b)\s+)"
                    r"(?P<k>(?!(?:le|la|les|l'|cours|ligne|ce|cette|france|r[ée]gion|bretagne)\b)[a-zà-ÿ][\w'-]*(?:\s+(?:de|des|du|d'|"
                    r"et)?\s*[a-zà-ÿ][\w'-]*){0,3})", re.I)  # fmt: skip
_TOPIC_STOP = re.compile(r"\s+(?:publi\w+|dans|en|sur|du|de\s+la|cette|ce|depuis|pour|à|a|au|aux|in|on|this|since|"
                         r"near|pr[èe]s|stp|svp|r[ée]cent\w*|ouverts?)\b.*$", re.I)  # fmt: skip


def tenders(text: str, lang: str = "fr") -> Intent | None:
    """« appels d'offres en nettoyage de locaux publiés cette semaine », « marchés publics informatique dans le 59 »."""
    t = _clean(text)
    if not t or len(t) > 200 or not _TENDER.search(t) or _TENDER_NO.search(t) or _HOWTO.search(t):
        return None
    # an ask word, or a search typed as a noun phrase (« marchés publics informatique dans le 59 »)
    if _DELIVERABLE.search(t) or not (_TENDER_ASK.search(t) or _TENDER.match(t)):
        return None
    after = t[_TENDER.search(t).end() :]
    # « appels d'offres nettoyage de locaux » : the subject right after the noun, before any preposition inside it
    after = re.sub(r"^(?:\s+(?:boamp|ouverts?|publi[ée]s?|en\s+cours))+", "", after, flags=re.I)
    lead = re.match(r"\s+(?:(?:en|de|des|du|pour|sur|concernant|in|for|on)\s+)?(?:(?:de\s+la|de\s+l'|la|le|les|l'|une?|d')\s*)?"
                    r"(?P<k>(?!(?:le|la|les|l'|cours|ligne|ce|cette|france|r[ée]gion|dans|à|a|au|aux)\b)[a-zà-ÿ]"
                    r"[\w'-]*(?:\s+(?:de|des|du|d'|et)?\s*[a-zà-ÿ][\w'-]*){0,3})", after, re.I)  # fmt: skip
    m = lead or _TOPIC.search(" " + after) or _TOPIC.search(t)
    kw = ""
    if m:
        kw = _TOPIC_STOP.sub("", m.group("k")).strip(" ,.?!")
        if re.fullmatch(r"(?i:publi\w*|ouverts?|r[ée]cents?|en\s+cours|france|ligne)", kw):
            kw = ""
    if len(kw) < 2:
        return Intent("find_tenders", None)
    label, deps = fr_where(t)
    days = 7 if re.search(r"\bcette\s+semaine|this\s+week|7\s+derniers\s+jours|last\s+week\b", t, re.I) else (
        1 if re.search(r"\baujourd'hui|today\b", t, re.I) else 30)  # fmt: skip
    if label:  # the place is an argument of its own, not a keyword (« voirie Gironde »)
        name = re.escape(label.split(" (")[0])
        kw = re.sub(rf"(?i)\s*\b(?:dans\s+(?:le|la|les|l')\s*|en\s+|du\s+)?{name}\b.*$", "", kw).strip(" ,.?!")
        if len(kw) < 2:
            return Intent("find_tenders", None)
    args = {"query": kw, "days": days}
    if deps:
        args["where"] = deps[0] if len(deps) == 1 else label
    return Intent("find_tenders", args, keep_web=False)


# ---------------------------------------------------------------- scholarly works (OpenAlex, Crossref)

_PAPERS = re.compile(
    r"\b(?:articles?\s+(?:scientifiques?|de\s+recherche|acad[ée]miques?|r[ée]cents?|les\s+plus\s+cit[ée]s)|"
    r"publications?\s+(?:scientifiques?|r[ée]centes?|les\s+plus\s+cit[ée]es|crossref|openalex)?|"
    r"(?:les\s+)?publications?|[ée]tudes?\s+(?:scientifiques?|acad[ée]miques?|publi[ée]es)|(?:quelles?|des|les)\s+"
    r"[ée]tudes|papers?|scientific\s+(?:articles?|papers?|literature)|research\s+(?:papers?|articles?)|"
    r"litt[ée]rature\s+scientifique|travaux\s+de\s+recherche|studies)\s+(?:sur|about|on|concernant|portant\s+sur|"
    r"traitant\s+de)\s+(?P<q>.{3,120}?)\s*\??$",
    re.I,
)
_PAPERS_NO = re.compile(r"\b(?:presse|blog|journal\s+local|loi|code\s+du\s+travail|article\s+l\.?\s*\d|r[ée]dige|"
                        r"[ée]cri[st]|lis|march[ée]|faisabilit[ée]|comparative|de\s+cas|d'impact\s+(?:du|de)\s+projet|linkedin|facebook|"
                        r"instagram|twitter|r[ée]seaux\s+sociaux|newsletter|site|page|notre|nos|mon|ma|mes)\b", re.I)  # fmt: skip
_RX_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.I)
_DOI_ASK = re.compile(r"\b(?:doi|v[ée]rifie|retrouve|r[ée]f[ée]rence|check|verify|cite|citation)\b", re.I)


def papers(text: str, lang: str = "fr") -> Intent | None:
    """« articles récents sur les batteries sodium-ion », « les publications les plus citées sur l'hydrogène vert »,
    « vérifie ce DOI 10.1038/nature12373 »."""
    t = _clean(text)
    if not t or len(t) > 220:
        return None
    d = _RX_DOI.search(t)
    if d and _DOI_ASK.search(t) and not re.search(r"\b(?:r[ée]dige|[ée]cri[st]|mail)\b", t, re.I):
        return Intent("find_papers", {"query": d.group(0).rstrip(".,;:)]")}, keep_web=False)
    m = _PAPERS.search(t)
    if not m or _PAPERS_NO.search(t) or _DELIVERABLE.search(t) or re.search(r"\b(?:comment|how)\b", t, re.I):
        return None
    q = re.sub(r"^(?:l'|le\s+|la\s+|les\s+|the\s+)", "", m.group("q").strip(" ?.!"), flags=re.I)
    q = re.sub(r"\s+(?:stp|svp|please|svp)$", "", q, flags=re.I)
    if len(q) < 3 or re.fullmatch(r"(?i:(?:le\s+|ce\s+)?sujet|[çc]a|cela|ce\s+(?:point|th[èe]me)|la\s+question|it|this)", q):
        return None
    order = ("cited" if re.search(r"plus\s+cit[ée]|most\s+cited|r[ée]f[ée]rence", t, re.I) else
             "recent" if re.search(r"r[ée]cent|derni[èe]r|latest|recent|new", t, re.I) else "relevance")  # fmt: skip
    args = {"query": q, "order": order}
    if re.search(r"\bcrossref\b", t, re.I):
        args["source"] = "crossref"
    return Intent("find_papers", args, keep_web=False)


# ---------------------------------------------------------------- communes and addresses

_RX_NORMALISE = re.compile(r"\b(?:normalis\w*|normaliz\w*|corrige\w*|v[ée]rifie\w*|formate\w*|standardis\w*|valide\w*|"
                           r"check|fix|clean)\s+(?:cette|l'|mon|notre|this|the|une?)?\s*adresse(?:\s+postale)?\s*[:：]?\s*"
                           r"(?P<a>.{6,140})$", re.I)  # fmt: skip
_RX_COMMUNE_FACT = re.compile(r"\b(?:code\s+postal|codes\s+postaux|code\s+insee|cp|postcode|zip\s+code)(?:\s+et\s+(?:la\s+)?"
                              r"population)?\s+(?:de|d'|du|of|pour|for)\s*(?P<x>[\w'À-ÿ -]{2,60}?)\s*\??$", re.I)  # fmt: skip
_RX_POP_TOWN = re.compile(r"^(?:quelle\s+est\s+la\s+)?(?:population|nombre\s+d'habitants)\s+(?:et\s+(?:le\s+)?code\s+postal\s+)?"
                          r"(?:de|d'|du|of)\s*(?P<x>[A-ZÀ-Ý][\w'À-ÿ -]{1,50}?)\s*\??$", re.I)  # fmt: skip
_RX_HOMONYMS = re.compile(r"\b(?:quelles?|combien\s+de|liste\s+des|les)\s+communes?\s+(?:s'appellent|nomm[ée]es|qui\s+"
                          r"s'appellent|portent\s+le\s+nom(?:\s+de)?|appel[ée]es)\s+(?P<x>[\w'À-ÿ -]{2,60}?)\s*\??$|"
                          r"\bcommunes?\s+(?:named|called)\s+(?P<y>[\w' -]{2,60}?)\s*\??$", re.I)  # fmt: skip


def commune(text: str, lang: str = "fr") -> Intent | None:
    """« code postal et population de Roubaix », « quelles communes s'appellent Saint-Martin ? », « normalise cette
    adresse : 8 bd du port amiens »."""
    t = _clean(text)
    if not t or len(t) > 200:
        return None
    m = _RX_NORMALISE.search(t)
    # « corrige l'adresse … dans le courrier »: an edit of the user's text, not a lookup
    in_doc = re.search(r"\b(?:dans|sur|de)\s+(?:le|la|ce|cette|mon|ma|notre|l')\s*(?:courrier|lettre|mail|courriel|"
                       r"document|fichier|contrat|devis|facture|texte|signature)\b", t, re.I)  # fmt: skip
    if m and not in_doc and looks_like_address(m.group("a")):
        return Intent("find_commune", {"name": m.group("a").strip(" .?!")}, keep_web=False, mode="address")
    if _DELIVERABLE.search(t):
        return None
    m = _RX_HOMONYMS.search(t)
    if m:
        x = (m.group("x") or m.group("y") or "").strip(" '")
        return Intent("find_commune", {"name": x}, keep_web=False) if len(x) >= 2 else None
    for rx in (_RX_COMMUNE_FACT, _RX_POP_TOWN):
        m = rx.search(t)
        if not m:
            continue
        x = re.sub(r"^(?:la\s+ville\s+de\s+|la\s+commune\s+de\s+)", "", m.group("x").strip(" '"), flags=re.I)
        if re.search(
            r"\b(?:entreprise|soci[ée]t[ée]|client|fournisseur|bureau|agence|si[èe]ge|mon|ma|notre)\b", x, re.I
        ):
            return None
        if countries.find(x) or _FOREIGN_CITY.search(x) or cal.fold(x) in FIRST_NAMES:
            return None
        if not (x[:1].isupper() or known_place(x)):
            return None
        if re.search(r"\b(?:depuis|since|sur\s+\d+|évolution|evolution|graphique|courbe)\b", t, re.I):
            return None  # a trend: the statistics chart
        return Intent("find_commune", {"name": x}, keep_web=False)
    return None


# ---------------------------------------------------------------- all together


def detect(text: str, attached: bool = False, lang: str = "fr", today: date | None = None) -> list[Intent]:
    """The open-data intent of the user's own words (at most one), prefilled when sure. Next to an attached
    document nothing is looked up automatically: the tool is only offered."""
    for fn in (lambda: papers(text, lang), lambda: tenders(text, lang), lambda: calendar(text, lang, today),
               lambda: commune(text, lang), lambda: statistics(text, lang, today), lambda: entity(text, lang)):  # fmt: skip
        got = fn()
        if got is not None:
            if attached and got.args:
                return [Intent(got.tool, None)]
            return [got]
    return []


def merge(found: list[Intent], text: str, attached: bool = False, lang: str = "fr") -> list[Intent]:
    """The agent's intents with the open-data one: an address to normalise wins over the map; otherwise a prefill
    already made by intents.detect (company, rate, weather, places) keeps priority."""
    mine = detect(text, attached, lang)
    if not mine:
        return found
    # « bank holidays in the UK »: holiday words are unambiguous, the map's « bank » is not
    if mine[0].args and (mine[0].mode == "address" or mine[0].tool == "work_calendar" or not any(i.args for i in found)):
        return mine + [i for i in found if not i.args][:1]
    return found + [Intent(mine[0].tool, None)]
