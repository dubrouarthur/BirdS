"""Parse model output: reasoning, answer text and tool calls in Qwen3.5's native format.

<tool_call>
<function=name>
<parameter=key>
value
</parameter>
</function>
</tool_call>
"""

from __future__ import annotations

import json
import re

_CALL = re.compile(r"<tool_call>\s*<function=([^>\n]+)>(.*?)</function>\s*</tool_call>", re.S)
_PARAM = re.compile(r"<parameter=([^>\n]+)>\n?(.*?)\n?</parameter>", re.S)


def _value(raw: str):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def parse_output(text: str) -> dict:
    """{'reasoning': str, 'content': str, 'tool_calls': [{'name', 'arguments'}]} from raw generated text."""
    text = text.replace("<|im_end|>", "")
    reasoning = ""
    if "</think>" in text:
        reasoning, text = text.split("</think>", 1)
        reasoning = reasoning.replace("<think>", "").strip()
    calls = [
        {"name": name.strip(), "arguments": {k.strip(): _value(v) for k, v in _PARAM.findall(body)}}
        for name, body in _CALL.findall(text)
    ]
    content = text.split("<tool_call>", 1)[0].strip() if calls else text.strip()
    return {"reasoning": reasoning, "content": content, "tool_calls": calls}
