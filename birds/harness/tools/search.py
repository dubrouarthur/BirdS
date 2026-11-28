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


class SearchError(Exception):
    """A search backend failed in a way worth telling the user. ``code`` is stable (UI translation)."""

    def __init__(self, code: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


def _status_error(r, label: str) -> SearchError:
    if r.status_code in (401, 403):
        return SearchError("search_unauthorized", f"{label} refused the API key (HTTP {r.status_code})")
    if r.status_code in (402, 432, 433):
        return SearchError("search_quota", f"{label}: search quota or plan limit reached (HTTP {r.status_code})")
    if r.status_code == 429:
        return SearchError("search_rate_limited", f"{label} is rate limiting searches (HTTP 429)")
    if r.status_code in (400, 422):
        return SearchError("search_bad_request", f"{label} rejected the query (HTTP {r.status_code})")
    return SearchError("search_failed", f"{label} failed (HTTP {r.status_code})")


def _json(r, label: str = "the search service") -> dict:
    if r.status_code >= 400:
        raise _status_error(r, label)
    if len(r.content) > MAX_BYTES:
        raise ValueError("search response too large")
    data = r.json()
    return data if isinstance(data, dict) else {}


def _retry_after(r) -> float | None:
    try:
        return float(r.headers.get("retry-after") or "")
    except ValueError:
        return None


def _image(url) -> dict:
    """{"image": url} for an absolute https image URL a backend tied to one result, else {} (never shown to the
    model; the web app proxies it through /api/img, see birds.web.server)."""
    url = str(url or "").strip()
    return {"image": url} if url.startswith("https://") and len(url) <= 2048 else {}


def _clean(text) -> str:
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    return " ".join(html.unescape(text).split())


# Engines a SearXNG instance can query without a key or a CAPTCHA, asked by name when its default engines answer
# nothing (``engines=`` reaches an engine even when the instance has it off). Probe of the production instance,
# 28/11/2026: duckduckgo (CAPTCHA) and google cse (suspended) answered 0 results; bing 10, brave 20, yahoo 7;
# qwant « access denied »; mojeek, startpage, wikipedia not installed. ``BIRD_SEARXNG_FALLBACK`` overrides the list.
FALLBACK_ENGINES = ("bing", "brave", "yahoo")
DEGRADED_S = 300.0  # once the default engines failed, the fallback engines are asked first for this long
_DEGRADED: dict[str, float] = {}


def fallback_engines() -> tuple[str, ...]:
    import os

    raw = os.environ.get("BIRD_SEARXNG_FALLBACK")
    if raw is None:
        return FALLBACK_ENGINES
    return tuple(e.strip() for e in raw.split(",") if re.fullmatch(r"[\w .-]{2,40}", e.strip()))


class SearxngBackend:
    """SearXNG JSON API (`/search?format=json`; the instance must enable the json format).

    The base URL is set by the operator, not by the model, so it may be a local address. An answer with no result
    while engines were unresponsive (CAPTCHA, suspended, timeout) is an outage, not « no results »: the keyless
    fallback engines are asked by name, and when they answer nothing either a ``search_unavailable`` error lets
    ``FallbackSearch`` answer from Wikipedia. ``last`` says which engines answered.
    """

    name, label = "searxng", "SearXNG"

    def __init__(self, base_url: str, http, timeout: float = 10.0, clock=None):
        import time

        self.url, self.http, self.timeout = base_url.rstrip("/") + "/search", http, timeout
        self.clock = clock or time.monotonic
        self.last: dict = {}

    def _ask(self, query: str, lang: str | None, engines: tuple[str, ...] = ()) -> dict:
        params = {"q": query, "format": "json", **({"language": lang} if lang else {})}
        if engines:
            params["engines"] = ",".join(engines)
        r = self.http.get(self.url, params=params, timeout=self.timeout)
        return _json(r, self.label)

    def search(self, query: str, n: int, lang: str | None = None) -> list[dict]:
        spare = fallback_engines()
        degraded = _DEGRADED.get(self.url, 0.0) > self.clock()
        data = self._ask(query, lang, spare if degraded and spare else ())
        down = [str(e[0]) for e in data.get("unresponsive_engines") or [] if isinstance(e, (list, tuple)) and e]
        used = "fallback" if degraded and spare else "default"
        if not data.get("results") and down and spare and not degraded:
            _DEGRADED[self.url] = self.clock() + DEGRADED_S
            data, used = self._ask(query, lang, spare), "fallback"
            down = [str(e[0]) for e in data.get("unresponsive_engines") or [] if isinstance(e, (list, tuple)) and e]
        results = data.get("results") or []
        if used == "fallback":  # bing and yahoo through SearXNG add home pages and broken links: kept out
            results = [x for x in results if _article(x.get("url"))]
        if not results and down:
            raise SearchError("search_unavailable", f"{self.label}: no engine answered ({', '.join(down[:4])})")
        if results and used == "default":
            _DEGRADED.pop(self.url, None)
        self.last = {"engines": used, **({"down": down[:6]} if down else {})}
        return [
            {
                "title": x.get("title") or "",
                "url": x.get("url") or "",
                "snippet": x.get("content") or "",
                **_image(x.get("thumbnail") or x.get("img_src")),
            }
            for x in results[:n]
        ]


def _article(url) -> bool:
    """A result that points at a page: an http(s) URL with a host and a path (not a bare home page)."""
    from urllib.parse import urlsplit

    try:
        p = urlsplit(str(url or ""))
    except ValueError:
        return False
    return p.scheme in ("http", "https") and "." in p.netloc and (p.path.strip("/") != "" or bool(p.query))


def probe(base_url: str, http, *, query: str = "Paris", timeout: float = 4.0) -> dict:
    """The health of a SearXNG instance (``/api/health``): results on a canary query with its default engines, the
    engines that answered, the unresponsive ones and why, and whether the fallback engines answer. Never raises."""
    import time

    url = base_url.rstrip("/") + "/search"
    out: dict = {"backend": "searxng", "query": query}
    t0 = time.monotonic()
    for key, engines in (("default", ()), ("fallback", fallback_engines())):
        if key == "fallback" and (out.get("results") or not engines):
            break
        params = {"q": query, "format": "json", **({"engines": ",".join(engines)} if engines else {})}
        try:
            r = http.get(url, params=params, timeout=timeout)
            data = _json(r, "SearXNG")
        except Exception as e:  # noqa: BLE001 - the probe reports, never raises
            out[key] = {"ok": False, "error": e.code if isinstance(e, SearchError) else type(e).__name__}
            continue
        results = data.get("results") or []
        alive = sorted({str(en) for x in results for en in (x.get("engines") or [])})
        down = [{"engine": str(e[0]), "why": str(e[1])[:80] if len(e) > 1 else ""}
                for e in data.get("unresponsive_engines") or [] if isinstance(e, (list, tuple)) and e]  # fmt: skip
        out[key] = {"ok": bool(results), "results": len(results), "alive": alive, "unresponsive": down,
                    **({"engines": list(engines)} if engines else {})}  # fmt: skip
        out["results"] = out.get("results", 0) or len(results)
    out["ok"] = bool((out.get("default") or {}).get("ok"))
    out["degraded"] = not out["ok"] and bool((out.get("fallback") or {}).get("ok"))
    out["seconds"] = round(time.monotonic() - t0, 2)
    return out


class BraveBackend:
    """Brave Search API (web results). Docs: https://api-dashboard.search.brave.com/app/documentation."""

    name, label = "brave", "Brave Search"
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, http, timeout: float = 10.0, sleep=None, retries: int = 1):
        import time

        self.key, self.http, self.timeout = api_key, http, timeout
        self.sleep, self.retries = sleep or time.sleep, retries

    @staticmethod
    def limit_error(r) -> SearchError:
        """429 from Brave: X-RateLimit-Remaining / -Reset hold one comma-separated value per window
        (per second, per month). A monthly remaining of 0 means the plan's quota is used up."""

        def values(name):
            try:
                return [float(x) for x in (r.headers.get(name) or "").split(",") if x.strip()]
            except ValueError:
                return []

        remaining, reset = values("x-ratelimit-remaining"), values("x-ratelimit-reset")
        if len(remaining) > 1 and remaining[-1] <= 0:
            return SearchError(
                "search_quota",
                "Brave Search: the monthly search quota is used up (HTTP 429)",
                reset[-1] if len(reset) > 1 else None,
            )
        return SearchError(
            "search_rate_limited", "Brave Search is rate limiting searches (HTTP 429)", reset[0] if reset else None
        )

    def search(self, query: str, n: int, lang: str | None = None) -> list[dict]:
        params = {
            "q": query,
            "count": max(1, min(int(n), 20)),
            **({"search_lang": lang} if lang else {}),
            "extra_snippets": "true",
        }
        headers = {"Accept": "application/json", "X-Subscription-Token": self.key}
        r = self.http.get(self.URL, params=params, headers=headers, timeout=self.timeout)
        if r.status_code == 429:
            err = self.limit_error(r)
            if err.code == "search_rate_limited" and (err.retry_after or 0) <= 2 and self.retries:
                self.sleep(max(1.0, err.retry_after or 1.0))  # per-second window: one polite retry
                r = self.http.get(self.URL, params=params, headers=headers, timeout=self.timeout)
                if r.status_code == 429:
                    raise self.limit_error(r)
            else:
                raise err
        results = ((_json(r, self.label).get("web") or {}).get("results")) or []
        out = []
        for x in results[:n]:
            if not isinstance(x, dict):
                continue
            extra = " ".join(_clean(e) for e in (x.get("extra_snippets") or [])[:2] if isinstance(e, str))
            snippet = _clean(x.get("description")) + (" " + extra if extra else "")
            age = _clean(x.get("age") or x.get("page_age") or "")
            thumb = x.get("thumbnail") if isinstance(x.get("thumbnail"), dict) else {}
            image = _image(thumb.get("src")) if not thumb.get("logo") else {}  # Brave's own image proxy
            out.append(
                {"title": _clean(x.get("title")), "url": x.get("url") or "", "snippet": snippet, "date": age, **image}
            )
        return out


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
            {"title": _clean(x.get("title")), "url": x.get("url") or "", "snippet": _clean(x.get("content"))[:600]}
            for x in (_json(r, self.label).get("results") or [])[:n]
            if isinstance(x, dict)
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

    def __init__(
        self, http, timeout: float = 10.0, contact: str | None = None, lang: str = "fr", sleep=None, retries: int = 1
    ):
        import time

        self.http, self.timeout, self.default_lang = http, timeout, lang if lang in self.LANGS else "fr"
        self.sleep, self.retries = sleep or time.sleep, retries
        self.headers = {"User-Agent": user_agent(contact), "Accept": "application/json"}

    @property
    def label(self) -> str:
        return self.label_for(self.default_lang)

    @staticmethod
    def label_for(lang: str | None) -> str:
        return "Wikipedia (en)" if lang == "en" else "Wikipédia"

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
            "prop": "extracts|info|pageimages",
            "piprop": "thumbnail",  # pilicense stays at its default, "free": free-licence images only
            "pithumbsize": 640,
            "pilimit": n,
            "exintro": 1,
            "explaintext": 1,
            "exsentences": 4,
            "exlimit": n,
            "inprop": "url",
            "utf8": 1,
            "maxlag": 5,
        }
        url = f"https://{lang}.wikipedia.org/w/api.php"
        r = self.http.get(url, params=params, headers=self.headers, timeout=self.timeout)
        if r.status_code in (429, 503):  # Wikimedia asks clients to honour Retry-After; one short, polite retry
            wait = _retry_after(r)
            if wait is not None and wait <= 3 and self.retries:
                self.sleep(max(1.0, wait))
                r = self.http.get(url, params=params, headers=self.headers, timeout=self.timeout)
        pages = ((_json(r, self.label).get("query") or {}).get("pages")) or []
        pages = sorted((p for p in pages if isinstance(p, dict)), key=lambda p: p.get("index") or 0)
        return [
            {
                "title": _clean(p.get("title")),
                "url": p.get("fullurl")
                or f"https://{lang}.wikipedia.org/wiki/{str(p.get('title', '')).replace(' ', '_')}",
                "snippet": _clean(p.get("extract"))[:600],
                **_image((p.get("thumbnail") or {}).get("source") if isinstance(p.get("thumbnail"), dict) else None),
            }
            for p in pages[:n]
        ]


