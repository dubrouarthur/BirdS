"""The agent loop: render -> generate -> parse -> run tools -> repeat, with every limit enforced in code."""

from __future__ import annotations

import copy
import inspect
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from birds.harness import calc, facts, followup, guard, intents, meter, repair, router
from birds.harness import plan as taskplan
from birds.harness import reflexion as reflex
from birds.harness.config import Config, Context
from birds.harness.llm import STOP, EndpointError, accepts
from birds.harness.tools import TOOLS, make_search
from birds.parse import parse_output
from birds.render import prompt as render_prompt
from birds.sources.identity import DEFAULT_SYSTEM  # same text as docs/PERSONA.md
from birds.tools import EXTRA_TOOL_NAMES, PRODUCT_TOOLS

FALLBACK = {
    "fr": "Je n'ai pas pu aboutir à une réponse fiable dans les limites fixées. Pouvez-vous reformuler ou préciser la demande ?",
    "en": "I could not reach a reliable answer within the set limits. Could you rephrase or narrow the request?",
}
OUT_OF_TIME = {
    "fr": "Je n'ai pas eu le temps de terminer dans le délai fixé pour une requête. Relancez, ou découpez la demande "
    "en étapes plus courtes.",
    "en": "I ran out of the time allowed for one request. Try again, or split the request into shorter steps.",
}
NO_FILE = {
    "fr": "Je n'ai pas produit de fichier cette fois. Redemandez-le en reprenant le contenu.",
    "en": "I did not produce a file this time. Ask for it again, with the content.",
}
# The answer says a file exists ("diapositive 6, intégrée à votre présentation") while no make_* tool ran.
_EDIT_ASK = re.compile(
    r"\b(?:ajoute[rz]?|modifie[rz]?|met[sz]? à jour|mettre à jour|add (?:a|an|one) (?:slide|section|sheet)|update)\b",
    re.I,
)
# Only a claim that something was done to a file counts: "prête", "disponible" or "ready" also describe an inline
# answer ("pour que votre présentation soit prête"), so they are not claims.
_FILE_CLAIM = re.compile(
    r"\b(?:fichier|pr[ée]sentation|diapositive|diapo|document|tableur|file|deck|presentation|slide|spreadsheet)\b"
    r".{0,40}\b(?:int[ée]gr[ée]e?s?|mise? à jour|ajout[ée]e?s?|enregistr[ée]e?s?|integrated|updated|saved|added)\b",
    re.I | re.S,
)
# A how-to question ("Comment ajouter une diapo dans PowerPoint ?") asks for steps, not for a file.
_HOWTO = re.compile(
    r"^\s*(?:comment|how|pourquoi|why|o[uù]|where|quand|when|est-ce qu)\b|\b(?:how (?:do|can|to|should)|"
    r"comment (?:faire|on|je|puis|peut))\b",
    re.I,
)
NO_FILE_NUDGE = (
    "No file exists: nothing was created or updated, because no make_* tool ran. Call the make_* tool now with the "
    "full content, or tell the user plainly that no file was produced."
)
NO_CHART_NUDGE = (
    "No chart was shown: call make_chart now with the figures, or say plainly that you have no figures to chart."
)
# Words that are not about a chart: « charte graphique », « identité graphique », « courbe en J »,
# « courbe d'apprentissage ». They are removed before any chart test (live model: « Rédige une charte graphique »
# made a correct document, was then reminded to call make_chart and answered « pas de chiffres à chartier »).
_NOT_CHART = re.compile(
    r"\b(?:chartes?|identit[ée]s?|lignes?|cr[ée]ations?|conceptions?|design|arts?|interfaces?|univers|rep[èe]res?|"
    r"cartes?|signal[ée]tiques?|moteurs?|logiciels?|suites?|cartes?)\s+graphiques?\b|"
    r"\bcourbes?\s+(?:en\s+[a-z]\b|d['’]apprentissage|de\s+gauss|de\s+niveau|de\s+bézier|de\s+bezier)|"
    # diagrams with no figures: a Gantt, a flowchart, UML, Venn or PERT is written in text, never by make_chart
    r"\bdiagrammes?\s+(?:de\s+|d['’]\s*)?(?:gantt|flux|s[ée]quence|classes?|uml|pert|ishikawa|cas d['’]utilisation|"
    r"activit[ée]s?|architecture|venn|d[ée]ploiement|[ée]tats?)\b|"
    r"\b(?:gantt|flow|org|organi[sz]ation(?:al)?|sequence)\s*(?:charts?|diagrams?)\b",
    re.I,
)
# A chart noun in the user's own words: make_chart is offered (an extra tool, nothing else). « secteurs » and
# « barres » alone are not chart nouns (« les secteurs qui recrutent », « barres de céréales »).
_CHART_ASK = re.compile(
    r"\b(?:graphiques?|graphes?|graphs?|courbes?|diagrammes?|camemberts?|histogrammes?|histograms?|charts?|plots?|"
    r"plotting|visualis\w*|visualiz\w*|repr[ée]sent\w* graphiquement|en barres|sous forme de (?:barres|b[âa]tons|"
    r"camembert|courbe|graphique)|bar charts?|line charts?|pie charts?)\b",
    re.I,
)
# A clear request for one: an action verb shortly before a chart noun (« fais un graphique », « trace la courbe »,
# « refais-le en courbe », « make a bar chart »), or a bare verb « plot / visualise »; or figures in the message.
_CHART_VERB = re.compile(
    r"\b(?:re)?(?:mett\w*|met|pass\w*|fai[st]e?s?|faites|faire|fasse|trac\w*|montr\w*|cr[ée]\w*|g[ée]n[èée]r\w*|dessin\w*|affich\w*|produi\w*|"
    r"pr[ée]par\w*|sort\w*|mets|mettez|transform\w*|convert\w*|make|draw|show|create|generate|build|render|"
    r"turn|redo|do|give|want|veux|voudrais|aimerais)\b[^.?!\n]{0,40}?\b(?:en\s+|in\s+|as\s+(?:an?\s+)?)?"
    r"(?:graphiques?|graphes?|graphs?|courbes?|diagrammes?|camemberts?|histogrammes?|histograms?|charts?|plots?|"
    r"barres|b[âa]tons|secteurs|lines?|bars?|pies?)\b|"
    r"(?:^|[.!?\n]\s*)(?:plot|chart|graph|visualis\w*|visualiz\w*|repr[ée]sente\w*)\b|"
    r"\b(?:you|tu|vous)\s+(?:please\s+)?(?:graph|plot|chart|visuali[sz]e)\b",  # « can you graph this for me »
    re.I,
)
_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?")
NO_CHART = {
    "fr": "Je n'ai pas pu afficher le graphique cette fois. Redemandez-le en redonnant les chiffres.",
    "en": "I could not show the chart this time. Ask again, with the figures.",
}
# An answer that presents a chart ("Voici la courbe du CA :") although none was shown. Tested on the answer
# without _NOT_CHART words (« Voici une proposition de charte graphique », « Voici l'idée de la courbe en J »).
_CHART_CLAIM = re.compile(
    r"\b(?:voici|voil[àa]|ci-dessous|here(?: is|'s)|below)\b.{0,30}\b(?:graphique|graphe|courbe|camembert|diagramme|"
    r"histogramme|chart|graph|plot)",
    re.I | re.S,
)


def _chart_words(text: str) -> str:
    return _NOT_CHART.sub(" ", text or "")


def chart_claim(answer: str) -> bool:
    """The answer presents a chart (« Voici le graphique : »)."""
    return bool(_CHART_CLAIM.search(_chart_words(answer)))


_TYPE_WORDS = (("line", r"courbe|line|évolution|evolution"), ("pie", r"camembert|secteurs|pie|donut"),
               ("bar", r"barres?|bâtons|histogramme|bar"))  # fmt: skip


def chart_nudge(request: str, messages: list[dict]) -> str:
    """NO_CHART_NUDGE, plus what a follow-up ("refais-le en courbe") needs: where the data is, and the type asked.
    Live model, « refais-le en courbe » after a bar chart: reminded with the bare nudge, it wrote "Voici la courbe :"
    again without calling the tool."""
    out = NO_CHART_NUDGE
    if any(
        "graphique affiché :" in str(m.get("content")) or "chart shown :" in str(m.get("content")) for m in messages
    ):
        out += " The earlier chart's columns and rows are in the memo of your previous answer: reuse them."
    kind = next((k for k, rx in _TYPE_WORDS if re.search(rf"\b(?:{rx})\b", request or "", re.I)), None)
    if kind:
        out += f' Use "type": "{kind}".'
    return out


# "Explique ce qu'est un histogramme": a question about charts, not a request for one (no nudge).
_ABOUT_CHARTS = re.compile(
    r"^\s*(?:explique|expliquez|explain|d[ée]finis|define|qu['’]est[- ]ce|what (?:is|are)|c['’]est quoi)\b", re.I
)
# How-to, advice or definition about charts: steps in a sheet tool, which chart to pick, what a chart is. No chart
# is drawn and make_chart is not offered (« comment faire un graphique dans Excel ? », « tuto pour faire une courbe
# sur Excel », « quel graphique choisir pour une répartition ? », « différence entre histogramme et barres »).
_CHART_HOWTO = re.compile(
    r"\b(?:comment|how\s+(?:do|can|to|should|would)|tuto\w*|tutorial|[ée]tapes?\s+pour|steps?\s+to|proc[ée]dure\s+pour|"
    r"m[ée]thode\s+pour|astuces?\s+pour|explique\w*|expliquer|explain\w*|d[ée]finition|define|diff[ée]rences?\s+entre|"
    r"difference\s+between|(?:quel|quelle|which|what)\s+(?:type\s+de\s+|sorte\s+de\s+|kind\s+of\s+|type\s+of\s+)?"
    r"(?:graphique|graphe|diagramme|chart|graph|visuali[sz]ation)s?\s+(?:choisir|utiliser|privil[ée]gier|"
    r"pour|to\s+(?:use|choose|pick)|should|is\s+best|est\s+le\s+(?:plus|mieux))|"
    r"(?:quand|when)\s+(?:utiliser|use|choisir)|dans\s+quels?\s+cas|in\s+which\s+cases?|c['’]est\s+quoi|"
    r"qu['’]est[- ]ce\s+qu)\b|"
    r"\b(?P<tool>dans|sous|avec|sur|on|in|with|using)\s+(?:excel|word|powerpoint|power\s?point|google\s+sheets|sheets|"
    r"libreoffice|calc|numbers|power\s?bi|tableau|looker|matplotlib|python|r)\b[^.?!\n]{0,40}"
    r"(?:\?|$)|\b(?:crois[ée]s?\s+dynamiques?|pivot\s+charts?|tableaux?\s+crois[ée]s?)\b",
    re.I,
)
# A sheet tool named with a how-to verb (« insérer un graphique dans Word », « ajouter une courbe de tendance »)
_SHEET_HOWTO = re.compile(
    r"\b(?:ins[ée]rer|ajouter|modifier|changer|mettre\s+en\s+forme|formater|insert|add|format|customi[sz]e|"
    r"courbe\s+de\s+tendance|trendline|axe\s+secondaire|secondary\s+axis|l[ée]gende|legend)\b",
    re.I,
)


