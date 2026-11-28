"""SearXNG outage (production, 28/11/2026): HTTP 200, 0 results, duckduckgo « CAPTCHA » and google cse « suspended ».
The keyless engines of the same instance are asked by name, then Wikipedia; /api/health reports it. No network."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from birds.harness.tools import search as S

DOWN = [["duckduckgo", "CAPTCHA"], ["google cse", "Suspended: too many requests"]]
HIT = {"title": "Monoprix Saint-Cloud", "url": "https://example.org/monoprix", "content": "Supermarché",
       "engines": ["bing"]}  # fmt: skip


@pytest.fixture(autouse=True)
def fresh():
    S._DEGRADED.clear()
    yield
    S._DEGRADED.clear()


def client(seen, *, fallback_ok=True):
    def handler(req: httpx.Request) -> httpx.Response:
        q = parse_qs(urlsplit(str(req.url)).query)
        seen.append(q.get("engines", [""])[0])
        if "wikipedia.org" in str(req.url):
            body = {"query": {"pages": [{"title": "Saint-Cloud", "fullurl": "https://fr.wikipedia.org/wiki/Saint-Cloud",
                                         "extract": "Commune des Hauts-de-Seine.", "index": 1}]}}  # fmt: skip
        elif q.get("engines") and fallback_ok:
            body = {"results": [HIT], "unresponsive_engines": []}
        else:
            body = {"results": [], "unresponsive_engines": DOWN}
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_no_result_with_unresponsive_engines_asks_the_keyless_engines():
    seen = []
    b = S.SearxngBackend("https://searx.example", client(seen))
    got = b.search("supermarchés Saint-Cloud", 5, lang="fr")
    assert [r["title"] for r in got] == ["Monoprix Saint-Cloud"]
    assert seen == ["", "bing,brave,yahoo"] and b.last["engines"] == "fallback"
    b.search("boulangerie Rennes", 5)  # degraded for a few minutes: the fallback engines straight away
    assert seen[2:] == ["bing,brave,yahoo"]


def test_every_engine_down_falls_back_to_wikipedia_with_a_calm_code():
    seen = []
    http = client(seen, fallback_ok=False)
    fs = S.FallbackSearch(S.SearxngBackend("https://searx.example", http), S.WikipediaBackend(http))
    got = fs.search("Saint-Cloud", 5, lang="fr")
    assert got and got[0]["title"] == "Saint-Cloud"
    assert fs.last["fallback_code"] == "search_unavailable" and fs.last["fallback_from"] == "SearXNG"


def test_a_real_empty_answer_stays_no_results():
    def handler(req):
        return httpx.Response(200, headers={"content-type": "application/json"},
                              content=json.dumps({"results": [], "unresponsive_engines": []}).encode())  # fmt: skip

    b = S.SearxngBackend("https://searx.example", httpx.Client(transport=httpx.MockTransport(handler)))
    assert b.search("zzqx", 5) == []


def test_probe_reports_engines_alive_and_down():
    out = S.probe("https://searx.example", client([]))
    assert out["ok"] is False and out["degraded"] is True and out["results"] == 1
    assert {d["engine"] for d in out["default"]["unresponsive"]} == {"duckduckgo", "google cse"}
    assert out["fallback"]["alive"] == ["bing"]


def test_health_carries_the_search_probe(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from birds.web import server
    from birds.web.server import create_app
    from birds.web.settings import Settings

    calls = []
    monkeypatch.setattr(server, "_search_probe", lambda s: calls.append(1) or {"backend": "searxng", "ok": False,
                                                                                "degraded": True})  # fmt: skip
    app = create_app(Settings(rate_limit=0, searxng_url="https://searx.example"))
    h = TestClient(app).get("/api/health").json()
    assert h["search"]["degraded"] is True and calls
