"""Extra sources added after the v0 run.

xlam_fc: single-turn requests answered directly by one or several tool calls. v0 lost the habit of
calling tools straight away (it asked for clarification instead); this source restores it, including
parallel calls.
"""

from __future__ import annotations

import json

from birds.sources import Source

_TYPES = {"str": "string", "string": "string", "int": "integer", "integer": "integer", "float": "number",
          "number": "number", "bool": "boolean", "boolean": "boolean", "dict": "object", "object": "object"}


def _json_type(t) -> str | None:
    t = str(t or "").lower().split(",")[0].strip()
    if t.startswith(("list", "array", "tuple", "set")):
        return "array"
    return _TYPES.get(t)


def convert_xlam_fc(row: dict) -> list[dict]:
    try:
        tools_in, answers = json.loads(row["tools"]), json.loads(row["answers"])
    except (KeyError, TypeError, ValueError):
        return []
    query = row.get("query")
    if not (isinstance(query, str) and query.strip() and isinstance(tools_in, list) and isinstance(answers, list) and answers):
        return []
    tools, names = [], set()
    for t in tools_in:
        if not (isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"]) or t["name"] in names:
            return []
        params = t.get("parameters") if isinstance(t.get("parameters"), dict) else {}
        props, required = {}, []
        for k, p in params.items():
            if not isinstance(p, dict):
                return []
            prop = {"description": str(p.get("description", ""))}
            if jt := _json_type(p.get("type")):
                prop["type"] = jt
            props[k] = prop
            if "default" not in p:
                required.append(k)
        names.add(t["name"])
        tools.append({"type": "function", "function": {"name": t["name"], "description": str(t.get("description", "")),
                                                        "parameters": {"type": "object", "properties": props, "required": required}}})
    calls = []
    for c in answers:
        if not (isinstance(c, dict) and c.get("name") in names and isinstance(c.get("arguments"), dict)):
            return []
        calls.append({"type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}})
    if len(calls) > 4 or any(ord(ch) > 0x2E7F for ch in query):
        return []
    return [{"lang": "en", "thinking": False, "tools": tools, "task": "tool_call_parallel" if len(calls) > 1 else "tool_call",
             "messages": [{"role": "user", "content": query.strip()}, {"role": "assistant", "content": "", "tool_calls": calls}]}]


SOURCES = [
    Source("xlam_fc", "Salesforce/xlam-function-calling-60k", "cc-by-4.0", "tool_call", 6000, convert_xlam_fc, scan=9000,
           note="gated dataset; direct single-turn and parallel calls"),
]