_DO_CHART = re.compile(
    r"^\s*(?:(?:peux-tu|pourrais-tu|tu peux|tu pourrais|pouvez-vous|can you|could you|please)\s+)?(?:me\s+)?"
    r"(?:fais|fait|faites|refais|trace|tracez|dessine|montre|affiche|g[ée]n[èe]re|cr[ée]e|mets|make|draw|plot|show|"
    r"create|generate|build|chart|graph|visualise|visualize|represent[ez]?)\b",
    re.I,
)


def chart_howto(text: str) -> bool:
    """A question ABOUT making or choosing a chart, not a request for one. The user's own figures (two numbers or
    more) always make it a request: « comment représenter ça : T1 120, T2 135 ? » is drawn."""
    words = _chart_words(text)
    if len(_NUMBER.findall(re.sub(r"\b(?:19|20)\d\d\b", " ", words))) >= 2:
        return False
    if _DO_CHART.match(words) and not re.match(r"^\s*\S+(?:[\s-]+(?:moi|me|nous|us))?\s+(?:comment|how)\b", words, re.I):
        return False  # « fais un graphique des ventes et explique la tendance »: a request that also asks for words
    if _HOWTO.search(words) or _ABOUT_CHARTS.search(words):
        return True
    m = _CHART_HOWTO.search(words)
    if not m:
        return False
    if m.group("tool"):
        return bool(_SHEET_HOWTO.search(words) or _HOWTO.search(words) or re.search(r"\bcomment\b|\bhow\b", words, re.I))
    return True


# an answer that only announces work the model could do now (« je reviens sur l'image », « je vais vérifier »)
_PROMISE = re.compile(
    r"\b(?:je (?:reviens|vais (?:relire|reprendre|vérifier|verifier|chercher|rechercher|récupérer|recuperer|compléter|"
    r"completer|regarder|lire|analyser|créer|creer|préparer|preparer|refaire|corriger|ajouter|calculer)|m'en occupe|"
    r"m'y (?:mets|remets))|let me (?:check|look|read|search|fix|add|redo|create)|i(?:'ll| will) (?:check|look|go back|"
    r"read|search|fix|add|redo|create|re-?read))\b",
    re.I,
)
DO_IT_NUDGE = (
    "Do it now, in this turn: call the tool you need (for example read_file on the attached file or image) and then "
    "answer with the result. Do not wait for the user to confirm."
)
LANG_NUDGE = {
    "fr": "The user writes in French: write your whole answer in French.",
    "en": "The user writes in English: write your whole answer in English.",
}
# stop reasons after which a last answer is attempted before the generic fallback
_SALVAGE = {"max_steps", "invalid_tool_calls", "loop", "empty_output", "malformed_output"}
LAST_CHANCE = {
    "fr": "[Consigne interne] Réponds maintenant à ma demande, sans appeler d'outil, avec ce que tu sais déjà et ce que "
    "les étapes précédentes ont trouvé. Si une information manque, dis-le simplement en une phrase.",
    "en": "[Internal instruction] Answer my request now, without calling any tool, using what you already know and "
    "what the previous steps found. If something is missing, say so plainly in one sentence.",
}
LOOPED = {
    "fr": "Je me suis mis à tourner en boucle, alors je me suis arrêté pour ne pas gaspiller de calcul. Relancez, ou "
    "reformulez la demande plus précisément.",
    "en": "I started going round in circles, so I stopped rather than waste compute. Try again, or phrase the request "
    "more precisely.",
}
DENIED = {
    "denied_unconfirmed": "Action not performed: this run read external content that looks like it contains instructions, "
    "and the user did not confirm this action. Tell the user what you wanted to do and why.",
    "denied_cap": "Action not performed: the limit of actions for one request is reached.",
}
_FR = re.compile(
    r"[éèêàùçîôâœ]|\b(?:le|la|les|des|une?|est|et|pour|que|qui|dans|sur|avec|vous|nous|je|peux|merci|bonjour)\b", re.I
)
_EN = re.compile(r"\b(?:the|is|are|and|for|that|with|you|we|what|how|please|can|this|of|to|hello|thanks)\b", re.I)


def detect_lang(text: str) -> str:
    return "fr" if len(_FR.findall(text)) >= len(_EN.findall(text)) and _FR.search(text) else "en"


def compact(messages: list[dict]) -> list[dict]:
    """History for the next user turn: tool calls and tool results of past turns are dropped to keep the context small."""
    return [
        m for m in messages if m["role"] in ("system", "user") or (m["role"] == "assistant" and not m.get("tool_calls"))
    ]


_FILE_ASK = re.compile(
    r"\b(?:pr[ée]sentation|diapo\w*|slides?|pptx|powerpoint|deck|document|docx|word|compte[- ]rendu|note de|"
    r"proc[ée]dure|rapport|report|minutes|memo|tableur|excel|xlsx|spreadsheet|feuille de calcul|mail|e-?mail|courriel)\b",
    re.I,
)
_NEEDS_WEB = re.compile(
    r"https?://|www\.|\b(?:cherch|recherch|search|look up|web|internet|en ligne|online|actualit|news|r[ée]cent|"
    r"latest|dernier|derni[èe]re|aujourd|today|cette ann[ée]e|this year|prix|price|taux|rate|cours|v[ée]rifi|"
    r"source|cite|20[2-3]\d|"
    # a trend over the years needs real figures: never withdraw the web from it (else the model invents a series)
    r"(?:depuis|since|entre|between|from|de)\s+(?:l.an\s+)?(?:19|20)\d\d|[ée]volu|trend|tendance|historique|"
    r"population|statisti|insee|eurostat)",
    re.I,
)


# A trend question: a span of years or a word of change, about a measurable quantity. « depuis 2019 » alone is not
# one (« je suis dans l'entreprise depuis 2019, aide-moi à rédiger… »), nor « la tendance mode de cet hiver ».
_SPAN = re.compile(
    r"\b(?:depuis|since|entre|between)\s+(?:l.an\s+)?(?:19|20)\d\d|\bde\s+(?:19|20)\d\d\s+[àa]\s+(?:19|20)\d\d|"
    r"\bfrom\s+(?:19|20)\d\d\s+to\b|\b(?:ces|les|sur les|des)\s+\d+\s+derni[èe]res\s+ann[ée]es|"
    r"\bdepuis\s+\d+\s+ans\b|\bsur\s+\d+\s+ans\b|\b(?:over|in)\s+the\s+(?:last|past)\s+\d+\s+years|"
    r"\bover the (?:years|decade)",
    re.I,
)
_MOVE = re.compile(r"\b(?:[ée]volu\w*|tendances?|trends?|progression|historique|changed|evolved)\b", re.I)
_QTY = re.compile(
    r"\b(?:population|co[uû]ts?|costs?|chiffres? d.affaires|ca|revenues?|ventes?|sales|"
    r"ch[ôo]mage|unemployment|taux|rates?|effectifs?|inflation|cours|pib|gdp|salaires?|wages?|smic|"
    r"abonn[ée]s|subscribers|clients|customers|budget|d[ée]penses|immobilier|loyers?|rents?|"
    r"bourse|cac|emplois?|jobs|production|consommation|consumption|trafic|traffic|visites|visits|habitants)\b",
    re.I,
)


# vague quantities: a trend only over a span of years (« le prix du gaz entre 2020 et 2024 ») or a named series,
# never with a change word alone (« nos prix évoluent au 1er janvier », « la tendance du marché est bonne »)
_QTY_WEAK = re.compile(r"\b(?:prix|prices?|nombre|number|march[ée]|markets?)\b", re.I)
# a series is named: « historique du prix du baril », « l'évolution des prix »
_SERIES = re.compile(r"\b(?:historique|history|[ée]volution|evolution)\s+(?:des?|du|of|d['’])", re.I)
# a piece of writing is asked: its figures are context, not a series to draw
_WRITE_ASK = re.compile(
    r"\b(?:r[ée]dig\w*|[ée]cri(?:s|re|vez|t)\b|mail|e-mail|courriel|lettre|mot pour|un mot|demande d'|traduis\w*|"
    r"traduire|reformule\w*|draft|write|compose|annonce)\b",
    re.I,
)


def trend_ask(text: str) -> bool:
    """« la population de Lyon ces 10 dernières années », « historique du prix du baril »: a span of years or a
    word of change about a quantity, where a line chart is the natural answer. Never a writing ask with no chart
    noun (« depuis 2019 mon salaire n'a pas évolué, rédige une demande d'augmentation »)."""
    text = text or ""
    if _WRITE_ASK.search(text) and not _CHART_ASK.search(_chart_words(text)):
        return False
    span = _SPAN.search(text) or _SERIES.search(text)
    return bool((span or _MOVE.search(text)) and (_QTY.search(text) or (span and _QTY_WEAK.search(text))))


CLOCK_NOTE = {
    "fr": "\n\n(Note de Bird : une fiche « Horloge » est affichée sous ta réponse. {facts} Réponds en une ou deux "
    "phrases avec ces heures exactes ; n'en calcule aucune autre et ne cherche rien sur le web.)",
    "en": "\n\n(Bird's note: a 'World clock' card is shown under your answer. {facts} Answer in one or two sentences "
    "with these exact times; compute no other and do not search the web.)",
}

ASK_NOTE = {  # maps: « autour de moi » (intents mode "ask")
    "fr": "\n\n(Note de Bird : la position de l'utilisateur est inconnue de Bird. Demande-lui en une phrase près de "
    "quelle adresse, gare, quartier ou ville chercher ; ne propose aucun lieu.)",
    "en": "\n\n(Bird's note: Bird does not know where the user is. Ask in one sentence near which address, station, "
    "area or town to search; suggest no place.)",
}
IMAGES_NOTE = {
    "fr": "\n\n(Note de Bird : la recherche d'images sur « {subject} » est faite. Les images qui correspondent, s'il y "
    "en a, sont affichées sous ta réponse avec leur source. Décris brièvement {subject} d'après les résultats ; "
    "n'écris aucun lien d'image et ne dis pas que tu ne peux pas montrer d'images.)",
    "en": "\n\n(Bird's note: the image search for '{subject}' is done. Matching images, if any, are shown under your "
    "answer with their source. Briefly describe {subject} from the results; write no image link and do not say you "
    "cannot show images.)",
}

EVENT_NOTE = {
    # the resolved day is written out: live model, given only "le 25 décembre", wrote "dimanche 25 décembre" (a Friday)
    "fr": "\n\n(Note de Bird : une fiche d'agenda pour le {slot} avec un bouton « Ajouter au calendrier » est affichée "
    "sous ta réponse. Confirme ce créneau en une phrase, avec ce jour exact ; ne fais un mail ou un document que si "
    "la demande le dit ; n'invente ni lieu ni participant.)",
    "en": "\n\n(Bird's note: an event card for {slot} with an 'Add to calendar' button is shown under your answer. "
    "Confirm this slot in one sentence, with this exact day; write an e-mail or a document only if the request says "
    "so; invent no place or participant.)",
}
_DAYS = {
    "fr": ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}
_MONTHS = {
    "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
}  # fmt: skip


