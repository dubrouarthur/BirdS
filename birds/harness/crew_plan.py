"""Mode Agent, wave 2: the typed plan shown before launch, and the typed instructions added while the team works.

The plan is built in code from the decided recipe (``crew.decide``) and the request's signals: steps, audience,
length, sections to cover, sites to prefer or exclude, deliverable. The user edits TYPED FIELDS only (enums, a
bounded count, domain names, short one-line headings); nothing they type reaches a model as raw text: every value
is validated here, then rendered by a template into one line of the shared brief (``constraint_lines``).

Instructions added during the run (« Ajouter une consigne ») are the same typed fields (``Note``), queued in a
``NoteBox`` and applied by the crew between two generations. A note that arrives too late for what it changes is
acknowledged as such, never silently dropped.
"""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

AUDIENCES = ("general", "decision", "experts")
LENGTHS = ("short", "standard", "long")
NOTE_KINDS = ("exclude_site", "prefer_site", "audience", "length", "add_section", "focus")
MAX_SECTIONS = 8
MAX_HEADING = 80
MAX_FOCUS = 100
MAX_SITES = 6
AUTO_START_S = 5  # Auto: the team starts after this countdown unless the user edits the plan (Auto never blocks)

LABELS = {
    "fr": {
        "audience": {"general": "Grand public", "decision": "Décideurs", "experts": "Experts"},
        "length": {"short": "Courte", "standard": "Standard", "long": "Approfondie"},
        "deliverable": {
            "make_slides": "Présentation (.pptx)",
            "make_document": "Document (.docx)",
            "draft_email": "Brouillon de mail",
            "make_sheet": "Tableur (.xlsx)",
        },  # fmt: skip
        "steps": {
            "research": "Chercher des sources sur le web",
            "read": "Lire les pages et relever les chiffres",
            "read_offers": "Lire les offres et calculer les coûts",
            "read_notes": "Lire les notes et relever les actions",
            "read_table": "Lire le tableau",
            "plan": "Lister les points indispensables",
            "drafts": "Rédiger deux versions en parallèle",
            "draft_one": "Rédiger le tableur",
            "check": "Vérifier chaque chiffre et chaque source",
            "build": "Créer le livrable",
        },
        "steps_deep": {
            "plan": "Découper la question en sous-questions",
            "research": "Chercher des sources sur le web",
            "read": "Lire les pages et relever les affirmations",
            "drafts": "Rédiger le rapport sourcé",
            "check": "Recouper chaque affirmation avec sa source",
        },
    },
    "en": {
        "audience": {"general": "General public", "decision": "Decision makers", "experts": "Experts"},
        "length": {"short": "Short", "standard": "Standard", "long": "In depth"},
        "deliverable": {
            "make_slides": "Deck (.pptx)",
            "make_document": "Document (.docx)",
            "draft_email": "Email draft",
            "make_sheet": "Spreadsheet (.xlsx)",
        },  # fmt: skip
        "steps": {
            "research": "Search the web for sources",
            "read": "Read the pages and record the figures",
            "read_offers": "Read the offers and compute the costs",
            "read_notes": "Read the notes and record the actions",
            "read_table": "Read the table",
            "plan": "List the points the request needs",
            "drafts": "Write two versions in parallel",
            "draft_one": "Write the spreadsheet",
            "check": "Check every figure and every source",
            "build": "Build the deliverable",
        },
        "steps_deep": {
            "plan": "Split the question into sub-questions",
            "research": "Search the web for sources",
            "read": "Read the pages and record the claims",
            "drafts": "Write the sourced report",
            "check": "Cross-check every claim with its source",
        },
    },
}
# what each typed value becomes in the shared brief (a template: the user's words are never the instruction)
RENDER = {
    "fr": {
        "audience": {
            "general": "Public : grand public (mots simples, pas de jargon)",
            "decision": "Public : décideurs (l'essentiel d'abord, une recommandation claire)",
            "experts": "Public : experts (vocabulaire du métier, détails chiffrés)",
        },  # fmt: skip
        "length": {
            "short": "Longueur : courte (l'essentiel, 3 à 4 sections ou diapositives)",
            "standard": "",
            "long": "Longueur : approfondie (5 à 7 sections détaillées)",
        },  # fmt: skip
        "sections": "Sections attendues (une chacune) : {v}",
        "focus": "Mettre l'accent sur : « {v} »",
        "exclude": "Ne pas citer ces sites : {v}",
    },
    "en": {
        "audience": {
            "general": "Audience: general public (plain words, no jargon)",
            "decision": "Audience: decision makers (key points first, a clear recommendation)",
            "experts": "Audience: experts (trade vocabulary, detailed figures)",
        },  # fmt: skip
        "length": {
            "short": "Length: short (the essentials, 3 to 4 sections or slides)",
            "standard": "",
            "long": "Length: in depth (5 to 7 detailed sections)",
        },  # fmt: skip
        "sections": "Expected sections (one each): {v}",
        "focus": "Put the emphasis on: “{v}”",
        "exclude": "Do not cite these sites: {v}",
    },
}

