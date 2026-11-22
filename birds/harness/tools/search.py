"""Search backends for web_search, chosen by configuration (first match wins):

1. SearXNG   (``searxng_url``)     self-hosted meta search engine, JSON API
2. Brave     (``brave_api_key``)   Brave Search API, https://api.search.brave.com/res/v1/web/search
3. Tavily    (``tavily_api_key``)  Tavily Search API, POST https://api.tavily.com/search
4. Wikipedia (default, no key)     MediaWiki Action API of fr/en.wikipedia.org, intro extracts of the matching pages

Every backend has ``name`` (stable id), ``label`` (shown in the UI) and ``search(query, n, lang=...)`` returning
``[{"title", "url", "snippet"}]``. The backend URLs are fixed here or set by the operator, never by the model, so
they are not subject to the read_page egress policy; each call has a timeout and a response size cap.
"""

from __future__ import annotations

import html
import re

USER_AGENT = "BirdAssistant/0.3 (bot; small work assistant{contact}) httpx"
MAX_BYTES = 1_000_000


def user_agent(contact: str | None = None) -> str:
    """Descriptive User-Agent as Wikimedia's policy requires: name/version (contact) library."""
    return USER_AGENT.format(contact=f"; {contact}" if contact else "")


def _json(r) -> dict:
    r.raise_for_status()
    if len(r.content) > MAX_BYTES:
        raise ValueError("search response too large")
    data = r.json()
    return data if isinstance(data, dict) else {}


def _clean(text) -> str:
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    return " ".join(html.unescape(text).split())


class SearxngBackend:
    """SearXNG JSON API (`/search?format=json`; the instance must enable the json format).

    The base URL is set by the operator, not by the model, so it may be a local address.
    """

    name, label = "searxng", "SearXNG"

    def __init__(self, base_url: str, http, timeout: float = 10.0):
        self.url, self.http, self.timeout = base_url.rstrip("/") + "/search", http, timeout

    def search(self, query: str, n: int, lang: str | None = None) -> list[dict]:
        params = {"q": query, "format": "json", **({"language": lang} if lang else {})}
        r = self.http.get(self.url, params=params, timeout=self.timeout)
        return [
            {"title": x.get("title") or "", "url": x.get("url") or "", "snippet": x.get("content") or ""}
            for x in (_json(r).get("results") or [])[:n]
        ]


class BraveBackend:
    """Brave Search API (web results). Docs: https://api-dashboard.search.brave.com/app/documentation."""

    name, label = "brave", "Brave Search"
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, http, timeout: float = 10.0):
        self.key, self.http, self.timeout = api_key, http, timeout

    def search(self, query: str, n: int, lang: str | None = None) -> list[dict]:
        params = {"q": query, "count": max(1, min(int(n), 20)), **({"search_lang": lang} if lang else {})}
        headers = {"Accept": "application/json", "X-Subscription-Token": self.key}
        r = self.http.get(self.URL, params=params, headers=headers, timeout=self.timeout)
        results = ((_json(r).get("web") or {}).get("results")) or []
        return [
            {"title": _clean(x.get("title")), "url": x.get("url") or "", "snippet": _clean(x.get("description"))}
            for x in results[:n]
        ]


class TavilyBackend:
    """Tavily Search API. Docs: https://docs.tavily.com/documentation/api-reference/endpoint/search."""

    name, label = "tavily", "Tavily"
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, http, timeout: float = 15.0):
        self.key, self.http, self.timeout = api_key, http, timeout

    def search(self, query: str, n: int, lang: str | None = None) -> list[dict]:
        body = {"query": query, "max_results": max(1, min(int(n), 20)), "search_depth": "basic"}
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        r = self.http.post(self.URL, json=body, headers=headers, timeout=self.timeout)
        return [
            {"title": _clean(x.get("title")), "url": x.get("url") or "", "snippet": _clean(x.get("content"))}
            for x in (_json(r).get("results") or [])[:n]
        ]


class WikipediaBackend:
    """Wikipedia full-text search with the intro of each page, in one call to the MediaWiki Action API.

    No key. Encyclopaedic, not news: fine for facts, definitions, organisations; weak for prices, rates or
    anything recent. The language follows the conversation (fr or en). Wikimedia asks API clients for a
    descriptive User-Agent with a contact (https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)
    and limits unauthenticated clients (https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits).
    """

    name = "wikipedia"
    LANGS = ("fr", "en")

    def __init__(self, http, timeout: float = 10.0, contact: str | None = None, lang: str = "fr"):
        self.http, self.timeout, self.default_lang = http, timeout, lang if lang in self.LANGS else "fr"
        self.headers = {"User-Agent": user_agent(contact), "Accept": "application/json"}

    @property
    def label(self) -> str:
        return "Wikipédia" if self.default_lang == "fr" else "Wikipedia"

    def search(self, query: str, n: int, lang: str | None = None) -> list[dict]:
        lang = lang if lang in self.LANGS else self.default_lang
        n = max(1, min(int(n), 10))
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": n,
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "exsentences": 4,
            "exlimit": n,
            "inprop": "url",
            "utf8": 1,
            "maxlag": 5,
        }
        r = self.http.get(
            f"https://{lang}.wikipedia.org/w/api.php", params=params, headers=self.headers, timeout=self.timeout
        )
        pages = ((_json(r).get("query") or {}).get("pages")) or []
        pages = sorted((p for p in pages if isinstance(p, dict)), key=lambda p: p.get("index") or 0)
        return [
            {
                "title": _clean(p.get("title")),
                "url": p.get("fullurl")
                or f"https://{lang}.wikipedia.org/wiki/{str(p.get('title', '')).replace(' ', '_')}",
                "snippet": _clean(p.get("extract"))[:600],
            }
            for p in pages[:n]
        ]


def make_search(cfg, http):
    """The backend the configuration asks for, or None when search is switched off (``search_default="none"``)."""
    if getattr(cfg, "searxng_url", None):
        return SearxngBackend(cfg.searxng_url, http)
    if getattr(cfg, "brave_api_key", None):
        return BraveBackend(cfg.brave_api_key, http)
    if getattr(cfg, "tavily_api_key", None):
        return TavilyBackend(cfg.tavily_api_key, http)
    if getattr(cfg, "search_default", "wikipedia") == "wikipedia":
        return WikipediaBackend(http, contact=getattr(cfg, "search_contact", None))
    return None