def _event_slot(text: str, lang: str) -> str:
    """'vendredi 25 décembre 2026, 12:00–13:00' for an event ask in the user's words, else ''."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from birds.harness import when

    got = when.event_ask(text, datetime.now(ZoneInfo("Europe/Paris")), lang)
    if got is None:
        return ""
    lg = "en" if lang == "en" else "fr"
    s, e = got["start"], got["end"]
    day = f"{_DAYS[lg][s.weekday()]} {s.day} {_MONTHS[lg][s.month - 1]} {s.year}"
    return day if got["all_day"] else f"{day}, {s:%H:%M}–{e:%H:%M}"


def route(user: str, attached: bool = False) -> set[str]:
    """Tools NOT worth offering for this request (a smaller prompt, and fewer detours for a small model).

    ``user`` must be the user's OWN words, without the text of attachments or image transcriptions: an invoice
    full of dates and prices must not look like a request for fresh information.

    A request for a file or a draft, or any request about an attached document or image, that names no need for
    outside information gets no web tools. Live model: offered web_search, it searched first on "make a 4-slide
    deck on remote work" and then never made the deck; on "make a spreadsheet from this invoice" (photo), it called
    read_page on the attachment and gave up.
    """
    words = _chart_words(user)
    # untrained tool: only when a chart is asked, or the question is about a trend over time (« la population de
    # Paris évolue comment depuis 2012 ») where a line chart is the natural answer
    about = chart_howto(user)  # « comment faire un graphique dans Excel ? », « quel graphique choisir ? »
    out = set() if (_CHART_ASK.search(words) and not about) or trend_ask(user) else {"make_chart"}
    # A chart of public facts (« la population des 5 plus grandes villes ») is researched first, as ChatGPT does:
    # the web tools are withheld only when the message itself carries the figures (or a document does).
    figures = chart_ask(user) and len(_NUMBER.findall(words)) >= 2
    asks = attached or _FILE_ASK.search(user or "") or figures
    if asks and not _NEEDS_WEB.search(user or ""):
        out |= {"web_search", "read_page"}
    return out


# ---------------------------------------------------------------- charts drawn by the harness from figures it can see
# One whole number: « 1,9 », « 12 500 », « 2 240 621 ». A space group is a thousands separator only as
# \d{1,3}( \d{3})+ with no digit before it, so « 2021 100 » is the label 2021 and the value 100; and a number is never
# split (« 1,9 M€. » was read as 1 because a full stop was not accepted after the value).
_NUM = r"[-+]?(?<![\d.,])(?:\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?!\d|[.,]\d)"
# never backtrack into a decimal: « 2,1 millions » is 2,1 (the (?![.,]\d) above), and the magnitude word is kept
_UNIT = (
    r"(?P<unit>%|k€|K€|M€|Md€|€|\$|h|ans?|k)?"
    r"(?:\s*(?P<mag>millions?|milliards?|mds?|md|mns?|bn|m)\b(?:\s*(?:d['’]\s*)?(?P<cur>euros?|€|\$))?)?"
)
_MAG = {"million": "M", "millions": "M", "m": "M", "mn": "M", "mns": "M", "milliard": "Md", "milliards": "Md",
        "md": "Md", "mds": "Md", "bn": "bn"}  # fmt: skip
# where a pair ends: a separator, a full stop (not a decimal point), a dash, « et / and / vs », or the end
_END = r"(?=\s*(?:[,;\n)/!?—–]|\.(?!\d)|\s-\s|\bet\b|\band\b|\bvs\b|$)|\s+(?:19|20)\d\d\s*[:=]?\s*\d)"
# « CA 2022 : 1,2 M€, 2023 : 1,5 M€ »: the first label is the year, like the others
_YEAR_END = re.compile(r"^.*?\s((?:19|20)\d\d)$")
_PAIR = re.compile(
    r"(?P<label>(?:19|20)\d\d|[^\W\d_][\w'’ .-]{0,30}?)\s*(?:[:=]|\s)\s*(?P<num>" + _NUM + r")\s*" + _UNIT + _END,
    re.I,
)
# number first: « 45 % CDI, 30 % CDD, 25 % intérim », « 120 en janvier, 135 en février »
_PAIR_REV = re.compile(
    r"(?P<num>" + _NUM + r")\s*" + _UNIT + r"\s+(?:en\s+|de\s+|d['’]\s*|pour\s+(?:les?\s+|la\s+)?)?"
    r"(?P<label>[^\W\d_][\w'’ -]{0,30}?)" + _END,
    re.I,
)
_LIST_ROW = re.compile(
    r"^\s*(?:[-*•]|\d+[.)])?\s*\**(?P<label>[^:\n|*]{1,40}?)\**\s*[:–—]\s*\**"
    r"(?P<num>" + _NUM + r")\s*" + _UNIT + r"\**\s*(?:\(.*\))?\s*$",
    re.M | re.I,
)
_PIE = re.compile(r"camembert|r[ée]partition|\bparts?\b|share|pie", re.I)
# the type the user names wins over any guess: « sous forme de courbe », « graphique en barres », « histogramme »
_KIND_ASKED = (
    ("line", re.compile(r"\b(?:courbes?|line\s+(?:charts?|graphs?)|en\s+lignes?|as\s+a\s+line)\b", re.I)),
    ("pie", re.compile(r"\b(?:camemberts?|pie(?:\s+charts?)?|donuts?|doughnuts?|secteurs)\b", re.I)),
    ("bar", re.compile(r"\b(?:barres?|b[âa]tons|histogrammes?|histograms?|bar\s+charts?|bars?)\b", re.I)),
)
_TIME_LABEL = re.compile(
    r"^(?:(?:19|20)\d\d|t[1-4]|q[1-4]|janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]|sept|oct|nov|d[ée]c|jan|feb|mar|apr|"
    r"may|jun|jul|aug|sep|dec|lundi|mardi|mercredi|jeudi|vendredi|semaine|mois|week|month)",
    re.I,
)


def _unit_of(m: re.Match) -> str:
    """« % », « M€ », or a magnitude word as a unit: « 2,1 millions » → M, « 1,2 Md € » → Md€."""
    if m.group("unit") or not m.group("mag"):
        return m.group("unit") or ""
    return _MAG[m.group("mag").lower()] + ("€" if (m.group("cur") or "").lower().startswith(("€", "euro")) else "")


# a label of several words that ends on a link word is a sentence, not a row: « le budget est de 1,5 million »
_LINK_END = re.compile(
    r"\b(?:de|du|des|d['’]|à|a|est|sont|était|soit|environ|par|pour|en|le|la|les|of|is|are|was|at|about|to)$", re.I
)


def _rows_of(pairs: list[tuple[str, str, str]]) -> tuple[list[str], list[list[str]], str] | None:
    rows, units = [], set()
    for label, num, unit in pairs:
        label = label.strip(" .-*").strip()
        if label and len(label) <= 40 and not (" " in label and _LINK_END.search(label)):  # « Est » is a label
            rows.append([label, num.replace(" ", "").replace("\u202f", "").replace("\xa0", "")])
            units.add(unit or "")
    if len(rows) < 3 or len({r[0].lower() for r in rows}) < len(rows):
        return None
    if sum(bool(re.fullmatch(r"(?:19|20)\d\d", r[0])) for r in rows) >= len(rows) - 1:
        rows = [[_YEAR_END.sub(r"\1", r[0]), *r[1:]] for r in rows]
    return ["Libellé", "Valeur"], rows, next(iter(units)) if len(units) == 1 else ""


def figures_in(text: str) -> tuple[list[str], list[list[str]], str] | None:
    """Label/number pairs a chart can be drawn from: a Markdown table with a numeric column, « label : 12 % » lines,
    or « janvier 120, février 135, mars 160 ». None when there are fewer than 3 or labels repeat."""
    text = text or ""
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(lines) >= 4:  # header, rule, 2+ rows
        cells = [[c.strip(" *") for c in ln.strip().strip("|").split("|")] for ln in lines]
        head, body = cells[0], [c for c in cells[2:] if len(c) >= 2]
        for j in range(1, len(head)):
            pairs = []
            for c in body:
                m = re.fullmatch(r"([-+]?\d[\d  .,]*\d|\d)\s*(%|k€|K€|M€|Md€|€|\$|h)?", c[j] if j < len(c) else "")
                if m:
                    pairs.append((c[0], m.group(1), m.group(2) or ""))
            if len(pairs) >= 3 and len(pairs) >= 0.7 * len(body):
                got = _rows_of(pairs)
                if got:
                    return [head[0] or "Libellé", head[j] or "Valeur"], got[1], got[2]
    for rx in (_LIST_ROW, _PAIR, _PAIR_REV):
        got = _rows_of([(m.group("label"), m.group("num"), _unit_of(m)) for m in rx.finditer(text)])
        if got:
            return got
    return None


def chart_call(request: str, data, lang: str) -> dict:
    """The make_chart arguments for figures found by the harness (type from the ask and the labels)."""
    columns, rows, unit = data
    kind = next((k for k, rx in _KIND_ASKED if rx.search(_chart_words(request))), None)
    if kind is None:
        kind = "pie" if _PIE.search(request) else "line" if (trend_ask(request) or all(
            _TIME_LABEL.match(r[0]) for r in rows)) else "bar"  # fmt: skip
    title = ("Vos chiffres" if lang != "en" else "Your figures") if columns[1] in ("Valeur", "Value") else columns[1]
    args = {"title": title, "type": kind, "columns": columns, "rows": rows}
    if unit:
        args["unit"] = unit
    return args


# a follow-up that points at the previous answer: « mets ça en graphique », « fais-en un camembert », « chart this »
_FOLLOWUP = re.compile(
    r"\b(?:ça|ca|cela|ce tableau|ces (?:chiffres|données|donnees|résultats|resultats|valeurs)|fais-en|"
    r"(?:le|la|les|l')\s*(?:mettre|mets|refaire|refais|passer|transformer|représenter|representer)|"
    r"(?:refais|remets|mets|passe|transforme|fais)\s+(?:le|la|les)\b|"
    r"(?:chart|graph|plot|make|turn|put|draw|show)\s+(?:it|this|that|these|them)\b|"
    r"(?:this|that|the) (?:table|data|figures|numbers)|(?:of|from) (?:it|this|that|these|them)\s*[.!?]*\s*"
    r"(?:please)?\s*[.!?]*$)|"
    r"-(?:le|la|les|en)\b",
    re.I,
)
# « fais un camembert du budget marketing », « a chart of revenue by region »: a new subject, not the last answer
_NEW_SUBJECT = re.compile(
    r"\b(?:de|du|des|d'|of|about|on)\s+(?:la\s+|le\s+|les\s+|l'|the\s+|our\s+|nos\s+|notre\s+)?"
    r"(?!(?:ça|ca|cela|ce|ces|cette|it|this|that|these|them|courbes?|barres?|b[âa]tons|camemberts?|secteurs|"
    r"graphiques?|histogrammes?|diagrammes?|lignes?|charts?|graphs?|pie|bars?|lines?|forme)\b)[^\W\d_]{3,}",
    re.I,
)
_CHART_MEMO = re.compile(r"(?:graphique affiché|chart shown) : ")
_MEMO_ROWS = re.compile(r"(?:graphique affiché|chart shown) : .*? — (?P<rows>[^\n]+)")


def _followup(request: str) -> bool:
    """The request points at the previous answer (« mets ça en graphique ») and names no subject of its own; or it
    is a bare type (« en camembert ? »)."""
    req = request or ""
    if _NEW_SUBJECT.search(req):
        return False
    return bool(_FOLLOWUP.search(req)) or len(req.split()) <= 3


def _previous_answer(history: list[dict]) -> str:
    """The last assistant answer in ``history``, its chart memo (« … — T1 120 ; T2 135 ») as one row per line."""
    last = next((m for m in reversed(history or []) if m.get("role") == "assistant" and m.get("content")), None)
    text = str(last.get("content") or "") if last else ""
    memo = _MEMO_ROWS.search(text)
    if memo:
        # the memo ends with « ] » and may go on with another part (« | … »): neither belongs to the last row
        rows = memo.group("rows").split(" | ", 1)[0].rstrip().removesuffix("]")
        return text[: memo.start()] + "\n" + "\n".join(r.strip() for r in rows.split(" ; "))
    return text


def chart_ask(text: str) -> bool:
    """The user's words clearly ask for a chart: an action verb near a chart noun (not « charte graphique » or
    « courbe en J »), and not a question about charts. Only then is a text answer reminded or replaced."""
    text = _chart_words(text)
    clear = _CHART_VERB.search(text) or len(_NUMBER.findall(text)) >= 2  # « graphique du CA : T1 120, T2 135 »
    return bool(_CHART_ASK.search(text) and clear and not chart_howto(text))


def _file_edit_ask(text: str, attached: bool = False) -> bool:
    """A request to change a file: an edit verb that names a format or comes with a document, and not a how-to
    question. "Mets à jour mon planning : réunion lundi 14h." or "Comment ajouter une diapo ?" are not."""
    text = text or ""
    return bool(_EDIT_ASK.search(text) and (attached or _FILE_ASK.search(text)) and not _HOWTO.search(text))


def _made_file(run, ctx: Context) -> bool:
    """A make_* tool succeeded in this run, or a draft exists (a mail ask is answered by a draft, not a file)."""
    return bool(ctx.drafts) or any(
        s.tool.startswith("make_") and s.tool != "make_chart" and not s.error for s in run.steps
    )  # a chart is shown in the chat, it is not a file


def _check_untrusted_url(url: object, ctx: Context) -> None:
    """After a page or a file held an injection, read_page may only open a URL the user gave, a search result or a
    page already read. read_page itself applies the same rule as soon as the run holds any external content
    (birds.harness.tools.web.tainted); this call also covers an injection flagged in another tool's result."""
    from birds.harness.tools.web import check_untrusted_url

    check_untrusted_url(url, ctx)