_DOMAIN = re.compile(r"^(?=.{3,80}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏  ‪-‮⁦-⁩]")


def clean_line(value, cap: int) -> str:
    """One short line of the user's own words, defanged: no control or bidi characters, no markup, no tool-call
    syntax, no URL; whitespace folded; at most ``cap`` characters (cut on a word)."""
    s = _CONTROL.sub(" ", str(value or ""))
    s = re.sub(r"https?://\S+|<[^>]{0,200}>|[<>{}\[\]`|\\]", " ", s)
    s = " ".join(s.split())
    if len(s) > cap:
        s = s[:cap].rsplit(" ", 1)[0]
    return s.strip(" .;:-–—")


def domain(value) -> str | None:
    """A site the user names (« insee.fr », « https://www.lemonde.fr/x ») as a bare lowercase domain, or None."""
    s = str(value or "").strip().lower()
    if "://" in s:
        s = urlsplit(s).netloc
    s = s.split("/")[0].split(":")[0].removeprefix("www.").strip(".")
    return s if _DOMAIN.match(s) else None


def site_of(url: str) -> str:
    return urlsplit(url or "").netloc.lower().split(":")[0].removeprefix("www.")


def matches(url: str, sites) -> bool:
    """The page's site is one of ``sites`` or a subdomain of one (« dares.travail-emploi.gouv.fr » ⊂ « gouv.fr »)."""
    host = site_of(url)
    return any(host == s or host.endswith("." + s) for s in sites)


@dataclass
class Plan:
    recipe: str
    deliverable: str | None
    steps: list = field(default_factory=list)  # [{"id", "label"}], from the recipe (not editable: the team's shape)
    audience: str = "general"
    length: str = "standard"
    n_slides: int | None = None  # decks only, 3..12
    sections: list = field(default_factory=list)  # headings the user wants covered (checked like points)
    prefer: list = field(default_factory=list)  # domains read first
    exclude: list = field(default_factory=list)  # domains never read nor cited
    focus: str = ""
    web: bool = False  # the recipe searches the web (the sites fields apply)
    confidence: str = "normal"  # "high": three load signals or more (recorded on the plan and in the evals)
    edited: bool = False

    def public(self, lang: str = "fr") -> dict:
        """The plan card's data: values and their labels (the client shows labels, sends values back)."""
        lab = LABELS["en" if lang == "en" else "fr"]
        out = asdict(self)
        out["labels"] = {
            "audience": lab["audience"][self.audience],
            "length": lab["length"][self.length],
            "deliverable": lab["deliverable"].get(self.deliverable or "", ""),
        }
        out["choices"] = {"audience": [[k, lab["audience"][k]] for k in AUDIENCES],
                          "length": [[k, lab["length"][k]] for k in LENGTHS]}  # fmt: skip
        return out


