"""Mode Agent: a small team of single-purpose generations around one deliverable (docs/HARNESS.md, section 11).

    route (code) -> brief (0-3 parallel specialists, checked in code) -> N=2 parallel drafts (one tool)
    -> deterministic checker -> 0-1 targeted fix -> the tool runs ONCE through Agent._call -> answer written by code

Why: a 4B model is reliable at one short, typed job at a time and unreliable at long free-form plans. vLLM batches
parallel requests on one GPU, so two drafts cost little more wall time than one, and a code checker picks the one that
carries the facts without inventing figures. Nothing here holds a side-effect tool except the final build step, which
goes through the same guard (validation, gate, audit) as the single agent, and can pause for a confirmation.
"""

from __future__ import annotations

import copy
import dataclasses
import itertools
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from birds.harness import crew_canvas, guard, meter
from birds.harness import crew_checks as cc
from birds.harness import crew_plan as cp
from birds.harness.agent import _HOWTO, _NEEDS_WEB, Hooks, Run, Step, _file_edit_ask
from birds.harness.config import Context
from birds.harness.crew_tools import (
    ANGLES,
    COST_MODEL,
    PLAN_SEARCH,
    PRODUCT,
    PROMPTS,
    RECORD_ACTIONS,
    RECORD_FACTS,
    RECORD_TABLE,
    SHAPE,
)
from birds.harness.llm import STOP, Cancelled, EndpointError, accepts
from birds.parse import parse_output
from birds.render import prompt as render_prompt
from birds.sources.identity import DEFAULT_SYSTEM

# ------------------------------------------------------------------ budget (spec section 5)
MAX_CONCURRENT = 4
_PAGE_LOCK = threading.Lock()
MAX_CALLS = 7
MAX_CALLS_GENERIC = 5
DRAFTS = 2
MAX_PAGES = 3
MORE_PAGES = 2  # pages of other sites read when the first ones gave fewer than 2 extracts
PAGE_CAP = 4000
TEXT_MIN = 300  # a page without a verified figure is a source of a document only with this much text
EXTRACT_CAP = 1500  # a page's extract given to the drafters of a document (3 pages: 4.5 kB of the shared prompt)
TOTAL_CAP = 12000
DEADLINE_S = 240.0
BRIEF_S = 90.0
DRAFTS_END_S = 190.0
FIX_MIN_LEFT = 45.0
RESERVE_S = 20.0
COLD_S = 120.0
STATE_CAP = 24_000
SLICE_CAP = 160_000  # a slice's signed state (compressed in the token: about a third of this)
SLICE_NEED_S = 110.0  # after the brief, less time than this left in the request: the writing goes to a new slice
LONG_PAGES = 5  # a long task (plan length « Approfondie », run in slices): pages read
LONG_TOTAL_CAP = 20000

_OFFICIAL = re.compile(
    r"(?:^|\.)(?:insee\.fr|gouv\.fr|dares\.travail-emploi\.gouv\.fr|ined\.fr|europa\.eu|banque-france\.fr|"
    r"service-public\.fr|urssaf\.fr|cre\.fr|ademe\.fr|oecd\.org|ecb\.europa\.eu|bpifrance\.fr)$",
    re.I,
)

# sources read last: forums, social networks, video and Q&A sites (a page there is rarely primary)
_LOW = re.compile(
    r"(?:^|\.)(?:reddit\.com|quora\.com|facebook\.com|linkedin\.com|x\.com|twitter\.com|youtube\.com|tiktok\.com|"
    r"pinterest\.\w+|instagram\.com|medium\.com|commentcamarche\.net|forum\.\w+|doctissimo\.fr)$",
    re.I,
)

# ------------------------------------------------------------------ routing (deterministic, own words only)

_DELIVERABLES = (
    ("make_slides", r"pr[ée]sentations?|diapos?\w*|slides?|pptx|powerpoint|decks?"),
    ("draft_email", r"e-?mails?|mails?|courriels?"),
    (
        "make_document",
        r"compte[- ]rendus?|rapports?|reports?|documents?|docx|notes? de synth[èe]se|memo|(?<!\d )minutes|"
        # a study the user names as a deliverable (« une étude comparative », « un dossier de veille », « un
        # benchmark »): a document, never « étude » or « dossier » alone (« le bureau d'études », « ce dossier »)
        r"[ée]tudes? (?:comparatives?|de march[ée]|sectorielles?|concurrentielles?)|benchmarks?|"
        r"(?:dossiers?|notes?|bulletins?) de veille|veille (?:concurrentielle|technologique|r[ée]glementaire|"
        r"sectorielle|strat[ée]gique)|comparative stud(?:y|ies)|market stud(?:y|ies)|white ?papers?|livres? blancs?",
    ),
    ("make_sheet", r"tableurs?|excel|xlsx|feuilles? de calcul|spreadsheets?"),
)
_FIGURES = re.compile(
    r"chiffr|statisti|donn[ée]es|%|[ée]volution|depuis\s+(?:l.an\s+)?(?:19|20)\d\d|\bco[ûu]ts?\b|budget|\bprix\b|"
    r"\bfigures?\b|\bstatistics\b|\bdata\b|since\s+(?:19|20)\d\d|\bcosts?\b|\bprices?\b",
    re.I,
)
_COMPARE = re.compile(r"compar|meilleur|recommand|choisir|arbitr|versus|\bvs\.?\b|\bbest\b|recommend|choose", re.I)
_ACTIONS = re.compile(r"compte[- ]rendu|\bminutes\b|\bactions?\b|tableau des actions|qui fait quoi|action items", re.I)
_ACTIONS_TABLE = re.compile(
    r"tableau des actions|actions?\s+(?:à|a)\s+mener|qui fait quoi|action items|\bactions\b", re.I
)
_SEQ = re.compile(r"\b(?:puis|ensuite|et enfin|then|and then|afterwards)\b", re.I)
_GREET = re.compile(
    r"^\s*(?:bonjour|bonsoir|salut|coucou|merci|ok|okay|d'accord|super|parfait|hello|hi|hey|thanks|thank you)\b", re.I
)
_RESEARCH = re.compile(r"\b(?:cherch|recherch|search|sourc|v[ée]rifi)", re.I)
# a study of what is out there: the public products, players or trends of a market, to be found on the web
_STUDY = re.compile(
    r"\b(?:veille|benchmarks?|[ée]tudes? (?:comparatives?|de march[ée]|sectorielles?|concurrentielles?)|comparatifs?|"
    r"(?:du|sur le|of the) march[ée]|acteurs du|leaders du|concurrents|[ée]tat de l.art|panorama|"
    r"comparative stud|market stud|competitors|state of the art|landscape|"
    r"avec (?:des |les |ses )?sources|sources? (?:officielles|fiables|r[ée]centes)|sourc[ée]e?s|with sources|sourced)",
    re.I,
)
# ... unless what is studied is the user's own (« un benchmark de nos fournisseurs actuels », « à partir de ces
# liens »), and only when asked for (« range ce dossier de veille », « qu'est-ce qu'un benchmark ? » are not asks)
_OWN_STUDY = re.compile(
    r"\b(?:veille|benchmarks?|comparatifs?|[ée]tudes? comparatives?)\s+(?:de|des|sur|of)\s+"
    r"(?:nos|notre|mes|mon|ma|our|my)\b|\b(?:[àa] partir d[eu]s?|d'apr[èe]s|based on|from)\s+"
    r"(?:ces|mes|nos|ce|cet|cette|this|these|my|our)\b",
    re.I,
)
_STUDY_NAME = (
    r"[ée]tudes? (?:comparatives?|de march[ée]|sectorielles?|concurrentielles?)|benchmarks?|comparatifs?|"
    r"(?:dossiers?|notes?|bulletins?) de veille|veille (?:concurrentielle|technologique|r[ée]glementaire|"
    r"sectorielle|strat[ée]gique)|comparative stud(?:y|ies)|market stud(?:y|ies)|panorama"
)
_ASK = re.compile(
    r"\b(?:fai[st]|r[ée]dige|r[ée]alise|pr[ée]pare|[ée]cri[st]|produi[st]|monte|dresse|[ée]labore|peux-tu|pourrais-tu|"
    r"j'ai besoin|il me faut|make|write|draft|prepare|produce|build|create|need)\w*",
    re.I,
)

RECIPES = {
    # auto: may start in Auto mode. Set by the live evaluation (docs/HARNESS.md, section 11); Activé ignores it.
    "deck_research": {"auto": True, "tool": "make_slides"},
    "compare_write": {"auto": True, "tool": None},  # draft_email or make_document, from the request
    "minutes_actions": {"auto": True, "tool": "make_document"},
    "doc_research": {"auto": True, "tool": "make_document"},  # studies, monitoring, reports with sources (live A/B 2026-11-27, docs/HARNESS.md)
    "sheet_pasted": {"auto": False, "tool": "make_sheet"},
    "deep_research": {"auto": True, "tool": None},  # explicit asks only (birds.harness.research.ask)
    "generic": {"auto": False, "tool": None},
}
REASONS = {
    "fr": {
        "deck_research": "présentation avec chiffres à sourcer",
        "compare_write": "comparaison de {n} offres puis rédaction",
        "minutes_actions": "compte rendu avec tableau des actions",
        "doc_research": "document avec chiffres à sourcer",
        "sheet_pasted": "tableur à partir de données collées",
        "generic": "plan, puis deux versions comparées",
        "deep_research": "recherche approfondie : plan, sources, vérification",
        "no_deliverable": "Rien à répartir : réponse en mode simple",
    },
    "en": {
        "deck_research": "a deck with figures to source",
        "compare_write": "{n} offers to compare, then writing",
        "minutes_actions": "minutes with an action table",
        "doc_research": "a document with figures to source",
        "sheet_pasted": "a spreadsheet from pasted data",
        "generic": "a plan, then two versions compared",
        "deep_research": "deep research: plan, sources, checks",
        "no_deliverable": "Nothing to split up: answered in simple mode",
    },
}


@dataclass
class Decision:
    recipe: str | None
    reason: str = ""
    mode: str = "auto"
    forced: bool = False
    deliverable: str | None = None
    signals: dict = field(default_factory=dict)
    no_deliverable: bool = False  # Activé with nothing to split up: single agent, and the chip says so


# « … : Devis 1 – Alpha 12 000 €, Devis 2 – Beta 10 500 € »: offers written on one line, one per line once split
_INLINE_ITEM = re.compile(
    r"[,;]\s+(?=(?i:devis|offre|offer|option|proposition|quote)\s+(?:(?i:n)[°o]\s*)?[A-Z\d]{1,2}\s*[:–—-])"
)


def split_request(own: str) -> tuple[str, str]:
    """(instruction, pasted text): the first paragraph is the request when more than 600 characters follow it, or
    the first line (or what comes before its first colon) when what follows is material of its own: two offers with
    a price, or an attendee list (« Compare ces devis et rédige un mail :\nDevis 1 – Alpha : 12 000 €\n… »)."""
    own = (own or "").strip()
    head, _, rest = own.partition("\n\n")
    if len(rest.strip()) > 600:
        return head.strip(), rest.strip()
    cut = min((i for i in (own.find("\n"), own.find(":")) if i > 0), default=-1)
    if cut > 0:
        head, rest = own[:cut].strip(), _INLINE_ITEM.sub("\n", own[cut + 1 :]).strip()
        if head and rest and (len(cc.offer_names(rest)) >= 2 or cc.roster(rest)):
            return head, rest
    return own, ""


def deliverable_kind(words: str) -> str | None:
    """The deliverable chosen in code from the user's own words: the first kind that matches, in a fixed order."""
    for tool, rx in _DELIVERABLES:
        if re.search(rf"\b(?:{rx})\b", words or "", re.I):
            return tool
    return None


def _kinds(words: str) -> set[str]:
    out = {tool for tool, rx in _DELIVERABLES if re.search(rf"\b(?:{rx})\b", words, re.I)}
    if _COMPARE.search(words):
        out.add("compare")
    if _ACTIONS_TABLE.search(words) and "make_document" in out:
        out.add("actions")
    if _RESEARCH.search(words):
        out.add("research")
    return out


# a deck or a document « sur le marché du vélo électrique en France avec des chiffres »: public figures, researched
_PUBLIC = re.compile(
    r"\b(?:march[ée]s?|markets?|secteurs?|industrie|chiffres? cl[ée]s|key figures|e-commerce|"
    r"en (?:France|Europe)|in (?:France|Europe))\b",
    re.I,
)
# the user's own figures (« avec ces chiffres : CA 2023 1,2 M€ », « nos chiffres 2025 »): nothing to research
_OWN_FIGURES = re.compile(
    r"\b(?:ces|nos|mes|notre|these|our|my)\s+(?:chiffres|donn[ée]es|r[ée]sultats|figures|data|results|numbers)\b", re.I
)


def signals(instr: str, pasted: str, attachments: int = 0) -> dict:
    deliverable = deliverable_kind(instr)
    is_pasted = bool(attachments) or bool(pasted)
    offers = cc.offer_names(pasted)
    names = cc.roster(pasted)
    kinds = _kinds(instr)
    study = (deliverable == "make_document" and bool(_STUDY.search(instr)) and bool(_ASK.search(instr))
             and not _OWN_STUDY.search(instr))  # fmt: skip
    verbs = len(
        re.findall(
            r"\b(?:compare|r[ée]dige|fais|fait|pr[ée]pare|cr[ée]e|cherche|r[ée]sume|write|make|draft)\w*", instr, re.I
        )
    )
    return {
        "deliverable": deliverable,
        "web": bool(_NEEDS_WEB.search(instr) or (_PUBLIC.search(instr) and _FIGURES.search(instr)) or study)
        and not is_pasted
        and not _OWN_FIGURES.search(instr),
        "figures": bool(_FIGURES.search(instr)),
        "study": study and not is_pasted,
        "pasted": is_pasted,
        "pasted_chars": len(pasted),
        "n_docs": attachments + (len(offers) if len(offers) >= 2 else 0),
        "offers": offers,
        "compare": bool(_COMPARE.search(instr)),
        "actions": bool(_ACTIONS.search(instr)) and bool(names),
        "steps": len(kinds) >= 2 or (bool(_SEQ.search(instr)) and verbs >= 2),
    }


def _simple(instr: str, sig: dict, attached: bool) -> bool:
    words = len(instr.split())
    return bool(
        (_GREET.search(instr) and words <= 8)
        or (words < 12 and not sig["deliverable"])
        or _HOWTO.search(instr)
        or _file_edit_ask(instr, attached)
    )


def _match(sig: dict) -> str | None:
    d = sig["deliverable"]
    if sig["pasted"] and sig["actions"] and d == "make_document":
        return "minutes_actions"
    if sig["pasted"] and sig["compare"] and sig["n_docs"] >= 2 and d in ("draft_email", "make_document"):
        return "compare_write"
    if d == "make_slides" and sig["web"] and sig["figures"]:
        return "deck_research"
    if d == "make_document" and sig["web"] and (sig["figures"] or sig["study"]):
        return "doc_research"
    if d == "make_sheet" and sig["pasted"] and sig["figures"]:
        return "sheet_pasted"
    return None


