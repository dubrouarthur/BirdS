"""web_search (pluggable backend) and read_page (guarded fetch + deterministic text extraction, no model)."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from birds.harness import guard
from birds.harness.guard import ToolError


class SearxngBackend:
    """SearXNG JSON API (`/search?format=json`; the instance must enable the json format).

    The base URL is set by the operator, not by the model, so it may be a local address.
    """

    def __init__(self, base_url: str, http, timeout: float = 10.0):
        self.url, self.http, self.timeout = base_url.rstrip("/") + "/search", http, timeout

    def search(self, query: str, n: int) -> list[dict]:
        r = self.http.get(self.url, params={"q": query, "format": "json"}, timeout=self.timeout)
        r.raise_for_status()
        return [
            {"title": x.get("title") or "", "url": x.get("url") or "", "snippet": x.get("content") or ""}
            for x in (r.json().get("results") or [])[:n]
        ]


class StaticBackend:
    """Fixed results, for tests and demos."""

    def __init__(self, results: list[dict]):
        self.results = results

    def search(self, query: str, n: int) -> list[dict]:
        return self.results[:n]


def web_search(args: dict, ctx) -> str:
    if ctx.search is None:
        raise ToolError("web search is not configured on this deployment")
    try:
        results = ctx.search.search(args["query"], args.get("max_results") or 5)
    except Exception as e:
        raise ToolError(f"search backend failed ({type(e).__name__})") from e
    if not results:
        return "No results."
    lines = []
    for i, r in enumerate(results, 1):
        snippet = " ".join(str(r.get("snippet") or "").split())[:300]
        lines.append(f"{i}. {' '.join(str(r.get('title') or '').split())[:150]}\n   {r.get('url')}\n   {snippet}")
    return "\n".join(lines)


class _Text(HTMLParser):
    """Minimal HTML-to-text fallback: drops scripts/styles/navigation, keeps headings and paragraphs as lines."""

    SKIP = {"script", "style", "noscript", "template", "svg", "nav", "footer", "header", "form", "aside", "iframe"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append(
                "\n" + ("#" * int(tag[1]) + " " if tag[0] == "h" and tag[1:].isdigit() else "- " if tag == "li" else "")
            )

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(page: str) -> str:
    p = _Text()
    p.feed(page)
    lines = (" ".join(x.split()) for x in "".join(p.out).splitlines())
    return "\n".join(x for x in lines if x and x not in ("-", "#"))


def extract(page: str, url: str) -> tuple[str, str]:
    """(title, main text) of an HTML page: trafilatura when installed, else the minimal fallback."""
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    title = " ".join(html.unescape(m.group(1)).split()) if m else ""
    text = None
    try:
        import trafilatura

        text = trafilatura.extract(page, url=url, output_format="markdown", include_links=False, include_images=False)
    except Exception:  # not installed, or the extractor choked on this page
        text = None
    return title, (text or html_to_text(page)).strip()


def read_page(args: dict, ctx) -> str:
    url, ctype, body = guard.fetch(ctx, args["url"])
    m = re.search(rb"charset=[\"']?([\w-]+)", body[:2048])
    try:
        page = body.decode(m.group(1).decode("ascii") if m else "utf-8", errors="replace")
    except LookupError:
        page = body.decode("utf-8", errors="replace")
    title, text = (
        extract(page, url)
        if "html" in ctype or page.lstrip()[:15].lower().startswith(("<!doctype", "<html"))
        else ("", page.strip())
    )
    if not text:
        raise ToolError("the page has no readable text (it may need JavaScript)")
    if url not in ctx.sources:
        ctx.sources.append(url)
    return f"URL: {url}\n" + (f"Title: {title}\n" if title else "") + "\n" + text
