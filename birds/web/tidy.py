"""Deterministic repairs of a raw model answer, and syntax checks of its code blocks.

The answer goes back into the history of the next turn, so a byte changed in the middle of it moves the prefix-cache
break point earlier (docs/HISTORY_SPEC.md). Rules, therefore:
- only what makes the Markdown *wrong* is repaired (an unclosed fence, a broken table, an echo, a loop at the end);
  typography and decoration are the client's job (markdown.js);
- idempotent: tidy(tidy(x)) == tidy(x), and a clean answer comes back unchanged (same object);
- the inside of a fenced code block is never touched, except to close it;
- nothing that looks like HTML is removed (the renderer escapes it; tests check it passes through as text).

`code_checks` only PARSES code (ast.parse, json.loads): nothing is ever executed.
"""

from __future__ import annotations

import ast
import json
import re
import textwrap
import warnings
from dataclasses import dataclass, field

RE_FENCE = re.compile(r"^\s{0,3}(```|~~~)\s*([\w+-]*)\s*$")
RE_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
RE_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
RE_SEP_CELL = re.compile(r"^\s*:?-{2,}:?\s*$")
RE_SEP_LINE = re.compile(r"^\s*\|\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|\s*$")

_MEMO_LINE = re.compile(r"(?m)^[ \t]*\[(?:Mémo de ce tour|Memo of this turn) —[^\]\n]*\]?[ \t]*\n?")
_INTERRUPTED = re.compile(r"\s*\[(?:réponse interrompue|answer interrupted)\]\s*$", re.I)
_ROLE_ECHO = re.compile(r"^\s*(?:Bird|Assistant)\s?:[ \t]*(?=\S)")
_GLUED_OPEN = re.compile(r"^(?P<text>[^`\n]*\S)[ \t]*(?P<fence>```[\w+-]*)[ \t]*$")
_GLUED_CLOSE = re.compile(r"^(?P<fence>\s{0,3}```)[ \t]*(?P<text>\S.*\s.*)$")


@dataclass
class Tidied:
    text: str
    repairs: list[str] = field(default_factory=list)
    stop_reason: str | None = None


def _fence_spans(lines: list[str]) -> list[tuple[int, int | None, str, str]]:
    """(open line, close line or None, marker, lang) for every fenced block, parsed like markdown.js does."""
    spans = []
    i = 0
    while i < len(lines):
        m = RE_FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not (RE_FENCE.match(lines[j]) and lines[j].strip().startswith(m.group(1))):
            j += 1
        spans.append((i, j if j < len(lines) else None, m.group(1), m.group(2)))
        i = j + 1
    return spans


def _code_mask(lines: list[str]) -> list[bool]:
    mask = [False] * len(lines)
    for start, end, _, _ in _fence_spans(lines):
        for k in range(start, (end if end is not None else len(lines) - 1) + 1):
            mask[k] = True
    return mask


def _split_glued_fences(lines: list[str], repairs: list[str]) -> list[str]:
    out: list[str] = []
    inside = None
    for line in lines:
        if inside is None:
            m = RE_FENCE.match(line)
            if m:
                inside = m.group(1)
                out.append(line)
                continue
            g = _GLUED_OPEN.match(line)
            if g and "```" not in g.group("text"):
                out += [g.group("text"), g.group("fence")]
                inside = "```"
                repairs.append("fence_glued")
                continue
            out.append(line)
        else:
            if RE_FENCE.match(line) and line.strip().startswith(inside):
                inside = None
                out.append(line)
                continue
            g = _GLUED_CLOSE.match(line) if inside == "```" else None
            if g:
                out += [g.group("fence"), g.group("text")]
                inside = None
                repairs.append("fence_glued")
                continue
            out.append(line)
    return out