def decide(
    own: str,
    *,
    attachments: int = 0,
    images: int = 0,
    mode: str = "auto",
    resume: bool = False,
    lang: str = "fr",
    recipes: dict | None = None,
    history: bool = False,
) -> Decision:
    """Whether this request runs as a team, and which recipe. No model call: the user's own words only (pasted text
    counts for its size, its offers and its attendee list, never for the intent). ``history``: the conversation
    already has an answer; Auto then starts the team only for a request that stands on its own (its own pasted text
    or attachment, or a topic of its own), never for a follow-up that leans on earlier turns."""
    lang = "en" if lang == "en" else "fr"
    mode = mode if mode in ("auto", "on", "off") else "auto"
    recipes = recipes or RECIPES
    if mode == "off" or resume:
        return Decision(None, mode=mode)
    instr, pasted = split_request(own)
    sig = signals(instr, pasted, attachments)
    # ---- deep research (birds.harness.research): an explicit ask, or Activé on an informational question
    from birds.harness import research

    deep = research.ask(instr)
    if deep and not images and sig["deliverable"] in (None, "make_document") and recipes.get("deep_research"):
        if mode == "on" or recipes["deep_research"].get("auto"):
            return Decision("deep_research", research.REASON[lang][deep], mode, mode == "on", None, sig)
    if (mode == "on" and not images and not sig["deliverable"] and not _match(sig) and research.question(instr)
            and recipes.get("deep_research")):  # fmt: skip
        return Decision("deep_research", research.REASON[lang]["deep"], mode, True, None, sig)
    recipe = _match(sig)
    reason = REASONS[lang].get(recipe or "", "").format(n=max(2, len(sig["offers"]) or sig["n_docs"]))
    if mode == "on":
        if images and not instr.strip():
            return Decision(None, REASONS[lang]["no_deliverable"], mode, True, None, sig, no_deliverable=True)
        if recipe:
            return Decision(recipe, reason, mode, True, sig["deliverable"], sig)
        if sig["deliverable"]:
            return Decision("generic", REASONS[lang]["generic"], mode, True, sig["deliverable"], sig)
        return Decision(None, REASONS[lang]["no_deliverable"], mode, True, None, sig, no_deliverable=True)
    # Auto: never on images, a short email, a chat, a how-to, a follow-up edit
    if images or not recipe or not recipes.get(recipe, {}).get("auto") or _simple(instr, sig, bool(attachments)):
        return Decision(None, mode=mode, signals=sig)
    if sig["deliverable"] == "draft_email" and sig["pasted_chars"] <= 600 and not sig["compare"]:
        return Decision(None, mode=mode, signals=sig)
    heavy = [
        sig["steps"],
        sig["figures"] and sig["deliverable"] in ("make_slides", "make_document", "make_sheet"),
        sig["n_docs"] >= 2,
        sig["web"] and bool(sig["deliverable"]),
        sig["pasted_chars"] >= 1000 or sig["actions"],  # a long or structured paste (attendee list)
        sig["study"],  # a study of a market: research, then writing
    ]
    if sum(map(bool, heavy)) < 2:
        return Decision(None, mode=mode, signals=sig)
    if history and not standalone(instr, sig):
        return Decision(None, mode=mode, signals=sig)
    return Decision(recipe, reason, mode, False, sig["deliverable"], sig)


_TOPIC = re.compile(
    r"\b(?:sur|à propos de|concernant|au sujet de|about|on)\s+(?:l['’]|la |le |les |the )?[\wÀ-ÿ-]{4,}", re.I
)
_LEANS = re.compile(r"\b(?:refai[st]|reprend|modifi|corrig|ajoute|enl[eè]ve|retire|change|remplace|la m[êe]me|"
                    r"le m[êe]me|ce (?:document|mail|fichier)|cette (?:pr[ée]sentation|version)|redo|again|same)\w*",
                    re.I)  # fmt: skip


def standalone(instr: str, sig: dict) -> bool:
    """A request that carries what it needs: pasted text or an attachment, or a topic of its own (« une présentation
    sur l'emploi des seniors »), and no word that points back at an earlier answer (« refais », « la même »)."""
    if _LEANS.search(instr):
        return False
    return bool(sig["pasted"] or _TOPIC.search(instr))


_QUERY_OK = re.compile(r"^[\w\s'’\-À-ÿ.,&+/:]{4,90}$")


def checked_sub_questions(args: dict | None, request: str, limit: int = 5) -> list[tuple[str, str]]:
    """The (sub-question, web query) pairs of a ``plan_search`` call, each checked in code: the query has 2 to 10
    words, no URL or operator, is about the request (a long word of the request in it) and is no duplicate. Shared by
    the deliverable recipes and deep research (birds.harness.research)."""
    # about the request: a long word of it (compared on its first 5 letters: « France » is « française »), or one of
    # its acronyms (« AI Act », « PME »)
    req = {cc.fold(w)[:5] for w in re.findall(r"[\wÀ-ÿ]{5,}", request)}
    acronyms = {w for w in re.findall(r"\b[A-Z][A-Z0-9]{1,6}\b", request)}
    out, keys = [], set()
    for sq in ((args or {}).get("sub_questions") or [])[:limit]:
        if not isinstance(sq, dict):
            continue
        q = " ".join(str(sq.get("query") or "").replace('"', " ").split())
        words = q.split()
        key = " ".join(sorted(cc.fold(q).split()))
        if (not _QUERY_OK.match(q) or not 2 <= len(words) <= 10 or "http" in q.lower() or ":" in q
                or key in keys or not any((len(w) >= 5 and cc.fold(w)[:5] in req) or w in acronyms
                                          for w in words)):  # fmt: skip
            continue
        keys.add(key)
        out.append((cp.clean_line(sq.get("question"), 140) or q, q))
    return out


def team(agent, decision: Decision, **kw):
    """The team for this decision: deep research has its own recipe class (birds.harness.research)."""
    if decision.recipe == "deep_research":
        from birds.harness.research import Research

        return Research(agent, decision, **kw)
    return Crew(agent, decision, **kw)


# ------------------------------------------------------------------ the team

ROLES = {
    "chercheur": ("Recherche web", "Web search"),
    "lecteur": ("Lecture", "Reading"),
    "analyste": ("Calculs", "Computations"),
    "planificateur": ("Plan", "Plan"),
    "redacteur": ("Version", "Version"),
    "verificateur": ("Vérification", "Check"),
    "correcteur": ("Correction", "Fix"),
    "assembleur": ("Création du fichier", "Building the file"),
}
ABSTAIN = {
    "fr": {
        "no_facts": "Je n'ai trouvé aucun chiffre vérifiable dans les sources consultées : je préfère ne pas produire "
        "un fichier avec des chiffres inventés. Donnez-moi les chiffres ou une source, ou relancez en mode simple.",
        "default": "L'équipe d'agents n'a pas pu aboutir dans le temps imparti. Relancez la demande en mode simple.",
    },
    "en": {
        "no_facts": "I found no verifiable figure in the sources I read, so I would rather not produce a file with "
        "invented figures. Give me the figures or a source, or try again in simple mode.",
        "default": "The agent team could not finish in the time allowed. Try the request again in simple mode.",
    },
}
_COUNTRIES = (
    "france", "japon", "japan", "allemagne", "germany", "europe", "union europeenne", "ue", "eu", "etats-unis",
    "united states", "usa", "royaume-uni", "united kingdom", "italie", "italy", "espagne", "spain", "chine", "china",
    "monde", "world", "canada", "belgique", "suisse",
)  # fmt: skip


_COVER = re.compile(
    r"^(?:titre(?: de la pr[ée]sentation)?|title(?: slide)?|page de garde|couverture|merci\w*|remerciements?|"
    r"questions?|q\s*&\s*a|thank\w*|fin|the end)\b",
    re.I,
)
_GENERIC = re.compile(
    r"^(?:analyse|conclusions?|synth[èe]se|introduction|sommaire|agenda|plan|perspectives?|summary|overview|outlook)\s*$",
    re.I,
)


def _figures_in(slide: dict) -> int:
    return sum(bool(cc.figures(str(x))) for x in slide.get("bullets") or [])


def _filler(slide: dict, deck_title=None) -> bool:
    """A cover or closing slide (the file already has its own cover), or a generic « Analyse / Conclusion » slide
    that carries no figure."""
    t = " ".join(str(slide.get("title") or "").split()).strip(" .:!?")
    if not t or _COVER.match(t) or (deck_title and cc.fold(t) == cc.fold(deck_title)):
        return True
    return bool(_GENERIC.match(t)) and not _figures_in(slide)


def _fit_slides(slides: list[dict], n: int, deck_title=None) -> list[dict]:
    """The requested number of content slides: cover, thank-you and empty generic slides out; if still too many,
    the slides with the fewest figures go, from the end, order kept."""
    out = [x for x in slides if not _filler(x, deck_title)] or slides
    while len(out) > n:
        weakest = min(range(len(out)), key=lambda i: (_figures_in(out[i]), -i))
        out.pop(weakest)
    return out


