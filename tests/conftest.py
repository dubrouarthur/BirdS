"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _fresh_search_state():
    """A SearXNG marked degraded by one test (module state, 5 minutes) must not change what the next test sees."""
    from birds.harness.tools import search

    search._DEGRADED.clear()
    yield
    search._DEGRADED.clear()
