"""The model router's checks for the open-data modules (catalogue entries in ``catalog.py``, family "opendata").

Same contract as the other modules in ``router.py``: an argument the model wrote must be GROUNDED in the user's words
(or the previous turn's context), and a known false-trigger family can VETO a module, but only when the open-data
parser of these words does not start the same tool itself (``opendata_intents.detect``). The parsers are hints and
a fallback; they never decide alone when the router answered. Pure functions, no I/O.
"""

from __future__ import annotations

import re
from datetime import date

from birds.opendata_schemas import OPENDATA_NAMES

NAMES = frozenset(OPENDATA_NAMES)


def _grounded(value: str, *sources: str) -> bool:
    from birds.harness.router import grounded

    return grounded(value, *sources)


def _country_codes(text: str) -> set[str]:
    """ISO codes of the countries a text names (« Allemagne », « Germany », « zone euro »), 1 to 3 words at a time."""
    from birds.harness.tools.opendata import countries

    words = re.findall(r"[\w'-]+", text or "")
    out: set[str] = set()
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            out |= set(countries.find(" ".join(words[i : i + n])) or [])
    return out


def ground(call, text: str, context: str) -> str:
    """'' when the call's arguments come from the user's words, else why not."""
    from birds.harness import opendata_intents as O
    from birds.harness.tools.opendata import calendar as cal
    from birds.harness.tools.opendata import countries
    from birds.harness.tools.opendata.places_fr import where as fr_where

    a, src = call.args, (text or "") + " " + (context or "")
    if call.tool == "work_calendar":
        years = set(re.findall(r"\b(?:19|20)\d\d\b", src))
        got = re.match(r"((?:19|20)\d\d)", str(a.get("period", "")))
        if got and years and got.group(1) not in years:
            return "year not in the user's words"
        try:
            cal.parse_period(str(a["period"]), date.today())
        except Exception:
            return "period is not a year, a month or a date"
        z = str(a.get("zone") or "")
        if z and cal.zone_of(z) not in ("metropole", "") and cal.zone_of(z) != cal.zone_of(O._zone_words(src)):
            if not _grounded(z, src):
                return "zone not in the user's words"
        return ""
    if call.tool == "get_statistics":
        for p in [x.strip() for x in str(a.get("places") or "").split(",") if x.strip()]:
            codes = set(countries.find(p) or [])
            if not (_grounded(p, src) or (codes and codes & _country_codes(src))):
                return "place not in the user's words"
        since = str(a.get("since") or "")
        if re.fullmatch(r"(?:19|20)\d\d", since) and since not in src:
            return "first year not in the user's words"
        return ""
    if call.tool == "find_tenders":
        if not _grounded(a["query"], src):
            return "query not in the user's words"
        w = str(a.get("where") or "")
        if w and not (_grounded(w, src) or (fr_where(w)[1] and fr_where(w)[1] == fr_where(src)[1])):
            return "where not in the user's words"
        return ""
    if call.tool == "find_papers":
        q = a["query"]
        doi = O._RX_DOI.search(q)
        if doi:
            return "" if doi.group(0).lower().rstrip(".,;") in src.lower() else "DOI not in the user's words"
        return "" if _grounded(q, src) else "query not in the user's words"
    if call.tool in ("lookup_entity", "find_commune"):
        return "" if _grounded(a["name"], src) else "name not in the user's words"
    return ""


# writing or the user's own data: the open-data words are context there, never a card
_OWN_DATA = re.compile(r"\b(?:nos|notre|mes|mon|ma|our|my)\s+(?:chiffres|ventes|clients?|fichier|donn[ée]es|"
                       r"[ée]quipe|publications?|campagne|cible|entreprise|soci[ée]t[ée]|bo[iî]te|site|appli\w*|"
                       r"sales|figures|data|team|churn|campaign|company)\b|\bpopulation\s+cible|"
                       r"\btarget\s+(?:audience|population)", re.I)  # fmt: skip


