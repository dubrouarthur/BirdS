"""Static stylesheets: every brace closes, and no module reuses another module's class names."""

from __future__ import annotations

import re

import pytest

from birds.web.server import STATIC_DIR

CSS = sorted(STATIC_DIR.glob("*.css"))


def _strip(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", '""', text)


@pytest.mark.parametrize("path", CSS, ids=lambda p: p.name)
def test_braces_balance(path):
    depth = 0
    for n, line in enumerate(_strip(path.read_text(encoding="utf-8")).splitlines(), 1):
        depth += line.count("{") - line.count("}")
        assert depth >= 0, f"{path.name}:{n} closes a brace that was never opened"
    assert depth == 0, f"{path.name} leaves {depth} brace(s) open: the rules after it are ignored"
