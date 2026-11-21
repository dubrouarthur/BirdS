"""The agent loop: render -> generate -> parse -> run tools -> repeat, with every limit enforced in code."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import httpx

from birds.harness import guard, meter
from birds.harness.config import Config, Context
from birds.harness.llm import STOP
from birds.harness.tools import TOOLS, SearxngBackend
from birds.parse import parse_output
from birds.render import prompt as render_prompt
from birds.sources.identity import DEFAULT_SYSTEM  # same text as docs/PERSONA.md
from birds.tools import BIRD_TOOLS

FALLBACK = {
    "fr": "Je n'ai pas pu aboutir à une réponse fiable dans les limites fixées. Pouvez-vous reformuler ou préciser la demande ?",
    "en": "I could not reach a reliable answer within the set limits. Could you rephrase or narrow the request?",
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

    def to_dict(self) -> dict:
        return asdict(self)


class Agent:
    def __init__(
        self,
        llm,
        tok,
        config: Config,
        *,
        confirm: Callable[[str, dict], bool] | None = None,
        search=None,
        http: httpx.Client | None = None,
    ):
        self.llm, self.tok, self.cfg, self.confirm = llm, tok, config, confirm
        # trust_env=False: the fetch client ignores proxy variables unless the operator passes its own client
        self.http = http or httpx.Client(trust_env=False, follow_redirects=False)
        self.search = search or (SearxngBackend(config.searxng_url, self.http) if config.searxng_url else None)
        self.audit = guard.Audit(config.workspace / config.audit_file)
        self.tools = [t for t in BIRD_TOOLS if t["function"]["name"] in self._allowed()]

    def _allowed(self) -> set[str]:
        """Tools shown to the model: the deployment allowlist, minus what is switched off or not configured."""
        off = set() if self.cfg.allow_python else {"run_python"}
        off |= set() if self.search else {"web_search"}
        return set(self.cfg.allowed_tools) - off

    def run(
        self,
        user: str,
        *,
        history: list[dict] | None = None,
        system: str | None = None,
        thinking: bool = False,
        lang: str | None = None,
    ) -> Run:
        cfg, t0 = self.cfg, time.monotonic()
        run = Run(lang=lang or detect_lang(user))
        ctx = Context(config=cfg, http=self.http, search=self.search)
        messages = list(history or [])
        if not messages or messages[0]["role"] != "system":
            messages.insert(0, {"role": "system", "content": system or DEFAULT_SYSTEM[run.lang]})
        messages.append({"role": "user", "content": guard.defang(user)})
        gpu = meter.GpuMeter(enabled=cfg.measure_gpu or getattr(self.llm, "local", False))
        seen: set[str] = set()
        budget, side_effects, bad_streak, content = cfg.max_context_chars, 0, 0, ""

        for gen in range(cfg.max_steps):
            if time.monotonic() - t0 > cfg.timeout_s:
                run.stop_reason = "timeout"
                break
            with gpu:
                out = self.llm.generate(render_prompt(self.tok, messages, self.tools, thinking), cfg.max_tokens, STOP)
            run.usage.append({k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds")})
            text = out.get("text") or ""
            if thinking and "</think>" not in text:
                text = "<think>" + text + "</think>"  # ran out of budget while reasoning: there is no answer
            parsed = parse_output(text)
            content, run.reasoning = guard.redact(parsed["content"]), parsed["reasoning"]
            calls = parsed["tool_calls"][: cfg.max_calls_per_step]
            if not calls:
                if "<tool_call>" in content:  # opened a call and never closed it
                    content, run.stop_reason = content.split("<tool_call>", 1)[0].strip(), "malformed_output"
                else:
                    run.stop_reason = "answer" if content else "empty_output"
                break
            if gen == cfg.max_steps - 1:
                run.stop_reason = "max_steps"  # the last allowed generation still asks for tools: they are not run
                break
            keys = [
                c["name"] + " " + json.dumps(c["arguments"], sort_keys=True, ensure_ascii=False, default=str)
                for c in calls
            ]
            if any(k in seen for k in keys) or len(set(keys)) < len(keys):
                run.stop_reason = "loop"  # the same call with the same arguments again
                break
            seen.update(keys)
            messages.append(
                {
                    "role": "assistant",
                    "content": parsed["content"],
                    "reasoning_content": parsed["reasoning"],
                    "tool_calls": [{"type": "function", "function": dict(c)} for c in calls],
                }
            )
            ok = 0
            for c in calls:
                step, result = self._call(c["name"], c["arguments"], gen, run, ctx, side_effects)
                side_effects += step.decision in ("allow", "confirmed") and step.tool in guard.SIDE_EFFECT_TOOLS
                ok += step.decision != "rejected"
                result = guard.truncate(result, min(cfg.max_result_chars, budget))
                budget = max(0, budget - len(result))
                step.chars, step.result = len(result), result[:200]
                run.steps.append(step)
                messages.append({"role": "tool", "content": result})
            bad_streak = 0 if ok else bad_streak + 1
            if bad_streak >= 2:
                run.stop_reason = "invalid_tool_calls"  # one retry after a malformed step, not more
                break
        else:
            run.stop_reason = "max_steps"

        run.answer = content if run.stop_reason == "answer" else (content or FALLBACK[run.lang])
        if run.stop_reason == "answer":
            messages.append({"role": "assistant", "content": content})
        run.messages, run.sources, run.drafts, run.files = messages, ctx.sources, ctx.drafts, ctx.files
        run.report = meter.report(
            run.usage,
            wall_seconds=time.monotonic() - t0,
            tool_calls=len(run.steps),
            bytes_fetched=ctx.bytes_fetched,
            measured_wh=gpu.wh,
            wh_per_1k_tokens=cfg.wh_per_1k_tokens,
            calibration_source=cfg.calibration_source,
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

    def _call(self, name: str, raw_args, gen: int, run: Run, ctx: Context, side_effects: int) -> tuple[Step, str]:
        """Validate, gate and execute one tool call. Returns the step record and the text given back to the model."""
        t0 = time.monotonic()
        step = Step(generation=gen, tool=name, arguments=raw_args if isinstance(raw_args, dict) else {})
        args, err = guard.validate_args(name, raw_args, self.cfg.allowed_tools)
        if err:
            step.decision, step.error, result = "rejected", err, f"Error: {err} Correct the call or answer without it."
        else:
            step.arguments = args
            if name != "run_python" or self.cfg.allow_python:  # a switched-off tool only returns "not enabled"
                step.decision = guard.gate(
                    name, args, tainted=run.flagged, side_effects=side_effects, cfg=self.cfg, confirm=self.confirm
                )
            if step.decision in DENIED:
                step.error = step.decision
                result = DENIED[step.decision]
            else:
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
        step.seconds = round(time.monotonic() - t0, 3)
        self.audit.log(
            "tool_call",
            tool=name,
            arguments=guard.short_args(step.arguments),
            seconds=step.seconds,
            chars=len(result),
            flags=step.flags,
            decision=step.decision,
            error=step.error,
        )
        return step, result
