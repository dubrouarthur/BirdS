"""A final answer that refuses what a tool of this turn could do: the final check's hint and its one retry.

Live model, production 28/11/2026, every one with the tool offered in the same turn:

- « fais un graphe de l'évolution de la natalité » → « Je ne peux pas générer de graphique directement ici, mais
  voici les données […] utilisez Excel » (make_chart offered);
- « Traduis ce mail en anglais » with mail.txt → « Je n'ai pas accès à votre bureau local » (read_file offered);
- « une image » after a topic → « je n'ai pas accès à Internet » (web_search offered).

The words below are a hint, never the decision: they only say « this answer may be a refusal », and the check then
sends the model back once with the tools that were available (``nudge``). The model still decides what to call; a
second refusal is delivered as it is. False positives cost one generation, never a wrong answer.
"""

from __future__ import annotations

import re

# « je ne peux pas générer de graphique », « I can't create charts », « je ne suis pas en mesure de tracer… »
_CANT = (
    r"(?:je\s+ne\s+(?:peux|pourrai|suis\s+pas\s+(?:en\s+mesure|capable))|je\s+peux\s+pas|il\s+m['’]est\s+impossible|"
    r"je\s+n['’]ai\s+pas\s+la\s+possibilit[ée]|"
    r"i\s+(?:can(?:no|['’])t|cannot|am\s+(?:not\s+able|unable)|['’]m\s+(?:not\s+able|unable)|am\s+not\s+capable))"
)
_MAKE = (
    r"(?:\s+pas)?\s+(?:de\s+|d['’]\s*|to\s+)?(?:g[ée]n[ée]rer|cr[ée]er|dessiner|tracer|produire|faire|afficher|montrer|"
    r"r[ée]aliser|construire|fournir|generate|create|draw|plot|make|produce|display|show|render)"
)
_THING = (
    r"(?:graph(?:e|ique)s?|diagrammes?|courbes?|charts?|graphs?|plots?|visuali[sz]ations?|images?|photos?|pictures?|"
    r"illustrations?)"
)
REFUSAL = re.compile(
    # « je ne peux pas générer de graphique (directement ici) »
    rf"\b{_CANT}{_MAKE}\s+(?:(?:de|des|un|une|le|la|les|a|an|the|any)\s+|d['’]\s*)?(?:\w+\s+){{0,2}}?{_THING}\b|"
    # « je n'ai pas accès à Internet / à votre bureau / à vos fichiers / au document »
    r"\bje\s+n['’]ai\s+(?:pas|aucun|ni)\s+(?:d['’]\s*)?(?:accès|acces|connexion)\s+(?:direct\s+)?(?:à|a|au|aux)?\s*"
    r"(?:l['’]\s*)?(?:internet|web|en\s+ligne|mes\s+outils|outils?|votre\s+(?:bureau|ordinateur|disque|poste)|"
    r"vos\s+(?:fichiers|documents)|(?:ce|ces|le|du|au)\s+(?:fichier|document|mail|e-?mail)|"
    r"(?:des\s+)?(?:données|informations)\s+(?:en\s+temps\s+réel|récentes|actuelles)|actualit|temps\s+réel|"
    r"images?|photos?)|"
    r"\b(?:je\s+ne\s+peux\s+pas|je\s+suis\s+incapable\s+d['’])\s*(?:accéder|acceder|naviguer|ouvrir|lire)\s+"
    r"(?:à\s+|a\s+)?(?:internet|le\s+web|votre\s+(?:bureau|ordinateur)|vos\s+fichiers|(?:ce|le)\s+(?:fichier|document|"
    r"mail))|"
    # « mes connaissances s'arrêtent en… », « utilisez Excel / Google Sheets pour tracer »
    r"\bmes\s+(?:connaissances|données)\s+(?:s['’]arrêtent|datent|ne\s+(?:vont|sont)\s+pas)|"
    r"\b(?:utilisez|utiliser|use)\s+(?:un\s+(?:tableur|outil)|excel|google\s+sheets|a\s+spreadsheet)\b[^.\n]{0,40}"
    r"(?:graph|courbe|chart|visuali)|"
    r"\bi\s+(?:do\s+not|don['’]t)\s+have\s+(?:access\s+to\s+)?(?:the\s+)?(?:internet|web|real[- ]time|browsing|"
    r"your\s+(?:desktop|computer|files)|(?:this|the)\s+(?:file|document|email))|"
    r"\bas\s+an\s+ai[^.\n]{0,40}(?:can(?:no|['’])t|unable)",
    re.I,
)

# what each tool lets Bird do, for the nudge (the model reads which ones were offered, then decides)
_CAN = {
    "make_chart": "make_chart draws a chart from figures you have (from a tool result or the user's message)",
    "web_search": "web_search finds current facts, figures and pictures",
    "read_file": "read_file reads the file the user attached (use its name as written in [Fichier joint : …])",
    "lookup_entity": "lookup_entity gives the card of a person, place or organisation (typos are tolerated)",
    "get_statistics": "get_statistics gives official series (births, unemployment, GDP…)",
    "read_page": "read_page reads a result page",
}

NUDGE = (
    "Your answer says you cannot do this, but this turn has the tools for it: {tools}. Never say you cannot make a "
    "chart, see a picture, read the attached file, or reach the internet, and never send the user to another tool. "
    "Call the tool now, then answer with its result. If a tool already ran and found nothing usable, say plainly "
    "what was found and what was not, without saying you are unable."
)


def refuses(text: str) -> bool:
    """The answer reads like a refusal of something a tool can do (a hint for the final check)."""
    return bool(REFUSAL.search(text or ""))


def nudge(offered: set[str] | list[str]) -> str | None:
    """The one retry message, naming the capable tools this turn offers; None when none of them is offered."""
    names = [n for n in _CAN if n in set(offered)]
    if not names:
        return None
    return NUDGE.format(tools="; ".join(_CAN[n] for n in names))


def capable(allowed: set[str], attached: bool) -> set[str]:
    """The tools of this deployment able to do what a refusal says Bird cannot (read_file only for an attached
    file: there is nothing else to read)."""
    out = {n for n in _CAN if n in set(allowed)}
    if not attached:
        out.discard("read_file")
    return out