def _cells(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return re.split(r"(?<!\\)\|", text)


def _is_row(line: str) -> bool:
    s = line.strip()
    return len(s) > 2 and s.startswith("|") and s.endswith("|") and len(_cells(s)) >= 2


def _is_sep(line: str) -> bool:
    return _is_row(line) and all(RE_SEP_CELL.match(c) for c in _cells(line))


def _repair_tables(lines: list[str], mask: list[bool], repairs: list[str]) -> tuple[list[str], list[bool]]:
    out: list[str] = []
    om: list[bool] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if mask[i]:
            out.append(line)
            om.append(True)
            i += 1
            continue
        # (a) a whole table written on one line: "| a | b | |---|---| | 1 | 2 |"
        if "| |" in line and re.search(r"\|\s*:?-{3,}", line) and line.strip().startswith("|"):
            rows = (
                ["| " + r.strip() + " |" for r in line.strip()[1:-1].split("| |")] if line.strip().endswith("|") else []
            )
            counts = {len(_cells(r)) for r in rows}
            if len(rows) >= 3 and len(counts) == 1 and _is_sep(rows[1]) and (width := counts.pop()) >= 2:
                rows[1] = "|" + "|".join(["---"] * width) + "|"
                out += rows
                om += [False] * len(rows)
                repairs.append("table_inline")
                i += 1
                continue
        if _is_row(line) and not (out and _is_row(out[-1]) and not om[-1]):
            # start of a table block: gather rows, allowing single blank lines between rows of the same width
            block = [line]
            j = i + 1
            while j < n and not mask[j]:
                if _is_row(lines[j]) or (j == i + 1 and RE_SEP_LINE.match(lines[j])):
                    block.append(lines[j])
                    j += 1
                elif (
                    not lines[j].strip()
                    and j + 1 < n
                    and not mask[j + 1]
                    and _is_row(lines[j + 1])
                    and len(_cells(lines[j + 1])) == len(_cells(block[-1]))
                    and len(block) >= 2
                ):
                    repairs.append("table_blank")
                    j += 1
                else:
                    break
            width = len(_cells(block[0]))
            if len(block) >= 2:
                if _is_sep(block[1]) or RE_SEP_LINE.match(block[1]):
                    if len(_cells(block[1])) != width:  # (c) separator of the wrong width
                        block[1] = "|" + "|".join(["---"] * width) + "|"
                        repairs.append("table_sep_width")
                elif all(len(_cells(r)) == width for r in block) and not any(_is_sep(r) for r in block):
                    block.insert(1, "|" + "|".join(["---"] * width) + "|")  # (b) missing separator
                    repairs.append("table_sep_missing")
            out += block
            om += [False] * len(block)
            i = j
            continue
        out.append(line)
        om.append(False)
        i += 1
    return out, om


def _norm_heading(line: str) -> str | None:
    m = RE_HEADING.match(line)
    text = m.group(1) if m else None
    if text is None:
        b = re.match(r"^\s*\*\*([^*\n]{1,60})\*\*\s*:?\s*$", line)
        text = b.group(1) if b else None
    return re.sub(r"[\W_]+", " ", text).strip().casefold() if text else None


def _dedupe_headings(lines: list[str], mask: list[bool], repairs: list[str]) -> tuple[list[str], list[bool]]:
    out: list[str] = []
    om: list[bool] = []
    last: str | None = None
    for line, m in zip(lines, mask, strict=True):
        key = None if m else _norm_heading(line)
        if key and key == last:
            while out and not out[-1].strip():  # drop the blank lines between the twins as well
                out.pop()
                om.pop()
            repairs.append("heading_duplicate")
            continue
        if line.strip():
            last = key
        out.append(line)
        om.append(m)
    return out, om


_LOOP_NOISE = re.compile(
    r"\b(?:j|d)?\d+(?:er|e|ème)?\b|\b(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|"
    r"décembre|january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.I,
)


def _trim_loop(lines: list[str], mask: list[bool], repairs: list[str]) -> list[str] | None:
    """The last list of the answer cycles (period <= 8, at least 12 items): keep the first two cycles."""
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1
    idx = []
    k = end - 1
    while k >= 0 and not mask[k] and (RE_ITEM.match(lines[k]) or not lines[k].strip()):
        if lines[k].strip():
            idx.append(k)
        k -= 1
    idx.reverse()
    if len(idx) < 12:
        return None
    norm = [_LOOP_NOISE.sub("", RE_ITEM.match(lines[x]).group(3)).casefold() for x in idx]
    norm = [re.sub(r"[\W_]+", " ", s).strip() for s in norm]
    for period in range(1, 9):
        # longest tail where item i equals item i - period
        start = len(norm)
        while start - period - 1 >= 0 and norm[start - 1] == norm[start - 1 - period]:
            start -= 1
        start -= period  # first item of the first cycle
        # a cycle of ONE line is not a loop: "Semaine 3 : point d'équipe" lines only differ by their numbers
        if len(norm) - start >= max(12, 3 * period) and start >= 0 and len(set(norm[start : start + period])) >= 2:
            keep = start + 2 * period
            if keep >= len(norm):
                return None
            repairs.append("loop_trimmed")
            return lines[: idx[keep - 1] + 1]
    return None


def tidy(text: str, stop_reason: str | None = None) -> Tidied:
    """Repair what is structurally broken; return the same text (and no repairs) when nothing matched."""
    original = text
    repairs: list[str] = []
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        repairs.append("newlines")
    stripped = _ROLE_ECHO.sub("", text, count=1)
    if stripped != text:
        text = stripped
        repairs.append("role_echo")
    if "[" in text:
        lines0 = text.split("\n")
        mask0 = _code_mask(lines0)
        kept = [ln for ln, m in zip(lines0, mask0, strict=True) if m or not _MEMO_LINE.fullmatch(ln + "\n")]
        if len(kept) != len(lines0):
            text = "\n".join(kept).rstrip()
            repairs.append("memo_echo")
        cut = _INTERRUPTED.sub("", text)
        if cut != text:
            text = cut
            repairs.append("interrupted_echo")
    lines = text.split("\n")
    if "```" in text:
        lines = _split_glued_fences(lines, repairs)
    mask = _code_mask(lines)
    if "|" in text:
        lines, mask = _repair_tables(lines, mask, repairs)
    lines, mask = _dedupe_headings(lines, mask, repairs)
    new_stop = stop_reason
    if stop_reason in ("length", "repetition"):
        trimmed = _trim_loop(lines, mask, repairs)
        if trimmed is not None:
            lines = trimmed
            new_stop = "repetition"
    spans = _fence_spans(lines)
    if spans and spans[-1][1] is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.append(spans[-1][2])
        repairs.append("fence_closed")
    if not repairs:
        return Tidied(original, [], stop_reason)
    return Tidied("\n".join(lines), repairs, new_stop)


# ------------------------------------------------------------------ syntax checks (parse only, never execute)

PY_LANGS = {"py", "python", "python3"}
JSON_LANGS = {"json", "jsonc", "json5"}
_ELISION = re.compile(r"^\s*(?:\.\.\.|…|#\s*\.\.\.|//\s*\.\.\.)\s*$|^\s*>>>", re.M)


def _check_python(code: str) -> dict:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ast.parse(textwrap.dedent(code), feature_version=(3, 12))
        return {"ok": True, "kind": "ok"}
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        line = getattr(exc, "lineno", None) or 0
        if _ELISION.search(code) or (code[:1].isspace() and code.strip()):
            return {"ok": False, "kind": "excerpt"}
        return {"ok": False, "kind": "error", "line": int(line), "msg": str(getattr(exc, "msg", exc))[:120]}


def _check_json(code: str) -> dict:
    try:
        json.loads(code)
        return {"ok": True, "kind": "ok"}
    except (ValueError, RecursionError) as exc:
        if re.search(r"//|/\*|\.\.\.|…", code):
            return {"ok": False, "kind": "excerpt"}
        return {"ok": False, "kind": "error", "line": int(getattr(exc, "lineno", 0) or 0), "msg": str(exc)[:120]}


def code_checks(text: str) -> list[dict]:
    """One verdict per Python or JSON fence: ``i`` is the index among all fences (the order markdown.js meets them
    in) and ``n`` the block's line count, so a fence the two parsers count differently is never mislabelled."""
    lines = text.split("\n")
    out = []
    for i, (start, end, _, lang) in enumerate(_fence_spans(lines)):
        if end is None:
            continue
        lang = lang.lower()
        code = "\n".join(lines[start + 1 : end])
        if not code.strip() or len(code) > 20_000 or end - start - 1 > 400:
            continue
        n = end - start - 1  # the client matches a verdict to its block by index AND line count
        if lang in PY_LANGS:
            out.append({"i": i, "n": n, "lang": "python", **_check_python(code)})
        elif lang in JSON_LANGS:
            out.append({"i": i, "n": n, "lang": "json", **_check_json(code)})
    return out