PAUSE = guard.PAUSE  # a confirm callback returns this to end the run with a pending action (see Agent.run)
_TOOL_OPEN = "<tool_call>"


@dataclass
class Step:
    generation: int
    tool: str
    arguments: dict
    result: str = ""  # short summary of what the model was given
    seconds: float = 0.0
    error: str | None = None
    flags: list[str] = field(default_factory=list)
    decision: str = "allow"
    chars: int = 0
    repairs: list[str] = field(default_factory=list)  # argument shapes fixed before validation (coerce.py)
    info: dict = field(default_factory=dict)  # tool-provided details for the UI (search backend used...)
    flagged_excerpt: str = ""  # the sentence that looked like an instruction (plain text, redacted), for the UI


@dataclass
class Hooks:
    """Optional callbacks for a front end that shows a run while it happens. All are called from the run's thread."""

    on_token: Callable[[str], None] | None = None  # visible answer text, as it is generated
    on_reset: Callable[[], None] | None = None  # text already streamed turned out to precede tool calls: drop it
    on_step_start: Callable[[int, str, dict], None] | None = None  # (index, tool, arguments)
    on_step_end: Callable[[int, Step], None] | None = None
    on_status: Callable[[str, dict], None] | None = None  # e.g. ("waking", {"attempt": 2, "retry_in": 5.0})
    cancel: Any = None  # a threading.Event the front end sets on stop: the model call ends at once
    on_agent: Callable[[dict], None] | None = None  # Mode Agent (crew.py): agent_* events and the crew's tool steps
    on_plan: Callable[[dict], None] | None = None  # the task plan's checklist (plan.py), each time it changes
    on_reflexion: Callable[[dict], None] | None = None  # Mode Réflexion: the level chosen, before the first word


@dataclass
class Run:
    answer: str = ""
    stop_reason: str = ""
    salvaged: bool = False  # the loop failed and the answer came from one last generation without tools
    think_cut: bool = False  # the reasoning ran past cfg.think_chars and the step was redone without it
    lang: str = "en"
    steps: list[Step] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    source_titles: dict[str, str] = field(default_factory=dict)  # url -> title, when known without the steps (crew)
    drafts: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)  # make_chart specs, drawn by the browser
    widgets: list[dict] = field(default_factory=list)  # cards computed by the harness without a tool (world clock)
    images: list[dict] = field(default_factory=list)  # web image candidates seen by web_search / read_page
    usage: list[dict] = field(default_factory=list)  # one entry per generation
    report: dict = field(default_factory=dict)
    flagged: bool = False  # some tool result looked like a prompt injection
    reasoning: str = ""
    messages: list[dict] = field(default_factory=list)  # full conversation, to continue a chat
    pending: dict | None = None  # stop_reason "confirm": {"tool", "arguments"} waiting for the user's decision
    state: dict | None = None  # stop_reason "confirm": JSON-serialisable loop state for Agent.run(resume=...)
    router: dict = field(default_factory=dict)  # the model router's decision, metadata only (router.log_meta)
    plan: dict | None = None  # the task plan's final checklist, when the request asked for two things or more
    notes: list[str] = field(default_factory=list)  # one short line per tool result (facts.note_of)
    figures: list[list[str]] = field(default_factory=list)  # labelled totals read by the tools ([label, amount])
    reflexion: dict | None = None  # Mode Réflexion (reflexion.py): level, who chose it, budget, checks, summary

    def to_dict(self) -> dict:
        return asdict(self)


class AnswerStream:
    """Forwards generated text to ``emit`` only once it is certain to be visible answer text.

    The reasoning block and tool-call markup never go through. Text is released at whitespace boundaries and
    after secret redaction of everything shown so far, so a credential split across chunks is not leaked.
    """

    def __init__(self, emit: Callable[[str], None], thinking: bool):
        self.emit, self.state, self.buf, self.shown = emit, ("think" if thinking else "lead"), "", ""

    def feed(self, piece: str) -> None:
        self.buf += piece
        if self.state == "think":
            end = self.buf.find("</think>")
            if end < 0:
                return
            self.buf, self.state = self.buf[end + len("</think>") :], "lead"
        if self.state == "lead":
            text = self.buf.lstrip()
            if text.startswith("<think>"):  # a reasoning block although none was asked for
                self.buf, self.state = text[len("<think>") :], "think"
                return self.feed("")
            if not text or (len(text) < len(_TOOL_OPEN) and _TOOL_OPEN.startswith(text)):
                return  # nothing yet, or it may still become a tool call
            if text.startswith(_TOOL_OPEN):
                self.state = "tool"
                return
            self.buf, self.state = text, "text"
        if self.state == "text":
            cut = self.buf.find(_TOOL_OPEN)
            if cut >= 0:
                self._release(self.buf[:cut])
                self.state = "tool"
                return
            tail = max((n for n in range(1, len(_TOOL_OPEN)) if self.buf.endswith(_TOOL_OPEN[:n])), default=0)
            safe = self.buf[: len(self.buf) - tail]
            boundary = max(safe.rfind(" "), safe.rfind("\n"))
            if boundary > 0:
                self._release(safe[: boundary + 1])

    def finish(self) -> None:
        if self.state == "text":
            self._release(self.buf)

    def _release(self, text: str) -> None:
        clean = guard.redact(text)
        if clean.startswith(self.shown) and len(clean) > len(self.shown):
            self.emit(clean[len(self.shown) :])
            self.shown = clean

    @property
    def streamed(self) -> bool:
        return bool(self.shown)