def _steps(recipe: str, deliverable: str | None, lang: str) -> list[dict]:
    lab = LABELS["en" if lang == "en" else "fr"]["steps" if recipe != "deep_research" else "steps_deep"]
    ids = {
        "deck_research": ["research", "read", "drafts", "check", "build"],
        "doc_research": ["research", "read", "drafts", "check", "build"],
        "compare_write": ["read_offers", "drafts", "check", "build"],
        "minutes_actions": ["read_notes", "drafts", "check", "build"],
        "sheet_pasted": ["read_table", "draft_one", "check", "build"],
        "deep_research": ["plan", "research", "read", "drafts", "check"],  # birds.harness.research: no file
    }.get(recipe, ["plan", "research", "drafts", "check", "build"])
    return [{"id": i, "label": lab[i]} for i in ids]


def heavy_count(sig: dict) -> int:
    """How many load signals the request carries (the same list ``crew.decide`` counts; read-only here)."""
    d = sig.get("deliverable")
    return sum(
        map(
            bool,
            [
                sig.get("steps"),
                sig.get("figures") and d in ("make_slides", "make_document", "make_sheet"),
                (sig.get("n_docs") or 0) >= 2,
                sig.get("web") and bool(d),
                (sig.get("pasted_chars") or 0) >= 1000 or sig.get("actions"),
                sig.get("study"),
            ],
        )
    )


def make_plan(decision, own: str = "", lang: str = "fr") -> Plan:
    """The plan of a decided run, in code: nothing generated. ``decision``: a ``crew.Decision`` with a recipe."""
    sig = dict(decision.signals or {})
    recipe = decision.recipe or "generic"
    tool = {"deck_research": "make_slides", "doc_research": "make_document", "minutes_actions": "make_document",
            "sheet_pasted": "make_sheet"}.get(recipe) or decision.deliverable  # fmt: skip
    p = Plan(recipe=recipe, deliverable=tool, steps=_steps(recipe, tool, lang))
    p.web = recipe in ("deck_research", "doc_research", "generic", "deep_research")
    if tool == "make_slides":
        m = re.search(r"(\d{1,2})\s*(?:slides?|diapo\w*|diapositives?)", own or "", re.I)
        p.n_slides = max(3, min(12, int(m.group(1)))) if m else 6
    if re.search(r"d[ée]cideurs?|direction|comit[ée]|codir|board|executives?|manag", own or "", re.I):
        p.audience = "decision"
    elif re.search(r"experts?|techniques?|ing[ée]nieurs?|specialists?", own or "", re.I):
        p.audience = "experts"
    if re.search(r"\b(?:court|br[eè]ve?|synth[ée]tique|short|brief)\b", own or "", re.I):
        p.length = "short"
    elif re.search(r"\b(?:d[ée]taill[ée]e?|approfondie?|complet|complète|exhaustive?|in[- ]depth|detailed)\b",
                   own or "", re.I):  # fmt: skip
        p.length = "long"
    # high confidence: at least three load signals (said on the plan; the countdown is the same in Auto)
    p.confidence = "high" if not decision.forced and heavy_count(sig) >= 3 else "normal"
    return p


def auto_start(plan: Plan, mode: str) -> int | None:
    """Seconds before an untouched plan starts by itself, or None (« Lancer » is needed). Auto never blocks: the
    model decided a team is worth it, so every Auto plan starts after the countdown (« Modifier » stops it), as
    Auto started at once before the plan card existed. Activé waits for « Lancer »."""
    return AUTO_START_S if mode == "auto" else None


