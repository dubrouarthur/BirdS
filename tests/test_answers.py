"""Answer content (cluster C2 of the chat audit): tool labels, math, citations, copy, mail recipient, feedback."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from birds.harness.tools import TOOLS
from birds.web.server import STATIC_DIR

ROOT = Path(__file__).parent


def _keys(text: str, lang: str) -> set[str]:
    """The string keys of one language block of an i18n file (``fr: {`` … ``en: {`` …)."""
    fr, en = text.split("\n  en: {", 1)
    block = fr.split("fr: {", 1)[1] if lang == "fr" else en.split("\n};", 1)[0]
    return set(re.findall(r'^\s+"([a-z][\w.]*)":', block, re.M))


def _labels(lang: str) -> set[str]:
    keys = set()
    for name in ("i18n.js", "answers-i18n.js"):
        keys |= _keys((STATIC_DIR / name).read_text(), lang)
    return keys


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_every_tool_has_a_human_label(lang):
    """R10: the steps line never shows a tool id such as « lookup_entity »."""
    keys = _labels(lang)
    missing = sorted(name for name in TOOLS if f"tool.{name}" not in keys)
    assert not missing, missing
    assert "tool.unknown" in keys  # the fallback for a tool added without its label


def test_answer_strings_have_french_english_parity():
    text = (STATIC_DIR / "answers-i18n.js").read_text()
    fr, en = _keys(text, "fr"), _keys(text, "en")
    assert fr and fr == en, sorted(fr ^ en)
    base = _keys((STATIC_DIR / "i18n.js").read_text(), "fr")
    assert not fr & base, sorted(fr & base)  # added, never overriding a string of i18n.js


def test_tool_label_falls_back_to_a_word_never_the_id():
    core = (STATIC_DIR / "core.js").read_text()
    body = core.split("export const toolLabel", 1)[1].split("};", 1)[0]
    assert 't("tool.unknown")' in body and "String(tool)" not in body


def test_answers_node_unit_tests():
    """tests/js/answers.test.mjs: math, citations, rich copy, feedback (pure parts)."""
    if shutil.which("node") is None:
        pytest.skip("Node not installed")
    result = subprocess.run(
        ["node", "--test", str(ROOT / "js" / "answers.test.mjs")],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "CI": "1"},
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
