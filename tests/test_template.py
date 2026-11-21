"""The jinja2-only renderer must produce byte-identical prompts to the real tokenizer's chat template."""

from __future__ import annotations

import hashlib
import subprocess
import sys

import pytest

from birds.harness.template import TEMPLATE_PATH, TemplateTokenizer
from birds.render import prompt as render_prompt
from birds.tools import BIRD_TOOLS

SYSTEM = "Tu es Bird, l'assistant de travail conçu par Bird Models."


def _call(name, **arguments):
    return {"type": "function", "function": {"name": name, "arguments": arguments}}


SLIDES = [{"title": "Été", "bullets": ["Coût : 12 €", 'Guillemets "droits" & <balises>']}]
CONVERSATIONS = {
    "plain": [{"role": "user", "content": "Bonjour, ça va ?"}],
    "system": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Résumez : « l'été à Noël » — œuvre."},
    ],
    "multi_turn": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hello! How can I help?"},
        {"role": "user", "content": "Écris un mail à Zoé.\nSur deux lignes."},
    ],
    "tool_call_pending": [
        {"role": "user", "content": "Cherche le taux directeur."},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "Je dois chercher.",
            "tool_calls": [_call("web_search", query="taux directeur BCE")],
        },
        {"role": "tool", "content": "[Donnée externe]\n1. Taux — https://news.test/rates\nLe taux est à 2,5 %."},
    ],
    "multi_step": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Lis la page puis prépare un mail et des diapositives."},
        {
            "role": "assistant",
            "content": "Je lis la page.",
            "reasoning_content": "",
            "tool_calls": [_call("read_page", url="https://example.org/a?b=1&c=é")],
        },
        {"role": "tool", "content": "Contenu <b>brut</b> & accents éèàùç — 100 % OK\n\nligne 2"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "Deux actions.",
            "tool_calls": [
                _call("draft_email", to=["a@example.org", "b@example.org"], subject="Offre", body="Bonjour,\n\nMerci."),
                _call("make_slides", title="Plan d'action", slides=SLIDES),
            ],
        },
        {"role": "tool", "content": "Draft saved."},
        {"role": "tool", "content": "File created: bird_out/plan.pptx"},
        {"role": "assistant", "content": "C'est prêt.", "reasoning_content": "Fini."},
        {"role": "user", "content": "Merci. Et en anglais ?"},
    ],
    "empty_system": [{"role": "system", "content": ""}, {"role": "user", "content": "x"}],
    "numbers_and_bools": [
        {"role": "user", "content": "calc"},
        {"role": "assistant", "content": "", "tool_calls": [_call("run_python", code="print(1 < 2 and 'é' != \"e\")")]},
        {"role": "tool", "content": "True"},
    ],
}
TOOLSETS = {"none": None, "all": BIRD_TOOLS, "two": BIRD_TOOLS[:2]}
CASES = [(c, t, th) for c in CONVERSATIONS for t in TOOLSETS for th in (False, True)]


@pytest.fixture(scope="module")
def real_tok():
    transformers = pytest.importorskip("transformers")
    try:
        return transformers.AutoTokenizer.from_pretrained("Qwen/Qwen3.5-4B", local_files_only=True)
    except Exception as exc:  # noqa: BLE001 - no cached tokenizer on this machine
        pytest.skip(f"Qwen/Qwen3.5-4B tokenizer not cached: {exc}")


def test_vendored_template_is_the_tokenizers_template(real_tok):
    assert TEMPLATE_PATH.read_text(encoding="utf-8") == real_tok.chat_template


@pytest.mark.parametrize(("conv", "tools", "thinking"), CASES)
def test_prompt_is_byte_identical(real_tok, conv, tools, thinking):
    messages = CONVERSATIONS[conv]
    expected = render_prompt(real_tok, messages, TOOLSETS[tools], thinking)
    got = render_prompt(TemplateTokenizer(), messages, TOOLSETS[tools], thinking)
    assert got.encode("utf-8") == expected.encode("utf-8")


def test_full_conversation_rendering_is_identical(real_tok):
    """Without a generation prompt too (what training uses), for every prefix that ends on an assistant turn."""
    light = TemplateTokenizer()
    for name, messages in CONVERSATIONS.items():
        for end in range(1, len(messages) + 1):
            if messages[end - 1]["role"] != "assistant" or messages[end - 1].get("tool_calls"):
                continue
            kw = {"tools": BIRD_TOOLS, "enable_thinking": True, "tokenize": False}
            assert light.apply_chat_template(messages[:end], **kw) == real_tok.apply_chat_template(
                messages[:end], **kw
            ), name


def test_template_file_is_pinned():
    """A changed template is a changed prompt format: updating the file must be a deliberate act."""
    digest = hashlib.sha256(TEMPLATE_PATH.read_bytes()).hexdigest()
    assert digest == "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715"


def test_renderer_does_not_import_transformers():
    code = (
        "import sys\n"
        "from birds.harness.template import TemplateTokenizer\n"
        "from birds.render import prompt\n"
        "out = prompt(TemplateTokenizer(), [{'role': 'user', 'content': 'Bonjour'}], None, False)\n"
        "assert out.endswith('<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n'), repr(out[-60:])\n"
        "bad = [m for m in ('transformers', 'torch', 'tokenizers', 'datasets') if m in sys.modules]\n"
        "assert not bad, bad\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-600:]
