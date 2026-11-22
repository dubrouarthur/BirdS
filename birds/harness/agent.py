"""The agent loop: render -> generate -> parse -> run tools -> repeat, with every limit enforced in code."""

from __future__ import annotations

import copy
import inspect
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import httpx

from birds.harness import guard, meter
from birds.harness.config import Config, Context
from birds.harness.llm import STOP, EndpointError
from birds.harness.tools import TOOLS, make_search
from birds.parse import parse_output
from birds.render import prompt as render_prompt
from birds.sources.identity import DEFAULT_SYSTEM  # same text as docs/PERSONA.md
from birds.tools import BIRD_TOOLS

FALLBACK = {
    "fr": "Je n'ai pas pu aboutir à une réponse fiable dans les limites fixées. Pouvez-vous reformuler ou préciser la demande ?",
    "en": "I could not reach a reliable answer within the set limits. Could you rephrase or narrow the request?",
}
OUT_OF_TIME = {
    "fr": "Je n'ai pas eu le temps de terminer dans le délai fixé pour une requête. Relancez, ou découpez la demande "
    "en étapes plus courtes.",
    "en": "I ran out of the time allowed for one request. Try again, or split the request into shorter steps.",
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
    r"source|cite|20[2-3]\d)",
    re.I,
)


def route(user: str) -> set[str]:
    """Tools NOT worth offering for this request (a smaller prompt, and fewer detours for a small model).

    A request for a file or a draft that names no need for outside information gets no web tools: the live model,
    offered web_search, searched first on "make a 4-slide deck on remote work" and then never made the deck.
    """
    if _FILE_ASK.search(user or "") and not _NEEDS_WEB.search(user or ""):
        return {"web_search", "read_page"}
    return set()


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


@dataclass
class Hooks:
    """Optional callbacks for a front end that shows a run while it happens. All are called from the run's thread."""

    on_token: Callable[[str], None] | None = None  # visible answer text, as it is generated
    on_reset: Callable[[], None] | None = None  # text already streamed turned out to precede tool calls: drop it
    on_step_start: Callable[[int, str, dict], None] | None = None  # (index, tool, arguments)
    on_step_end: Callable[[int, Step], None] | None = None
    on_status: Callable[[str, dict], None] | None = None  # e.g. ("waking", {"attempt": 2, "retry_in": 5.0})


@dataclass
class Run:
    answer: str = ""
    stop_reason: str = ""
    lang: str = "en"
    steps: list[Step] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    drafts: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
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
        self.tools = [t for t in BIRD_TOOLS if t["function"]["name"] in self._allowed()]
        params = inspect.signature(llm.generate).parameters
        self._llm_kwargs = any(p.kind is p.VAR_KEYWORD for p in params.values()) or "on_token" in params

    def _allowed(self) -> set[str]:
        """Tools shown to the model: the deployment allowlist, minus what is switched off or not configured."""
        off = set() if self.cfg.allow_python else {"run_python"}
        off |= set() if self.search else {"web_search"}
        return set(self.cfg.allowed_tools) - off

    def _generate(self, prompt: str, thinking: bool, deadline: float) -> tuple[dict, AnswerStream | None]:
        hooks = self.hooks
        if not self._llm_kwargs:
            return self.llm.generate(prompt, self.cfg.max_tokens, STOP), None
        stream = AnswerStream(hooks.on_token, thinking) if hooks.on_token else None
        out = self.llm.generate(
            prompt,
            self.cfg.max_tokens,
            STOP,
            on_token=stream.feed if stream else None,
            on_status=hooks.on_status,
            deadline=deadline,
            **({"extra": {"cache_salt": self.cfg.cache_salt}} if self.cfg.cache_salt else {}),
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
    ) -> Run:
        """Run one user request, or continue one that stopped on a pending confirmation.

        When the ``confirm`` callback returns ``PAUSE``, the run ends with ``stop_reason == "confirm"``,
        ``run.pending`` (the action) and ``run.state``. Calling ``run(resume=state, decision=True|False)`` later,
        possibly in another process, performs or refuses that action and carries on: nothing is generated twice.
        The caller is responsible for the integrity of ``state`` between the two calls (the web app signs it).
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
            )
            messages, seen, queue = st["messages"], set(st["seen"]), list(st["queue"])
            budget, side_effects, bad_streak = st["budget"], st["side_effects"], st["bad_streak"]
            nudged = bool(st.get("nudged", False))
            withdrawn = set(st.get("withdrawn", []))
            gen, ok, content = st["gen"], st["ok"], st.get("content", "")
            forced = "confirmed" if decision is True else "denied_unconfirmed"
        else:
            run = Run(lang=lang or detect_lang(user))
            ctx = Context(config=cfg, http=self.http, search=self.search, lang=run.lang)
            messages = list(history or [])
            if not messages or messages[0]["role"] != "system":
                messages.insert(0, {"role": "system", "content": system or DEFAULT_SYSTEM[run.lang]})
            messages.append({"role": "user", "content": guard.defang(user)})
            seen, queue = set(), []
            budget, side_effects, bad_streak, content = cfg.max_context_chars, 0, 0, ""
            nudged, withdrawn = False, (route(user) if cfg.route_tools else set())
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
                try:
                    with gpu:
                        out, stream = self._generate(
                            render_prompt(
                                self.tok,
                                messages,
                                [t for t in self.tools if t["function"]["name"] not in withdrawn],
                                thinking,
                            ),
                            thinking,
                            deadline,
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
                if thinking and "</think>" not in text:
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
                step, result = self._call(c["name"], c["arguments"], gen - 1, run, ctx, side_effects, forced)
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
                    "withdrawn": sorted(withdrawn),
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

        if run.stop_reason == "confirm":
            run.answer = ""
        elif run.stop_reason == "answer":
            run.answer = content
            messages.append({"role": "assistant", "content": content})
        elif run.stop_reason == "timeout":
            run.answer = OUT_OF_TIME[run.lang]
        else:
            run.answer = content or FALLBACK[run.lang]
        run.messages, run.sources, run.drafts, run.files = messages, ctx.sources, ctx.drafts, ctx.files
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
        self, name: str, raw_args, gen: int, run: Run, ctx: Context, side_effects: int, forced: str | None = None
    ) -> tuple[Step, str]:
        """Validate, gate and execute one tool call. Returns the step record and the text given back to the model.

        ``forced`` is the user's answer to a confirmation asked in an earlier call of ``run`` (resume).
        """
        t0 = time.monotonic()
        step = Step(generation=gen, tool=name, arguments=raw_args if isinstance(raw_args, dict) else {})
        args, err = guard.validate_args(name, raw_args, self.cfg.allowed_tools, step.repairs)
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
                    result = guard.defang(guard.redact(str(TOOLS[name](args, ctx))))
                    if guard.scan_injection(result):
                        step.flags.append("possible_injection")
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
