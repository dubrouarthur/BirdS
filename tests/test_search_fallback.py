"""Web search in production answered ``results: []`` 25 times out of 25 and nothing fell back: an empty list is a
failure of the first backend, the next one is asked, and after two empty searches the model is told plainly that
there is no figure to give (and to flag any estimate)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from birds.harness.config import Config, Context
from birds.harness.tools import web
from birds.harness.tools.search import FallbackSearch, SearchError, SearxngBackend, chain, probe


class Fixed:
    def __init__(self, name, results=None, error=None):
        self.name, self.label = name, name.title()
        self.results, self.error, self.calls = results or [], error, 0

    def search(self, query, n, lang=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.results[:n]


HIT = [{"title": "Horaires TGV Paris-Lyon", "url": "https://www.sncf-connect.com/x", "snippet": "2 h"}]


def test_empty_primary_falls_back_and_says_why():
    primary, wiki = Fixed("searxng"), Fixed("wikipedia", HIT)
    s = FallbackSearch(primary, wiki)
    assert s.search("train Paris Lyon", 5) == HIT
    assert s.last["backend"] == "wikipedia" and s.last["fallback_code"] == "empty"
    assert s.last["fallback_from"] == "Searxng"


def test_primary_with_results_is_kept():
    s = FallbackSearch(Fixed("searxng", HIT), Fixed("wikipedia", [{"title": "w", "url": "u", "snippet": ""}]))
    assert s.search("q", 5) == HIT and s.last == {"backend": "searxng", "label": "Searxng"}


def test_empty_then_failing_fallback_keeps_the_empty_answer():
    s = FallbackSearch(Fixed("searxng"), Fixed("wikipedia", error=SearchError("search_rate_limited", "429")))
    assert s.search("q", 5) == [] and s.last["backend"] == "searxng"


def test_chain_walks_every_backend_on_empty():
    brave, wiki = Fixed("brave"), Fixed("wikipedia", HIT)
    s = FallbackSearch(Fixed("searxng"), FallbackSearch(brave, wiki))
    assert s.search("q", 5) == HIT and brave.calls == 1
    assert s.last["backend"] == "wikipedia" and s.last["fallback_code"] == "empty"
    assert [b.name for b in chain(s)] == ["searxng", "brave", "wikipedia"]


def test_searxng_all_engines_unresponsive_is_an_outage_then_fallback():
    def handler(req):
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [["google", "CAPTCHA"],
                                                                                ["bing", "suspended"]]})  # fmt: skip

    searx = SearxngBackend("https://searx.local", httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(SearchError) as e:
        searx.search("q", 5)
    assert e.value.code == "search_unavailable"
    s = FallbackSearch(searx, Fixed("wikipedia", HIT))
    assert s.search("q", 5) == HIT and s.last["fallback_code"] == "search_unavailable"


def test_probe_reports_an_empty_backend_as_down():
    s = FallbackSearch(Fixed("searxng"), Fixed("wikipedia", HIT))
    rows = probe(s, "météo", clock=iter([0.0, 0.1, 0.1, 0.5]).__next__)
    assert [(r["backend"], r["ok"], r["code"], r["results"]) for r in rows] == [
        ("searxng", False, "empty", 0),
        ("wikipedia", True, "", 1),
    ]
    assert rows[0]["seconds"] == 0.1 and rows[1]["seconds"] == 0.4


def test_probe_never_raises():
    rows = probe(Fixed("brave", error=RuntimeError("boom")))
    assert rows == [{"backend": "brave", "label": "Brave", "ok": False, "results": 0, "code": "search_failed",
                     "seconds": rows[0]["seconds"]}]  # fmt: skip


# ---------------------------------------------------------------- the tool text after empty searches


def ctx_with(search, lang="fr"):
    return Context(config=Config(workspace=Path("/tmp")), http=httpx.Client(), search=search, lang=lang)


def test_two_empty_searches_stop_with_an_honest_directive():
    backend = Fixed("searxng")
    ctx = ctx_with(backend)
    first = web.web_search({"query": "temps train Paris Lyon"}, ctx)
    assert first.startswith("No results.") and "Try once more" in first
    second = web.web_search({"query": "durée TGV Paris Lyon"}, ctx)
    assert second.startswith("Search unavailable:") and "Do not search again" in second
    assert "aucun chiffre vérifié" in second and "estimation, non vérifiée" in second
    with pytest.raises(web.ToolError) as e:  # a third call does not even reach the backend
        web.web_search({"query": "prix billet avion Paris Lyon"}, ctx)
    assert backend.calls == 2 and "Do not search again" in str(e.value)
    assert ctx.step_info["code"] == "search_exhausted"


def test_directive_in_english():
    ctx = ctx_with(Fixed("searxng"), lang="en")
    web.web_search({"query": "a"}, ctx)
    text = web.web_search({"query": "b"}, ctx)
    assert "I found no verified figure" in text and "estimate, not verified" in text


def test_failures_count_like_empty_searches():
    ctx = ctx_with(Fixed("brave", error=SearchError("search_quota", "quota")))
    with pytest.raises(web.ToolError) as e1:
        web.web_search({"query": "a"}, ctx)
    assert "Do not search again" not in str(e1.value)
    with pytest.raises(web.ToolError) as e2:
        web.web_search({"query": "b"}, ctx)
    assert "Do not search again" in str(e2.value) and "estimation" in str(e2.value)


def test_a_search_with_results_does_not_count():
    backend = Fixed("searxng", HIT)
    ctx = ctx_with(backend)
    for q in ("a", "b", "c"):
        assert "sncf-connect" in web.web_search({"query": q}, ctx)
    assert ctx.empty_searches == 0


def test_agent_comparison_after_empty_searches_gets_the_directive(tmp_path):
    """g10-1: « train ou avion Paris-Lyon ? » after empty searches; the model sees the directive, not a bare
    « No results. », and the run keeps the directive among what it fetched (no invented figure is credited)."""
    from test_harness import Tok, call

    from birds.harness.agent import Agent
    from birds.harness.llm import FakeClient

    outs = [
        call("web_search", query="temps train Paris Lyon"),
        call("web_search", query="temps avion Paris Lyon"),
        call("web_search", query="prix billet"),
        "La recherche web n'a rien donné : je n'ai trouvé aucun chiffre vérifié.",
    ]
    llm = FakeClient(outs)
    agent = Agent(llm, Tok(), Config(workspace=tmp_path), search=Fixed("searxng"), http=httpx.Client())
    run = agent.run("Train ou avion entre Paris et Lyon : lequel est le plus rapide et le moins cher ?")
    searches = [s for s in run.steps if s.tool == "web_search"]
    assert len(searches) == 3
    assert searches[2].error and "Do not search again" in searches[2].error
    import json

    tools = [m["content"] for m in json.loads(llm.prompts[2])["messages"] if m["role"] == "tool"]
    assert any("Search unavailable:" in t and "estimation, non vérifiée" in t for t in tools)
