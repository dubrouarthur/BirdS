"""The one HTTP path of the open-data tools: fixed hosts, the egress guard, polite spacing, caching, one retry.

Every URL here is built by the server from a fixed base (never a URL the model or a page wrote) and must belong to
``HOSTS``; redirects may not leave the host. Requests go through ``guard.fetch_bytes`` (deny lists, private
addresses refused, DNS pinning, size and time caps), with a generic User-Agent naming the application and its site
(Wikimedia, Crossref and OpenAlex etiquette) and nothing about the person: only the query itself leaves.

Caching: answers are kept in the process-wide ``geo.POLICY`` cache (optionally mirrored on disk, file names are
hashes) for the time each provider's terms make reasonable (``TTL``); an answer marked ``no-store`` is never kept.
At most ``MAX_CALLS`` upstream requests per answer. A 429 or 5xx is a calm "try again later", never a crash.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlencode, urlsplit

from birds.harness import geo, guard
from birds.harness.guard import Blocked, ToolError

USER_AGENT = "BirdS/1.0 (+https://bird-s.vercel.app; open data client) httpx"
MAX_CALLS = 6  # upstream requests per answer, all open-data providers together
MAX_BYTES = 2_500_000
TIMEOUT = 12.0
RETRY_AFTER = 1.2
DAY = 86400.0

# host -> (seconds between two requests, process-wide; cache TTL in seconds)
HOSTS: dict[str, tuple[float, float]] = {
    "calendrier.api.gouv.fr": (0.1, 30 * DAY),  # static tables (Etalab 2.0)
    "date.nager.at": (0.5, 30 * DAY),  # single maintainer, donation-funded: cache hard
    "fr.wikipedia.org": (0.2, DAY),
    "en.wikipedia.org": (0.2, DAY),
    "www.wikidata.org": (0.2, DAY),
    "ec.europa.eu": (0.3, DAY),  # Eurostat dissemination API
    "api.worldbank.org": (0.3, DAY),
    "api.insee.fr": (2.1, DAY),  # Melodi anonymous quota: about 30 requests a minute
    "boamp-datadila.opendatasoft.com": (0.3, 3600.0),  # new notices all day long: 1 hour
    "api.openalex.org": (0.2, DAY),
    "api.crossref.org": (0.3, DAY),
    "geo.api.gouv.fr": (0.05, 7 * DAY),
    "data.geopf.fr": (0.05, 7 * DAY),
}
for _host, (_gap, _) in HOSTS.items():
    geo.INTERVALS.setdefault(_host, _gap)


def url(base: str, params: dict | list | None = None) -> str:
    if not params:
        return base
    return base + ("&" if "?" in base else "?") + urlencode(params, doseq=True)


def host_of(u: str) -> str:
    try:
        return (urlsplit(u).hostname or "").lower()
    except ValueError:
        return ""


def _no_store(headers: dict) -> bool:
    cc = str({str(k).lower(): v for k, v in (headers or {}).items()}.get("cache-control", "")).lower()
    return bool(re.search(r"\bno-store\b", cc))


def get(ctx, u: str, *, ttl: float | None = None, text: bool = False, accept: str = "application/json",
        types: tuple[str, ...] = ("application/json", "application/geo+json", "text/json", "application/vnd.api+json"),
        miss_ttl: float = 3600.0, max_bytes: int = MAX_BYTES):  # fmt: skip
    """JSON (or text) at ``u``, a URL built by the caller from a fixed base. Recorded answers when ``ctx.recorded``
    is set (the scripted demo and the tests): no network at all."""
    host = host_of(u)
    if host not in HOSTS:
        raise Blocked(f"host not allowed for open data: {host or '?'}")
    recorded = getattr(ctx, "recorded", None)
    if recorded is not None:
        data = recorded(u)
        if data is None:
            raise ToolError("the service could not be reached (recorded)")
        return data
    cfg = ctx.config
    disk = getattr(cfg, "geo_cache_dir", None)
    key = geo.Policy.key("opendata", u)
    hit = geo.POLICY.get(key, disk)
    if hit is not None:
        return hit
    used = getattr(ctx, "opendata_calls", 0)
    if used >= MAX_CALLS:
        raise ToolError("lookup limit of this answer reached")
    ctx.opendata_calls = used + 1
    geo.POLICY.wait_turn(host)
    body, hdrs = b"", {}
    for attempt in (0, 1):
        try:
            _, _, body, hdrs = guard.fetch_bytes(
                ctx.http, cfg, u, accept=accept, types=types, max_bytes=max_bytes, user_agent=USER_AGENT,
                timeout=min(TIMEOUT, cfg.http_timeout), redirect_ok=lambda nxt: host_of(nxt) == host,
            )  # fmt: skip
            break
        except ToolError as e:
            msg = str(e)
            if msg.startswith("HTTP 429"):
                if attempt == 0:  # Wikimedia and Crossref say « Retry-After: 1 »: one polite second, once
                    geo.POLICY.sleep(RETRY_AFTER)
                    continue
                raise ToolError("the service is busy (HTTP 429): try again in a minute") from None
            if msg.startswith("HTTP 404"):
                raise ToolError("HTTP 404") from None
            # a reset connection or a 5xx: one more try, then a calm failure
            if attempt == 0 and ("could not be reached" in msg or re.match(r"HTTP 5\d\d", msg)):
                continue
            raise
    ctx.bytes_fetched = getattr(ctx, "bytes_fetched", 0) + len(body)
    if text:
        data = body.decode("utf-8", errors="replace")
    else:
        try:
            data = json.loads(body)
        except ValueError as e:
            raise ToolError("the service returned invalid JSON") from e
    if not _no_store(hdrs):
        empty = data in (None, "", [], {})
        geo.POLICY.put(key, data, miss_ttl if empty else (ttl or HOSTS[host][1]), disk)
    return data


def cite(ctx, link: str) -> int:
    """Add ``link`` to the run's sources (once) and return its number."""
    if link not in ctx.sources:
        ctx.sources.append(link)
    return ctx.sources.index(link) + 1


def lang_of(ctx) -> str:
    return ctx.lang if getattr(ctx, "lang", "fr") in ("fr", "en") else "fr"


def clean(text, n: int = 200) -> str:
    """One line of plain text, at most ``n`` characters (provider text is data: no markup survives)."""
    s = re.sub(r"<[^>]{0,200}>", "", str(text or ""))
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"