# the family's own vocabulary: a module whose words are absent from the request is a made-up trigger
_CUES = {
    "work_calendar": re.compile(
        r"f[ée]ri|ouvr[ée]s?\b|ouvrables?|holiday|working\s+days?|business\s+days?|weekdays?|\bJ\s*\+\s*\d|"
        r"quel\s+jour|what\s+day|tombe|p[âa]ques|ascension|pentec[ôo]te|toussaint|no[ëe]l|armistice|assomption|"
        r"easter|christmas|whit|calendrier|calendar|\bpont\b", re.I),
    "lookup_entity": re.compile(r".", re.S),  # a proper name is enough (checked below)
    "get_statistics": re.compile(
        r"ch[ôo]mage|unemploy|inflation|prix\s+[àa]\s+la\s+consommation|\bpib\b|\bgdp\b|croissance|growth|"
        r"population|habitants|inhabitants|[ée]lectricit[ée]|electricity|export|cr[ée]ations?\s+d'entreprises|"
        r"start-?ups|statisti|eurostat|insee|banque\s+mondiale|world\s+bank", re.I),
    "find_tenders": re.compile(r"appels?\s+d'offres?|\bAO\b|march[ée]s?\s+publics?|consultations?\s+publiques?|"
                               r"commande\s+publique|boamp|tenders?", re.I),
    "find_papers": re.compile(r"articles?|publi\w+|[ée]tudes?|papers?|recherches?|research|scientifi|acad[ée]mi|"
                              r"\bdoi\b|10\.\d{4,9}/|openalex|crossref|th[èe]ses?|litt[ée]rature|studies|works", re.I),
    "find_commune": re.compile(r"code\s+postal|codes\s+postaux|postcode|zip|insee|commune|population|habitants|"
                               r"d[ée]partement|adresse|address|\d{5}|\d+\s*(?:bis|ter)?,?\s+(?:rue|av|bd|boulevard|"
                               r"avenue|place|chemin|all[ée]e|impasse|quai|route)", re.I),
}
_HOWTO = re.compile(r"\b(?:comment|how\s+(?:do|to|can|should)|pourquoi|why|explique\w*|explain|qu'est-ce\s+qu|"
                    r"c'est\s+quoi|what\s+is|what's|que\s+signifie|define|d[ée]finition)\b", re.I)
_TEXT_TASK = re.compile(r"\b(?:summari[sz]\w*|translate|rewrite|proofread|paraphrase)\b", re.I)


def veto_reason(call, text: str) -> str:
    """'' or the false-trigger family that blocks this open-data module."""
    from birds.harness import opendata_intents as O

    t = text or ""
    if O.own_data(call.tool, t):
        return "open data false trigger (own data)"  # even when a parser fires: the card would stand in for it
    if any(i.tool == call.tool and i.args for i in O.detect(t)):
        return ""  # the family's own parser starts it too
    if not _CUES[call.tool].search(t):
        return "open data: none of the family's words"
    if O._DELIVERABLE.search(t) or _TEXT_TASK.search(t) or _OWN_DATA.search(t):
        return "open data false trigger (writing or own data)"
    if call.tool == "lookup_entity":
        name = str(call.args.get("name", ""))
        # « c'est quoi un KPI ? »: a common noun is a definition to write, not a card (a proper name or an acronym)
        first = re.escape(name.split()[0]) if name.split() else "$^"
        if not name[:1].isupper() or re.search(rf"\b(?:un|une|a|an)\s+{first}", t, re.I):
            return "not a proper name"
        return ""
    if _HOWTO.search(t):
        return "open data false trigger (how-to or definition)"
    return ""


def hints(text: str, history, attached: bool, lang: str) -> list:
    """The open-data parsers' calls for these words, as router hints (and the fallback when the router is off)."""
    from birds.harness import opendata_intents as O

    if attached:
        return []
    return [i for i in O.detect(text, attached, lang) if i.args]