def apply_edits(plan: Plan, edits) -> tuple[Plan, list[str]]:
    """The plan with the user's edits, every field validated; unknown keys and invalid values are ignored. Returns
    the new plan and the names of the fields that changed."""
    if not isinstance(edits, dict):
        return plan, []
    p = Plan(**{**asdict(plan)})
    changed = []
    if edits.get("audience") in AUDIENCES and edits["audience"] != p.audience:
        p.audience = edits["audience"]
        changed.append("audience")
    if edits.get("length") in LENGTHS and edits["length"] != p.length:
        p.length = edits["length"]
        changed.append("length")
    if p.n_slides is not None and "n_slides" in edits:
        v = edits["n_slides"]
        try:  # Infinity and NaN parse as JSON in Python: int() of them raises OverflowError / ValueError
            n = max(3, min(12, int(v))) if not isinstance(v, bool) and (not isinstance(v, float) or math.isfinite(v)) \
                else p.n_slides
        except (TypeError, ValueError, OverflowError):
            n = p.n_slides
        if n != p.n_slides:
            p.n_slides = n
            changed.append("n_slides")
    if isinstance(edits.get("sections"), list):
        secs = [clean_line(s, MAX_HEADING) for s in edits["sections"][: MAX_SECTIONS * 2]]
        secs = list(dict.fromkeys(s for s in secs if len(s) >= 2))[:MAX_SECTIONS]
        if secs != p.sections:
            p.sections = secs
            changed.append("sections")
    for key in ("prefer", "exclude"):
        if p.web and isinstance(edits.get(key), list):
            sites = list(dict.fromkeys(d for d in map(domain, edits[key][: MAX_SITES * 2]) if d))[:MAX_SITES]
            if sites != getattr(p, key):
                setattr(p, key, sites)
                changed.append(key)
    if p.web:
        p.prefer = [d for d in p.prefer if d not in p.exclude]
    if "focus" in edits:
        f = clean_line(edits.get("focus"), MAX_FOCUS)
        if f != p.focus:
            p.focus = f
            changed.append("focus")
    p.edited = plan.edited or bool(changed)
    return p, changed


def from_public(data) -> Plan | None:
    """A plan carried in a signed token (fields re-validated all the same)."""
    if not isinstance(data, dict) or not isinstance(data.get("recipe"), str):
        return None
    base = Plan(recipe=data["recipe"], deliverable=data.get("deliverable") if isinstance(data.get("deliverable"), str)
                else None, steps=[s for s in data.get("steps") or [] if isinstance(s, dict)][:8],
                n_slides=6 if data.get("n_slides") is not None else None, web=bool(data.get("web")),
                confidence="high" if data.get("confidence") == "high" else "normal")  # fmt: skip
    p, _ = apply_edits(base, {k: data.get(k) for k in ("audience", "length", "n_slides", "sections", "prefer",
                                                         "exclude", "focus")})  # fmt: skip
    p.edited = bool(data.get("edited"))
    return p


def constraint_lines(plan: Plan | None, lang: str = "fr") -> list[str]:
    """The plan's typed choices as lines of the shared brief, from templates. Empty for an untouched default."""
    if plan is None:
        return []
    r = RENDER["en" if lang == "en" else "fr"]
    out = []
    if plan.audience != "general" or plan.edited:
        out.append(r["audience"][plan.audience])
    if r["length"][plan.length]:
        out.append(r["length"][plan.length])
    if plan.sections:
        out.append(r["sections"].format(v=" ; ".join(plan.sections)))
    if plan.focus:
        out.append(r["focus"].format(v=plan.focus))
    if plan.exclude:
        out.append(r["exclude"].format(v=", ".join(plan.exclude)))
    return [x for x in out if x]


# ------------------------------------------------------------------ instructions added during the run


@dataclass
class Note:
    id: str
    kind: str
    value: str
    at: float = field(default_factory=time.time)


def parse_note(kind, value, nid: str = "") -> Note | None:
    """A typed instruction, or None when the kind is unknown or the value invalid for it."""
    if kind not in NOTE_KINDS:
        return None
    if kind in ("exclude_site", "prefer_site"):
        v = domain(value)
    elif kind == "audience":
        v = value if value in AUDIENCES else None
    elif kind == "length":
        v = value if value in LENGTHS else None
    elif kind == "add_section":
        v = clean_line(value, MAX_HEADING) or None
    else:
        v = clean_line(value, MAX_FOCUS) or None
    if not v:
        return None
    return Note(id=re.sub(r"[^\w-]", "", str(nid or ""))[:24] or f"n{int(time.time() * 1000) % 10**8}", kind=kind,
                value=v)  # fmt: skip


