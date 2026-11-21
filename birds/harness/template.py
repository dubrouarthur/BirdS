"""Render Qwen3.5's chat template with jinja2 only (no transformers, no tokenizer download).

The template file next to this module, ``chat_template.jinja``, is a verbatim copy of
https://huggingface.co/Qwen/Qwen3.5-4B/resolve/main/chat_template.jinja (Apache-2.0, © Alibaba Cloud / Qwen).
``TemplateTokenizer`` offers the one tokenizer method the harness needs, ``apply_chat_template``, with the same
jinja2 settings as ``transformers``; ``tests/test_template.py`` proves the prompts are byte-identical to
``birds.render.prompt`` with the real tokenizer. Use it wherever the model weights live elsewhere (a serverless
deployment, a thin client): prompts are rendered here, token counts come from the model server.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

TEMPLATE_PATH = Path(__file__).with_name("chat_template.jinja")
TEMPLATE_SOURCE = "https://huggingface.co/Qwen/Qwen3.5-4B/resolve/main/chat_template.jinja"


@lru_cache(maxsize=4)
def _compile(source: str):
    import jinja2
    from jinja2.ext import loopcontrols
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    def raise_exception(message):
        raise jinja2.exceptions.TemplateError(message)

    def tojson(x, ensure_ascii=False, indent=None, separators=None, sort_keys=False):
        # Same override as transformers: jinja's own tojson escapes HTML characters, which we do not want.
        return json.dumps(x, ensure_ascii=ensure_ascii, indent=indent, separators=separators, sort_keys=sort_keys)

    def strftime_now(fmt):
        return datetime.now().strftime(fmt)

    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, extensions=[loopcontrols])
    env.filters["tojson"] = tojson
    env.globals["raise_exception"] = raise_exception
    env.globals["strftime_now"] = strftime_now
    return env.from_string(source)


class TemplateTokenizer:
    """Duck-types the tokenizer for prompt rendering: ``apply_chat_template(..., tokenize=False)`` only."""

    is_template_only = True  # no vocabulary here: token counts must come from the model server

    def __init__(self, template: str | None = None):
        self.chat_template = template if template is not None else TEMPLATE_PATH.read_text(encoding="utf-8")

    def apply_chat_template(
        self,
        messages: list[dict],
        tools: list | None = None,
        enable_thinking: bool = False,
        tokenize: bool = False,
        add_generation_prompt: bool = False,
        **kwargs,
    ) -> str:
        if tokenize:
            raise NotImplementedError("TemplateTokenizer renders text only; token ids need the real tokenizer")
        return _compile(self.chat_template).render(
            messages=messages,
            tools=tools or None,
            documents=None,
            add_generation_prompt=add_generation_prompt,
            enable_thinking=enable_thinking,
            **kwargs,
        )
