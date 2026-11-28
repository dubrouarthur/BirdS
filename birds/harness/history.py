"""Conversation history for the next turn: a token budget, coarse cuts, and a compact memo of past tool use.

Why coarse cuts: the model server (vLLM) caches the key/values of prompt PREFIXES it has already seen. If each new
turn dropped one more old message, the start of the prompt would change at every turn and nothing could be
reused. So whole turns are dropped in blocks of ``block`` turns: the cut point moves rarely, and between two moves
the rendered prompt of turn N+1 starts with exactly the bytes of turn N's prompt.

Nothing here calls the model. Dropped turns are summarised extractively (first line of each request, files and
sources they produced) in a fixed-format note appended to the system message.
"""

from __future__ import annotations

import re

CHARS_PER_TOKEN = 3.5  # conservative for French text; the budget is an estimate, the server counts exactly
NOTE = {
    "fr": "Plus tôt dans cette conversation (résumé, tours retirés pour rester court) :",
    "en": "Earlier in this conversation (summarised, turns removed to stay short):",
}
MEMO_LABELS = {
    "fr": {
        "head": "Mémo de ce tour",
        "tools": "outils",
        "sources": "sources",
        "files": "fichiers créés",
        "draft": "brouillon de mail",
        "results": "résultats de recherche",
        "notsent": "non envoyé",
        "chart": "graphique affiché",
        "columns": "colonnes",
        "figures": "chiffres lus",
        "todo": "reste à faire",
    },
    "en": {
        "head": "Memo of this turn",
        "tools": "tools",
        "sources": "sources",
        "files": "files created",
        "draft": "email draft",
        "results": "search results",
        "notsent": "not sent",
        "chart": "chart shown",
        "columns": "columns",
        "figures": "figures read",
        "todo": "still to do",
    },
}


def tokens(text: str) -> int:
    return int(len(text or "") / CHARS_PER_TOKEN) + 4  # + a few tokens of chat-template framing per message