class _Fallback(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Brief:
    tool: str
    instr: str
    pasted: str = ""
    n_slides: int = 6
    topic: str = ""
    to: str = ""
    facts: list = field(default_factory=list)  # [{"n", "year", "value", "fact"}]
    sources: list = field(default_factory=list)  # [{"n", "url", "title"}]
    extracts: list = field(default_factory=list)  # generic recipe: raw evidence windows [{"n", "text"}]
    table: dict | None = None
    costs: dict | None = None
    actions: list = field(default_factory=list)
    points: list = field(default_factory=list)
    must: list = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    blocks: dict = field(default_factory=dict)  # compare_write: offer name -> its pasted block
    emails: list = field(default_factory=list)  # every address written in the request or the pasted text
    allowed: set = field(default_factory=set)
    caveats: list = field(default_factory=list)
    dropped: int = 0
    study: bool = False  # a study of a market (doc_research): qualitative extracts go to the drafters too
    texts: dict = field(default_factory=dict)  # source n -> the extract read (citations are checked against it)
    allowed_by: dict = field(default_factory=dict)  # source n -> the figures of that page alone


@dataclass
class Draft:
    lane: str
    args: dict | None
    temperature: float
    score: dict = field(default_factory=dict)


def _compact_step(index: int, step: Step) -> dict:
    """A tool step as the confirmation state keeps it (signed, size-capped): enough for the memo and the titles."""
    return {"index": index, "tool": step.tool, "arguments": step.arguments, "result": (step.result or "")[:200],
            "seconds": round(float(step.seconds or 0.0), 2), "decision": step.decision, "error": step.error}  # fmt: skip


def _restore_step(s: dict) -> tuple[int, Step]:
    err = s.get("error")
    step = Step(generation=0, tool=str(s.get("tool") or ""),
                arguments=s.get("arguments") if isinstance(s.get("arguments"), dict) else {},
                result=str(s.get("result") or "")[:200], seconds=float(s.get("seconds") or 0.0),
                error=str(err) if err else None, decision=str(s.get("decision") or "allow"))  # fmt: skip
    step.chars = len(step.result)
    return _int(s.get("index"), 0), step


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class Crew:
    """One Mode Agent run. ``agent`` lends its model client, tokenizer, config, guard and tools (``Agent._call``);
    ``agent.hooks.on_agent`` receives the agent_* events and the crew's tool steps (``{"kind": "tool_start"|...}``)."""

    def __init__(
        self,
        agent,
        decision: Decision,
        *,
        system: str | None = None,
        thinking: bool = False,
        lang: str = "fr",
        deadline: float | None = None,
        attached: bool = False,
        plan: cp.Plan | None = None,
        notes: cp.NoteBox | None = None,
        run_id: str = "",
        slices: bool = False,
    ):
        self.agent, self.d, self.lang = agent, decision, ("en" if lang == "en" else "fr")
        # wave 2: the typed plan the user saw (and maybe edited), the instructions added while the team works, the
        # run id the browser sends them with, and whether this client continues a long task in slices
        self.plan, self.notes, self.run_id, self.slices = plan, notes, run_id, slices
        self.note_log: list[dict] = []
        self.removed_log: list[str] = []  # passages taken out of the drafts for want of a source (the card)
        self.final_sources: list[dict] | None = None
        self.cite_map: dict = {}
        self.slice_n = 0  # this request's slice number (0: the first request)
        self.lane_state: dict = {}  # lane -> its last status, for a slice resumed in another request
        self.carried_union = 0.0  # GPU time of the previous slices (their calls ran in other requests)
        self._late_findings: list = []  # notes about the writing that arrived after the drafts: the fix applies them
        self.excluded_n: set = set()
        self.llm, self.tok, self.cfg, self.hooks = agent.llm, agent.tok, agent.cfg, agent.hooks
        self.system = system or DEFAULT_SYSTEM[self.lang]
        self.thinking, self.attached = thinking, attached
        self.t0 = time.monotonic()
        self.deadline = min(self.t0 + DEADLINE_S, deadline if deadline is not None else float("inf"))
        self.lock, self.sem = threading.Lock(), threading.Semaphore(MAX_CONCURRENT)
        self.calls, self.active, self.peak = 0, 0, 0
        self.max_calls = MAX_CALLS_GENERIC if decision.recipe == "generic" else MAX_CALLS
        self.usage: list[dict] = []
        self.steps: list[tuple[int, Step]] = []
        self.index = 0
        self.flagged, self.found, self.bytes, self.images = False, [], 0, []
        self.lanes: list[dict] = []
        self.trace: dict = {}  # what the team did, for « Ce que l'équipe a fait » (counts only, no text)
        self.n_drafts = DRAFTS
        self.own = self.message = self.instr = self.pasted = self.history = ""
        self.docs: list[tuple[str, str]] = []
        self._last_progress: dict[str, float] = {}
        # a run resumed after a confirmation (Crew.resume): what the first request did, for the done event
        self.usage_carried: list[dict] = []
        self.carried_seconds = 0.0
        self.carried_agents: int | None = None

    # -------------------------------------------------------------- events
    def _emit(self, ev: dict) -> None:
        cb = getattr(self.hooks, "on_agent", None)
        if cb:
            cb(ev)

    def _label(self, lane: str) -> str:
        role, _, rest = lane.partition("_")
        fr, en = ROLES.get(role, (lane, lane))
        base = en if self.lang == "en" else fr
        if role == "redacteur":
            return f"{base} {rest.upper()}"
        if role == "lecteur" and rest.isdigit():
            return ("Reading page " if self.lang == "en" else "Lecture page ") + rest
        if role == "lecteur":
            what = {"make_document": ("des notes", "the notes")}.get(
                self.d.deliverable or "", ("des offres", "the offers")
            )
            if self.d.recipe == "minutes_actions":
                what = ("des notes", "the notes")
            elif self.d.recipe == "sheet_pasted":
                what = ("du tableau", "the table")
            return f"{base} {what[1] if self.lang == 'en' else what[0]}"
        return base

    def _step(self, lane: str, status: str, phase: str, **extra) -> None:
        ev = {"type": "agent_step", "id": lane, "role": lane.split("_")[0], "phase": phase, "status": status,
              "label": self._label(lane), **extra}  # fmt: skip
        if status != "running":
            self.lane_state[lane] = {k: ev[k] for k in ("phase", "status", "detail", "seconds", "tokens") if k in ev}
        self._emit(ev)

    def _start(self, lanes: list[tuple[str, str]]) -> None:
        """lanes: (id, group). Lanes of one group run side by side."""
        angles = ANGLES[self.lang].get(self._angle_key(self._tool_name() or ""), ("", ""))
        self.lanes = []
        for lane, group in lanes:
            item = {"id": lane, "role": lane.split("_")[0], "label": self._label(lane), "group": group}
            if lane.startswith("redacteur_"):
                item["detail"] = angles["ab".index(lane[-1])] if lane[-1] in "ab" else ""
            self.lanes.append(item)
        self._emit(
            {
                "type": "agent_start",
                "recipe": self.d.recipe,
                "reason": self.d.reason,
                "mode": self.d.mode,
                "forced": self.d.forced,
                "lanes": self.lanes,
                "budget": {"max_calls": self.max_calls, "max_seconds": round(self.deadline - self.t0)},
                **({"run": self.run_id} if self.run_id else {}),
                **({"plan": self.plan.public(self.lang)} if self.plan else {}),
                **({"slice": self.slice_n} if self.slice_n else {}),
            }
        )

    # -------------------------------------------------------------- one generation
    def _gen(
        self, lane, phase, messages, tools, max_tokens, *, temperature=None, seed=None, thinking=False, until=None
    ):
        """One specialist generation, or None (budget spent, no time left, endpoint error: the lane says so)."""
        with self.lock:
            if self.calls >= self.max_calls:
                self._step(lane, "skipped", phase, detail="budget")
                return None
            self.calls += 1
        deadline = min(until or self.deadline, self.deadline) - 5
        if deadline - time.monotonic() < 8:
            self._step(lane, "skipped", phase, detail="time")
            return None
        prompt = render_prompt(self.tok, messages, tools, thinking)
        self._step(lane, "running", phase, progress=0)
        seen = {"chars": 0}

        def on_token(piece: str) -> None:
            seen["chars"] += len(piece)
            now = time.monotonic()
            if now - self._last_progress.get(lane, 0) >= 0.4:
                self._last_progress[lane] = now
                tok = seen["chars"] // 4
                self._step(lane, "running", phase, progress=round(min(1.0, tok / max_tokens), 2), tokens=tok)

        extra = {}
        if self.cfg.cache_salt:
            extra["cache_salt"] = self.cfg.cache_salt
        if temperature is not None:
            extra["temperature"] = temperature
        if seed is not None:
            extra["seed"] = seed
        kw = {"on_token": on_token, "on_status": self.hooks.on_status, "deadline": deadline}
        if extra:
            kw["extra"] = extra
        if self.hooks.cancel is not None and accepts(self.llm.generate, "cancel"):
            kw["cancel"] = self.hooks.cancel
        with self.sem:
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            t0 = time.monotonic()
            try:
                out = self.llm.generate(prompt, max_tokens, STOP, **kw)
            except EndpointError as e:
                self._step(lane, "error", phase, detail=e.kind, seconds=round(time.monotonic() - t0, 1))
                return None
            finally:
                with self.lock:
                    self.active -= 1
            t1 = time.monotonic()
        u = {k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds", "busy_seconds", "first_token_seconds",
                                     "finish_reason", "cached_tokens", "prompt_chars", "completion_chars") if k in out}  # fmt: skip
        busy = float(out.get("busy_seconds") or out.get("seconds") or (t1 - t0))
        u.update(role=lane, t0=round(max(t0, t1 - busy) - self.t0, 3), t1=round(t1 - self.t0, 3))
        with self.lock:
            self.usage.append(u)
        text = out.get("text") or ""
        if thinking and "</think>" not in text:
            text = "<think>" + text + "</think>"
        parsed = parse_output(text)
        tokens = out.get("completion_tokens") or len(text) // 4
        return {"text": text, "parsed": parsed, "finish": out.get("finish_reason"), "tokens": tokens,
                "seconds": round(t1 - t0, 1)}  # fmt: skip

    @staticmethod
    def _args(gen: dict | None, name: str) -> dict | None:
        """The arguments of ``name`` in a generation: the parsed call, its JSON values repaired, or a salvage of a
        call cut by max_tokens."""
        if not gen:
            return None
        for c in gen["parsed"]["tool_calls"]:
            if c["name"] == name and isinstance(c["arguments"], dict):
                args = dict(c["arguments"])
                for k, v in list(args.items()):
                    if isinstance(v, str) and v.strip()[:1] in "[{":
                        fixed = cc.json_repair(v)
                        if fixed is not None:
                            args[k] = fixed
                return args
        raw = gen["text"]
        got = cc.salvage_items(raw, name)
        if got:
            return got
        m = re.search(r"<function=" + re.escape(name) + r">(.*)", raw, re.S)
        if m:  # parameters complete but the closing tags missing
            args = {}
            for key, val in re.findall(r"<parameter=([\w-]+)>\n?(.*?)(?:\n?</parameter>|$)", m.group(1), re.S):
                fixed = cc.json_repair(val) if val.strip()[:1] in "[{" else val.strip()
                if fixed is not None:
                    args[key] = fixed
            return args or None
        return None

    # -------------------------------------------------------------- one tool call, through the single agent's guard
    def _announce(self, lane: str, name: str, args: dict) -> int:
        """Number a tool call and announce it (in the caller's order, before any parallel run)."""
        with self.lock:
            index = self.index
            self.index += 1
        self._emit({"kind": "tool_start", "index": index, "tool": name, "arguments": args, "agent": lane})
        return index

    def _tools(self, lane: str, name: str, arg_list: list[dict]) -> list:
        """The same tool on several arguments, in parallel: numbered and announced in the given order (the activity
        feed and the read order stay those of the plan, whatever thread finishes first), results in that order."""
        started = [(self._announce(lane, name, a), a) for a in arg_list]
        return list(self.pool.map(lambda ia: self._tool(lane, name, ia[1], index=ia[0]), started))

    def _tool(self, lane: str, name: str, args: dict, *, forced: str | None = None, index: int | None = None):
        if index is None:
            index = self._announce(lane, name, args)
        ctx = Context(
            config=self.cfg,
            http=self.agent.http,
            search=self.agent.search,
            lang=self.lang,
            request=self.own,
            message=self.message,
            found=list(self.found),
            sources=[],
            images=list(self.images),  # web pictures the research saw: a deck or document may use the free ones
        )
        sub = Run(lang=self.lang, flagged=self.flagged)
        clone = copy.copy(self.agent)
        clone.hooks = Hooks()  # the crew reports its own steps (with the lane id)
        if name == "read_page":  # page parsing (lxml) crashed the process when run in parallel: one page at a time
            with _PAGE_LOCK:
                step, result = clone._call(name, args, 0, sub, ctx, 0, forced, frozenset())
        else:
            step, result = clone._call(name, args, 0, sub, ctx, 0, forced, frozenset())
        if step.decision == "pause":
            return index, step, "", ctx
        step.chars, step.result = len(result), result[:200]
        with self.lock:
            # a page only taints the run once its text is given to a model (see _research)
            self.flagged = self.flagged or (sub.flagged and name != "read_page")
            self.found += [u for u in ctx.found if u not in self.found]
            self.bytes += ctx.bytes_fetched
            self.images += [i for i in ctx.images if i not in self.images]
            self.steps.append((index, step))
        self._emit({"kind": "tool_end", "index": index, "step": step, "agent": lane})
        return index, step, result, ctx

    def _tool_name(self) -> str | None:
        tool = RECIPES.get(self.d.recipe or "", {}).get("tool")
        return tool or self.d.deliverable

    def _left(self) -> float:
        return self.deadline - time.monotonic()

    # -------------------------------------------------------------- wave 2: instructions added during the run
    # stages, in order: what a note can still change at each one
    _STAGES = ("research", "read", "drafts", "fix", "build")

    def _take_notes(self, stage: str, b: Brief | None = None) -> None:
        """Apply the instructions queued since the last generation, as typed edits of the plan, and say so in the
        activity feed. Called between generations only: a running generation is never changed."""
        if self.notes is None:
            return
        for n in self.notes.take() if stage != "end" else self.notes.close():
            self._apply_note(n, stage, b)

    def _apply_note(self, n: cp.Note, stage: str, b: Brief | None) -> None:
        plan = self.plan or cp.make_plan(self.d, self.instr, self.lang)
        at = self._STAGES.index(stage) if stage in self._STAGES else len(self._STAGES)
        writing = n.kind in ("audience", "length", "add_section", "focus")
        # what is too late: a site to prefer once the pages are read; a change of the writing once the versions are
        # written and no correction will run; anything once the file is being built
        late = (
            at >= self._STAGES.index("build")
            or (n.kind == "prefer_site" and at > self._STAGES.index("research"))
            or (writing and at >= self._STAGES.index("fix") and not self._fix_possible())
        )
        status = "late" if late else "applied"
        if not late:
            self.plan, _ = cp.apply_edits(plan, cp.note_edits(plan, n))
            if n.kind == "exclude_site" and b is not None:
                self._drop_site(b, n.value)
            if n.kind == "add_section" and b is not None:
                b.points.append(n.value)
            if writing and at >= self._STAGES.index("fix"):
                self._late_findings.append(n)
        entry = {"id": n.id, "kind": n.kind, "value": n.value, "status": status, "stage": stage}
        self.note_log.append(entry)
        self._emit({"type": "agent_note", **entry})

    def _fix_possible(self) -> bool:
        return self._left() > FIX_MIN_LEFT + RESERVE_S and not self._cold() and self.calls < self.max_calls

    def _drop_site(self, b: Brief, site: str) -> None:
        """A site the user excluded after its page was read: its facts, extracts and citations leave the brief."""
        gone = {s["n"] for s in b.sources if cp.matches(s.get("url") or "", [site])}
        if not gone:
            return
        b.sources = [s for s in b.sources if s["n"] not in gone]
        b.facts = [f for f in b.facts if f["n"] not in gone]
        b.extracts = [e for e in b.extracts if e["n"] not in gone]
        for k in gone:
            b.texts.pop(k, None)
            b.allowed_by.pop(k, None)
        b.must = [m for m in b.must if any(f["fact"] == m for f in b.facts)]
        b.allowed = cc.allowed_figures(self.instr, self.pasted, *(t for _, t in self.docs))
        for f in b.facts:
            b.allowed |= cc.allowed_figures(f["value"], f["fact"], f.get("quote", ""))
        for e in b.extracts:
            b.allowed |= cc.allowed_figures(e["text"])
        self.excluded_n |= gone

    # -------------------------------------------------------------- entry points
    def run(self, message: str, own: str, *, docs: list[tuple[str, str]] | None = None, history=None) -> Run:
        """``message``: the whole user message the model would get; ``own``: the user's own words (pasted text
        included, attachment notes excluded); ``docs``: (name, text) of attached documents; ``history``: the kept
        conversation messages (a compact digest of the last turn goes into the shared brief)."""
        self.message, self.own, self.docs = message, own, list(docs or [])
        self.history, self.kept = self._digest(history or []), list(history or [])
        self.instr, self.pasted = split_request(own)
        if not self.pasted and self.docs:
            self.pasted = "\n\n".join(f"{n}\n{t}" for n, t in self.docs)[:20000]
        return self._guarded(None)

    def _guarded(self, brief: Brief | None) -> Run:
        """The run (``brief`` None) or its next slice (the brief a previous request made), with the hand-overs."""
        self.pool = ThreadPoolExecutor(MAX_CONCURRENT, thread_name_prefix="bird-crew")
        try:
            self._start(self._plan())
            if brief is None:
                brief = getattr(self, "_brief_" + self.d.recipe)()
                if self.slices:
                    if self._slice_now():  # the writing goes to the next request: the client carries the state
                        return self._slice(brief)
                    self._emit({"kind": "slice", "state": self._state(brief), "auto": False})  # a checkpoint
            else:
                for lane, st in self.lane_state.items():  # the lanes the previous slice finished, as they ended
                    self._emit({"type": "agent_step", "id": lane, "role": lane.split("_")[0], "label": self._label(lane),
                                **st})  # fmt: skip
            return self._finish(brief)
        except Cancelled:
            raise
        except _Fallback as f:
            return self._fallback(f.reason, brief)
        except Exception as e:  # noqa: BLE001 - logged, then the single agent takes over
            self.agent.audit.log("crew_error", error=f"{type(e).__name__}: {guard.redact(str(e))[:200]}")
            return self._fallback("error", brief)
        finally:
            self.pool.shutdown(wait=False, cancel_futures=True)

    # -------------------------------------------------------------- wave 2: long tasks in resumable slices
    def _slice_now(self) -> bool:
        """After the brief: continue in a new request when the writing would not fit in this one, or when the plan
        asks for an in-depth deliverable (its research took this request; the writing gets a fresh one)."""
        if self.slice_n > 0:
            return False
        long = self.plan is not None and self.plan.length == "long"
        return long or self._left() < SLICE_NEED_S

    def _state(self, b: Brief) -> dict:
        """Everything the next slice needs, JSON only (signed by the web layer, carried by the browser)."""
        brief = dataclasses.asdict(b)
        brief["allowed"] = sorted(b.allowed)
        brief["texts"] = {str(k): v for k, v in b.texts.items()}
        brief["allowed_by"] = {str(k): sorted(v) for k, v in b.allowed_by.items()}
        elapsed = time.monotonic() - self.t0 + self.carried_seconds
        state = {"k": "crew_slice", "v": 1, "recipe": self.d.recipe, "reason": self.d.reason, "mode": self.d.mode,
                 "forced": self.d.forced, "deliverable": self.d.deliverable,
                 "study": bool((self.d.signals or {}).get("study")), "lang": self.lang, "run": self.run_id,
                 "slice": self.slice_n, "plan": self.plan.public(self.lang) if self.plan else None, "brief": brief,
                 "trace": self.trace, "calls": self.calls, "index": self.index, "bytes": self.bytes,
                 "flagged": self.flagged, "found": self.found[:40], "lanes": self.lane_state,
                 "usage": [{k: v for k, v in u.items() if k not in ("t0", "t1")} for u in self.usage_carried + self.usage],
                 "steps": [_compact_step(i, s) for i, s in sorted(self.steps, key=lambda x: x[0])],
                 "notes": self.note_log[-12:],
                 "carry": {"seconds": round(elapsed, 2), "gpu_union": round(self._union() + self.carried_union, 3)},
                 "message": self.message[:24000], "own": self.own[:24000], "instr": self.instr[:4000],
                 "history": self.history, "system": self.system[:8000], "thinking": self.thinking,
                 "attached": self.attached}  # fmt: skip
        size = len(json.dumps(state, ensure_ascii=False, default=str))
        if size > SLICE_CAP:
            state["steps"] = [{**s, "arguments": {}, "result": ""} for s in state["steps"]]
            state["brief"]["texts"] = {k: v[:2500] for k, v in brief["texts"].items()}
        return state

    def _slice(self, b: Brief) -> Run:
        state = self._state(b)
        self._emit({"kind": "slice", "state": state, "auto": True})
        run = Run(lang=self.lang, stop_reason="slice", flagged=self.flagged)
        run.state, run.usage = state, list(self.usage)
        run.steps = [s for _, s in sorted(self.steps, key=lambda x: x[0])]
        run.report = self._report()
        return run

    @classmethod
    def from_slice(cls, agent, state: dict, *, deadline: float | None = None, notes=None, history=None) -> Crew:
        """A crew rebuilt from a slice's state (verified by the web layer). ``continue_`` runs the next slice."""
        lang = "en" if state.get("lang") == "en" else "fr"
        recipe = state.get("recipe") if state.get("recipe") in RECIPES else "generic"
        d = Decision(recipe, str(state.get("reason") or ""), state.get("mode") if state.get("mode") in ("auto", "on")
                     else "on", bool(state.get("forced")), state.get("deliverable") if isinstance(state.get("deliverable"), str)
                     else None, {"study": bool(state.get("study"))})  # fmt: skip
        crew = cls(agent, d, system=str(state.get("system") or "") or None, thinking=bool(state.get("thinking")),
                   lang=lang, deadline=deadline, attached=bool(state.get("attached")),
                   plan=cp.from_public(state.get("plan")), notes=notes, run_id=str(state.get("run") or "")[:40],
                   slices=True)  # fmt: skip
        crew.slice_n = _int(state.get("slice"), 0) + 1
        crew.message, crew.own = str(state.get("message") or ""), str(state.get("own") or "")
        crew.instr, crew.pasted = split_request(crew.own)
        crew.history, crew.kept = str(state.get("history") or ""), list(history or [])
        crew.usage_carried = [u for u in state.get("usage") or [] if isinstance(u, dict)]
        crew.calls = _int(state.get("calls"), len(crew.usage_carried))
        crew.steps = [_restore_step(s) for s in state.get("steps") or [] if isinstance(s, dict)]
        crew.index = _int(state.get("index"), max((i for i, _ in crew.steps), default=-1) + 1)
        crew.bytes = _int(state.get("bytes"), 0)
        crew.flagged = bool(state.get("flagged"))
        crew.found = [u for u in state.get("found") or [] if isinstance(u, str)]
        crew.trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
        crew.lane_state = {k: v for k, v in (state.get("lanes") or {}).items() if isinstance(v, dict)}
        crew.note_log = [n for n in state.get("notes") or [] if isinstance(n, dict)]
        carry = state.get("carry") if isinstance(state.get("carry"), dict) else {}
        crew.carried_seconds = float(carry.get("seconds") or 0.0)
        crew.carried_union = float(carry.get("gpu_union") or 0.0)
        raw = state.get("brief") if isinstance(state.get("brief"), dict) else {}
        names = {f.name for f in dataclasses.fields(Brief)}
        b = Brief(**{k: v for k, v in raw.items() if k in names and k != "tool"}, tool=str(raw.get("tool") or
                                                                                         crew._tool_name() or "make_document"))  # fmt: skip
        b.allowed = {float(x) for x in raw.get("allowed") or []}
        b.texts = {int(k): str(v) for k, v in (raw.get("texts") or {}).items()}
        b.allowed_by = {int(k): {float(x) for x in v} for k, v in (raw.get("allowed_by") or {}).items()}
        crew._brief_state = b
        return crew

    def continue_(self) -> Run:
        return self._guarded(self._brief_state)

    HISTORY_CAP = 2000

    def _digest(self, history: list[dict]) -> str:
        """The previous request and answer (with its memo: tools, files, sources), at most HISTORY_CAP characters,
        so a follow-up such as « refais la présentation en 8 diapos » does not start from nothing."""
        last_a = next((m for m in reversed(history) if m.get("role") == "assistant" and m.get("content")), None)
        if last_a is None:
            return ""
        i = history.index(last_a)
        last_u = next((m for m in reversed(history[:i]) if m.get("role") == "user"), None)
        fr = self.lang == "fr"
        answer = str(last_a["content"])
        memo_at = max(answer.rfind("[Mémo de ce tour"), answer.rfind("[Memo of this turn"))
        memo = answer[memo_at:] if memo_at >= 0 else ""
        answer = (answer[:memo_at] if memo_at >= 0 else answer).strip()
        ask = " ".join(str((last_u or {}).get("content") or "").split())[:300]
        head = [("Demande précédente : " if fr else "Previous request: ") + ask] if ask else []
        room = self.HISTORY_CAP - sum(map(len, head)) - len(memo[:800]) - 40
        head.append(("Réponse précédente : " if fr else "Previous answer: ") + answer[: max(200, room)])
        if memo:
            head.append(memo[:800])
        return "\n".join(head)[: self.HISTORY_CAP]

    def _plan(self) -> list[tuple[str, str]]:
        r = self.d.recipe
        drafts = [("redacteur_a", "drafts"), ("redacteur_b", "drafts")]
        tail = [("verificateur", "check"), ("correcteur", "fix"), ("assembleur", "build")]
        if r in ("deck_research", "doc_research"):
            return [("chercheur", "research"), ("lecteur_1", "brief"), ("lecteur_2", "brief"), *drafts, *tail]
        if r == "compare_write":
            return [("lecteur", "brief"), ("analyste", "brief"), *drafts, *tail]
        if r == "minutes_actions":
            return [("lecteur", "brief"), *drafts, *tail]
        if r == "sheet_pasted":
            self.n_drafts = 1
            return [("lecteur", "brief"), ("redacteur_a", "drafts"), ("verificateur", "check"), ("assembleur", "build")]
        return [("planificateur", "plan"), ("chercheur", "research"), *drafts, *tail]

    def _user(self, data: str, instruction: str) -> list[dict]:
        return [{"role": "system", "content": self.system}, {"role": "user", "content": data + "\n\n" + instruction}]

    def _new_brief(self, tool: str) -> Brief:
        b = Brief(tool=tool, instr=self.instr, pasted=self.pasted)
        m = re.search(r"(\d{1,2})\s*(?:slides?|diapo\w*|diapositives?|pages?)", self.instr, re.I)
        b.n_slides = max(2, min(12, int(m.group(1)))) if m else 6
        if self.plan is not None and self.plan.n_slides and tool == "make_slides":
            b.n_slides = self.plan.n_slides  # the count the user set in the plan card
        if self.plan is not None:
            b.points += [x for x in self.plan.sections if x not in b.points]
        b.emails = cc.emails(self.instr + "\n" + self.pasted)
        b.to = (cc.emails(self.instr) or [""])[0]
        if not b.to and b.emails:  # « un mail à Nathalie » and the text gives nathalie.roux@…: that address
            firsts = [cc.fold(w) for w in re.findall(r"\b[A-ZÀ-Ý][a-zà-ÿ]{2,}", self.instr)]
            named = [e for e in b.emails if any(f and f in cc.fold(e.split("@")[0]) for f in firsts)]
            b.to = named[0] if named else (b.emails[0] if len(b.emails) == 1 else "")
        b.constraints = cc.constraints(self.instr + "\n" + cc.requirement_lines(self.pasted))
        b.allowed = cc.allowed_figures(self.instr, self.pasted, *(t for _, t in self.docs))
        return b

    # -------------------------------------------------------------- recipes: the brief
    def _topic(self) -> tuple[str, str, int | None]:
        own = self.instr
        m = re.search(r"\b(?:sur|à propos de|concernant|about|on)\s+(.+)", own, re.I)
        # « une étude comparative des 3 principaux CRM du marché »: what follows the deliverable's name
        m = m or re.search(rf"\b(?:{_STUDY_NAME})\s+(?:des |de la |du |de l['’]|de |d['’]|of (?:the )?)?(.+)", own, re.I)
        topic = m.group(1) if m else own
        topic = re.split(r"\s+(?:avec|pour|with|for|en\s+\d+\s+diapo)\b|[.?!\n]", topic)[0].strip()
        since = (
            int(m.group(1))
            if (m := re.search(r"(?:depuis|since|de|from)\s+(?:l.an\s+)?((?:19|20)\d\d)", own))
            else None
        )
        core = re.sub(r"^(?:l['’]|la |le |les |the )?(?:[ée]volution|histoire|[ée]tat|evolution|history)\s+"
                      r"(?:du |de la |des |de l['’]|de |of (?:the )?)?", "", topic, flags=re.I)  # fmt: skip
        core = re.sub(r"\s+(?:depuis|since|de|from)\s+(?:l.an\s+)?(?:19|20)\d\d.*$", "", core, flags=re.I).strip()
        return topic, core or topic, since

    def _plan_queries(self, topic: str, core: str, fallback: list[str]) -> list[str]:
        """Up to 3 web queries for the request's sub-questions, planned by the model in one short generation
        (``plan_search``), each checked in code: 2 to 10 words, no URL or operator, about the request (a long word
        of the request in it), no duplicate. Missing or invalid: the fixed queries. A site the plan prefers gets a
        ``site:`` query of its own."""
        fr = self.lang == "fr"
        instr = PROMPTS[self.lang]["search_plan"].format(topic=topic, year=time.localtime().tm_year)
        data = ("Demande : " if fr else "Request: ") + self.instr
        g = self._gen("chercheur", "research", self._user(data, instr), [PLAN_SEARCH], 260, temperature=0.0,
                      until=self.t0 + 25)  # fmt: skip
        args = self._args(g, "plan_search") or {}
        pairs = checked_sub_questions(args, self.instr + " " + core, 5)
        out, questions = [q for _, q in pairs], [sq for sq, _ in pairs]
        if g:
            self._step("chercheur", "running", "research", tokens=g["tokens"], questions=questions[:3])
        self.trace["planned"] = len(out[:3])
        queries = list(dict.fromkeys([*out[:3], *fallback]))[:3]  # the fixed queries fill what the plan lacks
        prefer = self.plan.prefer if self.plan is not None else []
        if prefer:  # the user's preferred site gets a query of its own (the engine reads « site: »)
            queries = [*queries[:2], f"{core} site:{prefer[0]}"]
        return queries

    def _research(self, lane: str, queries: list[str], since: int | None, head: list[str], pages: int,
                  *, need_figure: bool = True):  # fmt: skip
        """Searches in parallel, reads the top pages one site each (2 to 3 distinct sources, not three pages of one
        site), keeps evidence windows; when fewer than 2 pages gave an extract and time is left, reads up to
        MORE_PAGES more pages of other sites. 0 model calls."""
        self._step(lane, "running", "brief", detail=" · ".join(queries))
        results = self._tools(lane, "web_search", [{"query": q, "max_results": 5} for q in queries])
        rows = [re.findall(r"^\s+(https?://\S+)\s*$", text, re.M) for _, step, text, _ in results if not step.error]
        urls, seen = [], set()
        for row in itertools.zip_longest(*rows):  # the first result of each search, then the second...
            for u in row:
                if not u:
                    continue
                p = urlsplit(unquote(u))
                key = (p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), p.query)
                if key not in seen:
                    seen.add(key)
                    urls.append(u)
        if not urls:
            self._step(lane, "error", "brief", detail="no_results")
            raise _Fallback("no_results")
        site = lambda u: urlsplit(u).netloc.lower().removeprefix("www.")  # noqa: E731
        plan = self.plan
        if plan is not None and plan.exclude:  # never read a site the user excluded
            urls = [u for u in urls if not cp.matches(u, plan.exclude)]
            if not urls:
                self._step(lane, "error", "brief", detail="no_results")
                raise _Fallback("no_results")
        # primary and official sources first, then the engine's order; forums, social networks and video sites last
        prefer = plan.prefer if plan is not None else []
        rank = {u: (0 if cp.matches(u, prefer) else 1 if _OFFICIAL.search(site(u)) else 3 if _LOW.search(site(u))
                    else 2, i) for i, u in enumerate(urls)}  # fmt: skip
        urls = sorted(urls, key=rank.__getitem__)
        firsts, sites = [], set()
        for u in urls:
            if site(u) not in sites:
                sites.add(site(u))
                firsts.append(u)
        urls = firsts + [u for u in urls if u not in firsts]
        self.trace["queries"] = len(queries)
        windows, total = [], 0

        def keep(read) -> None:
            nonlocal total
            for _, step, text, _ in read:
                self.trace["read"] = self.trace.get("read", 0) + 1
                if step.error:
                    continue
                url = (re.search(r"^URL: (\S+)", text, re.M) or [None, step.arguments.get("url")])[1]
                title = (re.search(r"^Title: ([^\n]+)", text, re.M) or [None, ""])[1].strip()
                body = text.split("\n\n", 1)[-1]
                win = cc.evidence(body, head, since, PAGE_CAP, need_figure=need_figure)
                if win and any(cc.near_duplicate(win, w["text"]) for w in windows):
                    self.trace["dupes"] = self.trace.get("dupes", 0) + 1  # the same text on another site: one source
                    continue
                if win and total + len(win) <= (LONG_TOTAL_CAP if pages > MAX_PAGES else TOTAL_CAP):
                    windows.append(
                        {"url": url, "title": title or urlsplit(url).netloc, "text": win, "flagged": bool(step.flags)}
                    )
                    total += len(win)

        keep(self._tools(lane, "read_page", [{"url": u} for u in urls[:pages]]))
        have = {site(w["url"] or "") for w in windows}
        more = [u for u in urls[pages:] if site(u) not in have][:MORE_PAGES]
        if len(windows) < 2 and more and self._left() > BRIEF_S + 60:
            keep(self._tools(lane, "read_page", [{"url": u} for u in more]))
        self._step(
            lane, "done", "brief", detail=f"{len(windows)} page(s)", seconds=round(time.monotonic() - self.t0, 1)
        )
        return windows

    def _brief_deck_research(self, tool: str = "make_slides") -> Brief:
        b = self._new_brief(tool)
        doc = tool == "make_document"
        b.study = doc and bool((self.d.signals or {}).get("study"))
        topic, core, since = self._topic()
        b.topic = topic
        fr = self.lang == "fr"
        if b.study:  # what the market offers: a comparison or the trends, and this year's state
            compare = re.search(r"compar|benchmark|versus|\bvs\b|meilleur|best", self.instr, re.I)
            second = f"{core} comparatif" if fr and compare else f"{core} comparison" if compare else (
                f"{core} tendances" if fr else f"{core} trends")  # fmt: skip
            queries = [core, second, f"{core} {time.localtime().tm_year}"]
        else:
            queries = [core, f"{core} statistiques" if fr else f"{core} statistics"]
            if fr:
                queries.append(f"{core} INSEE")
        head = [w for w in re.findall(r"[\wÀ-ÿ]{5,}|\b[A-Z]{2,4}\b", core) if cc.fold(w) not in ("france", "monde")]
        head = head or [core]
        # sub-questions planned by the model (typed, checked in code); the fixed queries above are the safety net
        queries = self._plan_queries(topic, core, queries)
        self._take_notes("research", b)
        long = self.slices and self.plan is not None and self.plan.length == "long"
        windows = self._research("chercheur", queries, since, head, LONG_PAGES if long else MAX_PAGES,
                                 need_figure=not doc)  # fmt: skip
        self._take_notes("read", b)
        if self.plan is not None and self.plan.exclude:  # a site excluded while the pages were being read
            windows = [w for w in windows if not cp.matches(w["url"] or "", self.plan.exclude)]
        if not windows:
            raise _Fallback("no_facts")
        cold = self._cold()
        # official statistics first, then the richest extracts; page 1 has its own reader, pages 2 and 3 share one
        prefer = self.plan.prefer if self.plan is not None else []
        windows = sorted(windows, key=lambda w: (not cp.matches(w["url"] or "", prefer),
                                                 not _OFFICIAL.search(urlsplit(w["url"] or "").netloc),
                                                 -len(w["text"])))  # fmt: skip
        windows = windows[: 1 if cold else (LONG_PAGES if long else MAX_PAGES)]
        if any(w["flagged"] for w in windows):  # a flagged page whose text reaches a model taints the run
            self.flagged = True
        groups = [windows[:1], windows[1:]] if len(windows) > 1 else [windows]
        if len(groups) < 2:
            self._step("lecteur_2", "skipped", "brief")

        def extract(k_g):
            k, group = k_g
            lane = f"lecteur_{k + 1}"
            parts = [
                f"[{k + 1 + j}] {w['title']}\n{w['text']}" if len(group) > 1 else w["text"] for j, w in enumerate(group)
            ]
            data = guard.wrap_untrusted("\n\n".join(parts), self.lang)
            instr = PROMPTS[self.lang]["extract"].format(n=k + 1, topic=topic)
            g = self._gen(lane, "brief", self._user(data, instr), [RECORD_FACTS], 700 + 300 * (len(group) - 1),
                          temperature=0.0, until=self.t0 + BRIEF_S)  # fmt: skip
            args = self._args(g, "record_facts") or {}
            found, dropped = [], 0
            for f in args.get("facts") or []:  # each fact checked against each page of the group, kept on the first
                for w in group:
                    kept, _ = cc.check_facts([f], w["text"])
                    if kept:
                        found.append((w, kept[0]))
                        break
                else:
                    dropped += 1
            if g:
                self._step(lane, "done", "brief", tokens=g["tokens"], seconds=g["seconds"],
                           detail=f"{len(found)} chiffre(s) vérifié(s)" if self.lang == "fr" else f"{len(found)} verified figure(s)")  # fmt: skip
            return found, dropped

        per_page: dict[str, list] = {}
        for found, dropped in self.pool.map(extract, enumerate(groups)):
            b.dropped += dropped
            for w, f in found:
                per_page.setdefault(w["url"], []).append(f)
        n = 0
        # pages with a verified figure first; a document may also cite a page's text when it says enough
        for w in sorted(windows, key=lambda w: not per_page.get(w["url"])):
            kept = per_page.get(w["url"]) or []
            if not kept and (not doc or len(w["text"]) < TEXT_MIN):
                continue
            n += 1
            b.sources.append({"n": n, "url": w["url"], "title": w["title"]})
            b.texts[n] = w["text"]
            b.allowed_by[n] = cc.allowed_figures(w["text"])
            for f in kept:
                b.facts.append({"n": n, **f})
                figs = cc.allowed_figures(f["value"], f["fact"], f["quote"])
                b.allowed |= figs
                b.allowed_by[n] |= figs
            if doc:  # the page's own words: what a study or a report is written from (its figures are checked
                # against the page they come from, citation included)
                b.extracts.append({"n": n, "text": w["text"][:EXTRACT_CAP]})
                b.allowed |= cc.allowed_figures(w["text"][:EXTRACT_CAP])
        self.trace["facts"], self.trace["dropped"] = len(b.facts), b.dropped
        self.trace["sites"] = list(dict.fromkeys(urlsplit(src["url"] or "").netloc.removeprefix("www.") for src in b.sources))
        if not b.facts and not (doc and b.extracts):
            raise _Fallback("no_facts")
        # the points every draft must carry: one fact of each page in turn, so no source read is left unused
        by_n = [[f for f in b.facts if f["n"] == k] for k in range(1, n + 1)]
        mixed = [f for row in itertools.zip_longest(*by_n) for f in row if f]
        b.must = [f["fact"] for f in mixed[: b.n_slides]]
        if b.dropped:
            b.caveats.append(
                f"{b.dropped} chiffre(s) écarté(s) : valeur ou année absente de la même phrase de la page"
                if self.lang == "fr" else f"{b.dropped} figure(s) left out: value or year not in one sentence of the page"
            )  # fmt: skip
        return b

    def _brief_doc_research(self) -> Brief:
        return self._brief_deck_research("make_document")

    def _brief_compare_write(self) -> Brief:
        tool = self.d.deliverable if self.d.deliverable in ("draft_email", "make_document") else "draft_email"
        b = self._new_brief(tool)
        text = self.pasted
        b.points = cc.offer_names(text)

        def reader():
            g = self._gen("lecteur", "brief", self._user(text, PROMPTS[self.lang]["table"]), [RECORD_TABLE], 900,
                          temperature=0.0, until=self.t0 + BRIEF_S)  # fmt: skip
            args = self._args(g, "record_table") or {}
            cols, rows = args.get("columns"), args.get("rows")
            if not isinstance(cols, list) or not isinstance(rows, list):
                if g:
                    self._step("lecteur", "error", "brief", detail="table")
                return None
            whole, bad, in_text = cc.fold(text), 0, cc.allowed_figures(text)
            clean = []
            for r in rows:
                if not isinstance(r, list):
                    continue
                cells = []
                for c in r:
                    # words cannot be checked (the reader may rephrase them); every figure must be in the text
                    figs = cc.allowed_figures(str(c))
                    ok = cc.fold(c) in whole or all(any(abs(v - w) < 0.006 for w in in_text) for v in figs)
                    bad += not ok
                    cells.append(str(c) if ok else "?")
                clean.append(cells)
            self._step("lecteur", "done", "brief", tokens=g["tokens"], seconds=g["seconds"],
                       detail=f"{len(clean)} offre(s)" if self.lang == "fr" else f"{len(clean)} offer(s)")  # fmt: skip
            return {"columns": [str(c) for c in cols], "rows": clean, "bad": bad}

        parsed = cc.parse_offers(text)
        by_code = len(parsed) >= 2 and all(o["complete"] for o in parsed)

        def analyst():
            if by_code:  # every price, quantity and fee placed in code: no model call needed, nothing to misread
                costs = cc.compute_offers(parsed, b.constraints)
                v = costs["verdict"]
                detail = (f"calcul fait par Bird · retenue : {v['offer']}" if self.lang == "fr"
                          else f"computed by Bird · pick: {v['offer']}") if v else "—"  # fmt: skip
                self._step("analyste", "done", "brief", detail=detail)
                return costs, [], []
            g = self._gen("analyste", "brief", self._user(text, PROMPTS[self.lang]["analyst"]), [COST_MODEL], 900,
                          temperature=0.0, until=self.t0 + BRIEF_S)  # fmt: skip
            args = self._args(g, "cost_model") or {}
            offers = args.get("offers")
            if not isinstance(offers, list) or not offers:
                if g:
                    self._step("analyste", "error", "brief", detail="cost_model")
                return None, [], []
            offers, unchecked = self._reconcile([o for o in offers if isinstance(o, dict)], parsed)
            costs = cc.compute_offers(offers, b.constraints)
            missing = [ln for ln in cc.cost_coverage(offers, text) if not re.search(r"budget|contrainte", ln, re.I)]
            v = costs["verdict"]
            detail = (f"retenue : {v['offer']}" if self.lang == "fr" else f"pick: {v['offer']}") if v else "—"
            self._step("analyste", "done", "brief", tokens=g["tokens"], seconds=g["seconds"], detail=detail)
            return costs, missing, unchecked

        f_table, f_costs = self.pool.submit(reader), self.pool.submit(analyst)
        b.table = f_table.result()
        b.costs, missing, unchecked = f_costs.result()
        b.blocks = dict(cc.offer_blocks(text))
        if b.table is None and b.costs is None:
            raise _Fallback("no_brief")
        fr = self.lang == "fr"
        if b.costs:
            for r in b.costs["rows"]:
                b.allowed |= {round(r[k], 6) for k in ("monthly", "annual", "one_off", "year1", "term", "per_year")}
            v = b.costs["verdict"]
            if v:
                b.must = [v["offer"]]
            for ln in missing[:3]:
                b.caveats.append(("Poste non pris en compte dans le calcul : " if fr
                                  else "Line not used in the computation: ") + ln)  # fmt: skip
            for name in unchecked[:3]:
                b.caveats.append(f"Coûts de {name} lus par le modèle, non recalculés : à vérifier" if fr
                                 else f"Costs of {name} read by the model, not recomputed: to check")  # fmt: skip
            for o in parsed:
                for ln in o["variable"][:1]:
                    b.caveats.append((f"{o['name']} : coût à l'usage non chiffré (aucun volume dans le texte) — "
                                      if fr else f"{o['name']}: usage-based cost left out (no volume in the text) — ")
                                     + ln[:120])  # fmt: skip
        else:
            b.caveats.append("Calculs indisponibles : coûts à vérifier" if fr else "No computation: check costs")
        if b.table and b.table["bad"]:
            b.caveats.append(
                f"{b.table['bad']} valeur(s) du tableau introuvable(s) dans le texte"
                if self.lang == "fr" else f"{b.table['bad']} table value(s) not found in the text"
            )  # fmt: skip
        return b

    @staticmethod
    def _reconcile(offers: list[dict], parsed: list[dict]) -> tuple[list[dict], list[str]]:
        """The analyst's offers with every offer the code could read itself replaced by the code's version (its
        year-1 cost is then right even when the model multiplied a monthly total by the number of machines).
        Returns (offers, names of offers only the model read)."""
        out, unchecked, used = [], [], set()
        for o in offers:
            mine = next(
                (p for p in parsed if p["complete"] and cc.same_offer(p["name"], str(o.get("name") or ""))), None
            )
            if mine is not None:
                used.add(mine["name"])
                out.append(mine)
            else:
                out.append(o)
                unchecked.append(str(o.get("name") or "?"))
        out += [p for p in parsed if p["complete"] and p["name"] not in used]
        return out, unchecked

    def _brief_minutes_actions(self) -> Brief:
        b = self._new_brief("make_document")
        lines = cc.number_lines(self.pasted)
        names = cc.roster(self.pasted)
        notes = cc.numbered(lines)
        g = self._gen("lecteur", "brief", self._user(notes, PROMPTS[self.lang]["actions"]), [RECORD_ACTIONS], 900,
                      temperature=0.0, until=self.t0 + BRIEF_S)  # fmt: skip
        kept, dropped = cc.check_actions((self._args(g, "record_actions") or {}).get("actions"), lines, names)
        missing = [n for n in cc.action_lines(lines, names) if n not in {a["line"] for a in kept}]
        if missing and g and self._left() > 90:
            which = ", ".join(f"L{n}" for n in missing[:8])
            g2 = self._gen("lecteur", "brief", self._user(notes, PROMPTS[self.lang]["actions_repair"].format(lines=which)),
                           [RECORD_ACTIONS], 600, temperature=0.0, until=self.t0 + BRIEF_S)  # fmt: skip
            more, d2 = cc.check_actions((self._args(g2, "record_actions") or {}).get("actions"), lines, names)
            have = {(a["line"], a["owner"]) for a in kept}
            kept += [a for a in more if a["line"] in missing and (a["line"], a["owner"]) not in have]
            dropped += d2
        kept.sort(key=lambda a: a["line"])
        if g:
            self._step("lecteur", "done", "brief", tokens=g["tokens"], seconds=g["seconds"],
                       detail=f"{len(kept)} action(s) vérifiée(s)" if self.lang == "fr" else f"{len(kept)} checked action(s)")  # fmt: skip
        if not kept:
            raise _Fallback("no_brief")
        b.actions = kept
        b.points = [ln.strip(" -*•")[:160] for ln in lines if re.search(r"d[ée]cision|valid[ée]|accord", ln, re.I)][:6]
        if dropped:
            b.caveats.append(
                f"{dropped} action(s) proposée(s) écartée(s) : responsable absent de la ligne ou des présents"
                if self.lang == "fr" else f"{dropped} proposed action(s) left out: owner not on the line or the roster"
            )  # fmt: skip
        return b

    def _brief_sheet_pasted(self) -> Brief:
        b = self._new_brief("make_sheet")
        g = self._gen("lecteur", "brief", self._user(self.pasted, PROMPTS[self.lang]["table"]), [RECORD_TABLE], 900,
                      temperature=0.0, until=self.t0 + BRIEF_S)  # fmt: skip
        args = self._args(g, "record_table") or {}
        if isinstance(args.get("columns"), list) and isinstance(args.get("rows"), list):
            b.table = {"columns": args["columns"], "rows": args["rows"], "bad": 0}
            self._step("lecteur", "done", "brief", tokens=g["tokens"], seconds=g["seconds"])
        return b

    def _brief_generic(self) -> Brief:
        tool = self.d.deliverable or "make_document"
        b = self._new_brief(tool)
        data = (self.history + "\n\n" if getattr(self, "history", "") else "") + self.instr
        data += "\n\n" + self.pasted[:4000] if self.pasted else ""
        g = self._gen("planificateur", "brief", self._user(data, PROMPTS[self.lang]["planner"]), [], 400,
                      temperature=0.0, until=self.t0 + BRIEF_S)  # fmt: skip
        plan = cc.json_repair((g or {}).get("parsed", {}).get("content", "")) if g else None
        plan = plan if isinstance(plan, dict) else {}
        # a planner point with a figure the user never gave is the model's own arithmetic: not a point to check
        b.points = [str(p)[:160] for p in plan.get("points") or [] if str(p).strip()
                    and not cc.unsupported(str(p), b.allowed)][:8]  # fmt: skip
        searches = [str(q)[:120] for q in plan.get("recherches") or plan.get("searches") or [] if str(q).strip()][:3]
        if g:
            self._step("planificateur", "done", "brief", tokens=g["tokens"], seconds=g["seconds"],
                       detail=f"{len(b.points)} point(s)")  # fmt: skip
        if searches and self.agent.search is not None and not self.pasted:
            head = [w for w in re.findall(r"[\wÀ-ÿ]{5,}", searches[0])][:1]
            try:
                windows = self._research("chercheur", searches, None, head, 2)
            except _Fallback:
                windows = []
            for n, w in enumerate(windows, 1):
                b.sources.append({"n": n, "url": w["url"], "title": w["title"]})
                b.extracts.append({"n": n, "text": w["text"]})
                self.flagged = self.flagged or w["flagged"]
                b.allowed |= cc.allowed_figures(w["text"])
                b.texts[n], b.allowed_by[n] = w["text"], cc.allowed_figures(w["text"])
        else:
            self._step("chercheur", "skipped", "brief")
        return b

    def _cold(self) -> bool:
        """The endpoint woke up during this run and that took more than COLD_S: fewer calls from here on."""
        wait = max((float(u.get("seconds") or 0) - float(u.get("busy_seconds") or u.get("seconds") or 0)
                    for u in self.usage), default=0.0)  # fmt: skip
        return wait > COLD_S

    # -------------------------------------------------------------- drafts, check, fix
    def _shared(self, b: Brief) -> str:
        fr = self.lang == "fr"
        out = []
        if getattr(self, "history", ""):
            out.append(("Contexte de la conversation (tour précédent) :\n" if fr else "Conversation so far (last turn):\n")
                       + self.history)  # fmt: skip
        out.append(("Demande : " if fr else "Request: ") + b.instr)
        wants = cp.constraint_lines(self.plan, self.lang)
        if wants:  # the plan's typed choices, rendered from templates (never the user's raw text as an instruction)
            out.append(("Choix de l'utilisateur (à respecter) :\n" if fr else "The user's choices (to follow):\n")
                       + "\n".join(f"- {w}" for w in wants))  # fmt: skip
        c = b.constraints
        if c:
            bits = []
            if "budget_year" in c:
                bits.append(
                    ("budget annuel maximal " if fr else "max annual budget ") + cc.money(c["budget_year"], self.lang)
                )
            if "sla_hours" in c:
                bits.append(("intervention sous " if fr else "response within ") + f"{c['sla_hours']:g} h")
            if "months" in c:
                bits.append(("durée " if fr else "term ") + f"{c['months']} " + ("mois" if fr else "months"))
            out.append(("Contraintes : " if fr else "Constraints: ") + ", ".join(bits))
        if b.facts:
            out.append("Faits vérifiés :" if fr else "Verified facts:")
            out += [f"- ({f['year']}) {f['fact']} [{f['value']}] [{f['n']}]" for f in b.facts]
        if b.extracts:
            out.append("Extraits de sources :" if fr else "Source extracts:")
            out += [f"[{e['n']}] {e['text'][:3000]}" for e in b.extracts]
        if b.sources:
            out.append("Sources : " + " ; ".join(f"[{s['n']}] {s['title']}" for s in b.sources))
        if b.table:
            t = b.table
            out.append("Tableau des offres :" if fr else "Offers table:")
            out.append("| " + " | ".join(t["columns"]) + " |")
            out += ["| " + " | ".join(r) + " |" for r in t["rows"]]
        if b.costs:
            out.append("Calculs vérifiés (ne pas recalculer) :" if fr else "Verified computations (do not recompute):")
            for r in b.costs["rows"]:
                opt = f" + {r['option']}" if r["option"] else ""
                sla = f", délai {r['sla_hours']:g} h" if r["sla_hours"] else ""
                verdict = (
                    ("conforme" if fr else "compliant")
                    if r["ok"]
                    else (("non conforme : " if fr else "fails: ") + ", ".join(r["fails"]))
                )
                out.append(f"- {r['offer']}{opt} : {cc.money(r['monthly'], self.lang)}/mois, {cc.money(r['annual'], self.lang)}/an, "
                           f"1re année {cc.money(r['year1'], self.lang)}, {r['months']} mois {cc.money(r['term'], self.lang)}{sla} — {verdict}")  # fmt: skip
            v = b.costs["verdict"]
            if v:
                opt = f" avec {v['option']}" if v["option"] else ""
                out.append(f"Verdict : {v['offer']}{opt}, offre conforme la moins chère ({cc.money(v['year1'], self.lang)} la 1re année)."
                            if fr else f"Verdict: {v['offer']}{opt}, the cheapest compliant offer ({cc.money(v['year1'], self.lang)} in year 1).")  # fmt: skip
            else:
                out.append(
                    "Verdict : aucune offre ne respecte toutes les contraintes."
                    if fr
                    else "Verdict: no offer meets every constraint."
                )
        elif b.tool == "draft_email" and self.d.recipe == "compare_write":
            out.append(
                "Pas de calcul vérifié : ne donne aucun total." if fr else "No verified computation: give no total."
            )
        if b.actions:
            out.append("Actions vérifiées :" if fr else "Checked actions:")
            out.append(cc.actions_table(b.actions, self.lang))
        if b.to:
            out.append(("Destinataire : " if fr else "Recipient: ") + b.to)
        if b.points:
            out.append("Points à couvrir :" if fr else "Points to cover:")
            out += [f"- {p}" for p in b.points]
        if b.pasted and self.d.recipe in ("minutes_actions", "compare_write", "sheet_pasted", "generic"):
            out.append(("Texte fourni :\n" if fr else "Text provided:\n") + b.pasted[:8000])
        return "\n".join(out)

    def _shape(self, b: Brief) -> str:
        return SHAPE[self.lang][self._angle_key(b.tool)].format(n=b.n_slides)

    def _angle_key(self, tool: str) -> str:
        """A study of a market (doc_research with a study word) is drafted as a sourced comparison, not as notes."""
        study = tool == "make_document" and self.d.recipe == "doc_research" and (self.d.signals or {}).get("study")
        return "make_document_study" if study else tool

    def _valid(self, tool: str, args) -> dict | None:
        if not isinstance(args, dict):
            return None
        args.pop("_salvaged", None)
        ok, err = guard.validate_args(tool, args, self.cfg.allowed_tools, [])
        return None if err else ok

    def _drafts(self, b: Brief, shared: str) -> list[Draft]:
        tool = b.tool
        n = 1 if self._cold() else self.n_drafts
        if n < 2:
            self._step("redacteur_b", "skipped", "drafts")
        with self.lock:
            left = self.max_calls - self.calls
        if 0 < left < n:  # the budget left goes to the first versions, in order (never to whichever thread is first)
            for k in range(left, n):
                self._step("redacteur_" + "ab"[k], "skipped", "drafts", detail="budget")
            n = left
        angles = ANGLES[self.lang][self._angle_key(tool)]
        max_t = (900 if tool == "draft_email" else 1500) + (800 if self.thinking else 0)

        def one(k: int) -> Draft:
            lane = "redacteur_" + "ab"[k]
            instr = PROMPTS[self.lang]["draft"].format(shape=self._shape(b), angle=angles[k], tool=tool)
            if not b.sources:  # nothing to cite: no « [n] » asked for
                instr = re.sub(r" ?;[^.;]*\[n\][^.]*", "", instr)
            temp = (0.3, 0.7)[k]
            g = self._gen(lane, "drafts", self._user(shared, instr), [PRODUCT[tool]], max_t, temperature=temp,
                          seed=11 + k, thinking=self.thinking, until=self.t0 + DRAFTS_END_S)  # fmt: skip
            args = self._valid(tool, self._args(g, tool))
            if g:
                self._step(lane, "done" if args else "error", "drafts", tokens=g["tokens"], seconds=g["seconds"],
                           progress=1)  # fmt: skip
            return Draft(lane, args, temp)

        return list(self.pool.map(one, range(n)))

    def _structure(self, b: Brief, args: dict, text: str) -> tuple[float, list[str]]:
        fr, notes, checks = self.lang == "fr", [], []
        if b.tool == "make_slides":
            slides = args.get("slides") or []
            filler = [x for x in slides if _filler(x, args.get("title"))]
            ok = len(slides) == b.n_slides and not filler
            checks.append(ok)
            if not ok:
                notes.append(
                    f"il faut exactement {b.n_slides} diapositives de contenu, sans diapositive de titre, de "
                    "remerciements ni de diapositive générique sans chiffre" if fr else
                    f"exactly {b.n_slides} content slides are needed, no title, thank-you or generic slide without data"
                )  # fmt: skip
            fig = [x for s in slides for x in s.get("bullets") or [] if cc.figures(str(x))]
            cited = sum(bool(re.search(r"\[\d{1,2}\]\s*\W*$", str(x))) for x in fig)
            ok = not fig or not b.sources or cited / len(fig) >= 0.7
            checks.append(ok)
            if not ok:
                notes.append(
                    "termine chaque puce chiffrée par sa source [n]"
                    if fr
                    else "end every bullet with a figure with its source [n]"
                )
            if len(b.sources) >= 2:  # every page read that gave a verified fact is used at least once
                cited = {int(x) for x in re.findall(r"\[(\d{1,2})\]", json.dumps(slides, ensure_ascii=False))}
                ok = cited >= {src["n"] for src in b.sources}
                checks.append(ok)
                if not ok:
                    notes.append(
                        "utilise au moins un fait de chaque source " if fr else "use at least one fact of each source "
                    )
            facts = cc.fold(b.instr + " " + " ".join(f["fact"] + " " + f.get("quote", "") for f in b.facts))
            bad = []
            for s in slides:
                title = cc.fold(s.get("title") or "")
                for c in _COUNTRIES:
                    if re.search(rf"\b{re.escape(c)}\b", title) and not re.search(rf"\b{re.escape(c)}\b", facts):
                        bad.append(s.get("title"))
            checks.append(not bad)
            if bad:
                notes.append(("titre qui nomme un pays absent des faits : " if fr else "title naming a country absent from the facts: ")
                             + "; ".join(map(str, bad[:2])))  # fmt: skip
        elif b.tool == "draft_email":
            words = len(str(args.get("body") or "").split())
            checks.append(120 <= words <= 450)
            if not checks[-1]:
                notes.append("le mail doit faire 150 à 350 mots" if fr else "the email must be 150 to 350 words")
            v = (b.costs or {}).get("verdict")
            if v:
                ok = cc.fold(v["offer"]) in cc.fold(args.get("body"))
                checks.append(ok)
                if not ok:
                    notes.append(
                        f"recommande explicitement {v['offer']}" if fr else f"recommend {v['offer']} explicitly"
                    )
            if b.to:
                checks.append(any(b.to.lower() == str(t).lower() for t in args.get("to") or []))
        elif b.tool == "make_document":
            secs = args.get("sections") or []
            checks.append(len(secs) >= (3 if b.study else 2))
            if not checks[-1]:
                notes.append("structure le document en sections" if fr else "split the document into sections")
            if b.sources:  # a sourced document: its figures cited, every page read used
                body = "\n".join(str(x.get("content") or "") for x in secs)
                figs = [st for st in cc.sentences(body) if cc.figures(st)]
                cited = sum(bool(re.search(r"\[\d{1,2}\]", st)) for st in figs)
                checks.append(not figs or cited / len(figs) >= 0.7)
                if not checks[-1]:
                    notes.append("mets la source [n] après chaque chiffre" if fr else "put the source [n] after every figure")
                if len(b.sources) >= 2:
                    used = {int(x) for x in re.findall(r"\[(\d{1,2})\]", body)}
                    checks.append(used >= {src["n"] for src in b.sources})
                    if not checks[-1]:
                        notes.append("utilise au moins une information de chaque source " if fr
                                     else "use at least one piece of each source ")  # fmt: skip
            if b.study and re.search(r"\btableau|\btable\b|compar|benchmark", b.instr, re.I):
                checks.append(any(re.search(r"^\s*\|.+\|\s*$", str(x.get("content") or ""), re.M) for x in secs))
                if not checks[-1]:
                    notes.append("ajoute un tableau comparatif en markdown (| critère | … |)" if fr
                                 else "add a comparison table in markdown (| criterion | … |)")  # fmt: skip
        elif b.tool == "make_sheet":
            checks.append(bool(args.get("rows")))
        return (sum(checks) / len(checks) if checks else 1.0), notes

    @staticmethod
    def _bad(b: Brief, text: str) -> list[str]:
        """Figures to remove: not found in what was given or read, or a cost tied to an offer that is more than 5 %
        off what the harness computed for it."""
        uns = cc.unsupported(text, b.allowed)
        if b.costs:
            uns += [x for x in cc.cost_claims(text, b.costs, b.blocks) if x not in uns]
        return uns

    def _score(self, b: Brief, d: Draft) -> dict:
        text = cc.flat_text(d.args)
        missing_p = [p for p in b.points if not cc.covered(p, text)]
        missing_m = [m for m in b.must if not cc.covered(m, text)]
        uns = self._bad(b, text)
        structure, notes = self._structure(b, d.args, text)
        cites = cc.check_citations(text, b.texts, b.allowed_by) if b.texts else {"miscited": [], "weak": []}
        cov_p = 1 - len(missing_p) / len(b.points) if b.points else 1.0
        cov_m = 1 - len(missing_m) / len(b.must) if b.must else 1.0
        score = (2.0 * cov_p + 1.5 * cov_m + structure - 1.0 * len(uns) - 0.5 * len(cites["miscited"])
                 - min(1.0, 0.25 * len(cites["weak"])))  # fmt: skip
        return {"points": round(cov_p, 2), "must": round(cov_m, 2), "unsupported": len(uns), "structure": round(structure, 2),
                "score": round(score, 3), "missing_points": missing_p, "missing_must": missing_m, "bad": uns,
                "notes": notes, "words": len(text.split()), "miscited": cites["miscited"],
                "weak": cites["weak"]}  # fmt: skip

    @staticmethod
    def _rank(d: Draft):
        s = d.score
        return (s["unsupported"] == 0, s["score"], s["must"], -s["words"], -d.temperature)

    def _findings(self, b: Brief, s: dict) -> list[str]:
        fr, out = self.lang == "fr", []
        if s["missing_points"]:
            out.append(("points manquants : " if fr else "missing points: ") + " ; ".join(s["missing_points"][:4]))
        if s["missing_must"]:
            lines = []
            for m in s["missing_must"][:4]:
                f = next((f for f in b.facts if f["fact"] == m), None)
                lines.append(f"{m} [{f['n']}]" if f else m)
            out.append(("faits à intégrer : " if fr else "facts to include: ") + " ; ".join(lines))
        if s["bad"]:
            out.append(
                ("chiffres sans source à supprimer : " if fr else "unsourced figures to delete: ")
                + ", ".join(s["bad"][:6])
            )
        for m in s.get("miscited", [])[:3]:
            out.append(f"{m['value']} vient de la source [{m['source']}], pas [{m['cited'][0]}]" if fr
                        else f"{m['value']} comes from source [{m['source']}], not [{m['cited'][0]}]")  # fmt: skip
        for w in s.get("weak", [])[:2]:
            out.append((f"affirmation absente de la source [{w['cited'][0]}], à retirer ou à reformuler d'après elle : "
                        if fr else f"claim not in source [{w['cited'][0]}], remove it or rephrase it from the source: ")
                       + f"« {w['sentence'][:100]} »")  # fmt: skip
        out += s["notes"]
        return out

    def _public(self, s: dict) -> dict:
        return {k: s[k] for k in ("points", "must", "unsupported", "structure")}

    def _check_line(self, lane: str, s: dict, chosen: bool) -> str:
        name = self._label(lane)
        if self.lang == "fr":
            fig = "0 chiffre non sourcé" if not s["unsupported"] else f"{s['unsupported']} chiffre(s) non sourcé(s)"
            return f"{name} : {round(s['points'] * 100)} % des points, {fig}" + (" ✓ retenue" if chosen else "")
        fig = "0 unsourced figure" if not s["unsupported"] else f"{s['unsupported']} unsourced figure(s)"
        return f"{name}: {round(s['points'] * 100)}% of points, {fig}" + (" ✓ kept" if chosen else "")

    # -------------------------------------------------------------- post-processing and build
    def _left_out(self, b: Brief, s: dict) -> list[str]:
        """What the user should know is missing from the file, in plain words. Never the model's own planning
        points (a 4B planner's arithmetic, seen live as « dépasse le budget de 3 10 € »): only what the user gave
        or the team verified."""
        fr, out = self.lang == "fr", []
        if self.d.recipe == "compare_write":
            out += [("offre non mentionnée : " if fr else "offer not mentioned: ") + p for p in s["missing_points"]]
        elif self.d.recipe == "minutes_actions":
            out += [("décision non reprise : " if fr else "decision not included: ") + p[:120]
                    for p in s["missing_points"]]  # fmt: skip
        for m in s["missing_must"][:3]:
            if b.facts:
                out.append(("chiffre vérifié non repris : " if fr else "verified figure not used: ") + m[:120])
            elif self.d.recipe == "compare_write":
                out.append(("offre recommandée absente du texte : " if fr else "recommended offer missing: ") + m)
        return out

    def _post(self, b: Brief, args: dict, alts: list | None = None) -> tuple[dict, int]:
        """Unsupported figures removed, a Sources slide/section appended, the checked action table put in. A
        section left empty by the removals takes the same section of the other draft when that one is clean, or
        goes: a heading over nothing never reaches the file."""
        args, removed = copy.deepcopy(args), 0
        fr = self.lang == "fr"
        self.trace["recited"] = self.trace.get("recited", 0) + self._recite(b, args)
        if self.excluded_n:  # a site excluded after the drafts: the sentences that cite only it go
            args = self._without_sources(args, self.excluded_n)
        if b.texts:  # a figure written without its [n] gets the number of the page that holds it (code, not model)
            args, k = cc.autocite(args, b.allowed_by, b.instr + "\n" + b.pasted)
            self.trace["autocited"] = self.trace.get("autocited", 0) + k
        if not b.sources:  # no source was read: a « [3] » would point at nothing (seen live in a mail)
            args = json.loads(re.sub(r" ?\[\d{1,2}\]", "", json.dumps(args, ensure_ascii=False)))
        # citations made consistent: numbered in the order they first appear, the file lists the cited ones
        args, srcs, self.cite_map = cc.renumber(args, b.sources)
        if any(k != v for k, v in self.cite_map.items()):
            alts = [cc.apply_map(a, self.cite_map) for a in alts or []]
            self._remap(b, self.cite_map)
        if b.tool in ("make_slides", "make_document"):
            removed += self._clean_titles(b, args)
        cited = {int(x) for x in re.findall(r"\[(\d{1,2})\]", "\n".join(cc.deliverable_parts(args)))}
        self.final_sources = srcs
        src = [f"[{s['n']}] {s['title']} — {s['url']}" for s in srcs if not cited or s["n"] in cited]
        if b.tool == "make_slides":
            slides = []
            for s in args.get("slides") or []:
                keep = [x for x in s.get("bullets") or [] if not cc.unsupported(str(x), b.allowed)]
                removed += len(s.get("bullets") or []) - len(keep)
                self.removed_log += [str(x) for x in s.get("bullets") or [] if x not in keep]
                if keep:
                    slides.append({**s, "bullets": keep})
            slides = _fit_slides(slides, b.n_slides, args.get("title"))
            if src:  # the Sources slide comes on top of the requested count
                slides.append({"title": "Sources", "bullets": src})
            args["slides"] = slides or args.get("slides") or []
        elif b.tool == "make_document":
            secs = []
            for s in args.get("sections") or []:
                content = str(s.get("content") or "")
                if b.pasted:  # « janvier 2026 » for a training the notes put in janvier 2027
                    content, _ = cc.fix_years(content, b.instr + "\n" + b.pasted)
                if b.actions:
                    content = "\n".join(ln for ln in content.split("\n") if not ln.lstrip().startswith("|"))
                parts = re.split(r"(?<=[.!?])\s+|\n", content)
                keep = [p for p in parts if not self._bad(b, p)]
                removed += sum(1 for p in parts if p.strip()) - sum(1 for p in keep if p.strip())
                self.removed_log += [p for p in parts if p.strip() and p not in keep]
                text = "\n".join(p for p in keep if p.strip()) if removed else content
                if not text.strip():
                    text = self._clean_alt(b, s.get("heading"), alts)
                    if not text:
                        continue
                secs.append({**s, "content": text})
            if b.actions:
                table = {
                    "heading": "Actions" if not fr else "Tableau des actions",
                    "content": cc.actions_table(b.actions, self.lang),
                }
                at = next((i for i, s in enumerate(secs) if re.search(r"\baction", str(s.get("heading")), re.I)), None)
                nxt = next(
                    (
                        i
                        for i, s in enumerate(secs)
                        if re.search(r"prochaine|next meeting", str(s.get("heading")), re.I)
                    ),
                    None,
                )
                if at is not None:
                    secs[at] = {**secs[at], "content": table["content"]}
                elif nxt is not None:
                    secs.insert(nxt, table)
                else:
                    secs.append(table)
            if src:
                secs.append({"heading": "Sources", "content": "\n".join(src)})
            args["sections"] = secs
        elif b.tool == "draft_email":
            args["to"] = cc.fix_recipients(args.get("to"), b.emails, b.to)
            if b.to and not any(b.to.lower() == str(t).lower() for t in args.get("to") or []):
                args["to"] = [b.to]
            args["body"], _ = cc.strip_signature(str(args.get("body") or ""), self.own)
            if b.costs:  # a sentence with a wrong cost goes: a short true mail beats a long wrong one
                lines = []
                for ln in str(args.get("body") or "").split("\n"):
                    parts = re.split(r"(?<=[.!?])\s+", ln)
                    keep = [p for p in parts if not cc.cost_claims(p, b.costs, b.blocks)]
                    removed += len(parts) - len(keep)
                    self.removed_log += [p for p in parts if p not in keep]
                    if keep or not ln.strip():
                        lines.append(" ".join(keep))
                args["body"] = "\n".join(lines)
            if src:
                args["body"] = str(args.get("body") or "").rstrip() + "\n\nSources :\n" + "\n".join(src)
        return args, removed

    def _clean_titles(self, b: Brief, args: dict) -> int:
        """Titles and headings checked like the text (in place): an unsourced figure in « 37 % en télétravail » is
        taken out of the title (« Télétravail »), so a figure removed from a bullet never stays on the slide above
        it. Returns the titles changed; each one is listed on the card as removed."""
        fr, n = self.lang == "fr", 0

        def clean(title, fallback: str) -> str:
            nonlocal n
            title = str(title or "")
            bad = self._bad(b, title)
            if not bad:
                return title
            n += 1
            self.removed_log.append(title)
            return cc.drop_figures(title, bad) or fallback

        if args.get("title"):
            topic = cc.drop_figures(b.topic, self._bad(b, b.topic))
            args["title"] = clean(args["title"], topic or ("Présentation" if b.tool == "make_slides" else "Document"))
        for s in args.get("slides") or []:
            if s.get("title"):
                s["title"] = clean(s["title"], "Points clés" if fr else "Key points")
        for s in args.get("sections") or []:
            if s.get("heading"):
                s["heading"] = clean(s["heading"], "Détails" if fr else "Details")
        return n

    @staticmethod
    def _remap(b: Brief, m: dict) -> None:
        """The brief's source numbers after ``cc.renumber`` (the final checks read the renumbered deliverable)."""
        b.sources = sorted(({**x, "n": m.get(x["n"], x["n"])} for x in b.sources), key=lambda x: x["n"])
        b.facts = [{**f, "n": m.get(f["n"], f["n"])} for f in b.facts]
        b.extracts = [{**e, "n": m.get(e["n"], e["n"])} for e in b.extracts]
        b.texts = {m.get(k, k): v for k, v in b.texts.items()}
        b.allowed_by = {m.get(k, k): v for k, v in b.allowed_by.items()}

    @staticmethod
    def _without_sources(args: dict, gone: set) -> dict:
        """Sentences that cite only excluded sources removed (a sentence citing another source too keeps it)."""
        def keep(sent: str) -> bool:
            ns = {int(x) for x in re.findall(r"\[(\d{1,2})\]", sent)}
            return not ns or not ns <= gone

        def strip(text: str) -> str:
            text = re.sub(r" ?\[(\d{1,2})\]", lambda m: "" if int(m.group(1)) in gone else m.group(0), text)
            return text

        out = copy.deepcopy(args)
        for sl in out.get("slides") or []:
            sl["bullets"] = [strip(str(x)) for x in sl.get("bullets") or [] if keep(str(x))]
        for sec in out.get("sections") or []:
            lines = []
            for ln in str(sec.get("content") or "").split("\n"):
                lines.append(" ".join(strip(p) for p in re.split(r"(?<=[.!?])\s+", ln) if keep(p)))
            sec["content"] = "\n".join(lines)
        if out.get("body"):
            out["body"] = strip(str(out["body"]))
        return out

    @staticmethod
    def _recite(b: Brief, args: dict) -> int:
        """« 26 % [1] » when page 2 holds the 26 %: the right number, not a removal (in place). Returns the fixes."""
        if not b.texts:
            return 0
        miscited = cc.check_citations(cc.flat_text(args), b.texts, b.allowed_by)["miscited"]
        fixes = 0
        for sec in args.get("sections") or []:
            sec["content"], k = cc.recite(str(sec.get("content") or ""), miscited)
            fixes += k
        for sl in args.get("slides") or []:
            bullets = []
            for x in sl.get("bullets") or []:
                x, k = cc.recite(str(x), miscited)
                bullets.append(x)
                fixes += k
            sl["bullets"] = bullets
        return fixes

    def _clean_alt(self, b: Brief, heading, alts) -> str:
        """The content of the same section in another draft, if it carries no figure to remove."""
        h = cc.fold(heading or "")
        for a in alts or []:
            for sec in (a or {}).get("sections") or []:
                text = str(sec.get("content") or "").strip()
                if h and cc.fold(sec.get("heading") or "") == h and text and not self._bad(b, text):
                    return text
        return ""

    def _answer_ctx(self, b: Brief, args: dict, n_points: int = 0) -> dict:
        ctx = {
            "tool": b.tool,
            "recipe": self.d.recipe,
            "title": str(args.get("title") or args.get("subject") or "")[:200],
        }
        if b.tool == "make_slides":
            ctx["titles"] = [str(s.get("title") or "")[:80] for s in args.get("slides") or []][:14]
        if b.tool == "make_document":
            ctx["titles"] = [str(s.get("heading") or "")[:80] for s in args.get("sections") or []][:14]
        if b.tool == "draft_email":
            ctx["to"] = ", ".join(map(str, args.get("to") or []))[:200]
        if b.costs:
            v = b.costs["verdict"]
            ctx["verdict"] = None if not v else {"offer": v["offer"], "option": v["option"], "year1": v["year1"]}
            ctx["rows"] = [[r["offer"] + (f" + {r['option']}" if r["option"] else ""), r["annual"], r["year1"],
                            r["sla_hours"], r["ok"], r.get("fails") or []] for r in b.costs["rows"]][:8]  # fmt: skip
        ctx["n_actions"] = len(b.actions)
        ctx["n_sources"] = len(b.sources)
        return ctx

    def _answer(self, actx: dict, step: Step | None, caveats: list[str]) -> str:
        fr = self.lang == "fr"
        tool = actx["tool"]
        if step is None or step.error or step.decision.startswith("denied"):
            why = (step.error if step is not None else "") or ""
            head = (f"Je n'ai pas pu créer le fichier ({why})." if fr else f"I could not create the file ({why}).") if why else (
                "Je n'ai pas pu créer le fichier." if fr else "I could not create the file.")  # fmt: skip
            if step is not None and step.decision.startswith("denied"):
                head = (
                    "Action non réalisée : vous ne l'avez pas confirmée."
                    if fr
                    else "Action not performed: you did not confirm it."
                )
            lines = [head]
        elif tool == "make_slides":
            titles = [t for t in actx.get("titles", []) if t]
            content = [x for x in titles if x != "Sources"]
            extra = len(content) != len(titles)
            lines = [(f"La présentation « {actx['title']} » est prête : {len(content)} diapositives"
                      + (", plus une diapositive Sources." if extra else ".") if fr
                      else f"The deck “{actx['title']}” is ready: {len(content)} slides"
                      + (", plus a Sources slide." if extra else "."))]  # fmt: skip
            lines.append(" · ".join(titles))
        elif tool == "make_document":
            lines = [
                (f"Le document « {actx['title']} » est prêt." if fr else f"The document “{actx['title']}” is ready.")
            ]
            if actx.get("n_actions"):
                n = actx["n_actions"]
                lines.append(f"Il contient le tableau des {n} actions, avec responsable et échéance tels qu'écrits dans les notes."
                             if fr else f"It holds the table of the {n} actions, owner and due date as written in the notes.")  # fmt: skip
            else:
                lines.append(" · ".join(t for t in actx.get("titles", []) if t))
        elif tool == "draft_email":
            to = actx.get("to") or ("le destinataire" if fr else "the recipient")
            lines = [(f"Le brouillon de mail à {to} est prêt (rien n'est envoyé)." if fr
                      else f"The email draft to {to} is ready (nothing is sent).")]  # fmt: skip
        else:
            lines = ["Le fichier est prêt." if fr else "The file is ready."]
        if actx.get("rows") and step is not None and not step.error:
            v = actx.get("verdict")
            if v:
                opt = f" avec {v['option']}" if v["option"] and fr else (f" with {v['option']}" if v["option"] else "")
                lines.append(f"Recommandation : **{v['offer']}**{opt}, l'offre conforme la moins chère "
                              f"({cc.money(v['year1'], self.lang)} la 1re année)." if fr else
                              f"Recommendation: **{v['offer']}**{opt}, the cheapest compliant offer "
                              f"({cc.money(v['year1'], self.lang)} in year 1).")  # fmt: skip
            else:
                lines.append(
                    "Aucune offre ne respecte toutes les contraintes." if fr else "No offer meets every constraint."
                )
            head = (
                "| Offre | Annuel | 1re année | Délai | Conforme |"
                if fr
                else "| Offer | Annual | Year 1 | Response | Compliant |"
            )
            fails_en = {"budget": "budget", "délai": "response time", "durée": "term", "rétention": "retention",
                        "hébergement": "hosting"}  # fmt: skip

            def verdict(ok, why):
                if ok:
                    return "oui" if fr else "yes"
                why = [w if fr else fails_en.get(w, w) for w in why]
                return ("non" if fr else "no") + (f" ({', '.join(why)})" if why else "")

            rows = [f"| {r[0]} | {cc.money(r[1], self.lang)} | {cc.money(r[2], self.lang)} | "
                    f"{f'{r[3]:g} h' if r[3] else '—'} | {verdict(r[4], r[5] if len(r) > 5 else [])} |"
                    for r in actx["rows"]]  # fmt: skip
            lines.append("\n".join([head, "|---|---|---|---|---|", *rows]))
            lines.append(
                "Calculs faits par Bird à partir des montants du texte."
                if fr
                else "Computed by Bird from the amounts in the text."
            )
        if actx.get("n_sources") and step is not None and not step.error and not step.decision.startswith("denied"):
            n = actx["n_sources"]
            what = "Les informations" if actx.get("recipe") == "doc_research" else "Les chiffres"
            what_en = "The information" if actx.get("recipe") == "doc_research" else "The figures"
            lines.append(f"{what} viennent de {n} source(s) vérifiée(s), citées [n] et listées à la fin."
                         if fr else f"{what_en} come from {n} checked source(s), cited [n] and listed at the end.")  # fmt: skip
        if actx.get("team") and step is not None and not step.error and not step.decision.startswith("denied"):
            lines.append(("**Ce que l'équipe a fait** :\n" if fr else "**What the team did**:\n")
                         + "\n".join(f"- {x}" for x in actx["team"][:5]))  # fmt: skip
        if caveats:
            lines.append(("**À vérifier** :\n" if fr else "**To check**:\n") + "\n".join(f"- {c}" for c in caveats[:6]))
        return "\n\n".join(x for x in lines if x)

    def _stream(self, text: str) -> None:
        if self.hooks.on_token:
            for piece in re.findall(r"\S+\s*|\s+", text):
                self.hooks.on_token(piece)

    def _finish(self, b: Brief) -> Run:
        self._take_notes("drafts", b)
        shared = self._shared(b)
        drafts = [d for d in self._drafts(b, shared) if d.args]
        if not drafts:
            raise _Fallback("no_draft")
        self._step("verificateur", "running", "check")
        for d in drafts:
            d.score = self._score(b, d)
        drafts.sort(key=self._rank, reverse=True)
        best = drafts[0]
        for d in drafts:
            self._step(d.lane, "scored", "check", score=self._public(d.score), chosen=d is best)
        self._step("verificateur", "done", "check", detail=self._check_line(best.lane, best.score, True),
                   chosen=best.lane, score=self._public(best.score))  # fmt: skip
        self._take_notes("fix", b)
        findings = self._findings(b, best.score) + [f for f in map(self._note_finding, self._late_findings) if f]
        fixed = False
        if (
            findings
            and self._left() > FIX_MIN_LEFT + RESERVE_S
            and not self._cold()
            and any(ln["id"] == "correcteur" for ln in self.lanes)
        ):
            instr = PROMPTS[self.lang]["fix"].format(draft=json.dumps(best.args, ensure_ascii=False)[:6000],
                                                      findings=" ; ".join(findings), tool=b.tool)  # fmt: skip
            g = self._gen("correcteur", "fix", self._user(shared, instr), [PRODUCT[b.tool]],
                          (900 if b.tool == "draft_email" else 1500), temperature=0.0, until=self.deadline - RESERVE_S)  # fmt: skip
            args = self._valid(b.tool, self._args(g, b.tool))
            if args:
                cand = Draft("correcteur", args, 0.0)
                cand.score = self._score(b, cand)
                keep = (
                    cand.score["score"] >= best.score["score"]
                    and cand.score["unsupported"] <= best.score["unsupported"]
                )
                self._step("correcteur", "done", "fix", tokens=g["tokens"], seconds=g["seconds"], score=self._public(cand.score),
                           chosen=keep, detail=("correction retenue" if keep else "version d'origine gardée") if self.lang == "fr"
                           else ("fix kept" if keep else "original kept"))  # fmt: skip
                if keep:
                    best, fixed = cand, True
            elif g:
                self._step("correcteur", "error", "fix")
        else:
            self._step("correcteur", "skipped", "fix")
        kept_lane = best.lane
        best, merged = self._merge(b, best, drafts)
        if merged:
            fr = self.lang == "fr"
            other = self._label(merged["from"])
            self._step("verificateur", "done", "check", chosen=kept_lane, merged=merged["from"], score=self._public(best.score),
                       detail=self._check_line(kept_lane, best.score, True)
                       + (f" · complétée par {merged['parts']} partie(s) de {other}" if fr
                          else f" · completed with {merged['parts']} part(s) of {other}"))  # fmt: skip
        args, removed = self._post(b, best.args, alts=[d.args for d in drafts if d is not best and d.args])
        self.trace.update(drafts=len(drafts), chosen=kept_lane, merged=merged, fixed=fixed, removed=removed)
        caveats = list(b.caveats)
        if removed:
            caveats.insert(0, f"{removed} passage(s) avec un chiffre sans source retiré(s)" if self.lang == "fr"
                           else f"{removed} passage(s) with an unsourced figure removed")  # fmt: skip
        final = self._score(b, Draft(best.lane, args, 0.0))
        caveats += self._left_out(b, final)[:3]
        for w in final.get("weak", [])[:2]:  # a claim the cited page does not hold: said, never silently shipped
            caveats.append(f"affirmation non retrouvée dans la source [{w['cited'][0]}] : « {w['sentence'][:110]} »"
                            if self.lang == "fr" else
                            f"claim not found in source [{w['cited'][0]}]: “{w['sentence'][:110]}”")  # fmt: skip
        if b.tool == "draft_email" and best.score["bad"]:
            caveats.append(("chiffres à vérifier dans le mail : " if self.lang == "fr" else "figures to check in the email: ")
                           + ", ".join(best.score["bad"][:6]))  # fmt: skip
        actx = self._answer_ctx(b, args)
        actx["team"] = self._team_lines(b)
        self._emit_checks(b, args, final)
        self._take_notes("end", b)  # what arrives now is too late for this deliverable: said in the feed
        run = self._build(b.tool, args, actx, caveats, b.sources, chosen=kept_lane, fixed=fixed)
        run.widgets = [*getattr(run, "widgets", []), *self._modules(b)]
        return run

    def _modules(self, b: Brief) -> list[dict]:
        """Cards of what the harness computed or checked: the offers' matrix, the minutes' action items."""
        from birds.harness import modules

        out = [modules.matrix_from_costs(b.costs, self.lang), modules.checklist_from_actions(b.actions, self.lang)]
        return [w for w in out if w]

    def _note_finding(self, n: cp.Note) -> str:
        """A note about the writing that arrived after the drafts, as an instruction of the correction (a template
        around the typed value)."""
        fr = self.lang == "fr"
        if n.kind == "add_section":
            return (f"ajoute une section « {n.value} » à partir des faits ci-dessus" if fr
                    else f"add a section “{n.value}” from the facts above")  # fmt: skip
        if n.kind == "focus":
            return f"mets l'accent sur « {n.value} »" if fr else f"put the emphasis on “{n.value}”"
        line = cp.RENDER[self.lang][n.kind][n.value]
        return (("adapte le texte : " if fr else "adapt the text: ") + line) if line else ""

    def _emit_checks(self, b: Brief, args: dict, final: dict) -> None:
        """The « Vérifications faites » card: every figure of the deliverable with its source line and status, from
        the checks already run (code only)."""
        computed = []
        for r in (b.costs or {}).get("rows") or []:
            computed += [r.get(k) for k in ("monthly", "annual", "year1", "term") if isinstance(r.get(k), int | float)]
        led = cc.ledger(args, texts=b.texts, allowed_by=b.allowed_by, request=b.instr + "\n" + b.pasted,
                        computed=computed, removed=self.removed_log, weak=final.get("weak") or [],
                        sources=b.sources)  # fmt: skip
        actions = [{"owner": a.get("owner", ""), "action": str(a.get("action", ""))[:140], "due": a.get("due", ""),
                    "line": a.get("line")} for a in b.actions][:20]  # fmt: skip
        self._emit({"type": "agent_checks", **led, "read_dropped": b.dropped, "actions": actions,
                    "costs": len((b.costs or {}).get("rows") or []),
                    "sources": [{"n": x["n"], "title": str(x.get("title") or "")[:120],
                                 "site": urlsplit(str(x.get("url") or "")).netloc.removeprefix("www.")}
                                for x in b.sources]})  # fmt: skip

    def _merge(self, b: Brief, best: Draft, drafts: list[Draft]) -> tuple[Draft, dict | None]:
        """When both versions are clean, the kept one completed with the best parts of the other instead of picking
        one: a section (or a slide) of the other that carries a verified fact or a point the kept one misses, or the
        comparison table it lacks. The result must score at least as well, with no more unsourced figures."""
        if b.tool not in ("make_document", "make_slides") or best.score.get("unsupported"):
            return best, None
        other = next((d for d in drafts if d is not best and d.lane != best.lane and d.args
                      and not d.score.get("unsupported")), None)  # fmt: skip
        if other is None:
            return best, None
        missing = list(best.score["missing_must"]) + list(best.score["missing_points"])
        args, added = copy.deepcopy(best.args), 0
        theirs = copy.deepcopy(other.args)
        # what is borrowed comes with its right source number
        wrong = cc.check_citations(cc.flat_text(theirs), b.texts, b.allowed_by)["miscited"] if b.texts else []
        recited = 0

        def fix(text: str) -> str:
            nonlocal recited
            text, k = cc.recite(text, wrong)
            recited += k
            return text
        table = re.compile(r"^\s*\|.+\|\s*$", re.M)
        if b.tool == "make_document":
            secs = args.get("sections") or []
            heads = {cc.fold(x.get("heading")) for x in secs}
            has_table = any(table.search(str(x.get("content") or "")) for x in secs)
            end = r"conclusion|recommand|synth[eè]se|sources?$|next steps|recommend|summary"
            tail = next((i for i, x in enumerate(secs) if re.search(end, str(x.get("heading") or ""), re.I)), len(secs))
            for sec in theirs.get("sections") or []:
                content, h = str(sec.get("content") or ""), cc.fold(sec.get("heading"))
                if added >= 2 or not content.strip() or h in ("source", "sources") or self._bad(b, content):
                    continue
                brings = [m for m in missing if cc.covered(m, content)]
                if h not in heads and (brings or (b.study and not has_table and table.search(content))):
                    secs.insert(tail, {**sec, "content": fix(content)})
                    tail, added, has_table = tail + 1, added + 1, has_table or bool(table.search(content))
                elif h in heads and brings:  # the same section: only the sentences that bring what is missing
                    same = next(x for x in secs if cc.fold(x.get("heading")) == h)
                    extra = [st for st in cc.sentences(content) if any(cc.covered(m, st) for m in brings)
                             and not self._bad(b, st) and st.strip() not in str(same.get("content") or "")]  # fmt: skip
                    if not extra:
                        continue
                    same["content"] = str(same.get("content") or "").rstrip() + "\n" + fix(" ".join(extra))
                    added += 1
                missing = [m for m in missing if m not in brings]
            args["sections"] = secs
        else:  # a slide of the other version that carries a missing fact replaces one that carries none
            slides = args.get("slides") or []
            for sl in theirs.get("slides") or []:
                text = " ".join(map(str, sl.get("bullets") or []))
                brings = [m for m in missing if cc.covered(m, text)]
                if added >= 2 or not brings or self._bad(b, text):
                    continue
                weak = [i for i, x in enumerate(slides) if not any(cc.covered(m, " ".join(map(str, x.get("bullets") or [])))
                                                                    for m in b.must)]  # fmt: skip
                if not weak:
                    break
                slides[weak[-1]] = {**sl, "bullets": [fix(str(x)) for x in sl.get("bullets") or []]}
                added += 1
                missing = [m for m in missing if m not in brings]
            args["slides"] = slides
        if not added:
            return best, None
        cand = Draft(best.lane, args, best.temperature)
        cand.score = self._score(b, cand)
        if cand.score["unsupported"] > best.score["unsupported"] or cand.score["score"] < best.score["score"]:
            return best, None
        self.trace["recited"] = self.trace.get("recited", 0) + recited
        return cand, {"from": other.lane, "parts": added}

    def _team_lines(self, b: Brief) -> list[str]:
        """« Ce que l'équipe a fait »: counts written by code (searches, pages, figures checked, versions, what the
        checker changed), never a model's words."""
        fr, t, out = self.lang == "fr", self.trace, []
        if t.get("queries"):
            sites = t.get("sites") or []
            out.append((f"Recherche : {t['queries']} recherche(s), {t.get('read', 0)} page(s) lue(s)" if fr
                        else f"Research: {t['queries']} search(es), {t.get('read', 0)} page(s) read")
                       + (f", {len(sites)} source(s) retenue(s) ({', '.join(sites)})" if fr and sites
                          else f", {len(sites)} source(s) kept ({', '.join(sites)})" if sites else ""))  # fmt: skip
        if "facts" in t:
            d = t.get("dropped") or 0
            out.append((f"Lecture : {t['facts']} chiffre(s) vérifié(s) dans leur page" if fr
                        else f"Reading: {t['facts']} figure(s) checked in their page")
                       + ((f", {d} écarté(s)" if fr else f", {d} left out") if d else ""))  # fmt: skip
        if b.actions:
            out.append(f"Lecture : {len(b.actions)} action(s) vérifiée(s) ligne par ligne" if fr
                       else f"Reading: {len(b.actions)} action(s) checked line by line")  # fmt: skip
        if b.costs:
            n = len(b.costs.get("rows") or [])
            out.append(f"Calcul : coûts de {n} offre(s) calculés par Bird, verdict choisi par le code" if fr
                       else f"Computation: costs of {n} offer(s) computed by Bird, verdict chosen in code")  # fmt: skip
        if t.get("drafts"):
            chosen, merged = self._label(t.get("chosen") or "redacteur_a"), t.get("merged")
            line = (f"Rédaction : {t['drafts']} version(s) en parallèle, {chosen} retenue" if fr
                    else f"Writing: {t['drafts']} version(s) in parallel, {chosen} kept")  # fmt: skip
            if merged:
                line += (f", complétée par {merged['parts']} partie(s) de {self._label(merged['from'])}" if fr
                         else f", completed with {merged['parts']} part(s) of {self._label(merged['from'])}")  # fmt: skip
            out.append(line)
            bits = ["chiffres contrôlés contre le texte et les sources" if fr else "figures checked against the text and sources"]
            if t.get("recited"):
                bits.append(f"{t['recited']} citation(s) corrigée(s)" if fr else f"{t['recited']} citation(s) fixed")
            if t.get("autocited"):
                bits.append(f"{t['autocited']} citation(s) ajoutée(s)" if fr else f"{t['autocited']} citation(s) added")
            if t.get("fixed"):
                bits.append("1 correction ciblée" if fr else "1 targeted fix")
            if t.get("removed"):
                bits.append(f"{t['removed']} passage(s) sans source retiré(s)" if fr
                            else f"{t['removed']} unsourced passage(s) removed")  # fmt: skip
            out.append(("Vérification : " if fr else "Check: ") + ", ".join(bits))
        return out

    def _build(self, tool, args, actx, caveats, sources, *, chosen=None, fixed=False, forced=None, carry=None) -> Run:
        self._step("assembleur", "running", "build")
        if self.final_sources is not None:
            sources = self.final_sources  # renumbered in the order the deliverable cites them
        canvas = None
        if forced is None and crew_canvas.available(tool):
            try:  # the checked deliverable, section by section into the canvas model (the file is built too)
                canvas = crew_canvas.Sink(self._emit, tool, self.lang).write(args, str(args.get("title") or ""))
            except Exception as e:  # noqa: BLE001 - the canvas never costs the deliverable
                self.agent.audit.log("crew_canvas_error", error=f"{type(e).__name__}: {str(e)[:120]}")
        index, step, result, ctx = self._tool("assembleur", tool, args, forced=forced)
        run = Run(lang=self.lang, flagged=self.flagged)
        if canvas:
            run.canvas = canvas  # birds.web.canvas_web.ref reads it: the answer links to the canvas document
        run.usage = (self.usage_carried if self.slice_n > 0 else []) + list(self.usage)
        if self.slice_n > 0 and carry is None:  # the previous slices' calls ran in other requests
            carry = {"gpu_union": self.carried_union, "seconds": self.carried_seconds}
        run.sources = [s["url"] for s in sources]
        run.source_titles = {s["url"]: str(s.get("title") or "") for s in sources if s.get("title")}
        run.images = list(self.images)
        if step.decision == "pause":
            # everything the resumed request needs to look like an uninterrupted run: the build step's own index
            # (its resumed tool_start/tool_end update that step, never step 0), the earlier tool steps (the memo,
            # the sources' titles, tool_calls), the bytes read, the version kept and the team's size
            state = {"k": "crew", "v": 1, "recipe": self.d.recipe, "tool": tool, "args": args, "sources": sources,
                     "caveats": caveats, "usage": run.usage, "answer_ctx": actx, "lang": self.lang,
                     "index": index, "bytes": self.bytes, "chosen": chosen,
                     "agents": self.carried_agents if self.carried_agents is not None else self._agents(),
                     "steps": [_compact_step(i, s) for i, s in sorted(self.steps, key=lambda x: x[0])],
                     "carry": {"seconds": round(time.monotonic() - self.t0 + self.carried_seconds, 2),
                               "gpu_union": self._union() + self.carried_union}}  # fmt: skip
            if len(json.dumps(state, ensure_ascii=False, default=str)) > STATE_CAP:
                state["steps"] = [{**s, "arguments": {}, "result": ""} for s in state["steps"]]
            if len(json.dumps(state, ensure_ascii=False, default=str)) <= STATE_CAP:
                self._emit(
                    {"kind": "tool_start", "index": index, "tool": tool, "arguments": args, "agent": "assembleur"}
                )
                self._step("assembleur", "queued", "build", detail="confirmation")
                run.stop_reason, run.pending, run.state = "confirm", {"tool": tool, "arguments": args}, state
                run.steps = [s for _, s in sorted(self.steps, key=lambda x: x[0])]
                run.report = self._report(carry, extra_usage=self.usage_carried if self.slice_n > 0 else None)
                return run
            index, step, result, ctx = self._tool("assembleur", tool, args, forced="denied_unconfirmed")
        ok = not step.error and not step.decision.startswith("denied")
        # the user refused the confirmation (Crew.resume): their choice, a neutral « refusé », not a red failure
        refused = forced == "denied_unconfirmed" and step.decision.startswith("denied")
        if refused:
            self._step("assembleur", "skipped", "build", detail="refusé" if self.lang == "fr" else "declined")
        else:
            self._step("assembleur", "done" if ok else "error", "build", seconds=step.seconds,
                       detail=(ctx.files[0].rsplit("/", 1)[-1] if ctx.files else (step.error or "")[:80]))  # fmt: skip
        if ok:
            name = ctx.files[0].rsplit("/", 1)[-1] if ctx.files else ""
            parts = args.get("slides") or args.get("sections") or []
            self._emit({"type": "agent_deliverable", "tool": tool, "title": str(args.get("title") or args.get("subject")
                        or "")[:200], "file": name, "parts": len(parts), "canvas": (canvas or {}).get("aid")})  # fmt: skip
        run.answer = self._answer(actx, step, caveats)
        self._stream(run.answer)
        run.stop_reason = "answer"
        run.steps = [s for _, s in sorted(self.steps, key=lambda x: x[0])]
        run.files, run.drafts = list(ctx.files), list(ctx.drafts)
        run.messages = [{"role": "assistant", "content": run.answer}]
        run.report = self._report(carry, extra_usage=self.usage_carried if self.slice_n > 0 else None)
        if self.slice_n > 0:
            run.report["carried_seconds"] = self.carried_seconds
        done = self._done_event(ok, chosen, run.report, caveats, fixed=fixed)
        if refused:
            done["denied"] = True
        self._emit(done)
        return run

    def _agents(self) -> int:
        return sum(1 for ln in self.lanes if ln["role"] != "verificateur")

    # -------------------------------------------------------------- accounting
    def _union(self, extra: float = 0.0) -> float:
        return round(cc.union_seconds((u["t0"], u["t1"]) for u in self.usage if "t0" in u) + extra, 3)

    def _report(self, carry: dict | None = None, extra_usage: list | None = None, extra_busy: float = 0.0) -> dict:
        carry = carry or {}
        usage = list(self.usage) + list(extra_usage or [])
        union = self._union(extra_busy) + float(carry.get("gpu_union") or 0.0)
        cfg = self.cfg
        rep = meter.report(
            usage,
            wall_seconds=time.monotonic() - self.t0,
            tool_calls=len(self.steps),
            bytes_fetched=self.bytes,
            measured_wh=None,
            **meter.energy_options(cfg),
            busy_seconds_override=union,  # power x time only: the tokens of parallel calls are simply summed
        )
        roles: dict[str, dict] = {}
        for u in usage:
            role = str(u.get("role") or "agent").split("_")[0]
            r = roles.setdefault(
                role, {"role": role, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}
            )
            r["calls"] += 1
            r["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
            r["completion_tokens"] += int(u.get("completion_tokens") or 0)
            r["seconds"] = round(r["seconds"] + float(u.get("busy_seconds") or u.get("seconds") or 0), 2)
        rep["agents"] = list(roles.values())
        rep["gpu_seconds_union"] = round(union, 2)
        rep["busy_seconds_sum"] = round(sum(float(u.get("busy_seconds") or u.get("seconds") or 0) for u in usage), 2)
        rep["crew_calls"] = len(usage)
        return rep

    def _done_event(self, ok: bool, chosen, report: dict, caveats, *, reason=None, fallback=None, fixed=False) -> dict:
        # after a confirmation the figures cover both requests: the team's calls and time before the pause count
        ev = {"type": "agent_done", "recipe": self.d.recipe, "ok": ok, "chosen": chosen,
              "calls": len(self.usage) + len(self.usage_carried),
              "seconds": round(time.monotonic() - self.t0 + self.carried_seconds, 1),
              "gpu_seconds_union": report.get("gpu_seconds_union"),
              "energy_wh": report.get("energy_wh"), "energy_kind": report.get("energy_kind"),
              "caveats": list(caveats)[:6], "fixed": fixed,
              "agents": self.carried_agents if self.carried_agents is not None else self._agents()}  # fmt: skip
        if reason:
            ev["reason"] = reason
        if fallback:
            ev["fallback"] = fallback
        return ev

    # -------------------------------------------------------------- fallbacks
    def _context(self, b: Brief | None) -> str:
        if b is None or not (b.facts or b.sources or b.actions):
            return ""
        fr = self.lang == "fr"
        lines = ["[Éléments déjà vérifiés par l'équipe d'agents]" if fr else "[Already checked by the agent team]"]
        lines += [f"- ({f['year']}) {f['fact']} [{f['n']}]" for f in b.facts]
        lines += [f"[{s['n']}] {s['url']}" for s in b.sources]
        if b.actions:
            lines.append(cc.actions_table(b.actions, self.lang))
        return "\n".join(lines)

    def _fallback(self, reason: str, b: Brief | None) -> Run:
        need = 120.0 if reason in ("no_results", "no_facts") else 60.0
        if self._left() <= need:
            run = Run(lang=self.lang, stop_reason="answer", flagged=self.flagged)
            run.answer = ABSTAIN[self.lang]["no_facts" if reason in ("no_results", "no_facts") else "default"]
            self._stream(run.answer)
            run.usage, run.steps = list(self.usage), [s for _, s in sorted(self.steps, key=lambda x: x[0])]
            run.report = self._report()
            self._emit(self._done_event(False, None, run.report, [], reason=reason))
            return run
        self._emit(self._done_event(False, None, self._report(), [], reason=reason, fallback="single"))
        shift = self.index
        base = self.agent.hooks
        agent = copy.copy(self.agent)
        agent.hooks = dataclasses.replace(
            base,
            on_step_start=(lambda i, t, a: base.on_step_start(i + shift, t, a)) if base.on_step_start else None,
            on_step_end=(lambda i, s: base.on_step_end(i + shift, s)) if base.on_step_end else None,
        )
        agent.cfg = dataclasses.replace(self.cfg, timeout_s=max(10.0, self._left() - 5))
        context = self._context(b)
        user = self.message + ("\n\n" + context if context else "")
        run = agent.run(user, history=getattr(self, "kept", None) or None, system=self.system, thinking=self.thinking,
                        lang=self.lang, request_text=self.own, attached=self.attached)  # fmt: skip
        crew_steps = [s for _, s in sorted(self.steps, key=lambda x: x[0])]
        single = list(run.usage)
        run.steps = crew_steps + run.steps
        extra_busy = sum(float(u.get("busy_seconds") or u.get("seconds") or 0) for u in single)
        report = self._report(extra_usage=single, extra_busy=extra_busy)
        report["tool_calls"] = len(run.steps)
        run.usage = list(self.usage) + single
        run.report = report
        if run.stop_reason == "confirm" and isinstance(run.state, dict):
            # the single agent's own pause (k: "harness"): its signed state carries the team's work as ONE usage
            # entry whose busy time is the union of the team's parallel calls, so the resumed request's energy
            # report counts the team once, not as the sum of its calls and not zero
            team = {"role": "crew", "busy_seconds": self._union(), "seconds": self._union(),
                    "prompt_tokens": sum(int(u.get("prompt_tokens") or 0) for u in self.usage),
                    "completion_tokens": sum(int(u.get("completion_tokens") or 0) for u in self.usage),
                    "cached_tokens": sum(int(u.get("cached_tokens") or 0) for u in self.usage)}  # fmt: skip
            run.state["usage"] = ([team] if self.usage else []) + list(run.state.get("usage") or [])
        return run

    # -------------------------------------------------------------- resume after a confirmation
    @classmethod
    def resume(cls, agent, state: dict, decision: bool, *, deadline: float | None = None) -> Run:
        """Run (or refuse) the paused build step and write the answer. Nothing is generated again."""
        lang = "en" if state.get("lang") == "en" else "fr"
        d = Decision(str(state.get("recipe") or "generic"), mode="on")
        crew = cls(agent, d, lang=lang, deadline=deadline)
        crew.usage = [u for u in state.get("usage") or [] if isinstance(u, dict)]
        sources = [s for s in state.get("sources") or [] if isinstance(s, dict) and isinstance(s.get("url"), str)]
        caveats = [str(c) for c in state.get("caveats") or []][:6]
        actx = state.get("answer_ctx") if isinstance(state.get("answer_ctx"), dict) else {"tool": state["tool"]}
        actx.setdefault("tool", state["tool"])
        carry = state.get("carry") if isinstance(state.get("carry"), dict) else {}
        # the stored usage already counts in the carried GPU union: only new generations (none) would add to it
        crew.usage_carried = crew.usage
        crew.usage = []
        # the paused run's steps, bytes and build index: the build reuses its own step index, and run.steps, the
        # memo, the sources' titles and the usage figures match a run that was never interrupted
        crew.steps = [_restore_step(s) for s in state.get("steps") or [] if isinstance(s, dict)]
        crew.index = _int(state.get("index"), max((i for i, _ in crew.steps), default=-1) + 1)
        crew.bytes = _int(state.get("bytes"), 0)
        crew.carried_seconds = float(carry.get("seconds") or 0.0)
        crew.carried_agents = _int(state.get("agents"), 0) if "agents" in state else None
        chosen = state.get("chosen") if isinstance(state.get("chosen"), str) else None
        run = crew._build(state["tool"], state["args"], actx, caveats, sources, chosen=chosen,
                          forced="confirmed" if decision else "denied_unconfirmed", carry=carry)  # fmt: skip
        run.usage = crew.usage_carried + run.usage
        run.report = crew._report(carry, extra_usage=crew.usage_carried)
        return run
