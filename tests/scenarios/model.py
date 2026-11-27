"""A scripted small model for the scenario suite.

FakeClient replays a fixed list of outputs, whatever the harness says in between. A real 4B model reacts to what
it is given (an error message, a reminder, a tool result), so a fixed list cannot measure a harness: an output
written for "the call failed" would be replayed after a call that worked. ``PolicyModel`` instead reads the
conversation it is given (the test tokenizer renders it as JSON) and answers with the first rule that matches.
Rules imitate the failure modes seen on the live endpoint (docs/HARNESS.md § 2 bis and § 10): wrong argument
names, a JSON call instead of the trained XML, a call written inside prose, empty arguments, an invented tool,
repeating a call, answering before reading, forgetting a sub-request, the wrong language, dropping figures.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field


class Tok:
    """Stands in for the tokenizer: the 'prompt' is the JSON of what the chat template was given."""

    def apply_chat_template(
        self, messages, tools=None, enable_thinking=False, tokenize=False, add_generation_prompt=False
    ):
        names = [t["function"]["name"] for t in tools or []]
        return json.dumps({"tools": names, "think": enable_thinking, "messages": messages}, ensure_ascii=False)


def call(name: str, **args) -> str:
    """A tool call in the trained XML format."""
    params = "".join(
        f"<parameter={k}>\n{v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}\n</parameter>\n"
        for k, v in args.items()
    )
    return f"<tool_call>\n<function={name}>\n{params}</function>\n</tool_call>"


def json_call(name: str, args: dict, tail: str = "") -> str:
    """A tool call in the JSON (Hermes) format a small model falls back to, sometimes with text after it."""
    body = json.dumps({"name": name, "arguments": args}, ensure_ascii=False)
    return f"<tool_call>\n{body}\n</tool_call>{tail}"


# the harness's last-chance instruction (agent.LAST_CHANCE): only the rules written for it answer it
LAST_CHANCE = r"\[(?:Consigne interne|Internal instruction)\]"


@dataclass
class View:
    """What the model is given at one generation."""

    messages: list[dict]
    tools: list[str]

    @property
    def turn(self) -> list[dict]:
        """Messages since the last user message (this request's own steps)."""
        idx = max((i for i, m in enumerate(self.messages) if m.get("role") == "user"), default=0)
        return self.messages[idx + 1 :]

    @property
    def user(self) -> str:
        idx = max((i for i, m in enumerate(self.messages) if m.get("role") == "user"), default=0)
        return str(self.messages[idx].get("content") or "")

    @property
    def tail(self) -> str:
        """Text the model just received: the tool messages after its last output, or the user message."""
        out = []
        for m in reversed(self.messages):
            if m.get("role") == "assistant":
                break
            out.append(str(m.get("content") or ""))
        return "\n".join(reversed(out))

    @property
    def gens(self) -> int:
        return sum(m.get("role") == "assistant" for m in self.turn)

    def called(self, tool: str) -> bool:
        return any(
            (tc.get("function") or {}).get("name") == tool
            for m in self.turn
            if m.get("role") == "assistant"
            for tc in m.get("tool_calls") or []
        )

    def results(self) -> list[tuple[str, str]]:
        """(tool, text) of every tool message of this request, in order; a reminder has the tool name '?'."""
        out, names = [], []
        for m in self.turn:
            if m.get("role") == "assistant":
                names = [(tc.get("function") or {}).get("name") for tc in m.get("tool_calls") or []]
            elif m.get("role") == "tool":
                out.append((names.pop(0) if names else "?", str(m.get("content") or "")))
        return out

    def done(self, tool: str) -> bool:
        """``tool`` was called and its result was not an error."""
        return any(n == tool and not c.lstrip().startswith("Error") for n, c in self.results())

    def has(self, pattern: str) -> bool:
        return bool(re.search(pattern, self.tail, re.I | re.S))


@dataclass
class Rule:
    when: Callable[[View], bool] | str | None
    say: Callable[[View], str] | str
    times: int = 99
    used: int = 0

    def matches(self, v: View) -> bool:
        if self.used >= self.times:
            return False
        if self.when is None:
            return True
        if isinstance(self.when, str):
            return v.has(self.when)
        return bool(self.when(v))


def R(when, say, times: int = 99) -> Rule:  # noqa: N802 - short constructor used in long scenario tables
    return Rule(when, say, times)


@dataclass
class PolicyModel:
    """generate(prompt) -> the first matching rule's text. Records every View it was given."""

    rules: list[Rule]
    default: str = ""
    views: list[View] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def generate(self, prompt: str, max_tokens: int, stop: list[str], *, on_token=None, **_) -> dict:
        self.prompts.append(prompt)
        data = json.loads(prompt)
        v = View(data["messages"], data["tools"])
        self.views.append(v)
        text = self.default
        last = data["messages"][-1] if data["messages"] else {}
        salvage = last.get("role") == "user" and re.search(LAST_CHANCE, str(last.get("content") or ""))
        for r in [r for r in self.rules if (r.when == LAST_CHANCE) == bool(salvage)]:
            if r.matches(v):
                r.used += 1
                text = r.say(v) if callable(r.say) else r.say
                break
        if on_token:
            for i in range(0, len(text), 9):
                on_token(text[i : i + 9])
        return {"text": text, "prompt_tokens": len(prompt) // 4, "completion_tokens": len(text) // 4, "seconds": 0.0}


# ------------------------------------------------------------------ small predicates used by the scenarios


def first(v: View) -> bool:
    """The first generation of the request."""
    return v.gens == 0


def after(tool: str) -> Callable[[View], bool]:
    """The tool just returned something that is not an error."""

    def check(v: View) -> bool:
        res = v.results()
        return bool(res) and res[-1][0] == tool and not res[-1][1].lstrip().startswith("Error")

    return check


def error(v: View) -> bool:
    return bool(re.match(r"\s*Error", v.tail))


def reminded(*words: str) -> Callable[[View], bool]:
    """The harness reminded the model of something (a tool message that is not a tool result) naming ``words``."""

    def check(v: View) -> bool:
        t = v.tail
        return all(re.search(w, t, re.I) for w in words) and bool(
            re.search(r"not done|missing|manque|still|do it now|did not|is not|no file|no chart|answer in|"
                      r"figures|already called|use (?:that|this) result|tu n'as pas|pas encore", t, re.I)
        )  # fmt: skip

    return check
