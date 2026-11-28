"""Inline citations [n] the harness can stand behind (chat audit R27).

The model is told which number to cite (« Source à citer : [1] ») but a small model often writes a sourced answer
with no mark at all, so a claim cannot be checked one by one. After the run, each sentence of a sourced answer
that the model left unmarked gets ``[n]`` only when the text of source n really holds it: a figure of the
sentence is on that page and a fair share of its long words too, or most of its long words are. Nothing is
invented: a sentence that no page read supports keeps no mark, and an answer the model already cited is left as
it is (its marks are the model's choice; a mark pointing to no source is ignored by the renderer).

The page texts are what the tools returned to the model in this run (``read_page`` results, the entity card's
extract and facts), never fetched again.
"""

from __future__ import annotations

import re

from birds.harness import crew_checks as cc

_CITE = re.compile(r"\[(\d{1,2})\]")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_SKIP_LINE = re.compile(r"^\s{0,3}(?:#|\||>|\[!|[-*_]{3,}\s*$)")  # headings, tables, quotes, rules
_SENTENCE = re.compile(r"(?<=[.!?…»”)\]])\s+(?=[A-ZÀ-ÖØ-Þ«\"0-9])")
_TAIL = re.compile(r"([.!?…:;]+[»”)\]]*|\s*)$")


def source_texts(messages: list[dict], steps, sources: list[dict]) -> dict[int, str]:
    """{n: what the tools returned for source n in this run}: pages read (« URL: … » results) and entity cards."""
    by_url = {str(s.get("url")): int(s["n"]) for s in sources if s.get("url") and str(s.get("n", "")).isdigit()}
    out: dict[int, list[str]] = {}
    for m in messages or []:
        content = m.get("content")
        if m.get("role") != "tool" or not isinstance(content, str) or not content.startswith("URL: "):
            continue
        url = content.split("\n", 1)[0][5:].strip()
        if url in by_url:
            out.setdefault(by_url[url], []).append(content)
    for s in steps or []:
        w = (getattr(s, "info", None) or {}).get("widget") or {}
        if getattr(s, "tool", "") != "lookup_entity" or w.get("type") != "entity":
            continue
        url = str((w.get("source") or {}).get("url") or w.get("url") or "")
        if url in by_url:
            facts = " ; ".join(
                f"{f.get('label')} : {f.get('value')} {f.get('date') or ''}" for f in w.get("facts") or []
            )
            parts = [w.get("title"), w.get("description"), w.get("extract"), facts]
            out.setdefault(by_url[url], []).append("\n".join(str(p) for p in parts if p))
    return {n: "\n".join(t) for n, t in out.items()}


def _backs(sentence: str, text: str, figures: set[float]) -> float:
    """How well one page backs one sentence (0: not at all). A figure of the sentence on the page counts most."""
    words = [w for w in re.findall(r"[a-z]{5,}", cc.fold(sentence)) if w not in cc._STOPWORDS]
    share = cc.support(sentence, text) if len(words) >= 3 else 0.0
    figs = [v for _raw, v in cc.figures(sentence)]
    on = sum(cc.on_page(v, figures) for v in figs)
    if figs and on == len(figs) and share >= 0.3:
        return 2.0 + share
    if not figs and share >= 0.6:
        return share
    return 0.0


def attribute(content: str, sources: list[dict], texts: dict[int, str]) -> tuple[str, int]:
    """(content with [n] after each sentence a page read backs, number of marks added)."""
    texts = {n: t for n, t in (texts or {}).items() if t and t.strip()}
    if not texts or not content or _CITE.search(content):
        return content, 0
    figures = {n: cc.allowed_figures(t) for n, t in texts.items()}
    out, added, fenced = [], 0, False
    for line in content.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
        if fenced or _FENCE.match(line) or _SKIP_LINE.match(line) or len(line.strip()) < 40:
            out.append(line)
            continue
        parts = _SENTENCE.split(line)
        cited = []
        for part in parts:
            if len(part.strip()) < 40 or re.search(r"https?://", part):
                cited.append(part)
                continue
            score, n = max(((_backs(part, texts[n], figures[n]), -n) for n in sorted(texts)), default=(0.0, 0))
            if score <= 0:
                cited.append(part)
                continue
            body, tail = part[: _TAIL.search(part).start()], _TAIL.search(part).group(1)
            cited.append(f"{body} [{-n}]{tail}")
            added += 1
        out.append(" ".join(cited) if len(parts) > 1 else cited[0])
    return "\n".join(out), added