class Agent:
    def __init__(
        self,
        llm,
        tok,
        config: Config,
        *,
        confirm: Callable[[str, dict], bool | str] | None = None,
        search=None,
        http: httpx.Client | None = None,
        hooks: Hooks | None = None,
    ):
        self.llm, self.tok, self.cfg, self.confirm = llm, tok, config, confirm
        self.hooks = hooks or Hooks()
        # trust_env=False: the fetch client ignores proxy variables unless the operator passes its own client
        self.http = http or httpx.Client(trust_env=False, follow_redirects=False)
        # The search backend is called at a fixed, operator-chosen address: it gets its own client, which may use
        # the host's proxy settings (unlike read_page, whose target the model chooses).
        self.search = search if search is not None else make_search(config, http or httpx.Client(timeout=15.0))
        self.audit = guard.Audit(config.workspace / config.audit_file if config.audit_file else None)
        # the 8 trained tools first, in their trained order; make_chart (EXTRA_TOOLS) last, when it is offered at all
        self.tools = [t for t in PRODUCT_TOOLS if t["function"]["name"] in self._allowed()]
        params = inspect.signature(llm.generate).parameters
        self._llm_kwargs = any(p.kind is p.VAR_KEYWORD for p in params.values()) or "on_token" in params

    @staticmethod
    def _clock(req: str, lang: str, tz: str | None, ctx: Context) -> str:
        """World clock / common slot in the user's own words: the card goes to ``ctx.widgets``, the facts for the
        model are returned ('' when there is none). A town missing from the table is geocoded for its COUNTRY only
        (its zone always comes from the table)."""
        from datetime import datetime

        from birds.harness import clock

        found = clock.detect(req)
        if not found:
            return ""
        if not found["cities"] and found["unknown"]:
            try:
                city = clock.lookup(found["unknown"], ctx, lang)
            except (guard.Blocked, guard.ToolError):
                city = None
            found["cities"] = [city] if city else []
        zone = clock.valid_zone(tz)
        w = clock.card(found, datetime.now(clock.ZoneInfo(zone)), lang, zone) if found["cities"] else None
        if not w:
            return ""
        ctx.widgets.append(w)
        return clock.summary(w, lang)

    @staticmethod
    def _calc(req: str, lang: str, ctx: Context) -> str:
        """Exact calculator card in the user's own words (VAT, margin, loan, percent, units): the card goes to
        ``ctx.widgets``, the results for the model are returned, or ''."""
        w, facts = calc.facts_for(req, lang)
        if w:
            ctx.widgets.append(w)
        return facts

    def _allowed(self) -> set[str]:
        """Tools shown to the model: the deployment allowlist, minus what is switched off or not configured."""
        off = set() if self.cfg.allow_python else {"run_python"}
        off |= set() if self.search else {"web_search"}
        off |= set() if getattr(self.cfg, "widgets", True) else set(EXTRA_TOOL_NAMES)
        return set(self.cfg.allowed_tools) - off

    def _last_answer(
        self, messages: list[dict], lang: str, deadline: float, notes: list[str] | None = None
    ) -> tuple[str, dict | None]:
        """One generation with no tools and no reasoning, asked to answer from what is already in the conversation.
        The instruction is a temporary last message: it is never kept in the history. ``notes`` (the run's result
        memory) is repeated in it, so a result pushed out of view by later errors is not lost."""
        text = LAST_CHANCE[lang if lang in LAST_CHANCE else "en"]
        if notes:
            text += ("\nRésultats obtenus : " if lang == "fr" else "\nResults so far: ") + " | ".join(notes[-6:])
        note = {"role": "user", "content": text}
        try:
            out, stream = self._generate(render_prompt(self.tok, [*messages, note], [], False), False, deadline)
        except EndpointError:
            return "", None
        parsed = parse_output(out.get("text") or "")
        text = guard.redact(parsed["content"]).strip()
        if _TOOL_OPEN in text:
            text = text.split(_TOOL_OPEN, 1)[0].strip()
        if text and stream is not None:
            stream.finish()
        return text, out

    # ---------------------------------------------------------------- between actions (plan.py, repair.py, facts.py)

    _base = ""  # the user's messages and the history of this run, where the figures a follow-up refers to are

    @staticmethod
    def _base_text(messages: list[dict], turn_at: int) -> str:
        return "\n".join(
            str(m.get("content") or "") for m in messages[: turn_at + 1] if m.get("role") in ("user", "assistant")
        )

    def _offered(self, withdrawn: set[str]) -> set[str]:
        return {t["function"]["name"] for t in self.tools if t["function"]["name"] not in withdrawn}

    def _repair_calls(self, calls: list[dict], offered: set[str], ctx: Context, salvage: str = ""):
        """(calls with tool names and arguments repaired, the repair notes of each call). Runs before the repeat
        guard, so « Taux livret A » and « taux livret a » are the same call."""
        out, notes = [], []
        for c in calls:
            n = [salvage] if salvage else []
            name, fixed = repair.resolve_tool(c.get("name"), offered)
            if fixed:
                n.append(fixed)
            args, more = repair.repair_args(name, c.get("arguments"), request=ctx.request, workspace=ctx.workspace)
            out.append({"name": name, "arguments": args})
            notes.append(n + more)
        return out, notes

    @staticmethod
    def _remember(step: Step, result: str, run: Run, memory: dict, key: str) -> None:
        """The result memory: one note per result (Run.notes), the note of each successful call by its key (recalled
        on a repeat), and the labelled totals read in files and pages (Run.figures, kept in the turn's memo)."""
        note = facts.note_of(step.tool, step.arguments, result, step.error)
        run.notes.append(note)
        if step.error:
            return
        memory[key] = note
        if step.tool in ("read_file", "read_page"):
            for label, num in facts.key_figures(result, 6):
                if [label, num] not in run.figures and len(run.figures) < 8:
                    run.figures.append([label, num])

    @staticmethod
    def _delivered(run: Run, ctx: Context, content: str) -> str:
        """The answer and what the run made: draft subjects and bodies, the arguments of files and charts."""
        parts = [content or ""]
        for d in ctx.drafts:
            parts += [str(d.get("subject") or ""), str(d.get("body") or "")]
        for s in run.steps:
            if (s.tool.startswith("make_") or s.tool == "draft_email") and not s.error:
                parts.append(json.dumps(s.arguments, ensure_ascii=False, default=str))
        return "\n".join(parts)

    def _figure_gap(self, ctx: Context, text: str) -> list[tuple[str, str]]:
        """Labelled totals of the results (and of the user's messages) that the request is about, missing from
        ``text``. Only when the request asks about totals, amounts or VAT."""
        if not facts.FIGURE_ASK.search(ctx.request or ""):
            return []
        src = self._base + "\n" + "\n".join(t for _, t in ctx.fetched)
        return facts.missing_figures(facts.wanted(facts.key_figures(src), ctx.request), text)[:5]

    def _plan_event(self, tplan, run: Run, ctx: Context, content: str, *, offered_names: set[str], final=False):
        """The checklist ticked from what really happened; sent to the UI when the plan is active."""
        if not tplan:
            return None
        text = self._delivered(run, ctx, content)
        statuses = taskplan.status(tplan, run.steps, text, offered_names, figures_ok=not self._figure_gap(ctx, text))
        if taskplan.active(tplan) and self.hooks.on_plan:
            self.hooks.on_plan(taskplan.to_dict(statuses, run.lang, final=final))
        return statuses

    def _final_check(self, tplan, run: Run, ctx: Context, content: str, messages, turn_at, offered: set[str]):
        """(reminder, reasons) for an answer that lacks something the request asked for, or ('', set())."""
        text = self._delivered(run, ctx, content)
        gap = self._figure_gap(ctx, text)
        statuses = taskplan.status(tplan, run.steps, text, offered, figures_ok=not gap) if tplan else []
        todo = taskplan.missing(statuses, enforced_only=not taskplan.active(tplan))
        if _made_file(run, ctx):  # « un document avec un graphique »: no chart reminder after a file (see chart_ask)
            todo = [s for s in todo if s["kind"] != "chart"]
        parts, reasons = [], set()
        if todo:
            read = next((i.path for i in tplan if i.kind == "read"), "")
            parts.append(taskplan.nudge(todo, facts.figures_line(gap), read))
            reasons |= {s["kind"] for s in todo}
        if gap and "totals" not in reasons:
            parts.append(
                "Some figures of the results are missing or changed in your answer. Write them exactly as in the "
                f"results: {facts.figures_line(gap)}."
            )
            reasons.add("figures")
        if facts.wrong_language(content, run.lang) and not facts.other_language_asked(ctx.request, run.lang):
            parts.append(LANG_NUDGE["en" if run.lang == "en" else "fr"])
            reasons.add("lang")
        return " ".join(parts), reasons

    def _review(self, messages, parsed, content: str, run: Run, rinfo: dict, deadline: float) -> str:
        """Chouette and Albatros: the model re-reads its draft once (no tools, not streamed) and answers « OK » or
        the corrected text. A changed answer replaces the one shown; the review never adds a turn to the history."""
        rinfo["reviewed"] = True
        draft = [{"role": "assistant", "content": parsed["content"], "reasoning_content": parsed["reasoning"]},
                 {"role": "tool", "content": reflex.REVIEW}]  # fmt: skip
        try:
            out, _ = self._generate(render_prompt(self.tok, [*messages, *draft], [], True), True, deadline, quiet=True)
        except EndpointError:
            return content
        run.usage.append({**{k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds", "busy_seconds",
                                                    "finish_reason") if k in out}, "kind": "review"})  # fmt: skip
        text = out.get("text") or ""
        got = parse_output(text if "</think>" in text else "<think>" + text + "</think>")
        if got["tool_calls"] or _TOOL_OPEN in got["content"]:
            return content
        new, changed = reflex.review_kept(content, guard.redact(got["content"]))
        rinfo["review_changed"] = changed
        if changed and self.hooks.on_reset and self.hooks.on_token:
            self.hooks.on_reset()
            self.hooks.on_token(new)
        return new

    _think_chars: int | None = None  # this run's reasoning budget (Mode Réflexion), else cfg.think_chars
    _extra_tokens = 0  # output tokens added for the reasoning (reflexion.Level.think_tokens)

    def _generate(
        self, prompt: str, thinking: bool, deadline: float, *, quiet: bool = False, lead: bool = False
    ) -> tuple[dict, AnswerStream | None]:
        """One generation. ``quiet``: nothing is streamed (the review of a draft); ``lead``: the prompt already
        closed the reasoning (budget forcing), the output is answer text from its first character."""
        hooks = self.hooks
        budget = self._think_chars or self.cfg.think_chars
        can_cut = thinking and not lead and accepts(self.llm.generate, "think_limit")
        limit = {"think_limit": budget} if can_cut else {}
        max_tokens = self.cfg.max_tokens + (self._extra_tokens if thinking and not lead else 0)
        if not self._llm_kwargs:
            return self.llm.generate(prompt, max_tokens, STOP, **limit), None
        stream = AnswerStream(hooks.on_token, thinking and not lead) if hooks.on_token and not quiet else None
        out = self.llm.generate(
            prompt,
            max_tokens,
            STOP,
            on_token=stream.feed if stream else None,
            on_status=hooks.on_status,
            deadline=deadline,
            **({"extra": {"cache_salt": self.cfg.cache_salt}} if self.cfg.cache_salt else {}),
            **({"cancel": hooks.cancel} if hooks.cancel is not None and accepts(self.llm.generate, "cancel") else {}),
            **limit,
        )
        return out, stream

    def run(
        self,
        user: str = "",
        *,
        history: list[dict] | None = None,
        system: str | None = None,
        thinking: bool = False,
        lang: str | None = None,
        resume: dict | None = None,
        decision: bool | None = None,
        request_text: str | None = None,
        attached: bool = False,
        tz: str | None = None,
        reflexion: str | None = None,
    ) -> Run:
        """Run one user request, or continue one that stopped on a pending confirmation.

        When the ``confirm`` callback returns ``PAUSE``, the run ends with ``stop_reason == "confirm"``,
        ``run.pending`` (the action) and ``run.state``. Calling ``run(resume=state, decision=True|False)`` later,
        possibly in another process, performs or refuses that action and carries on: nothing is generated twice.
        The caller is responsible for the integrity of ``state`` between the two calls (the web app signs it).
        ``request_text`` is the user's own words when ``user`` also carries attachment text (used to choose the
        tools); ``attached`` says the request comes with a document or an image.
        ``reflexion`` (Mode Réflexion, ``reflexion.py``): a level key, or « auto » for the model to choose; it sets
        ``thinking``, the reasoning budget, the self-check rounds and the review. None keeps ``thinking`` as given.
        """
        cfg, t0, hooks = self.cfg, time.monotonic(), self.hooks
        deadline = t0 + cfg.timeout_s
        self._think_chars, self._extra_tokens = None, 0
        choice: reflex.Choice | None = None
        if resume is not None:
            st = copy.deepcopy(resume)
            thinking = bool(st["thinking"])
            if st.get("reflexion") in reflex.LEVELS:
                choice = reflex.Choice(str(st["reflexion"]), "resume")
            run = Run(lang=st["lang"], flagged=bool(st["flagged"]), reasoning=st.get("reasoning", ""))
            run.steps = [Step(**s) for s in st["steps"]]
            run.usage = list(st["usage"])
            ctx = Context(
                config=cfg,
                http=self.http,
                search=self.search,
                sources=list(st["sources"]),
                drafts=list(st["drafts"]),
                files=list(st["files"]),
                bytes_fetched=int(st["bytes_fetched"]),
                lang=st["lang"],
                request=str(st.get("request", "")),
                message=str(st.get("message", "")),
                attached=bool(st.get("attached", False)),
                found=[str(u) for u in st.get("found", [])],
                used=[str(u) for u in st.get("used", [])],
                fetched=[[str(k), str(v)] for k, v in st.get("fetched", []) if k in ("web", "file")],
                charts=[c for c in st.get("charts", []) if isinstance(c, dict)],
                images=[i for i in st.get("images", []) if isinstance(i, dict)],
                widgets=[w for w in st.get("widgets", []) if isinstance(w, dict)],
            )
            messages, seen, queue = st["messages"], set(st["seen"]), list(st["queue"])
            budget, side_effects, bad_streak = st["budget"], st["side_effects"], st["bad_streak"]
            nudged = bool(st.get("nudged", False))
            promise_nudged = True  # a resumed run never re-nudges
            chartable = False
            file_nudged = bool(st.get("file_nudged", False))
            withdrawn = set(st.get("withdrawn", []))
            routed = set(st.get("routed", []))
            gen, ok, content = st["gen"], st["ok"], st.get("content", "")
            forced = "confirmed" if decision is True else "denied_unconfirmed"
            auto_calls = 0
            tplan = [taskplan.Item(**i) for i in st.get("plan", []) if isinstance(i, dict)]
            checked, earlier = bool(st.get("checked", True)), None
            run.notes = [str(n) for n in st.get("notes", [])]
            memory = {str(k): str(v) for k, v in (st.get("memory") or {}).items()}
            turn_at = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=0)
            self._base = self._base_text(messages, turn_at)
        else:
            run = Run(lang=lang or detect_lang(user))
            ctx = Context(
                config=cfg,
                http=self.http,
                search=self.search,
                lang=run.lang,
                request=user if request_text is None else request_text,
                message=user,
                attached=attached,
            )
            messages = list(history or [])
            if not messages or messages[0]["role"] != "system":
                messages.insert(0, {"role": "system", "content": system or DEFAULT_SYSTEM[run.lang]})
            messages.append({"role": "user", "content": guard.defang(user)})
            seen, queue = set(), []
            budget, side_effects, bad_streak, content = cfg.max_context_chars, 0, 0, ""
            words = req = user if request_text is None else request_text
            routed = route(words, attached) if cfg.route_tools else (route(words) & {"make_chart"})
            # widget tools (find_places, find_company, convert_currency) are offered only when the user's own words
            # ask for them: an ordinary turn keeps the trained tool block byte for byte (see intents.py)
            found = intents.detect(req, attached, run.lang) if getattr(cfg, "widgets", True) else []
            # --- open data (birds/harness/opendata_intents.py): holidays, entity cards, statistics, tenders...
            from birds.harness import opendata_intents

            found = opendata_intents.merge(found, req, attached, run.lang) if getattr(cfg, "widgets", True) else found
            # --- end open data
            # « et à Lyon ? », « et en livres ? »: a short follow-up re-asks the previous turn's rich result, read from
            # the memo the server wrote after it (never from the model's text, see followup.py)
            prev = followup.previous(history) if history and getattr(cfg, "widgets", True) and not attached else None
            again = None if any(i.args for i in found) else followup.resolve(req, prev, run.lang)
            clock_words = req
            if again is not None and again.tool == "clock":
                clock_words = again.args["text"]
            elif again is not None:
                found = [again]
            # ---- model router (birds/harness/router.py) -------------------------------------------------------
            # Bird decides the modules in one short call; the parsers above become its hints, its fallback (router
            # off, too slow, unusable answer: plan.active is False and nothing below changes) and a veto.
            # ---- Mode Réflexion « Auto » (reflexion.py): the model chooses its level in one short call, at the same
            # time as the router's (no extra wall time); a chosen level needs no call
            box: dict = {}
            picker = None
            if reflexion == "auto":
                picker = threading.Thread(
                    target=lambda: box.update(c=reflex.decide(self.llm, self.tok, req, lang=run.lang,
                                                          cache_salt=cfg.cache_salt)),
                    daemon=True,
                )  # fmt: skip
                picker.start()
            elif reflexion in reflex.LEVELS:
                choice = reflex.Choice(reflexion, "user")
            plan = router.plan_turn(self, req, history, attached=attached, lang=run.lang, deadline=deadline)
            if picker is not None:
                picker.join(timeout=reflex.BUDGET_S * 1.5 + 0.5)
                choice = box.get("c") or reflex.Choice(reflex.hint_level(req), "hint", reflex.BUDGET_S, None, "join_timeout")
                if choice.usage:
                    run.usage.append({**choice.usage, "kind": "reflexion"})
            if plan.decision is not None:
                run.router = router.log_meta(plan.decision)
                if plan.decision.meta.get("usage"):
                    run.usage.append({**plan.decision.meta["usage"], "kind": "router"})
            found, clock_words = plan.found(found), plan.clock_words(clock_words)
            routed = plan.routed(routed)
            # ---- end of the model router hook ------------------------------------------------------------------
            routed |= set(EXTRA_TOOL_NAMES) - {"make_chart"} - {i.tool for i in found}
            prefill = next((i for i in found if i.args), None)
            # « météo aujourd'hui », « taux du jour »: words that usually call for the web, but the tool has the answer
            own_answer = prefill and prefill.tool in ("convert_currency", "get_weather")
            # --- open data: the card answers by itself; a statistics chart is drawn once (no second make_chart)
            own_answer = own_answer or opendata_intents.own(prefill)
            routed |= opendata_intents.withdraw(prefill)
            # --- end open data
            if prefill and not prefill.keep_web and (own_answer or not _NEEDS_WEB.search(req)):
                routed |= {"web_search", "read_page"}
            # ---- maps: « une pharmacie autour de moi »: Bird does not know where the user is; nothing is looked up,
            # the model asks for a place and the memo keeps the kind for the reply (« gare de Lyon »)
            if not prefill and any(i.mode == "ask" for i in found):
                kind = intents.ask_kind(req)
                routed |= {"find_places", "web_search", "read_page"}
                messages[-1]["content"] += ASK_NOTE["en" if run.lang == "en" else "fr"]
                ctx.widgets.append({"type": "ask_place", "kind": kind})
            facts = "" if prefill or not getattr(cfg, "widgets", True) else self._clock(clock_words, run.lang, tz, ctx)
            if facts:
                # « décalage horaire avec Tokyo »: the harness computes the times and the slot itself (no tool, no
                # network); the model only puts them in a sentence
                routed |= {"web_search", "read_page"}
                messages[-1]["content"] += CLOCK_NOTE["en" if run.lang == "en" else "fr"].format(facts=facts)
            # the small modules (« card »): the kinds the router decided, or the parsers' guess when it is off; each
            # card is built from the user's own data only (birds.harness.modules), none when the data is missing
            kinds = plan.cards()
            cards_on = getattr(cfg, "widgets", True) and not attached and not prefill
            sums = (
                ""
                if not cards_on or facts or (kinds is not None and "calc" not in kinds)
                else self._calc(req, run.lang, ctx)
            )
            if cards_on:
                from birds.harness import modules as small

                have = {w.get("type") for w in ctx.widgets}
                ctx.widgets += [w for w in small.cards(req, run.lang, [k for k in kinds if k not in ("calc", "sources")]
                                                       if kinds is not None else None) if w["type"] not in have]  # fmt: skip
                ctx.want_sources = "sources" in (kinds if kinds is not None else small.asked_kinds(req))
            if sums:
                # « mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 % »: the harness computes exactly (calc.py);
                # the model only puts the results in a sentence (a 4B model gets compound interest wrong)
                routed |= {"web_search", "read_page"}
                messages[-1]["content"] += calc.NOTE["en" if run.lang == "en" else "fr"].format(facts=sums)
                facts = sums
            no_slot = prefill or facts or _NEEDS_WEB.search(req) or not plan.allows("event")
            slot = "" if no_slot else _event_slot(req, run.lang)
            if slot:
                # "cale un déjeuner le 25 décembre à midi": the UI shows an event card (.ics) built from these
                # words; live model, offered the web, searched "restaurants ouverts le 25 décembre" and refused
                routed |= {"web_search", "read_page"}
                messages[-1]["content"] += EVENT_NOTE["en" if run.lang == "en" else "fr"].format(slot=slot)
            pictures = None if prefill or facts or slot or attached else plan.images(req, run.lang)
            if pictures is not None and self.search:
                # « montre-moi une photo de la tour Eiffel »: the harness searches the subject itself; the images
                # shown are the ones whose page title names it (birds.web.backends.pick_web_images)
                prefill = pictures
                routed -= {"web_search", "read_page"}
                messages[-1]["content"] += IMAGES_NOTE["en" if run.lang == "en" else "fr"].format(
                    subject=pictures.args["query"]
                )
            nudged, withdrawn, file_nudged = False, set(routed), False
            promise_nudged = False
            gen, ok, forced = 0, 0, None
            auto_calls = 0
            # « en camembert plutôt » right after a chart: only a type, the data is the chart just shown
            last = next((m for m in reversed(history or []) if m.get("role") in ("user", "assistant")), None) or {}
            retype = (
                last.get("role") == "assistant"
                and bool(_CHART_MEMO.search(str(last.get("content") or "") + str(last.get("memo") or "")))
                and followup.chart_retype(req)
                and plan.allows("make_chart")
            )
            if retype:
                routed.discard("make_chart")
            chartable = "make_chart" not in routed and plan.chart(chart_ask(req) or trend_ask(req) or retype)
            mine = figures_in(req) if chartable and not prefill else None
            if chartable and not prefill and mine is None and history and (_followup(req) or retype):
                # « mets ça en graphique », « refais-le en courbe »: the figures are in the previous answer (its
                # table, or the memo of the chart it showed); the harness draws them, with the type now asked
                mine = figures_in(_previous_answer(history))
            if mine:
                # « graphique des ventes : janvier 120, février 135, mars 160 »: the figures are the user's own, so
                # the harness draws the chart itself instead of hoping the small model calls make_chart
                prefill = intents.Intent("make_chart", chart_call(req, mine, run.lang), keep_web=True)
            # ---- task plan (plan.py): the deliverables of this request, from the user's own words only
            turn_at, checked, earlier, memory = len(messages) - 1, False, None, {}
            # a file attached in an earlier turn (the app sends it with every request) is not « to read first »
            told = "\n".join(str(m.get("content") or "") for m in history or [] if m.get("role") == "user")
            fresh = re.sub(r"\[(?:Fichier joint|Attached file)\s*:\s*([^\]\n]+)\]",
                           lambda m: "" if m.group(0) in told else m.group(0), user)  # fmt: skip
            tplan = taskplan.extract(req, run.lang, fresh, chart_ask(req)) if getattr(cfg, "task_plan", True) else []
            if getattr(cfg, "canvas_sink", None) is not None:  # the canvas is the file: never « présentation manque »
                tplan = taskplan.for_canvas(tplan, getattr(cfg, "canvas_kind", "") or "deck")
            if taskplan.active(tplan):
                messages[-1]["content"] += taskplan.note(tplan, run.lang)
            self._base = self._base_text(messages, turn_at)
            if prefill and prefill.tool in self._allowed():
                # "prefill": the harness makes the call the parser is sure of, before the first generation, on the
                # same path as a model call (validation, gate, injection scan); the step is tagged auto for the UI
                call = {"name": prefill.tool, "arguments": dict(prefill.args)}
                messages.append(
                    {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": dict(call)}]}
                )
                seen.add(repair.canonical(call["name"], call["arguments"]))
                queue, gen, auto_calls = [call], 1, 1
        lvl = reflex.LEVELS.get(choice.level) if choice is not None else None
        rinfo: dict = dict((resume or {}).get("rx") or {}) if resume is not None else {}
        if lvl is not None:
            thinking = lvl.thinking
            self._think_chars, self._extra_tokens = (lvl.think_chars or None), lvl.think_tokens
            if not rinfo:
                if hooks.on_reflexion:
                    hooks.on_reflexion({"level": lvl.key, "auto": choice.source in ("model", "hint")})
                rinfo = {"level": lvl.key, "auto": choice.source in ("model", "hint"), "source": choice.source,
                         "decide": choice.meta(), "think_chars": 0, "cut": None, "rounds": 0, "corrected": False,
                         "reviewed": False, "review_changed": False, "checks": {}}  # fmt: skip
        reasonings: list[str] = []
        gpu = meter.GpuMeter(enabled=cfg.measure_gpu or getattr(self.llm, "local", False))
        pre_notes: list[list[str]] = []  # argument repairs made before validation, one list per queued call
        self._plan_event(tplan, run, ctx, "", offered_names=self._offered(withdrawn))

        while True:
            if not queue:  # ---- ask the model
                if gen >= cfg.max_steps:
                    run.stop_reason = "max_steps"
                    break
                if time.monotonic() > deadline:
                    run.stop_reason = "timeout"
                    break
                step_thinking = thinking
                try:
                    with gpu:
                        offered = [t for t in self.tools if t["function"]["name"] not in withdrawn]
                        out, stream = self._generate(
                            render_prompt(self.tok, messages, offered, step_thinking), step_thinking, deadline
                        )
                        stuck = out.get("finish_reason") in ("think_budget", "repetition")
                        if step_thinking and stuck and "</think>" not in (out.get("text") or ""):
                            # the reasoning ran on, or looped, with no answer in sight: count it, then answer this
                            # step directly instead of showing nothing
                            run.usage.append(
                                {
                                    k: out.get(k)
                                    for k in (
                                        "prompt_tokens",
                                        "completion_tokens",
                                        "seconds",
                                        "busy_seconds",
                                        "finish_reason",
                                    )
                                    if k in out
                                }
                            )
                            # budget forcing: what was reasoned is kept, the reasoning is closed with a short note
                            # and the model answers from there (a loop is cut at its start by the client)
                            run.think_cut = True
                            reason = out.get("finish_reason") or "think_budget"
                            if rinfo:
                                rinfo["cut"] = reason
                            if stream is not None and hooks.on_reset:
                                hooks.on_reset()
                            closed = reflex.close_text(out.get("text") or "", reason, run.lang)
                            head = render_prompt(self.tok, messages, offered, True)
                            out, stream = self._generate(head + closed, True, deadline, lead=True)
                            out = {**out, "text": closed.replace("\n</think>\n\n", "</think>") + (out.get("text") or "")}
                except EndpointError as e:
                    if e.kind != "timeout":
                        raise
                    run.stop_reason = "timeout"  # the endpoint was still answering when the budget ran out
                    break
                run.usage.append(
                    {
                        k: out.get(k)
                        for k in (
                            "prompt_tokens",
                            "completion_tokens",
                            "seconds",
                            "busy_seconds",
                            "first_token_seconds",
                            "finish_reason",
                            "cached_tokens",
                            "prompt_chars",
                            "completion_chars",
                        )
                        if k in out
                    }
                )
                text = out.get("text") or ""
                if step_thinking and "</think>" not in text:
                    text = "<think>" + text + "</think>"  # ran out of budget while reasoning: there is no answer
                parsed = parse_output(text)
                content, run.reasoning = guard.redact(parsed["content"]), parsed["reasoning"]
                if parsed["reasoning"]:
                    reasonings.append(parsed["reasoning"])
                calls = parsed["tool_calls"][: cfg.max_calls_per_step]
                offered_names = {t["function"]["name"] for t in offered}
                salvage_note = ""
                if not calls and parsed["content"]:
                    # « <tool_call>{"name": …, "arguments": …}</tool_call> », a bare JSON call or « read_file(path=…) »
                    # in the text: the trained parser reads none of them (repair.salvage_calls)
                    got, before, salvage_note = repair.salvage_calls(
                        parsed["content"],
                        offered_names,
                        code_ask=bool(repair.CODE_ASK.search(ctx.request or "")),
                        flagged=run.flagged,
                    )
                    if got:
                        calls = got[: cfg.max_calls_per_step]
                        parsed = {**parsed, "content": before}
                        content = guard.redact(before)
                calls, pre_notes = self._repair_calls(calls, offered_names, ctx, salvage_note)
                if stream is not None:
                    if calls or _TOOL_OPEN in content:
                        if stream.streamed and hooks.on_reset:
                            hooks.on_reset()  # some text was shown before the model called a tool
                    else:
                        stream.finish()
                if not calls:
                    if _TOOL_OPEN in content:  # opened a call and never closed it
                        content, run.stop_reason = content.split(_TOOL_OPEN, 1)[0].strip(), "malformed_output"
                    else:
                        run.stop_reason = "answer" if content else "empty_output"
                        if content and out.get("finish_reason") == "length":
                            run.stop_reason = "length"  # cut by max_tokens: kept, but marked as interrupted
                    if out.get("finish_reason") == "repetition":
                        run.stop_reason = "repetition"  # the model looped: stopped early, one copy kept
                    canvas = getattr(cfg, "canvas_sink", None) is not None  # the canvas shows the content
                    if run.stop_reason == "answer" and not _made_file(run, ctx) and not canvas:
                        claims = bool(_FILE_CLAIM.search(content))
                        if not file_nudged and claims and _file_edit_ask(ctx.request, attached):
                            if gen < cfg.max_steps - 1 and time.monotonic() < deadline:
                                # it claims a file that does not exist: tell it once, and let it make the file
                                file_nudged = True
                                if stream is not None and stream.streamed and hooks.on_reset:
                                    hooks.on_reset()
                                messages.append(
                                    {
                                        "role": "assistant",
                                        "content": parsed["content"],
                                        "reasoning_content": parsed["reasoning"],
                                    }
                                )
                                messages.append({"role": "tool", "content": NO_FILE_NUDGE})
                                gen += 1
                                continue
                            content = NO_FILE[run.lang]
                        elif file_nudged and claims:
                            content = NO_FILE[run.lang]  # reminded once, and still claims a file: say so, plainly
                        # reminded once and now answering inline without a claim: that answer is kept
                    if (
                        run.stop_reason == "answer"
                        and not promise_nudged
                        and _PROMISE.search(content)
                        and len(content) < 500
                        and not content.rstrip().endswith("?")
                        and gen < cfg.max_steps - 1
                        and time.monotonic() < deadline
                    ):
                        # « Je reviens sur l'image pour récupérer les totaux. » and then nothing until the user says
                        # « vas-y »: the model announced work it can do now. Tell it once to do it in this turn.
                        promise_nudged = True
                        if stream is not None and stream.streamed and hooks.on_reset:
                            hooks.on_reset()
                        messages.append(
                            {
                                "role": "assistant",
                                "content": parsed["content"],
                                "reasoning_content": parsed["reasoning"],
                            }
                        )
                        messages.append({"role": "tool", "content": DO_IT_NUDGE})
                        gen += 1
                        continue
                    if (
                        run.stop_reason == "answer"
                        and not file_nudged
                        and not canvas
                        and "make_chart" not in withdrawn
                        and chart_ask(ctx.request)
                        and not ctx.charts
                        and not _made_file(run, ctx)
                        and not content.rstrip().endswith("?")
                        and gen < cfg.max_steps - 1
                        and time.monotonic() < deadline
                    ):
                        # a chart was asked and the model answered in text only: remind it once (same budget and
                        # flag as the file reminder, so at most one reminder per run)
                        file_nudged = True
                        if stream is not None and stream.streamed and hooks.on_reset:
                            hooks.on_reset()
                        messages.append(
                            {
                                "role": "assistant",
                                "content": parsed["content"],
                                "reasoning_content": parsed["reasoning"],
                            }
                        )
                        messages.append({"role": "tool", "content": chart_nudge(ctx.request, messages)})
                        gen += 1
                        continue
                    if (
                        run.stop_reason == "answer"
                        and chart_ask(ctx.request)
                        and not ctx.charts
                        and not _made_file(run, ctx)
                        and not canvas
                        and chart_claim(content)
                    ):
                        content = NO_CHART[run.lang]  # "Voici la courbe :" with no chart: say so, plainly
                    if (
                        run.stop_reason == "answer"
                        and not checked
                        and not content.rstrip().endswith("?")
                        and gen < cfg.max_steps - 1
                        and time.monotonic() < deadline
                    ):
                        # one reminder for everything the answer still lacks: a requested deliverable, the reading
                        # of an attached file, the figures of the results, the user's language (no extra
                        # generation when all is in order)
                        why, reasons = self._final_check(tplan, run, ctx, content, messages, turn_at, offered_names)
                        if why:
                            checked, earlier = True, (content, reasons)
                            if stream is not None and stream.streamed and hooks.on_reset:
                                hooks.on_reset()
                            messages.append(
                                {"role": "assistant", "content": parsed["content"],
                                 "reasoning_content": parsed["reasoning"]}
                            )  # fmt: skip
                            messages.append({"role": "tool", "content": why})
                            gen += 1
                            continue
                    if (
                        lvl is not None
                        and run.stop_reason == "answer"
                        and rinfo.get("rounds", 0) < lvl.checks
                        and not content.rstrip().endswith("?")
                        and gen < cfg.max_steps - 1
                        and deadline - time.monotonic() > 10
                    ):
                        # Mode Réflexion: the harness recomputes the answer's calculations and checks every point
                        # asked; anything wrong goes back to the model in one reminder that names it
                        verdict = reflex.verify(ctx.request, content, parsed["reasoning"], run.lang)
                        if not rinfo.get("checks"):
                            rinfo["checks"] = verdict.as_dict()
                        if not verdict.ok:
                            # what was found, for the evaluation (scripts/reflexion_eval.py); never sent to the page
                            rinfo.setdefault("issues", []).append(
                                {"calc": verdict.calc_wrong[:4], "missing": [p[:80] for p in verdict.missing[:4]]})
                            rinfo["rounds"] = rinfo.get("rounds", 0) + 1
                            rinfo["corrected"] = True
                            # what was sent back, each on its own: a missing point is never shown as a wrong calc
                            rinfo["calc_fixed"] = rinfo.get("calc_fixed", False) or bool(verdict.calc_wrong)
                            rinfo["points_fixed"] = rinfo.get("points_fixed", False) or bool(verdict.missing)
                            if stream is not None and stream.streamed and hooks.on_reset:
                                hooks.on_reset()
                            messages.append(
                                {"role": "assistant", "content": parsed["content"],
                                 "reasoning_content": parsed["reasoning"]}
                            )  # fmt: skip
                            messages.append({"role": "tool", "content": reflex.nudge(verdict, run.lang)})
                            gen += 1
                            continue
                        rinfo["rounds"] = lvl.checks  # all right: no more rounds
                    if (
                        lvl is not None
                        and lvl.review
                        and run.stop_reason == "answer"
                        and not rinfo.get("reviewed")
                        and not content.rstrip().endswith("?")
                        and gen < cfg.max_steps - 1
                        and deadline - time.monotonic() > 20
                    ):
                        content = self._review(messages, parsed, content, run, rinfo, deadline)
                    break
                if gen == cfg.max_steps - 1:
                    run.stop_reason = "max_steps"  # the last allowed generation still asks for tools: they are not run
                    break
                keys = [repair.canonical(c["name"], c["arguments"]) for c in calls]
                if any(k in seen for k in keys) or len(set(keys)) < len(keys):
                    if nudged:
                        run.stop_reason = "loop"  # the same call with the same arguments again, after a reminder
                        break
                    # A small model sometimes repeats a call it already made. Tell it once, withdraw that tool for
                    # the rest of the run (so the next generation must use the result), then go on.
                    nudged = True
                    withdrawn.update(c["name"] for c in calls)
                    messages.append(
                        {
                            "role": "assistant",
                            "content": parsed["content"],
                            "reasoning_content": parsed["reasoning"],
                            "tool_calls": [{"type": "function", "function": dict(c)} for c in calls],
                        }
                    )
                    for c, k in zip(calls, keys, strict=True):
                        recall = f" Its result: {memory[k]}." if k in memory else ""
                        messages.append(
                            {
                                "role": "tool",
                                "content": f"Error: {c['name']} was already called with these exact arguments and its "
                                f"result is above.{recall} Do not repeat it: use that result now, either to answer the "
                                "user or to call the next tool the request needs.",
                            }
                        )
                    gen += 1
                    continue
                seen.update(keys)
                messages.append(
                    {
                        "role": "assistant",
                        "content": parsed["content"],
                        "reasoning_content": parsed["reasoning"],
                        "tool_calls": [{"type": "function", "function": dict(c)} for c in calls],
                    }
                )
                queue, ok = [dict(c) for c in calls], 0
                gen += 1
            # ---- run the tool calls of generation gen-1
            paused = False
            while queue:
                c = queue[0]
                fixes = pre_notes.pop(0) if pre_notes else []
                step, result = self._call(c["name"], c["arguments"], gen - 1, run, ctx, side_effects, forced, routed,
                                          pre_notes=fixes)  # fmt: skip
                forced = None
                if auto_calls:
                    step.info["auto"], auto_calls = True, 0
                if step.decision == "pause":
                    paused = True
                    break
                queue.pop(0)
                side_effects += step.decision in ("allow", "confirmed") and step.tool in guard.SIDE_EFFECT_TOOLS
                ok += step.decision != "rejected"
                result = guard.truncate(result, min(cfg.max_result_chars, budget))
                budget = max(0, budget - len(result))
                step.chars, step.result = len(result), result[:200]
                run.steps.append(step)
                if hooks.on_step_end:
                    hooks.on_step_end(len(run.steps) - 1, step)
                messages.append({"role": "tool", "content": result})
                self._remember(step, result, run, memory, repair.canonical(c["name"], c["arguments"]))
            if not paused and taskplan.active(tplan) and messages and messages[-1]["role"] == "tool":
                # the checklist, ticked from what really happened, after the last result of the step
                shown = self._plan_event(tplan, run, ctx, "", offered_names=self._offered(withdrawn))
                messages[-1]["content"] += taskplan.progress(shown)
            if paused:
                run.stop_reason = "confirm"
                run.pending = {"tool": step.tool, "arguments": step.arguments}
                run.state = {
                    "v": 1,
                    "lang": run.lang,
                    "thinking": thinking,
                    "messages": messages,
                    "seen": sorted(seen),
                    "queue": queue,
                    "budget": budget,
                    "side_effects": side_effects,
                    "bad_streak": bad_streak,
                    "nudged": nudged,
                    "file_nudged": file_nudged,
                    "withdrawn": sorted(withdrawn),
                    "routed": sorted(routed),
                    "found": ctx.found,
                    "request": ctx.request,
                    "message": ctx.message,
                    "used": ctx.used,
                    "fetched": ctx.fetched,
                    "charts": ctx.charts,
                    "images": ctx.images,
                    "widgets": ctx.widgets,
                    "attached": ctx.attached,
                    "gen": gen,
                    "ok": ok,
                    "content": content,
                    "flagged": run.flagged,
                    "reasoning": run.reasoning,
                    "steps": [asdict(s) for s in run.steps],
                    "usage": run.usage,
                    "sources": ctx.sources,
                    "drafts": ctx.drafts,
                    "files": ctx.files,
                    "bytes_fetched": ctx.bytes_fetched,
                    "plan": taskplan.item_dicts(tplan),
                    "checked": checked,
                    "notes": run.notes,
                    "memory": memory,
                    "reflexion": lvl.key if lvl is not None else None,
                    "rx": rinfo,
                }
                break
            bad_streak = 0 if ok else bad_streak + 1
            if bad_streak >= 2:
                run.stop_reason = "invalid_tool_calls"  # one retry after a malformed step, not more
                break

        if (run.stop_reason == "answer" and chartable and not ctx.charts and "make_chart" in self._allowed()
                and getattr(cfg, "canvas_sink", None) is None):
            # a chart was asked and the model answered with a table or a list of figures instead of drawing it:
            # the harness draws that table (make_chart checks where the numbers come from and tags them)
            found = figures_in(content)
            if found:
                step, _ = self._call("make_chart", chart_call(ctx.request, found, run.lang), gen, run, ctx, 0, None)
                step.info = {**(step.info or {}), "auto": True}
                run.steps.append(step)
                if hooks.on_step_end:
                    hooks.on_step_end(len(run.steps) - 1, step)
        salvage = run.stop_reason in _SALVAGE and not (content or "").strip() and deadline - time.monotonic() > 8
        if salvage:
            # The loop ended without a usable answer (tool calls that kept failing, the step budget, an empty or
            # broken output). Before giving up, one last generation with no tools and no reasoning: answer with what
            # was gathered. Cheap, and far better than a generic "could not answer".
            last, used = self._last_answer(messages, run.lang, deadline, run.notes)
            if used:  # the last generation counts in the receipt like any other
                run.usage.append(
                    {
                        k: used.get(k)
                        for k in ("prompt_tokens", "completion_tokens", "seconds", "busy_seconds", "finish_reason")
                        if k in used
                    }
                )
            if last:
                content, run.stop_reason, run.salvaged = last, "answer", True
        if run.stop_reason == "answer" and earlier is not None:
            content = (
                taskplan.merged(earlier[0], content, earlier[1]) if detect_lang(earlier[0]) == run.lang else content
            )
        if tplan and run.stop_reason != "confirm":
            final = self._plan_event(tplan, run, ctx, content, offered_names=self._offered(withdrawn), final=True)
            if not taskplan.active(tplan):
                run.plan = None
            elif final is not None:
                run.plan = taskplan.to_dict(final, run.lang, final=True)
        if rinfo:
            if run.stop_reason == "answer" and rinfo.get("checks") and rinfo.get("corrected"):
                rinfo["checks"] = {**rinfo["checks"], **{k: v for k, v in reflex.verify(
                    ctx.request, content, "", run.lang).as_dict().items() if k in ("calc_wrong", "missing")}}  # fmt: skip
                rinfo["checks"]["fixed"] = True
            all_reasoning = "\n".join(reasonings)
            rinfo["think_chars"] = rinfo.get("think_chars", 0) + len(all_reasoning)
            rinfo["summary"] = reflex.summary(all_reasoning, run.lang) if all_reasoning else rinfo.get("summary", [])
            run.reflexion = rinfo
        if run.stop_reason == "confirm":
            run.answer = ""
        elif run.stop_reason == "answer":
            run.answer = content
            messages.append({"role": "assistant", "content": content})
        elif run.stop_reason == "timeout":
            run.answer = OUT_OF_TIME[run.lang]
        elif run.stop_reason == "repetition":
            run.answer = content or LOOPED[run.lang]
        else:
            run.answer = content or FALLBACK[run.lang]
        run.messages, run.sources, run.drafts, run.files = messages, ctx.sources, ctx.drafts, ctx.files
        run.charts, run.images, run.widgets = ctx.charts, ctx.images, ctx.widgets
        if getattr(ctx, "want_sources", False):  # « donne-moi tes sources »: the pages read, as cards
            from birds.harness import modules as small

            got = small.source_cards(run.sources, run.lang)
            if got:
                run.widgets.append(got)
        run.report = meter.report(
            run.usage,
            wall_seconds=time.monotonic() - t0,
            tool_calls=len(run.steps),
            bytes_fetched=ctx.bytes_fetched,
            measured_wh=gpu.wh,
            **meter.energy_options(cfg),
        )
        self.audit.log(
            "run",
            stop_reason=run.stop_reason,
            lang=run.lang,
            flagged=run.flagged,
            sources=run.sources,
            files=run.files,
            drafts=len(run.drafts),
            **run.report,
        )
        return run

    def _call(
        self,
        name: str,
        raw_args,
        gen: int,
        run: Run,
        ctx: Context,
        side_effects: int,
        forced: str | None = None,
        routed: set[str] | frozenset[str] = frozenset(),
        pre_notes: list[str] | None = None,
    ) -> tuple[Step, str]:
        """Validate, gate and execute one tool call. Returns the step record and the text given back to the model.

        ``forced`` is the user's answer to a confirmation asked in an earlier call of ``run`` (resume).
        ``pre_notes`` are the repairs already made to the name and arguments (``Agent._repair_calls``).
        """
        t0 = time.monotonic()
        step = Step(generation=gen, tool=name, arguments=raw_args if isinstance(raw_args, dict) else {})
        step.repairs.extend(pre_notes or [])
        args, err = guard.validate_args(name, raw_args, self.cfg.allowed_tools, step.repairs)
        if not err and name in routed:  # not offered for this request (route): calling it anyway is not allowed
            err = f"unknown tool '{name}': it is not available for this request"
        if self.hooks.on_step_start and forced is None:
            self.hooks.on_step_start(len(run.steps), str(name), step.arguments if err else args)
        if err:
            tail = "" if err.startswith("invalid arguments") else " Correct the call or answer without it."
            step.decision, step.error, result = "rejected", err, f"Error: {err}{tail}"
        else:
            step.arguments = args
            if name != "run_python" or self.cfg.allow_python:  # a switched-off tool only returns "not enabled"
                if forced is not None and name in guard.SIDE_EFFECT_TOOLS:
                    capped = side_effects >= self.cfg.max_side_effects
                    step.decision = "denied_cap" if capped else forced
                else:
                    step.decision = guard.gate(
                        name, args, tainted=run.flagged, side_effects=side_effects, cfg=self.cfg, confirm=self.confirm
                    )
            if step.decision == "pause":
                return step, ""
            if step.decision in DENIED:
                step.error = step.decision
                result = DENIED[step.decision]
            else:
                ctx.step_info = None
                try:
                    if name == "read_page" and run.flagged:
                        _check_untrusted_url(args.get("url"), ctx)
                    result = guard.defang(guard.redact(str(TOOLS[name](args, ctx))))
                    ctx.used.append(name)
                    if name in ("web_search", "read_page", "read_file"):
                        ctx.fetched.append(["file" if name == "read_file" else "web", result[:40_000]])
                    if guard.scan_injection(result):
                        step.flags.append("possible_injection")
                        step.flagged_excerpt = guard.injection_excerpt(result)
                        run.flagged = True
                    if name in guard.EXTERNAL_TOOLS:
                        result = guard.wrap_untrusted(result, run.lang)
                except guard.Blocked as e:
                    step.decision, step.error, result = (
                        "blocked",
                        str(e),
                        f"Error: blocked by the security policy ({e}).",
                    )
                except guard.ToolError as e:
                    step.error, result = str(e), f"Error: {e}"
                    if name == "read_file" and "not found" in str(e):
                        # name the files that exist, so the next call can be right (a 4B model otherwise retries
                        # the same wrong name)
                        names = repair.workspace_files(ctx.workspace)[:8]
                        if names:
                            result += " Files in the workspace: " + ", ".join(f'"{n}"' for n in names) + "."
                except Exception as e:  # a tool bug must never crash the run, nor leak a stack trace to the model
                    step.error = f"{type(e).__name__}: {guard.redact(str(e))[:200]}"
                    result = f"Error: the tool failed ({type(e).__name__})."
        if ctx.step_info:
            step.info, ctx.step_info = dict(ctx.step_info), None
        step.seconds = round(time.monotonic() - t0, 3)
        self.audit.log(
            "tool_call",
            tool=name,
            arguments=guard.short_args(step.arguments),
            repairs=step.repairs,
            seconds=step.seconds,
            chars=len(result),
            flags=step.flags,
            decision=step.decision,
            error=step.error,
        )
        return step, result
