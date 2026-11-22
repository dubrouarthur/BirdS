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
        "image": "image lue",
    },
    "en": {
        "head": "Memo of this turn",
        "tools": "tools",
        "sources": "sources",
        "files": "files created",
        "draft": "email draft",
        "image": "image read",
    },
}


def tokens(text: str) -> int:
    return int(len(text or "") / CHARS_PER_TOKEN) + 4  # + a few tokens of chat-template framing per message


def _plain(text: str, limit: int) -> str:
    """One line, no markup that the chat template or the defang step could react to."""
    s = " ".join(str(text or "").replace("<", "‹").replace(">", "›").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def memo(
    lang: str, steps: list[dict], sources: list[dict], files: list[str], draft: dict | None, image: str = ""
) -> str:
    """Deterministic, compact record of what the tools did in one turn (never the raw tool outputs)."""
    lab = MEMO_LABELS["en" if lang == "en" else "fr"]
    parts = []
    used = []
    for s in steps[:8]:
        tool, a = str(s.get("tool") or ""), s.get("arguments") or {}
        key = a.get("query") or a.get("url") or a.get("path") or a.get("title") or a.get("subject") or ""
        used.append(f"{tool} « {_plain(key, 80)} »" if key else tool)
    if used:
        parts.append(f"{lab['tools']} : " + " ; ".join(used))
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
        parts.append(f"{lab['draft']} : « {_plain(draft.get('subject'), 120)} » (non envoyé)")
    if image:
        parts.append(f"{lab['image']} : {_plain(image, 600)}")
    return f"[{lab['head']} — " + " | ".join(parts) + "]" if parts else ""


def _turns(history: list[dict]) -> list[list[dict]]:
    """Group messages into turns: a user message and the assistant message(s) that follow it."""
    turns: list[list[dict]] = []
    for m in history:
        if m.get("role") == "user" or not turns:
            turns.append([m])
        else:
            turns[-1].append(m)
    return turns


def _render(m: dict) -> dict:
    content = str(m.get("content") or "")
    if m.get("role") == "assistant" and m.get("memo"):
        content = (content + "\n\n" + _plain(m["memo"], 2400)).strip()
    return {"role": m["role"], "content": content}


def _summary(turns: list[list[dict]], lang: str) -> str:
    lines = []
    for t in turns:
        user = next((m for m in t if m["role"] == "user"), None)
        first = _plain((str(user.get("content") or "").strip().splitlines() or [""])[0], 120) if user else ""
        extra = []
        for m in t:
            for chunk in re.findall(
                r"\b(?:fichiers créés|files created|sources) : [^|\]]+", str(m.get("memo") or "")
            ):
                extra.append(_plain(chunk, 160))
        lines.append("- " + first + (" → " + " ; ".join(extra) if extra else ""))
    return NOTE["en" if lang == "en" else "fr"] + "\n" + "\n".join(lines[-12:])


def window(
    history: list[dict], budget_tokens: int, *, lang: str = "fr", block: int = 4
) -> tuple[list[dict], str, dict]:
    """(messages to send, summary note or "", stats). ``history`` excludes the system and the current user message.

    Keeps the newest turns that fit ``budget_tokens``; when it must drop, it drops the oldest turns in multiples
    of ``block``, so the cut moves at most once every ``block`` turns. The newest turn is always kept (its
    assistant text is shortened in the middle if it alone exceeds the budget).
    """
    turns = _turns([m for m in history if m.get("role") in ("user", "assistant")])
    rendered = [[_render(m) for m in t] for t in turns]
    sizes = [sum(tokens(m["content"]) for m in t) for t in rendered]
    total = sum(sizes)
    drop = 0
    if total > budget_tokens:
        while drop < len(turns) - 1 and sum(sizes[drop:]) > budget_tokens:
            drop += 1
        drop = min(len(turns) - 1, -(-drop // block) * block)  # round the cut up to a whole block
    kept = [m for t in rendered[drop:] for m in t]
    if kept and sum(tokens(m["content"]) for m in kept) > budget_tokens:
        last = kept[-1]
        room = max(400, int((budget_tokens - sum(tokens(m["content"]) for m in kept[:-1])) * CHARS_PER_TOKEN))
        if len(last["content"]) > room:
            half = room // 2
            last["content"] = last["content"][:half] + "\n[…]\n" + last["content"][-half:]
    note = _summary(turns[:drop], lang) if drop else ""
    stats = {
        "turns": len(turns),
        "dropped_turns": drop,
        "history_tokens_est": sum(tokens(m["content"]) for m in kept),
        "budget": budget_tokens,
    }
    return kept, note, stats
