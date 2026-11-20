"""Unified training/benchmark record and its validator.

One record = one conversation that ends with an assistant message:

    {
      "id": "toucan-000123",          # unique within the mix
      "source": "toucan",             # key of the source registry
      "license": "apache-2.0",        # license of the upstream row
      "lang": "fr" | "en",
      "task": "tool_call",            # free tag, used for stats and caps
      "thinking": false,              # true => assistant turns carry reasoning_content
      "tools": [ {"type": "function", "function": {"name", "description", "parameters"}} ],  # optional
      "messages": [
        {"role": "system", "content": "..."},                       # optional, first only
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "", "reasoning_content": "...",
         "tool_calls": [{"type": "function", "function": {"name": "web_search", "arguments": {"query": "..."}}}]},
        {"role": "tool", "content": "..."},
        {"role": "assistant", "content": "final answer"}
      ]
    }

Tool calls are always structured (name + arguments dict). The model's own chat template turns them
into its native text format; converters must never write <tool_call> or <think> markup in `content`.
"""

from __future__ import annotations

LANGS = {"fr", "en"}
ROLES = {"system", "user", "assistant", "tool"}
FORBIDDEN = ("<think>", "</think>", "<tool_call>", "</tool_call>", "<|im_start|>", "<|im_end|>", "<tool_response>")


def errors(rec: dict) -> list[str]:
    """Return the list of problems in `rec` (empty list = valid)."""
    out: list[str] = []
    for k in ("id", "source", "license", "lang", "task", "messages"):
        if not rec.get(k):
            out.append(f"missing {k}")
    if out:
        return out
    if rec["lang"] not in LANGS:
        out.append(f"lang {rec['lang']!r}")
    if not isinstance(rec.get("thinking"), bool):
        out.append("thinking must be a bool")
    tools = rec.get("tools") or []
    names = set()
    for t in tools:
        fn = t.get("function") if isinstance(t, dict) else None
        if not (isinstance(fn, dict) and isinstance(fn.get("name"), str) and fn["name"]):
            out.append("tool without function.name")
            continue
        if not isinstance(fn.get("parameters", {}), dict):
            out.append(f"tool {fn['name']}: parameters must be an object")
        names.add(fn["name"])
    msgs = rec["messages"]
    if not isinstance(msgs, list) or len(msgs) < 2:
        return out + ["need at least 2 messages"]
    if msgs[-1].get("role") != "assistant":
        out.append("last message must be assistant")
    if not any(m.get("role") == "user" for m in msgs):
        out.append("no user message")
    prev = None
    for i, m in enumerate(msgs):
        role, content = m.get("role"), m.get("content")
        if role not in ROLES:
            out.append(f"msg {i}: role {role!r}")
            continue
        if not isinstance(content, str):
            out.append(f"msg {i}: content must be a string")
            continue
        if any(f in content for f in FORBIDDEN) or any(f in (m.get("reasoning_content") or "") for f in FORBIDDEN):
            out.append(f"msg {i}: control markup in text")
        if role == "system" and i != 0:
            out.append(f"msg {i}: system must be first")
        if role == "user" and not content.strip():
            out.append(f"msg {i}: empty user")
        if role == "tool" and prev not in ("assistant", "tool"):
            out.append(f"msg {i}: tool message without a preceding call")
        if role == "assistant":
            calls = m.get("tool_calls") or []
            if prev == "assistant":
                out.append(f"msg {i}: two assistant messages in a row")
            if not content.strip() and not calls:
                out.append(f"msg {i}: empty assistant")
            if "reasoning_content" in m and not isinstance(m["reasoning_content"], str):
                out.append(f"msg {i}: reasoning_content must be a string")
            for c in calls:
                fn = c.get("function") if isinstance(c, dict) else None
                if not (isinstance(fn, dict) and isinstance(fn.get("arguments"), dict)):
                    out.append(f"msg {i}: tool call needs function.arguments as an object")
                elif fn.get("name") not in names:
                    out.append(f"msg {i}: call to undeclared tool {fn.get('name')!r}")
            if calls and i == len(msgs) - 1:
                pass  # ending on a call is fine (the label is the call itself)
        if prev == "assistant" and role == "tool" and not (msgs[i - 1].get("tool_calls")):
            out.append(f"msg {i}: tool result after an assistant turn without tool_calls")
        prev = role
    if not rec.get("thinking") and any((m.get("reasoning_content") or "").strip() for m in msgs):
        out.append("reasoning_content present but thinking is false")
    return out


def is_valid(rec: dict) -> bool:
    return not errors(rec)
