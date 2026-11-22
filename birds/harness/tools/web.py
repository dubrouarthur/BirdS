"""web_search (pluggable backend) and read_page (guarded fetch + deterministic text extraction, no model)."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from birds.harness import guard
from birds.harness.guard import ToolError
from birds.harness.tools.search import (  # noqa: F401 - re-exported
    BraveBackend,
    FallbackSearch,
    SearchError,
    SearxngBackend,
    TavilyBackend,
    WikipediaBackend,
    make_search,
)


class StaticBackend:
    """Fixed results, for tests and demos."""

    name, label = "static", "Static"

    def __init__(self, results: list[dict]):
        self.results = results

    def search(self, query: str, n: int, lang: str | None = None) -> list[dict]:
        return self.results[:n]


def web_search(args: dict, ctx) -> str:
    if ctx.search is None:
        raise ToolError("web search is not configured on this deployment")
    backend = ctx.search
    try:
        try:
            results = backend.search(args["query"], args.get("max_results") or 5, lang=ctx.lang)
        except TypeError:  # a backend written before the lang parameter existed
            results = backend.search(args["query"], args.get("max_results") or 5)
    except SearchError as e:
        ctx.step_info = {
            "backend": getattr(backend, "name", "?"),
            "label": getattr(backend, "label", ""),
            "code": e.code,
        }
        raise ToolError(f"{e}. Answer without searching and tell the user the search is unavailable.") from e
    except Exception as e:
        ctx.step_info = {
            "backend": getattr(backend, "name", "?"),
            "label": getattr(backend, "label", ""),
            "code": "search_failed",
        }
        raise ToolError(f"search backend failed ({type(e).__name__})") from e
    last = getattr(backend, "last", None)
    if last:
        ctx.step_info = dict(last)
    else:
        label = backend.label_for(ctx.lang) if hasattr(backend, "label_for") else getattr(backend, "label", "")
        ctx.step_info = {"backend": getattr(backend, "name", "?"), "label": label}
    # titles and URLs only (never snippets): the memo of the turn keeps them for follow-ups ("the second source")
    ctx.step_info["results"] = [
        {"title": " ".join(str(r.get("title") or "").split())[:150], "url": str(r.get("url") or "")}
        for r in results[:5]
    ]
    for r in results:
        url = str(r.get("url") or "")
        if url and url not in ctx.found:
            ctx.found.append(url)
    for r in results[:3]:  # image candidates for the UI only: an image URL is never put in the model's text
        if r.get("image"):
            add_image(ctx, str(r["image"]), str(r.get("url") or ""), str(r.get("title") or ""), "", "search")
    if not results:
        return "No results."
    lines = []
    for i, r in enumerate(results, 1):
        snippet = " ".join(str(r.get("snippet") or "").split())[:300]
        date = f" ({r['date']})" if r.get("date") else ""
        lines.append(f"{i}. {' '.join(str(r.get('title') or '').split())[:150]}{date}\n   {r.get('url')}\n   {snippet}")
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


MAX_IMAGE_CANDIDATES = 8
_BAD_IMAGE = re.compile(
    r"logo|favicon|sprite|icon|avatar|placeholder|default|blank|pixel|spacer|badge|banner|ads?[/_-]|tracking", re.I
)


def add_image(ctx, src: str, page: str, title: str, alt: str, origin: str) -> None:
    """Remember an image candidate (one per page, never the same src twice, at most 8). Shown only by the web app,
    which chooses among them at answer time (birds.web.backends.pick_web_images)."""
    images = getattr(ctx, "images", None)
    if images is None or not src or not page or len(images) >= MAX_IMAGE_CANDIDATES:
        return
    if any(i["src"] == src or i["page"] == page for i in images):
        return
    images.append(
        {"src": src, "page": page, "title": " ".join(title.split())[:120], "alt": " ".join(alt.split())[:160],
         "origin": origin}
    )  # fmt: skip


def _int(value) -> int | None:
    m = re.match(r"\s*(\d+)", str(value or ""))
    return int(m.group(1)) if m else None


class _Images(HTMLParser):
    """The page's own illustration: og:image / twitter:image / image_src metas, else a large <img> in the article."""

    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.imgs: list[dict] = []
        self.depth = 0  # inside <article> or <main>

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "link" and "image_src" in a.get("rel", "").lower() and a.get("href"):
            self.meta.setdefault("image_src", a["href"].strip())
        elif tag in ("article", "main"):
            self.depth += 1
        elif tag == "img" and self.depth and len(self.imgs) < 40:
            self.imgs.append(a)

    def handle_endtag(self, tag):
        if tag in ("article", "main"):
            self.depth = max(0, self.depth - 1)