def note_edits(plan: Plan, note: Note) -> dict:
    """A note as an edit of the plan's typed fields."""
    if note.kind == "exclude_site":
        return {"exclude": [*plan.exclude, note.value]}
    if note.kind == "prefer_site":
        return {"prefer": [*plan.prefer, note.value]}
    if note.kind == "add_section":
        return {"sections": [*plan.sections, note.value]}
    return {note.kind: note.value}


class NoteBox:
    """The notes of one run, queued by the web endpoint and taken by the crew between two generations."""

    def __init__(self):
        self._lock = threading.Lock()
        self._queue: list[Note] = []
        self.closed = False

    def put(self, note: Note) -> bool:
        with self._lock:
            if self.closed or len(self._queue) >= 12:
                return False
            self._queue.append(note)
            return True

    def take(self) -> list[Note]:
        with self._lock:
            out, self._queue = self._queue, []
            return out

    def close(self) -> list[Note]:
        with self._lock:
            self.closed = True
            out, self._queue = self._queue, []
            return out


class Registry:
    """Runs of this process that accept notes, by run id (random). On serverless another instance may receive the
    note: ``deliver`` then returns False and the browser carries the note into the next slice of the run."""

    TTL = 900.0

    def __init__(self):
        self._lock = threading.Lock()
        self._boxes: dict[str, tuple[float, NoteBox]] = {}

    def open(self, run_id: str) -> NoteBox:
        box = NoteBox()
        now = time.monotonic()
        with self._lock:
            self._boxes = {k: v for k, v in self._boxes.items() if now - v[0] < self.TTL and not v[1].closed}
            self._boxes[run_id] = (now, box)
        return box

    def deliver(self, run_id: str, note: Note) -> bool:
        with self._lock:
            got = self._boxes.get(run_id)
        return bool(got) and got[1].put(note)

    def close(self, run_id: str, box: NoteBox | None = None) -> list[Note]:
        """The run's box closed. With ``box``: only if it is still the one registered (a second request for the same
        run, e.g. two tabs, opened its own; the first to end must not take the other's away)."""
        with self._lock:
            got = self._boxes.get(run_id)
            if got is None or (box is not None and got[1] is not box):
                got = None
            else:
                self._boxes.pop(run_id)
        if box is not None and got is None:
            return box.close()
        return got[1].close() if got else []


REGISTRY = Registry()


class Once:
    """Signed agent states used once per process: a plan token « Lancé », a slice (run, slice) continued. Refuses a
    second request while the first runs (two tabs, a replayed request) or after it ended normally; a run that was
    cut (client gone, error) frees its key, so « Reprendre » can use the same state. Best effort: another serverless
    instance does not see this set (the token's own expiry is the bound there)."""

    TTL = 900.0  # the tokens' own lifetime (confirm_ttl): a key is not kept longer than its token is valid
    RUNNING_MAX = 900.0  # a claim whose request never started its run is not held for ever

    def __init__(self):
        self._lock = threading.Lock()
        self._running: dict[str, tuple[float, object]] = {}
        self._done: dict[str, float] = {}

    def claim(self, key: str) -> object | None:
        """A ticket for ``key``, or None when it is running or done."""
        now = time.monotonic()
        with self._lock:
            self._done = {k: t for k, t in self._done.items() if now - t < self.TTL}
            self._running = {k: v for k, v in self._running.items() if now - v[0] < self.RUNNING_MAX}
            if key in self._running or key in self._done:
                return None
            ticket = object()
            self._running[key] = (now, ticket)
            return ticket

    def release(self, key: str, ticket: object, finished: bool) -> None:
        """Ends the claim ``ticket`` (twice is harmless: the stream frees it when the client leaves, the run when
        it ends). A later claim of the same key is never released by an earlier ticket."""
        with self._lock:
            if self._running.get(key, (0, None))[1] is ticket:
                self._running.pop(key)
                if finished:
                    self._done[key] = time.monotonic()


ONCE = Once()
