"""The agent loop: render -> generate -> parse -> run tools -> repeat, with every limit enforced in code."""

from __future__ import annotations

import copy
import inspect
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from birds.harness import guard, meter
from birds.harness.config import Config, Context
from birds.harness.llm import STOP, EndpointError, accepts
from birds.harness.tools import TOOLS, make_search
from birds.parse import parse_output
from birds.render import prompt as render_prompt
from birds.sources.identity import DEFAULT_SYSTEM  # same text as docs/PERSONA.md
from birds.tools import PRODUCT_TOOLS

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
    r"\bcourbes?\s+(?:en\s+[a-z]\b|d['’]apprentissage|de\s+gauss|de\s+niveau|de\s+bézier|de\s+bezier)",
    re.I,
)
# A chart noun in the user's own words: make_chart is offered (an extra tool, nothing else). « secteurs » and
# « barres » alone are not chart nouns (« les secteurs qui recrutent », « barres de céréales »).
_CHART_ASK = re.compile(
    r"\b(?:graphiques?|graphes?|graphs?|courbes?|diagrammes?|camemberts?|histogrammes?|histograms?|charts?|plots?|"
    r"plotting|visualis\w*|visualiz\w*|repr[ée]sent\w* graphiquement)\b",
    re.I,
)
# A clear request for one: an action verb shortly before a chart noun (« fais un graphique », « trace la courbe »,
# « refais-le en courbe », « make a bar chart »), or a bare verb « plot / visualise »; or figures in the message.
_CHART_VERB = re.compile(
    r"\b(?:re)?(?:fai[st]e?s?|faites|faire|fasse|trac\w*|montr\w*|cr[ée]\w*|g[ée]n[èée]r\w*|dessin\w*|affich\w*|produi\w*|"
    r"pr[ée]par\w*|sort\w*|mets|mettez|transform\w*|convert\w*|make|draw|show|create|generate|build|render|"
    r"turn|redo|do|give|want|veux|voudrais|aimerais)\b[^.?!\n]{0,40}?\b(?:en\s+|in\s+|as\s+(?:an?\s+)?)?"
    r"(?:graphiques?|graphes?|graphs?|courbes?|diagrammes?|camemberts?|histogrammes?|histograms?|charts?|plots?|"
    r"barres|b[âa]tons|secteurs|lines?|bars?|pies?)\b|"
    r"(?:^|[.!?\n]\s*)(?:plot|chart|graph|visualis\w*|visualiz\w*|repr[ée]sente\w*)\b",
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


_TREND_ASK = re.compile(
    r"\b(?:depuis|since|entre|between)\s+(?:l.an\s+)?(?:19|20)\d\d|\b[ée]volu\w*|\btendance|\btrend|\bover the (?:years|decade)",
    re.I,
)


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
    out = set() if _CHART_ASK.search(words) or _TREND_ASK.search(user or "") else {"make_chart"}
    # A chart of public facts (« la population des 5 plus grandes villes ») is researched first, as ChatGPT does:
    # the web tools are withheld only when the message itself carries the figures (or a document does).
    figures = chart_ask(user) and len(_NUMBER.findall(words)) >= 2
    asks = attached or _FILE_ASK.search(user or "") or figures
    if asks and not _NEEDS_WEB.search(user or ""):
        out |= {"web_search", "read_page"}
    return out


def chart_ask(text: str) -> bool:
    """The user's words clearly ask for a chart: an action verb near a chart noun (not « charte graphique » or
    « courbe en J »), and not a question about charts. Only then is a text answer reminded or replaced."""
    text = _chart_words(text)
    clear = _CHART_VERB.search(text) or len(_NUMBER.findall(text)) >= 2  # « graphique du CA : T1 120, T2 135 »
    return bool(_CHART_ASK.search(text) and clear and not _HOWTO.search(text) and not _ABOUT_CHARTS.search(text))


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


_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def _check_untrusted_url(url: object, ctx: Context) -> None:
    """After a page or a file held an injection, read_page may only open a URL the user gave, a search result or a
    page already read: a GET to an address the untrusted text chose is how data would leave (``?d=<secret>``)."""
    url = str(url or "").strip()
    if len(urlsplit(url).query) > 64:
        raise guard.Blocked("page suggested by untrusted content (long query string)")
    own = {u.rstrip(".,;:") for u in _URL_IN_TEXT.findall(ctx.request or "")}
    known = set(ctx.sources) | set(ctx.found) | own
    if url not in known and url.rstrip("/") not in {k.rstrip("/") for k in known}:
        raise guard.Blocked("page suggested by untrusted content")


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


@dataclass
class Run:
    answer: str = ""
    stop_reason: str = ""
    salvaged: bool = False  # the loop failed and the answer came from one last generation without tools
    think_cut: bool = False  # the reasoning ran past cfg.think_chars and the step was redone without it
    lang: str = "en"
    steps: list[Step] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    drafts: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)  # make_chart specs, drawn by the browser
    images: list[dict] = field(default_factory=list)  # web image candidates seen by web_search / read_page
    usage: list[dict] = field(default_factory=list)  # one entry per generation
    report: dict = field(default_factory=dict)
    flagged: bool = False  # some tool result looked like a prompt injection
    reasoning: str = ""
    messages: list[dict] = field(default_factory=list)  # full conversation, to continue a chat
    pending: dict | None = None  # stop_reason "confirm": {"tool", "arguments"} waiting for the user's decision
    state: dict | None = None  # stop_reason "confirm": JSON-serialisable loop state for Agent.run(resume=...)

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

    def _allowed(self) -> set[str]:
        """Tools shown to the model: the deployment allowlist, minus what is switched off or not configured."""
        off = set() if self.cfg.allow_python else {"run_python"}
        off |= set() if self.search else {"web_search"}
        return set(self.cfg.allowed_tools) - off

    def _last_answer(self, messages: list[dict], lang: str, deadline: float) -> tuple[str, dict | None]:
        """One generation with no tools and no reasoning, asked to answer from what is already in the conversation.
        The instruction is a temporary last message: it is never kept in the history."""
        note = {"role": "user", "content": LAST_CHANCE[lang if lang in LAST_CHANCE else "en"]}
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

    def _generate(self, prompt: str, thinking: bool, deadline: float) -> tuple[dict, AnswerStream | None]:
        hooks = self.hooks
        limit = {"think_limit": self.cfg.think_chars} if thinking and accepts(self.llm.generate, "think_limit") else {}
        if not self._llm_kwargs:
            return self.llm.generate(prompt, self.cfg.max_tokens, STOP, **limit), None
        stream = AnswerStream(hooks.on_token, thinking) if hooks.on_token else None
        out = self.llm.generate(
            prompt,
            self.cfg.max_tokens,
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
    ) -> Run:
        """Run one user request, or continue one that stopped on a pending confirmation.

        When the ``confirm`` callback returns ``PAUSE``, the run ends with ``stop_reason == "confirm"``,
        ``run.pending`` (the action) and ``run.state``. Calling ``run(resume=state, decision=True|False)`` later,
        possibly in another process, performs or refuses that action and carries on: nothing is generated twice.
        The caller is responsible for the integrity of ``state`` between the two calls (the web app signs it).
        ``request_text`` is the user's own words when ``user`` also carries attachment text (used to choose the
        tools); ``attached`` says the request comes with a document or an image.
        """
        cfg, t0, hooks = self.cfg, time.monotonic(), self.hooks
        deadline = t0 + cfg.timeout_s
        if resume is not None:
            st = copy.deepcopy(resume)
            thinking = bool(st["thinking"])
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
                found=[str(u) for u in st.get("found", [])],
                used=[str(u) for u in st.get("used", [])],
                fetched=[[str(k), str(v)] for k, v in st.get("fetched", []) if k in ("web", "file")],
                charts=[c for c in st.get("charts", []) if isinstance(c, dict)],
                images=[i for i in st.get("images", []) if isinstance(i, dict)],
            )
            messages, seen, queue = st["messages"], set(st["seen"]), list(st["queue"])
            budget, side_effects, bad_streak = st["budget"], st["side_effects"], st["bad_streak"]
            nudged = bool(st.get("nudged", False))
            file_nudged = bool(st.get("file_nudged", False))
            withdrawn = set(st.get("withdrawn", []))
            routed = set(st.get("routed", []))
            gen, ok, content = st["gen"], st["ok"], st.get("content", "")
            forced = "confirmed" if decision is True else "denied_unconfirmed"
        else:
            run = Run(lang=lang or detect_lang(user))
            ctx = Context(
                config=cfg,
                http=self.http,
                search=self.search,
                lang=run.lang,
                request=user if request_text is None else request_text,
                message=user,
            )
            messages = list(history or [])
            if not messages or messages[0]["role"] != "system":
                messages.insert(0, {"role": "system", "content": system or DEFAULT_SYSTEM[run.lang]})
            messages.append({"role": "user", "content": guard.defang(user)})
            seen, queue = set(), []
            budget, side_effects, bad_streak, content = cfg.max_context_chars, 0, 0, ""
            words = user if request_text is None else request_text
            routed = route(words, attached) if cfg.route_tools else (route(words) & {"make_chart"})
            nudged, withdrawn, file_nudged = False, set(routed), False
            gen, ok, forced = 0, 0, None
        gpu = meter.GpuMeter(enabled=cfg.measure_gpu or getattr(self.llm, "local", False))

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
                            run.usage.append({k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds",
                                                                      "busy_seconds", "finish_reason") if k in out})
                            run.think_cut, step_thinking = True, False
                            if stream is not None and hooks.on_reset:
                                hooks.on_reset()
                            out, stream = self._generate(
                                render_prompt(self.tok, messages, offered, False), False, deadline
                            )
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
                calls = parsed["tool_calls"][: cfg.max_calls_per_step]
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
                    if run.stop_reason == "answer" and not _made_file(run, ctx):
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
                        and not file_nudged
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
                        and chart_claim(content)
                    ):
                        content = NO_CHART[run.lang]  # "Voici la courbe :" with no chart: say so, plainly
                    break
                if gen == cfg.max_steps - 1:
                    run.stop_reason = "max_steps"  # the last allowed generation still asks for tools: they are not run
                    break
                keys = [
                    c["name"] + " " + json.dumps(c["arguments"], sort_keys=True, ensure_ascii=False, default=str)
                    for c in calls
                ]
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
                    for c in calls:
                        messages.append(
                            {
                                "role": "tool",
                                "content": f"Error: {c['name']} was already called with these exact arguments and its "
                                "result is above. Do not repeat it: use that result now, either to answer the user or "
                                "to call the next tool the request needs.",
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
                step, result = self._call(c["name"], c["arguments"], gen - 1, run, ctx, side_effects, forced, routed)
                forced = None
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
                }
                break
            bad_streak = 0 if ok else bad_streak + 1
            if bad_streak >= 2:
                run.stop_reason = "invalid_tool_calls"  # one retry after a malformed step, not more
                break

        salvage = run.stop_reason in _SALVAGE and not (content or "").strip() and deadline - time.monotonic() > 8
        if salvage:
            # The loop ended without a usable answer (tool calls that kept failing, the step budget, an empty or
            # broken output). Before giving up, one last generation with no tools and no reasoning: answer with what
            # was gathered. Cheap, and far better than a generic "could not answer".
            last, used = self._last_answer(messages, run.lang, deadline)
            if used:  # the last generation counts in the receipt like any other
                run.usage.append({k: used.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds",
                                                           "busy_seconds", "finish_reason") if k in used})
            if last:
                content, run.stop_reason, run.salvaged = last, "answer", True
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
        run.charts, run.images = ctx.charts, ctx.images
        run.report = meter.report(
            run.usage,
            wall_seconds=time.monotonic() - t0,
            tool_calls=len(run.steps),
            bytes_fetched=ctx.bytes_fetched,
            measured_wh=gpu.wh,
            wh_per_1k_tokens=cfg.wh_per_1k_tokens,
            calibration_source=cfg.calibration_source,
            gpu_watts=cfg.gpu_watts,
            gpu_label=cfg.gpu_label,
            pue=cfg.pue,
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
    ) -> tuple[Step, str]:
        """Validate, gate and execute one tool call. Returns the step record and the text given back to the model.

        ``forced`` is the user's answer to a confirmation asked in an earlier call of ``run`` (resume).
        """
        t0 = time.monotonic()
        step = Step(generation=gen, tool=name, arguments=raw_args if isinstance(raw_args, dict) else {})
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