class FallbackSearch:
    """A keyed backend first; when it fails (quota, refused key, outage), the no-key Wikipedia search.

    ``last`` says which backend answered the latest call and why the first one was skipped, for the UI.
    """

    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback
        self.name, self.label = primary.name, primary.label
        self.last: dict = {}

    def search(self, query: str, n: int, lang: str | None = None) -> list[dict]:
        try:
            results = self.primary.search(query, n, lang=lang)
            self.last = {"backend": self.primary.name, "label": self.primary.label,
                         **dict(getattr(self.primary, "last", None) or {})}  # fmt: skip
            return results
        except Exception as e:  # noqa: BLE001 - any failure of the keyed backend: try the free one
            code = e.code if isinstance(e, SearchError) else "search_failed"
            results = self.fallback.search(query, n, lang=lang)
            inner = dict(getattr(self.fallback, "last", None) or {})  # a chain (SearXNG → Brave → Wikipedia)
            self.last = {
                "backend": inner.get("backend") or self.fallback.name,
                "label": inner.get("label")
                or (self.fallback.label_for(lang) if hasattr(self.fallback, "label_for") else self.fallback.label),
                "fallback_from": self.primary.label,
                "fallback_code": code,
            }
            return results


def make_search(cfg, http):
    """The search chain the configuration gives: SearXNG first (the default), then Brave, then Tavily, each one
    the backup of the one before, and the no-key Wikipedia search last (unless ``search_default="none"``).
    None when search is off."""
    contact = getattr(cfg, "search_contact", None)
    wiki = (
        WikipediaBackend(http, contact=contact) if getattr(cfg, "search_default", "wikipedia") == "wikipedia" else None
    )
    chain = []
    if getattr(cfg, "searxng_url", None):
        chain.append(SearxngBackend(cfg.searxng_url, http))
    if getattr(cfg, "brave_api_key", None):
        chain.append(BraveBackend(cfg.brave_api_key, http))
    if getattr(cfg, "tavily_api_key", None):
        chain.append(TavilyBackend(cfg.tavily_api_key, http))
    tail = wiki
    for backend in reversed(chain):
        tail = FallbackSearch(backend, tail) if tail else backend
    return tail