def _usable(src: str, base: str) -> str | None:
    from urllib.parse import urljoin, urlsplit

    src = html.unescape(str(src or "").strip())
    if not src or src.startswith("data:"):
        return None
    full = urljoin(base, src)
    parts = urlsplit(full)
    if parts.scheme not in ("http", "https") or not parts.netloc or len(full) > 2048:
        return None
    if parts.path.lower().endswith((".svg", ".ico", ".svgz")) or _BAD_IMAGE.search(parts.path):
        return None
    return full


def _srcset_best(srcset: str) -> tuple[str, int]:
    best, width = "", 0
    for part in srcset.split(","):
        bits = part.strip().split()
        if len(bits) == 2 and bits[1].endswith("w") and (_int(bits[1]) or 0) > width:
            best, width = bits[0], _int(bits[1]) or 0
    return best, width


def extract_image(page: str, url: str) -> dict | None:
    """{"src", "alt"} of the page's main image, or None. No new dependency: the standard HTML parser."""
    p = _Images()
    try:
        p.feed(page[:400_000])
    except Exception:  # a malformed page: no image rather than an error
        return None
    m = p.meta
    w, h = _int(m.get("og:image:width")), _int(m.get("og:image:height"))
    sized_ok = not (w and h) or (min(w, h) >= 200 and 1 / 3 <= w / h <= 3)
    if sized_ok:
        for key in (
            "og:image:secure_url",
            "og:image",
            "og:image:url",
            "twitter:image",
            "twitter:image:src",
            "image_src",
        ):
            src = _usable(m.get(key, ""), url)
            if src:
                alt = m.get("og:image:alt") or m.get("twitter:image:alt") or ""
                return {"src": src, "alt": alt}
    for img in p.imgs:
        best, bw = _srcset_best(img.get("srcset", ""))
        iw, ih = _int(img.get("width")), _int(img.get("height"))
        if iw and ih and iw >= 300 and ih >= 150 and 1 / 3 <= iw / ih <= 3:
            src = _usable(img.get("src") or best, url)
        elif bw >= 300:
            src = _usable(best, url)
        else:
            continue
        if src:
            return {"src": src, "alt": img.get("alt", "")}
    return None


def read_page(args: dict, ctx) -> str:
    url, ctype, body = guard.fetch(ctx, args["url"])
    m = re.search(rb"charset=[\"']?([\w-]+)", body[:2048])
    try:
        page = body.decode(m.group(1).decode("ascii") if m else "utf-8", errors="replace")
    except LookupError:
        page = body.decode("utf-8", errors="replace")
    is_html = "html" in ctype or page.lstrip()[:15].lower().startswith(("<!doctype", "<html"))
    title, text = extract(page, url) if is_html else ("", page.strip())
    if not text:
        raise ToolError("the page has no readable text (it may need JavaScript)")
    if url not in ctx.sources:
        ctx.sources.append(url)
    if is_html:
        found = extract_image(page, url)  # for the UI only: the model gets the text, never the image URL
        if found:
            add_image(ctx, found["src"], url, title, found["alt"], "page")
    return f"URL: {url}\n" + (f"Title: {title}\n" if title else "") + "\n" + text
