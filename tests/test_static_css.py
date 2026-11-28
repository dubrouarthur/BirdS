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


def _classes(path) -> set[str]:
    """Class names a stylesheet defines rules for (in its selectors, not in its declarations)."""
    text = _strip(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for sel in re.findall(r"([^{};]+)\{", text):
        if sel.strip().startswith("@"):
            continue
        out |= set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", sel))
    return out


# shared on purpose: generic utilities and states every module styles in its own scope
SHARED = {
    "icon", "btn", "is-on", "is-done", "is-full", "is-open", "is-active", "is-failed", "is-todo", "is-unavailable",
    "is-busy", "is-error", "is-hidden", "is-current", "is-selected", "is-new", "sr-only", "visually-hidden",
    "is-part", "is-bad", "is-ok", "is-low",
    "md-copying",  # the answer's « being copied » state (turns.plainText): each module hides its own chrome in it
    # app components that agents.css / canvas.css extend on purpose (the composer, the modal, buttons)
    "agent-pill", "btn-stop", "composer-row", "modal", "switch-label", "btn-label",
}


def test_no_class_is_defined_by_two_modules():
    """A class styled in two module stylesheets collides (« 0. DIAPOSITIVES »): one module renames its own."""
    sheets = {p.name: _classes(p) for p in CSS}
    names = sorted(sheets)
    clashes = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            both = (sheets[a] & sheets[b]) - SHARED
            clashes += [f"{c} ({a}, {b})" for c in sorted(both)]
    assert not clashes, "classes defined in two stylesheets: " + ", ".join(clashes)
