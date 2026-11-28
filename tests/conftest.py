"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _fresh_search_state():
    """A SearXNG marked degraded by one test (module state, 5 minutes) must not change what the next test sees."""
    from birds.harness.tools import search

    search._DEGRADED.clear()
    yield
    search._DEGRADED.clear()


@pytest.fixture(autouse=True)
def _single_generation_canvas(monkeypatch):
    """The scripted models of the canvas and crew tests write a deck in ONE generation: the progressive pipeline
    (plan, then one generation per slide) is tested on its own in tests/test_canvas_progressive.py, which turns it
    back on where it needs the whole turn."""
    monkeypatch.setenv("BIRD_CANVAS_PROGRESSIVE", "0")