def _plain(text: str, limit: int) -> str:
    """One line, no markup that the chat template or the defang step could react to."""
    s = " ".join(str(text or "").replace("<", "‹").replace(">", "›").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


INTERRUPTED = {"fr": "[réponse interrompue]", "en": "[answer interrupted]"}
MEMO_CAP = 2400
CHART_CAP = 400


def _num(v) -> str:
    if v is None:
        return "–"
    return f"{v:g}" if isinstance(v, float) else str(v)


def chart_line(chart: dict, lab: dict) -> str:
    """'graphique : « CA » (bar, k€) colonnes Trimestre / CA — T1 120 ; T2 135', at most CHART_CAP characters."""
    cols = [str(c) for c in chart.get("columns") or []]
    unit = f", {chart['unit']}" if chart.get("unit") else ""
    head = (
        f"{lab['chart']} : « {_plain(chart.get('title'), 80)} » ({chart.get('type')}{unit}) "
        f"{lab['columns']} {' / '.join(_plain(c, 30) for c in cols)} — "
    )
    rows = " ; ".join(_plain(r[0], 30) + " " + "/".join(_num(v) for v in r[1:]) for r in chart.get("rows") or [] if r)
    line = head + rows
    return line if len(line) <= CHART_CAP else line[: CHART_CAP - 1].rstrip() + "…"


SUMMARY_CAP = 2100


def memo(
    lang: str,
    steps: list[dict],
    sources: list[dict],
    files: list[str],
    draft: dict | None,
    results: list[dict] | None = None,
    charts: list[dict] | None = None,
    context: dict | None = None,
    figures: list | None = None,
    todo: list[str] | None = None,
) -> str:
    """Deterministic, compact record of what the tools did in one turn: tool names and key arguments, search result
    titles and URLs (so "the second source" can be answered later), pages read, files made, draft subject, the data
    of the charts shown (so "refais-le en courbe" can chart it again), and the arguments of the rich result shown (so « et
    à Lyon ? » can ask it again, see followup.py). ``figures`` are the labelled totals the tools read
    (facts.key_figures: « Total TTC 300,00 € », label and amount only), so « envoie ces totaux par mail » has them
    next turn; ``todo`` is what the task plan could not complete, so « vas-y, fais le mail » knows what is left.
    Never raw tool output, never excerpts, never an image transcription (it lives in the user turn)."""
    lab = MEMO_LABELS["en" if lang == "en" else "fr"]
    parts = []
    used = []
    for s in steps[:8]:
        tool, a = str(s.get("tool") or ""), s.get("arguments") or {}
        key = a.get("query") or a.get("url") or a.get("path") or a.get("title") or a.get("subject") or ""
        used.append(f"{tool} « {_plain(key, 80)} »" if key else tool)
    if used:
        parts.append(f"{lab['tools']} : " + " ; ".join(used))
    if results:
        parts.append(
            f"{lab['results']} : "
            + " ; ".join(
                f"{i}. {_plain(r.get('title'), 70)} ({_plain(r.get('url'), 120)})" for i, r in enumerate(results[:5], 1)
            )
        )
    if sources:
        parts.append(
            f"{lab['sources']} : "
            + " ; ".join(
                f"[{s.get('n')}] {_plain(s.get('title'), 90)} ({_plain(s.get('url'), 160)})" for s in sources[:6]
            )
        )
    if files:
        parts.append(f"{lab['files']} : " + ", ".join(_plain(f, 80) for f in files[:6]))
    if draft:
        parts.append(f"{lab['draft']} : « {_plain(draft.get('subject'), 120)} » ({lab['notsent']})")
    if context:
        from birds.harness.followup import memo_part

        part = memo_part(context, lang)
        if part:
            parts.append(part)
    if figures:
        parts.append(f"{lab['figures']} : " + " ; ".join(f"{_plain(f[0], 32)} {_plain(f[1], 24)}" for f in figures[:6]))
    if todo:
        parts.append(f"{lab['todo']} : " + ", ".join(_plain(t, 40) for t in todo[:4]))
    for c in (charts or [])[:3]:
        parts.append(chart_line(c, lab))
    out = f"[{lab['head']} — " + " | ".join(parts) + "]" if parts else ""
    return out if len(out) <= MEMO_CAP else out[: MEMO_CAP - 2] + "…]"


def _turns(history: list[dict]) -> list[list[dict]]:
    """Group messages into turns: a user message and the assistant message(s) that follow it."""
    turns: list[list[dict]] = []
    for m in history:
        if m.get("role") == "user" or not turns:
            turns.append([m])
        else:
            turns[-1].append(m)
    return turns


def cap(text: str, cap_chars: int) -> str:
    """Head 2/3 + tail 1/3 of a long message. Position-independent: the same message renders the same everywhere."""
    if len(text) <= cap_chars:
        return text
    head = (cap_chars * 2) // 3
    tail = cap_chars - head
    return text[:head] + "\n[…]\n" + text[-tail:]


def _render(m: dict, lang: str, cap_chars: int) -> dict:
    content = str(m.get("content") or "")
    if m.get("role") == "assistant":
        if m.get("memo"):
            content = (content + "\n\n" + _plain(m["memo"], MEMO_CAP)).strip()
        if m.get("interrupted"):
            content += "\n\n" + INTERRUPTED["en" if lang == "en" else "fr"]
    return {"role": m["role"], "content": cap(content, cap_chars)}


def _summary(turns: list[list[dict]], lang: str) -> str:
    lines = []
    for t in turns:
        user = next((m for m in t if m["role"] == "user"), None)
        first = _plain((str(user.get("content") or "").strip().splitlines() or [""])[0], 120) if user else ""
        extra = []
        for m in t:
            for chunk in re.findall(r"\b(?:fichiers créés|files created|sources|chiffres lus|figures read) : [^|\]]+", str(m.get("memo") or "")):
                extra.append(_plain(chunk, 160))
        lines.append("- " + first + (" → " + " ; ".join(extra)[:160] if extra else ""))
    out = NOTE["en" if lang == "en" else "fr"] + "\n" + "\n".join(lines[-12:])
    return out[:SUMMARY_CAP]


def window(
    history: list[dict], budget_tokens: int, *, lang: str = "fr", msg_cap_tokens: int = 3168
) -> tuple[list[dict], str, dict]:
    """(messages to send, summary note or "", stats). ``history`` excludes the system and the current user message.

    Hysteresis cut: the kept history grows until it passes HIGH = budget; then the oldest whole turns are dropped
    until it is under LOW = HIGH / 2. The cut is replayed over the conversation from its start, so it is a pure
    function of the history (stateless server) and only moves about once per HIGH/2 tokens of new conversation:
    between two moves, turn N+1's prompt starts with exactly the bytes of turn N's prompt (vLLM prefix cache).
    Every message is capped at ``msg_cap_tokens`` (head 2/3 + tail 1/3). The newest turn is always kept.
    """
    cap_chars = int(msg_cap_tokens * CHARS_PER_TOKEN)
    turns = _turns([m for m in history if m.get("role") in ("user", "assistant")])
    rendered = [[_render(m, lang, cap_chars) for m in t] for t in turns]
    sizes = [sum(tokens(m["content"]) for m in t) for t in rendered]
    high, low = budget_tokens, budget_tokens // 2
    drop, running, moved = 0, 0, False
    for k, size in enumerate(sizes):  # replay: as if each turn were the newest
        running += size
        moved = False
        if running > high:
            while drop < k and running > low:
                running -= sizes[drop]
                drop += 1
                moved = True
    kept = [m for t in rendered[drop:] for m in t]
    note = _summary(turns[:drop], lang) if drop else ""
    stats = {
        "turns": len(turns),
        "dropped_turns": drop,
        "cut_moved": moved,
        "history_tokens_est": sum(tokens(m["content"]) for m in kept),
        "budget": budget_tokens,
    }
    return kept, note, stats
