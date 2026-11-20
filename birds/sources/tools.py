"""Tool-calling / agentic sources.

Every upstream format (Hermes `<tool_call>{json}</tool_call>` text, ShareGPT `from/value`, JSON-string
`messages`, `function_call`, OpenAI `tool_calls` with string arguments, ...) is parsed into the unified
record of birds.schema: structured tool calls, `tools` in OpenAI function format, tool results as
`role: tool`, reasoning in `reasoning_content`.

Shared rules (see `_finish`):
  * system prompts that only describe the upstream tool protocol are removed (the chat template writes
    its own); what is left must be <= MAX_SYSTEM characters;
  * a call to an undeclared tool, a result without a call, a result count that differs from the call
    count, malformed JSON, CJK text, a non English/French user, an assistant that claims another
    vendor's identity, an empty final answer: the row is dropped;
  * long agent traces (sources created with `budget=`) are cut to the longest prefix that ends on an
    assistant turn and fits the character budget; such records get the task suffix `_prefix` so the
    mix can tell complete conversations from "next step" examples.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re

from birds.schema import FORBIDDEN

from . import Source

MAX_SYSTEM = 6000  # characters of system prompt left after removing the tool protocol
BUDGET = 15000  # characters (tools + messages) that roughly fit 4096 tokens; the builder has the last word
TRACE_BUDGET = 11000  # code and JSON heavy traces tokenise at ~3 characters per token
TOOLS_BUDGET = 5000  # characters of tool definitions kept when a huge toolbox is pruned

# Toucan judge scores (all on a 1-5 scale). A row is kept when the question's `overall_score` (mean of
# six question-quality scores) is >= 4.0 and the response is rated >= 4 for completeness and >= 3 for
# conciseness. Rows without scores (the `irrelevant` subset, the SFT config) are not used.
TOUCAN_MIN_QUESTION = 4.0
TOUCAN_MIN_COMPLETENESS = 4
TOUCAN_MIN_CONCISENESS = 3

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯＀-￯]")
_NON_LATIN = re.compile(r"[Ͱ-῿Ⰰ-퟿]")
_LETTER = re.compile(r"[^\W\d_]")
_WORD = re.compile(r"[a-zàâäçéèêëîïôöùûüÿœñáíóúãõß']+")
_VENDORS = (
    r"(?:ChatGPT|OpenAI|GPT-?[345][\w.-]*|Claude|Anthropic|Gemini|Bard|Google DeepMind|Kimi|Moonshot(?: AI)?"
    r"|Qwen|Tongyi|Alibaba(?: Cloud)?|DeepSeek|GLM|Zhipu(?: AI)?|Nous Research|Hermes|Llama|Meta AI|Mistral)"
)
_IDENTITY = re.compile(
    r"\b(?:I am|I'm|I’m|as an?|you are|you're|my name is|call me|this is)\s+(?:an?\s+|the\s+)?(?:\w+\s+){0,3}?"
    + _VENDORS
    + r"\b"
    r"|\b(?:developed|created|trained|made|built|designed|powered)\s+by\s+(?:the\s+)?(?:\w+\s+){0,2}?"
    + _VENDORS
    + r"\b"
    r"|\b(?:je suis|en tant qu[e'’])\s*(?:une?\s+)?(?:\w+\s+){0,3}?" + _VENDORS + r"\b",
    re.I,
)
_ERROR_ANSWER = re.compile(
    r"^\s*(?:error\b|traceback|\{\s*\"error\"|\[error)|i (?:have )?encountered an? (?:\w+ )?error|an? (?:internal|unexpected) error occurred",
    re.I,
)
_EN = frozenset(
    "the and of to is in for that with you this what can are i me my on how please it need want have from an "
    "would could about your do does which will be".split()
)
_FR = frozenset(
    "le les des est et une pour je vous dans du avec sur pas quel quelle quels quelles comment mon nous ce au "
    "aux peux veux puis merci bonjour ma mes notre votre qui où cette ces il elle sont ai".split()
)
_OTHER = frozenset(
    "el los las por para qué cómo del não você uma os das dos eu meu minha der die und ist nicht ich ein eine "
    "für mit di che per sono della é são y está quiero necesito puedes preciso kann bitte wie het een van "
    "com em um na no se lo al es con wir sie auf den zu och att jag".split()
)

_TYPES = {
    "dict": "object",
    "object": "object",
    "map": "object",
    "json": "object",
    "str": "string",
    "string": "string",
    "text": "string",
    "date": "string",
    "datetime": "string",
    "enum": "string",
    "int": "integer",
    "integer": "integer",
    "long": "integer",
    "float": "number",
    "number": "number",
    "double": "number",
    "decimal": "number",
    "numeric": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "list": "array",
    "array": "array",
    "set": "array",
    "tuple": "array",
    "sequence": "array",
    "iterable": "array",
    "null": "null",
    "none": "null",
    "nonetype": "null",
}


_drops: dict[str, int] | None = None  # debugging aid: set to {} to count why rows are dropped


def _drop(reason: str) -> list:
    if _drops is not None:
        _drops[reason] = _drops.get(reason, 0) + 1
    return []


# ----------------------------------------------------------------------------------------------- helpers
def _loads(x):
    """json.loads for strings (None when it fails); other values are returned unchanged."""
    if not isinstance(x, str):
        return x
    try:
        return json.loads(x, strict=False)  # strict=False: raw newlines inside strings are common upstream
    except (ValueError, TypeError, RecursionError):
        return None


def _json_objects(text: str) -> list | None:
    """Concatenated JSON values ("{...}\n{...}" or one "[...]") -> list; None when the text is not only JSON."""
    dec, out, i = json.JSONDecoder(strict=False), [], 0
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except (ValueError, RecursionError):
            return None
        out.append(obj)
    return out[0] if len(out) == 1 and isinstance(out[0], list) else out


def _loads_loose(x):
    """JSON first, then a Python literal (some upstream calls are written with single quotes)."""
    v = _loads(x)
    if v is None and isinstance(x, str):
        try:
            v = ast.literal_eval(x.strip())
        except (ValueError, SyntaxError, MemoryError, RecursionError, TypeError):
            v = None
    return v


def _text(x) -> str:
    if x is None:
        return ""
    return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)


def _type(t):
    """Map an upstream type name ('str, optional', 'List[int]', 'dict', ...) to a JSON-schema type or None."""
    if isinstance(t, list):
        out = [x for x in (_type(i) for i in t) if x]
        return out or None
    if not isinstance(t, str):
        return None
    base = re.split(r"[,\[( ]", t.strip(), maxsplit=1)[0].lower()
    return _TYPES.get(base)


def _schema(s, depth: int = 0):
    """Normalise a JSON-schema fragment: canonical `type` names, object schemas always have `properties`."""
    if not isinstance(s, dict) or depth > 12:
        return s
    out = {}
    for k, v in s.items():
        if k == "type":
            t = _type(v)
            if t:
                out["type"] = t
        elif k in ("properties", "$defs", "definitions", "patternProperties") and isinstance(v, dict):
            out[k] = {str(n): _schema(p, depth + 1) if isinstance(p, dict) else {} for n, p in v.items()}
        elif k in ("items", "additionalProperties", "not") and isinstance(v, dict):
            out[k] = _schema(v, depth + 1)
        elif k in ("anyOf", "oneOf", "allOf") and isinstance(v, list):
            out[k] = [_schema(i, depth + 1) for i in v]
        elif k == "required" and not isinstance(v, list):
            continue  # per-property `required: true` flags are not JSON schema
        else:
            out[k] = v
    if out.get("type") == "object" and not isinstance(out.get("properties"), dict):
        out["properties"] = {}
    return out


def _parameters(p) -> dict | None:
    """Tool parameters as a JSON-schema object. Accepts a schema or a bare {name: {type, description}} map."""
    if p is None or p == {}:
        return {"type": "object", "properties": {}}
    p = _loads(p) if isinstance(p, str) else p
    if not isinstance(p, dict):
        return None
    if isinstance(p.get("properties"), dict) or p.get("type") in ("object", "dict") or "$ref" in p:
        out = _schema({**p, "type": "object"})
        props = out["properties"]
        req = [r for r in out.get("required") or [] if isinstance(r, str) and r in props]
        for name, spec in p.get("properties", {}).items() if isinstance(p.get("properties"), dict) else []:
            if isinstance(spec, dict) and spec.get("required") is True and name not in req:
                req.append(name)
        out.pop("required", None)
        if req:
            out["required"] = req
        return out
    if not all(isinstance(v, dict) for v in p.values()):
        return None
    props, req = {}, []  # xlam style: {"arg": {"description", "type": "str, optional", "default"}}
    for name, spec in p.items():
        props[str(name)] = _schema(spec)
        t = spec.get("type")
        if isinstance(t, str) and "optional" not in t.lower() and "default" not in t.lower():
            req.append(str(name))
    return {"type": "object", "properties": props, **({"required": req} if req else {})}


def _tool(t) -> dict | None:
    """One tool definition in OpenAI function format, or None when it cannot be understood."""
    t = _loads(t) if isinstance(t, str) else t
    if not isinstance(t, dict):
        return None
    fn = t.get("function") if isinstance(t.get("function"), dict) else t
    name = fn.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    params = _parameters(fn.get("parameters", fn.get("input_schema", fn.get("inputSchema"))))
    if params is None:
        return None
    return {
        "type": "function",
        "function": {"name": name.strip(), "description": _text(fn.get("description")).strip(), "parameters": params},
    }


def _tools(raw) -> list[dict] | None:
    """A list of tool definitions (None when one is malformed or two different tools share a name)."""
    raw = _loads(raw) if isinstance(raw, str) else raw
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    out, names = [], set()
    for t in raw:
        t = _tool(t)
        if t is None:
            return None
        if t["function"]["name"] in names:
            if t in out:  # exact duplicate upstream: keep one
                continue
            return None
        names.add(t["function"]["name"])
        out.append(t)
    return out


def _call(name, arguments) -> dict | None:
    """A structured call; arguments may be a dict, a JSON string or missing."""
    if arguments is None or (isinstance(arguments, str) and not arguments.strip()):
        arguments = {}
    elif isinstance(arguments, str):
        arguments = _loads_loose(arguments)
    if not isinstance(name, str) or not name.strip() or not isinstance(arguments, dict):
        return None
    return {"type": "function", "function": {"name": name.strip(), "arguments": arguments}}


def _split_think(text: str) -> tuple[str, str] | None:
    """('reasoning', 'rest') from text with an inline <think> block; None when the block is not closed."""
    if "</think>" in text:
        head, rest = text.split("</think>", 1)
        if "<think>" in rest or "</think>" in rest:
            return None
        pre, _, reasoning = head.partition("<think>") if "<think>" in head else ("", "", head)
        if "<think>" in reasoning:
            return None
        return reasoning.strip(), (pre.strip() + "\n\n" + rest.strip()).strip()
    if "<think>" in text:
        return None
    return "", text.strip()


_TOOL_CALL = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
_TOOL_RESPONSE = re.compile(r"<tool_response>(.*?)</tool_response>", re.S)
_CODE = re.compile(r"<code>(.*)</code>", re.S)
_TOOLCALL_LIST = re.compile(r"<TOOLCALL>(.*?)</TOOLCALL>", re.S)


def _hermes_turn(text: str) -> dict | None:
    """Assistant message from Hermes text: `<think>..</think> words <tool_call>{json}</tool_call>...`."""
    split = _split_think(text or "")
    if split is None:
        return None
    reasoning, rest = split
    calls = []
    for raw in _TOOL_CALL.findall(rest):
        code = _CODE.search(raw)  # S1 PythonInterpreter: `{"name":..,"arguments":{}}<code>...</code>`
        obj = _loads_loose(raw[: code.start()] if code else raw)
        call = _call(obj.get("name"), obj.get("arguments", obj.get("parameters"))) if isinstance(obj, dict) else None
        if call is None:
            return None
        if code:
            call["function"]["arguments"]["code"] = code.group(1).strip("\n")
        calls.append(call)
    for raw in _TOOLCALL_LIST.findall(rest):  # When2Call style: <TOOLCALL>[{"name":..,"arguments":..}]</TOOLCALL>
        objs = _loads_loose(raw)
        for obj in objs if isinstance(objs, list) else [None]:
            call = _call(obj.get("name"), obj.get("arguments")) if isinstance(obj, dict) else None
            if call is None:
                return None
            calls.append(call)
    content = _TOOLCALL_LIST.sub("", _TOOL_CALL.sub("", rest)).strip()
    msg = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    if calls:
        msg["tool_calls"] = calls
    return msg


def _hermes_results(text: str) -> list[dict]:
    """Tool messages from Hermes text: one per <tool_response> block, `{"name","content"}` wrappers removed."""
    blocks = _TOOL_RESPONSE.findall(text or "")
    if not blocks:
        blocks = [text or ""]
    out = []
    for b in blocks:
        obj = _loads(b.strip())
        if isinstance(obj, dict) and "content" in obj and set(obj) <= {"name", "content", "tool_call_id", "id"}:
            b = _text(obj["content"])
        out.append({"role": "tool", "content": b.strip()})
    return out


_PROTOCOL_START = re.compile(
    r"<\|im_system\|>tool_declare|^#+ *Tools\s*$|You are a function calling AI model|"
    r"You (?:may|can) call one or more functions|You are provided with function signatures|"
    r"You have access to the following (?:tools|functions)",
    re.M,
)
_TOOLS_BLOCK = re.compile(r"<tools>(.*?)</tools>", re.S)


def _strip_protocol(system: str) -> tuple[str, list | None]:
    """(system prompt without the upstream tool protocol, tools declared in it or None).

    The protocol runs from its first marker to the last `</tool_call>` example (or `</tools>`, or the
    Kimi `<|im_end|>`); text before and after it is genuine instruction and is kept.
    """
    system = system or ""
    declared = None
    blocks = [b for b in _TOOLS_BLOCK.findall(system) if b.strip()]  # "<tools></tools> XML tags" is not a block
    if blocks:
        declared = _json_objects(max(blocks, key=len))
    elif "<|im_middle|>" in system:
        declared = _loads(system.split("<|im_middle|>", 1)[1].split("<|im_end|>", 1)[0])
    start = _PROTOCOL_START.search(system)
    if not start:
        return system.strip(), declared
    end = max(
        system.rfind(tag) + len(tag) if tag in system else -1 for tag in ("</tool_call>", "</tools>", "<|im_end|>")
    )
    if end < start.start():
        end = len(system)
    kept = (system[: start.start()].strip() + "\n\n" + system[end:].strip()).strip()
    return kept, declared


def _merge(msgs: list[dict]) -> list[dict]:
    """Merge consecutive assistant messages (upstream often splits words / reasoning / each call)."""
    out: list[dict] = []
    for m in msgs:
        prev = out[-1] if out else None
        if m["role"] == "assistant" and prev and prev["role"] == "assistant":
            prev["content"] = "\n\n".join(x for x in (prev["content"].strip(), m["content"].strip()) if x)
            r = "\n\n".join(
                x for x in (prev.get("reasoning_content", "").strip(), m.get("reasoning_content", "").strip()) if x
            )
            if r:
                prev["reasoning_content"] = r
            if m.get("tool_calls"):
                prev["tool_calls"] = (prev.get("tool_calls") or []) + m["tool_calls"]
        else:
            out.append(dict(m))
    return out


def _lang(msgs: list[dict]) -> str | None:
    """'en' / 'fr' from the user turns; None for any other language or script."""
    text = " ".join(m["content"] for m in msgs if m["role"] == "user")
    letters = len(_LETTER.findall(text))
    if letters and len(_NON_LATIN.findall(text)) > 0.2 * letters:
        return None
    words = _WORD.findall(text.lower())
    en, fr, other = (sum(w in s for w in words) for s in (_EN, _FR, _OTHER))
    if other > max(en, fr) and other >= 2:
        return None
    return "fr" if fr > en and fr >= 2 else "en"


def _size(m: dict) -> int:
    n = len(m["content"]) + len(m.get("reasoning_content") or "")
    return n + sum(len(json.dumps(c, ensure_ascii=False)) for c in m.get("tool_calls") or [])


def _well_formed(msgs: list[dict]) -> bool:
    """[system] user (assistant [tool x number of calls])* ... with no dangling call inside the conversation."""
    pending = 0  # tool results still expected
    prev = None
    for i, m in enumerate(msgs):
        role = m["role"]
        if role == "system":
            if i:
                return False
        elif role == "tool":
            if pending <= 0:
                return False
            pending -= 1
        else:
            if pending > 0:
                return False
            if role == "user":
                if not m["content"].strip() or prev == "user":
                    return False
            elif role == "assistant":
                if prev not in ("user", "tool"):
                    return False
                calls = m.get("tool_calls") or []
                if not calls and not m["content"].strip():
                    return False
                pending = len(calls) if i < len(msgs) - 1 else 0
            else:
                return False
        prev = role
    return pending == 0


def _finish(
    msgs: list[dict],
    tools: list[dict] | None,
    *,
    task: str | None = None,
    complete: bool = True,
    budget: int = 0,
    max_system: int = MAX_SYSTEM,
    lang: str | None = None,
) -> list[dict]:
    """Common checks; returns [record] or [].

    complete: the conversation must end on an assistant answer in words (no pending call).
    budget:   when > 0, cut the conversation to the longest prefix ending on an assistant turn whose
              size (tools + messages, characters) fits; the task gets the suffix `_prefix` when cut.
    """
    if tools is None:
        return _drop("bad tools")
    msgs = _merge([m for m in msgs if not (m["role"] == "system" and not m["content"].strip())])
    cut = False
    if budget:
        while msgs and msgs[-1]["role"] != "assistant":  # upstream trace that stops on a tool result / user turn
            msgs, cut = msgs[:-1], True
        used = len(json.dumps(tools, ensure_ascii=False)) if tools else 0
        last = -1
        for i, m in enumerate(msgs):
            used += _size(m)
            if used > budget:
                break
            if m["role"] == "assistant":
                last = i
        if last < 0:
            return _drop("nothing fits the budget")
        cut = cut or last < len(msgs) - 1
        msgs = msgs[: last + 1]
    if len(msgs) < 2 or msgs[-1]["role"] != "assistant" or not _well_formed(msgs):
        return _drop("malformed turn order")
    final = msgs[-1]
    if complete and not cut and (final.get("tool_calls") or not final["content"].strip()):
        return _drop("no final answer")
    if not final.get("tool_calls") and _ERROR_ANSWER.search(final["content"][:400]):
        return _drop("error answer")
    if msgs[0]["role"] == "system" and len(msgs[0]["content"]) > max_system:
        return _drop("system prompt too long")
    declared = {t["function"]["name"] for t in tools}
    if tools and _CJK.search(json.dumps(tools, ensure_ascii=False)):
        return _drop("CJK in tools")
    for m in msgs:
        text = m["content"] + (m.get("reasoning_content") or "")
        if any(f in text for f in FORBIDDEN) or _CJK.search(text):
            return _drop("markup or CJK in text")
        if m["role"] in ("assistant", "system") and _IDENTITY.search(text):
            return _drop("vendor identity")
        for c in m.get("tool_calls") or []:
            if c["function"]["name"] not in declared or _CJK.search(json.dumps(c, ensure_ascii=False)):
                return _drop("undeclared tool or CJK in call")
    lang = lang or _lang(msgs)
    if lang is None:
        return _drop("language")
    rec = {"messages": msgs, "lang": lang, "thinking": any((m.get("reasoning_content") or "").strip() for m in msgs)}
    if tools:
        rec["tools"] = tools
    if task:
        rec["task"] = task + ("_prefix" if cut else "")
    return [rec]


def _prune_tools(tools: list[dict], msgs: list[dict], limit: int = TOOLS_BUDGET) -> list[dict]:
    """Keep every tool the conversation calls, then the others in upstream order while they fit `limit` chars."""
    used = {c["function"]["name"] for m in msgs for c in m.get("tool_calls") or []}
    size = sum(len(json.dumps(t, ensure_ascii=False)) for t in tools if t["function"]["name"] in used)
    keep = set(used)
    for t in tools:
        n = len(json.dumps(t, ensure_ascii=False))
        if t["function"]["name"] not in keep and size + n <= limit:
            keep.add(t["function"]["name"])
            size += n
    return [t for t in tools if t["function"]["name"] in keep]


def _openai_messages(raw) -> list[dict] | None:
    """Messages in (loose) OpenAI format -> unified messages. Handles `function_call`, `tool_calls` with
    string arguments, `function`/`tool` result roles, None content and inline <think> blocks."""
    raw = _loads(raw) if isinstance(raw, str) else raw
    if not isinstance(raw, list):
        return None
    out = []
    for m in raw:
        if not isinstance(m, dict):
            return None
        role, content = m.get("role"), m.get("content")
        if isinstance(content, list):  # [{"type": "text", "text": ...}]
            if not all(isinstance(p, dict) and isinstance(p.get("text"), str) for p in content):
                return None
            content = "\n".join(p["text"] for p in content)
        content = _text(content)
        if role in ("system", "user"):
            out.append({"role": role, "content": content.strip()})
        elif role in ("tool", "function", "tool_response", "observation"):
            out += (
                _hermes_results(content)
                if "<tool_response>" in content
                else [{"role": "tool", "content": content.strip()}]
            )
        elif role == "assistant":
            msg = _hermes_turn(content)
            if msg is None:
                return None
            reasoning = _text(m.get("reasoning_content") or m.get("reasoning")).strip()
            if reasoning:
                msg["reasoning_content"] = "\n\n".join(x for x in (reasoning, msg.get("reasoning_content", "")) if x)
            calls = list(msg.get("tool_calls") or [])
            structured = list(m.get("tool_calls") or []) + ([m["function_call"]] if m.get("function_call") else [])
            for c in structured:
                fn = c.get("function") if isinstance(c, dict) and isinstance(c.get("function"), dict) else c
                call = _call(fn.get("name"), fn.get("arguments")) if isinstance(fn, dict) else None
                if call is None:
                    return None
                calls.append(call)
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            return None
    return out


def _sharegpt_messages(raw) -> list[dict] | None:
    """ShareGPT `[{from, value}]` with Hermes markup -> unified messages."""
    if not isinstance(raw, list):
        return None
    out = []
    for m in raw:
        if not isinstance(m, dict) or not isinstance(m.get("value"), str):
            return None
        who, value = m.get("from"), m["value"]
        if who == "system":
            out.append({"role": "system", "content": value})
        elif who in ("human", "user"):
            out.append({"role": "user", "content": value.strip()})
        elif who in ("gpt", "assistant"):
            msg = _hermes_turn(value)
            if msg is None:
                return None
            out.append(msg)
        elif who in ("tool", "function", "observation"):
            out += _hermes_results(value)
        else:
            return None
    return out


def _system_and_tools(msgs: list[dict], tools_column) -> tuple[list[dict], list[dict] | None]:
    """Remove the tool protocol from the system prompt; tools come from the column, else from the prompt."""
    declared = None
    if msgs and msgs[0]["role"] == "system":
        kept, declared = _strip_protocol(msgs[0]["content"])
        msgs = [{"role": "system", "content": kept}] + msgs[1:]
    column = _loads(tools_column) if isinstance(tools_column, str) else tools_column
    return msgs, _tools(column if column else declared)


# ------------------------------------------------------------------------------------------- converters
def _score(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def convert_toucan(row: dict) -> list[dict]:
    """Agent-Ark/Toucan-1.5M (configs Kimi-K2, OSS, Qwen3): judge-filtered MCP tool-use trajectories."""
    q, a = _loads(row.get("question_quality_assessment")), _loads(row.get("response_quality_assessment"))
    if not isinstance(q, dict) or not isinstance(a, dict):
        return _drop("no judge scores")
    completeness, conciseness = a.get("completeness"), a.get("conciseness")
    if not isinstance(completeness, dict) or not isinstance(conciseness, dict):
        return _drop("no judge scores")
    if (
        _score(q.get("overall_score")) < TOUCAN_MIN_QUESTION
        or _score(completeness.get("score")) < TOUCAN_MIN_COMPLETENESS
        or _score(conciseness.get("score")) < TOUCAN_MIN_CONCISENESS
    ):
        return _drop("below judge threshold")
    msgs = _openai_messages(row.get("messages"))
    if not msgs:
        return _drop("bad messages")
    msgs, tools = _system_and_tools(msgs, row.get("available_tools") or row.get("tools"))
    if not tools:
        return _drop("bad tools")
    multi = sum(m["role"] == "user" for m in msgs) > 1
    return _finish(msgs, tools, task="tool_multi_turn" if multi else "tool_call")


def convert_nemotron(row: dict) -> list[dict]:
    """nvidia/Nemotron-SFT-Agentic-v4: OpenAI messages + tools, reasoning in `reasoning_content`."""
    msgs = _openai_messages(row.get("messages"))
    tools = _tools(row.get("tools"))
    if not msgs or not tools:
        return _drop("bad messages or tools")
    # many rows end on the next tool call (the label is the call itself): that is a valid record
    return _finish(msgs, tools, task="tool_call", complete=False)


def convert_nemotron_knowledge(row: dict) -> list[dict]:
    """knowledge_agent split: long support-agent traces with retrieval; cut to the character budget."""
    msgs = _openai_messages(row.get("messages"))
    tools = _tools(row.get("tools"))
    if not msgs or not tools:
        return _drop("bad messages or tools")
    return _finish(msgs, tools, task="knowledge_agent", budget=BUDGET)


def convert_when2call(row: dict) -> list[dict]:
    """nvidia/When2Call train_sft: tools (JSON strings, `type: dict`) + a call, a follow-up question or an
    'I cannot do that with these tools' answer."""
    msgs = _openai_messages(row.get("messages"))
    raw = row.get("tools")
    tools = _tools(list(raw) if isinstance(raw, list | tuple) else raw)
    if not msgs or tools is None:
        return _drop("bad messages or tools")
    final = msgs[-1]
    task = "tool_call" if final.get("tool_calls") else "tool_abstain"
    return _finish(msgs, tools, task=task, complete=False)


_IRRELEVANT = (
    "I can't help with that using the tools I have here: {tools} {cover} something else, and none of them can {do} this request.",
    "None of the tools available to me ({tools}) can handle this request, so I'm not going to call any of them. "
    "With a tool suited to this, I could help.",
    "I don't have a tool for this. The {only} I can call {are} {tools}, which {does} not cover what you're asking.",
    "This request is outside what my available tools can do ({tools}), so I can't look it up or carry it out here.",
    "The available tools ({tools}) are not relevant to this request, so I can't complete it with them.",
    "I'm unable to do this with the tools I've been given. {tools} {cover} other needs; calling {them} would not answer your question.",
    "No tool I have access to fits this request: {tools} {do2} not provide what you need, so I won't make a tool call.",
    "I can't fulfil this one: it needs a capability that {tools} {do2} not offer.",
)


def convert_xlam_irrelevance(row: dict) -> list[dict]:
    """MadeAgents/xlam-irrelevance-7.5k: `query`, `tools` (xlam format) and `answers == []` (no tool applies).
    Upstream has no answer text, so the assistant turn is a templated abstention naming the tools."""
    query, tools = row.get("query"), _tools(row.get("tools"))
    if not isinstance(query, str) or not query.strip() or not tools or _loads(row.get("answers")) != []:
        return _drop("bad query, tools or answers")
    names = [f"`{t['function']['name']}`" for t in tools]
    many = len(names) > 1
    listed = names[0] if not many else ", ".join(names[:-1]) + " and " + names[-1]
    pick = int(hashlib.sha1(query.encode()).hexdigest(), 16) % len(_IRRELEVANT)
    answer = _IRRELEVANT[pick].format(
        tools=listed,
        cover="cover" if many else "covers",
        do="handle",
        only="only tools" if many else "only tool",
        are="are" if many else "is",
        does="do" if many else "does",
        them="them" if many else "it",
        do2="do" if many else "does",
    )
    msgs = [
        {"role": "user", "content": query.strip()},
        {"role": "assistant", "content": answer[0].upper() + answer[1:]},
    ]
    return _finish(msgs, tools, task="tool_irrelevant")


def convert_hermes_fc(row: dict) -> list[dict]:
    """NousResearch/hermes-function-calling-v1, function-calling configs (ShareGPT + Hermes markup)."""
    msgs = _sharegpt_messages(row.get("conversations"))
    if not msgs:
        return _drop("bad messages")
    msgs, tools = _system_and_tools(msgs, row.get("tools"))
    if not tools:
        return _drop("bad tools")
    return _finish(msgs, tools, task="tool_call", complete=False)


def convert_hermes_json(row: dict) -> list[dict]:
    """json-mode configs: the system prompt holds the JSON schema, the answer must be valid JSON. No tools."""
    msgs = _sharegpt_messages(row.get("conversations"))
    if not msgs or any(m["role"] == "tool" or m.get("tool_calls") for m in msgs):
        return _drop("bad messages")
    final = msgs[-1]["content"].strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", final, re.S)
    if _loads(fenced.group(1) if fenced else final) is None:
        return _drop("answer is not JSON")
    return _finish(msgs, [], task="json_mode")


def convert_hermes_agent_traces(row: dict) -> list[dict]:
    """lambda/hermes-agent-reasoning-traces: long ShareGPT agent traces with <think>, <tool_call>, <tool_response>.
    The toolbox (up to 25k characters) is pruned to the tools the trace uses plus what fits TOOLS_BUDGET."""
    msgs = _sharegpt_messages(row.get("conversations"))
    if not msgs:
        return _drop("bad messages")
    msgs, tools = _system_and_tools(msgs, row.get("tools"))
    if not tools:
        return _drop("bad tools")
    declared = {t["function"]["name"] for t in tools}
    if any(c["function"]["name"] not in declared for m in msgs for c in m.get("tool_calls") or []):
        return _drop("undeclared tool")
    return _finish(msgs, _prune_tools(tools, msgs), task="agent_trace", budget=TRACE_BUDGET)


_PYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "PythonInterpreter",
        "description": "Executes Python code in a sandboxed environment. Any output you want to see must be printed "
        "to standard output using the print() function.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "The Python code to execute."}},
            "required": ["code"],
        },
    },
}


def _s1_tools(system: str) -> list[dict] | None:
    """Tools of the S1 system prompt: one JSON object per `{"type": "function"` chunk. The PythonInterpreter
    entry is not valid JSON upstream (unescaped quotes) and asks for code in a <code> block after empty
    arguments; it is replaced by a normal tool with a `code` argument (calls are converted in `_hermes_turn`)."""
    blocks = [b for b in _TOOLS_BLOCK.findall(system) if b.strip()]
    if not blocks:
        return None
    out = []
    for chunk in re.split(r'\n(?=\{"type": "function")', max(blocks, key=len).strip()):
        if chunk.startswith('{"type": "function", "function": {"name": "PythonInterpreter"'):
            out.append(_PYTHON_TOOL)
        else:
            out.append(_loads_loose(chunk))  # some entries use Python literals (False)
    return _tools(out)


def convert_s1_deepresearch(row: dict) -> list[dict]:
    """ScienceOne-AI/S1-DeepResearch-15k: search/visit research traces, Hermes markup inside OpenAI messages."""
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    if meta.get("language") not in (None, "en"):
        return _drop("language")
    msgs = _openai_messages(row.get("messages"))
    if not msgs or _CJK.search(" ".join(m["content"] for m in msgs if m["role"] != "tool")):
        return _drop("bad messages or CJK")
    if msgs[0]["role"] != "system":
        return _drop("bad tools")
    tools = _s1_tools(msgs[0]["content"])
    if not tools:
        return _drop("bad tools")
    msgs = [{"role": "system", "content": _strip_protocol(msgs[0]["content"])[0]}] + msgs[1:]
    return _finish(msgs, tools, task="deep_research", budget=BUDGET, lang="en")


def convert_deepresearch_sft(row: dict) -> list[dict]:
    """FractalAIResearch/DeepResearch-SFT: system prompt + research trace -> `<think>plan</think>report`."""
    system, prompt, report = row.get("system_prompt"), row.get("prompt"), row.get("deepresearch_report")
    if not all(isinstance(x, str) and x.strip() for x in (system, prompt, report)):
        return _drop("empty field")
    turn = _hermes_turn(report)
    if turn is None or turn.get("tool_calls") or not turn.get("reasoning_content") or len(turn["content"]) < 500:
        return _drop("bad report")
    # the prompt is a flattened trace ("USER:... ASSISTANT:... <tool_call>..."): neutralise its markup, it is plain input here
    user = prompt.strip()
    for tag in FORBIDDEN:
        user = user.replace(tag, tag.replace("<", "[").replace(">", "]"))
    # the prompt asks for `<think>[Plan]</think>[Report]`: say the same thing without the control markup
    system = system.strip().replace(
        "<think>[Plan here]</think>[Report here]", "thinking: [Plan here], then answer: [Report here]"
    )
    system = system.replace("enclosed within the <think></think>", "kept in your thinking")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}, turn]
    return _finish(msgs, [], task="research_report", max_system=6500, lang="en")


# --------------------------------------------------------------------------------------------- registry
_TOUCAN = "Agent-Ark/Toucan-1.5M"
_HERMES = "NousResearch/hermes-function-calling-v1"
_TRACES = "lambda/hermes-agent-reasoning-traces"
# only the columns the converter reads: the builder's 10k-row shuffle buffer is several GB with all of them
_TOUCAN_COLUMNS = {
    "columns": ["messages", "available_tools", "question_quality_assessment", "response_quality_assessment"]
}
_TOUCAN_NOTE = (
    f"judge filter: question overall_score >= {TOUCAN_MIN_QUESTION}, completeness >= {TOUCAN_MIN_COMPLETENESS}, "
    f"conciseness >= {TOUCAN_MIN_CONCISENESS}; rows without scores dropped"
)

SOURCES: list[Source] = [
    # toucan: 40000 shared by three configs (the SFT config has no judge scores and is not used)
    Source(
        "toucan_kimi",
        _TOUCAN,
        "apache-2.0",
        "tool_call",
        15000,
        convert_toucan,
        config="Kimi-K2",
        scan=200_000,
        kwargs=_TOUCAN_COLUMNS,
        note=_TOUCAN_NOTE,
    ),
    Source(
        "toucan_oss",
        _TOUCAN,
        "apache-2.0",
        "tool_call",
        15000,
        convert_toucan,
        config="OSS",
        scan=150_000,
        kwargs=_TOUCAN_COLUMNS,
        note=_TOUCAN_NOTE + "; gpt-oss reasoning kept as reasoning_content",
    ),
    Source(
        "toucan_qwen3",
        _TOUCAN,
        "apache-2.0",
        "tool_call",
        10000,
        convert_toucan,
        config="Qwen3",
        scan=100_000,
        kwargs=_TOUCAN_COLUMNS,
        note=_TOUCAN_NOTE,
    ),
    # nemotron_agentic: 25000 shared by the two splits
    Source(
        "nemotron_agentic",
        "nvidia/Nemotron-SFT-Agentic-v4",
        "openmdw-1.1",
        "tool_call",
        20000,
        convert_nemotron,
        split="tool_calling",
        scan=80_000,
    ),
    Source(
        "nemotron_agentic_knowledge",
        "nvidia/Nemotron-SFT-Agentic-v4",
        "openmdw-1.1",
        "knowledge_agent",
        5000,
        convert_nemotron_knowledge,
        split="knowledge_agent",
        scan=40_000,
        note="traces cut to a prefix that fits the budget (task knowledge_agent_prefix)",
    ),
    # train_sft only: the `test` config is our benchmark and must never be read here
    Source("when2call", "nvidia/When2Call", "cc-by-4.0", "tool_abstain", 9000, convert_when2call, config="train_sft"),
    Source(
        "xlam_irrelevance",
        "MadeAgents/xlam-irrelevance-7.5k",
        "cc-by-4.0",
        "tool_irrelevant",
        5000,
        convert_xlam_irrelevance,
        note="upstream has no answer text: templated abstention",
    ),
    # hermes_fc: 10000 shared (func_calling_singleturn is a prefix of func_calling and is not used)
    Source("hermes_fc", _HERMES, "apache-2.0", "tool_call", 1900, convert_hermes_fc, config="func_calling"),
    Source(
        "hermes_fc_glaive", _HERMES, "apache-2.0", "tool_call", 5300, convert_hermes_fc, config="glaive_func_calling"
    ),
    Source(
        "hermes_json_agentic", _HERMES, "apache-2.0", "json_mode", 1400, convert_hermes_json, config="json_mode_agentic"
    ),
    Source(
        "hermes_json_single",
        _HERMES,
        "apache-2.0",
        "json_mode",
        1400,
        convert_hermes_json,
        config="json_mode_singleturn",
    ),
    # hermes_agent_traces: 10000 shared by the two teacher configs
    Source(
        "hermes_agent_traces_kimi",
        _TRACES,
        "apache-2.0",
        "agent_trace",
        5000,
        convert_hermes_agent_traces,
        config="kimi",
        note="toolbox pruned; traces cut to a prefix that fits the budget (task agent_trace_prefix)",
    ),
    Source(
        "hermes_agent_traces_glm",
        _TRACES,
        "apache-2.0",
        "agent_trace",
        5000,
        convert_hermes_agent_traces,
        config="glm-5.1",
        note="toolbox pruned; traces cut to a prefix that fits the budget (task agent_trace_prefix)",
    ),
    Source(
        "s1_deepresearch",
        "ScienceOne-AI/S1-DeepResearch-15k",
        "apache-2.0",
        "deep_research",
        5000,
        convert_s1_deepresearch,
        scan=16_000,
        note="English rows only; traces cut to a prefix that fits the budget (task deep_research_prefix)",
    ),
    Source(
        "deepresearch_sft",
        "FractalAIResearch/DeepResearch-SFT",
        "mit",
        "research_report",
        3000,
        convert_deepresearch_sft,
        note="every row is far above 4096 tokens (prompt >= 35k chars): nothing survives the default --max-len",
    ),
]
