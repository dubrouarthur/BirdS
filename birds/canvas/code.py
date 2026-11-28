"""Code in the canvas: a page, a small app, a component (several files), or a script shown with its syntax.

The model writes each file in its own fence, the file name after the language (```` ```css style.css ````). The
harness reads that leniently (a name in bold before the fence, ``title="…"``, a first-line comment, or no name at
all: ``index.html`` / ``style.css`` / ``script.js`` by language), validates every name and size, and keeps a list of
files in the document::

    "code": {"lang": <entry's language>, "text": <entry's text>, "entry": "index.html",
             "files": [{"name": "index.html", "lang": "html", "text": "…"}, …]}

``lang`` / ``text`` mirror the entry file, so a reader of the one-file shape (older versions kept in a browser, the
memo line) still works. While the model writes, the file being written is ``open``: the browser shows it streaming
and refreshes the preview only when a file is complete. A patch turn rewrites only the files it names; the others
are kept as they are, and the change is summed up per file (lines added / removed).

Nothing here runs code: the preview runs in the browser's sandboxed frame (/canvas/frame), and Python or JSON is
only checked for syntax (``/api/canvas/check``).
"""

from __future__ import annotations

import re
from collections import Counter

MAX_FILES = 8
MAX_FILE = 60_000  # = dsl.MAX_CODE
MAX_TOTAL = 160_000
PROMPT_BUDGET = 14_000  # characters of files shown to the model on a patch turn

EXT_LANG = {"html": "html", "htm": "html", "css": "css", "js": "js", "mjs": "js", "svg": "svg", "py": "python",
            "json": "json", "md": "markdown", "mmd": "mermaid", "txt": "text", "ts": "ts", "sql": "sql",
            "sh": "bash", "yml": "yaml", "yaml": "yaml"}  # fmt: skip
LANG_EXT = {"html": "html", "css": "css", "js": "js", "svg": "svg", "python": "py", "json": "json",
            "markdown": "md", "mermaid": "mmd", "text": "txt", "ts": "ts", "sql": "sql", "bash": "sh",
            "yaml": "yaml"}  # fmt: skip
DEFAULT_NAME = {"html": "index.html", "css": "style.css", "js": "script.js", "svg": "image.svg", "python": "main.py",
                "json": "data.json", "markdown": "README.md", "mermaid": "schema.mmd", "text": "notes.txt",
                "ts": "main.ts", "sql": "query.sql", "bash": "script.sh", "yaml": "config.yaml"}  # fmt: skip
WEB = ("html", "css", "js", "svg")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}(?:\.[A-Za-z0-9_-]{1,12})?\.([A-Za-z0-9]{1,5})")
_FENCE_OPEN = re.compile(r"(?m)^[ \t]*(`{3,}|~{3,})([^\n`]*)\n")
_FILE_WORD = re.compile(r"[\w./-]+\.(?:" + "|".join(EXT_LANG) + r")\b", re.I)


def lang_of(word: object) -> str:
    from .dsl import code_lang

    return code_lang(word)


def safe_name(raw: object) -> str | None:
    """A file name the canvas accepts (letters, digits, ``_ - .``, a known extension), or None. A path keeps only its
    last part (``src/app.js`` → ``app.js``): the files are flat, nothing names a folder of the server."""
    s = str(raw or "").strip().strip("`*'\"«»“”:() ").replace("\\", "/")
    s = s.rsplit("/", 1)[-1]
    m = _NAME.fullmatch(s)
    if not m or m.group(1).lower() not in EXT_LANG:
        return None
    return s


def name_lang(name: str) -> str:
    return EXT_LANG.get(name.rsplit(".", 1)[-1].lower(), "text")


# ------------------------------------------------------------------ reading the model's answer


def _info(info: str) -> tuple[str, str | None]:
    """The language word and the file name of a fence's info string: ``html index.html``, ``html:index.html``,
    ``css title="style.css"``, ``index.html``, ``js // script.js``."""
    s = info.strip()
    name = None
    m = re.search(r"""(?:title|file|filename|name)\s*=\s*["']?([^"'\s]+)""", s, re.I)
    if m:
        name = safe_name(m.group(1))
    words = re.split(r"[\s:]+", s)
    lang_word = words[0] if words and words[0] else ""
    if name is None:
        for w in words:
            n = safe_name(w)
            if n:
                name = n
                break
    if lang_word and safe_name(lang_word):  # ```index.html
        lang_word = ""
    return lang_word, name


def _name_before(src: str, start: int) -> str | None:
    """A file name announced on the line just before a fence: ``**style.css**``, ``### script.js``, ``Fichier :
    index.html``, `` `app.js` : ``."""
    head = src[:start].rstrip("\n").rsplit("\n", 2)
    for line in reversed(head[-2:]):
        line = line.strip()
        if not line:
            continue
        if len(line) > 90:
            return None
        found = _FILE_WORD.findall(line)
        if len(found) == 1:
            return safe_name(found[0])
        return None
    return None


def _name_inside(code: str, lang: str) -> str | None:
    """A first-line comment naming the file: ``<!-- index.html -->``, ``/* style.css */``, ``// script.js``,
    ``# main.py``."""
    first = code.lstrip("\n").split("\n", 1)[0].strip()
    m = re.fullmatch(r"(?:<!--|/\*|//|#)\s*(?:fichier|file)?\s*:?\s*([\w./-]+\.\w+)\s*(?:-->|\*/)?", first, re.I)
    return safe_name(m.group(1)) if m else None


def _sniff(code: str) -> str:
    from .dsl import _sniff as sniff

    s = code.lstrip()
    if re.match(r"[.#]?[\w-]+(?:\s*[,>+~]\s*[.#]?[\w-]+)*\s*\{[^}]*:[^}]*\}", s) and not re.search(
        r"\b(?:function|const|let|var)\b", s[:400]
    ):
        return "css"
    if s.startswith((":root", "*", "body {", "html {", "@media", "@import")):
        return "css"
    return sniff(code)


def scan(text: object) -> list[dict]:
    """Every fence of an answer, in order: {'lang', 'name' (None when unnamed), 'text', 'closed', 'start', 'end'}.
    A fence left open (the answer still streaming, or cut) runs to the end and is not ``closed``."""
    src = str(text or "").replace("\r\n", "\n")
    out = []
    pos = 0
    while True:
        m = _FENCE_OPEN.search(src, pos)
        if not m:
            break
        mark = m.group(1)
        close = re.compile(rf"(?m)^[ \t]*{re.escape(mark[0])}{{{len(mark)},}}[ \t]*$").search(src, m.end())
        body = src[m.end() : close.start()] if close else src[m.end() :]
        lang_word, name = _info(m.group(2))
        body = body.rstrip("\n") if close else body
        if name is None:
            name = _name_before(src, m.start()) or _name_inside(body, lang_word)
        lang = lang_of(lang_word) if lang_word else (name_lang(name) if name else _sniff(body))
        if lang == "text" and name:
            lang = name_lang(name)
        out.append({"lang": lang, "name": name, "text": body, "closed": bool(close), "start": m.start(),
                    "end": close.end() if close else len(src)})  # fmt: skip
        pos = close.end() if close else len(src)
    return out


def parse_files(text: object, want: str | None = None) -> dict | None:
    """The files of an answer: {'files': [{'name', 'lang', 'text'}], 'open': <name of a file still being written> |
    None, 'before', 'after'}, or None when there is no code.

    Named fences are files. Unnamed web fences (html, css, js) become ``index.html`` / ``style.css`` / ``script.js``
    when the answer has a page; otherwise the single main fence is kept (the longest, a picture or a diagram first),
    as before: a ``pip install`` snippet beside a script is not a file."""
    src = str(text or "").replace("\r\n", "\n")
    fences = [f for f in scan(src) if f["text"].strip() or not f["closed"]]
    if want == "mermaid":
        fences = [f for f in fences if f["lang"] == "mermaid"] or fences
    if not fences:
        s = src.strip()
        if re.match(r"(?is)^(?:<!doctype html|<html|<svg)\b", s):
            lang = "svg" if s.lower().startswith("<svg") else "html"
            return {"files": [{"name": DEFAULT_NAME[lang], "lang": lang, "text": s[:MAX_FILE]}], "open": None,
                    "before": "", "after": ""}  # fmt: skip
        return None
    named = [f for f in fences if f["name"]]
    unnamed = [f for f in fences if not f["name"]]
    chosen: list[dict] = []
    if named and want != "mermaid":
        chosen = list(named)
        taken = {f["name"].lower() for f in named}
        for f in unnamed:
            if f["lang"] in ("css", "js", "html") and DEFAULT_NAME[f["lang"]] not in taken:
                f["name"] = DEFAULT_NAME[f["lang"]]
                taken.add(f["name"])
                chosen.append(f)
    elif want != "mermaid" and any(f["lang"] == "html" for f in unnamed):
        for lang in ("html", "css", "js"):
            same = [f for f in unnamed if f["lang"] == lang]
            if same:
                best = max(same, key=lambda f: (len(f["text"]), not f["closed"]))
                best["name"] = DEFAULT_NAME[lang]
                chosen.append(best)
        chosen.sort(key=lambda f: f["start"])
    else:

        def score(f: dict) -> int:
            return (len(f["text"]) + (100_000 if f["lang"] in ("html", "svg", "mermaid") else 0)
                    + (200_000 if want and f["lang"] == want else 0))  # fmt: skip

        best = max(fences, key=score)
        best["name"] = best["name"] or DEFAULT_NAME.get(best["lang"], "notes.txt")
        chosen = [best]
    files, seen, total = [], set(), 0
    open_name = None
    for f in chosen[:MAX_FILES]:
        name = f["name"]
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        body = f["text"][:MAX_FILE]
        total += len(body)
        if total > MAX_TOTAL:
            break
        files.append({"name": name, "lang": f["lang"], "text": body})
        if not f["closed"]:
            open_name = name
    if not files:
        return None
    first = min(f["start"] for f in chosen)
    last = max(f["end"] for f in chosen)
    return {"files": files, "open": open_name, "before": src[:first].strip(), "after": src[last:].strip()}


# ------------------------------------------------------------------ the document's files


def entry_index(files: list[dict]) -> int:
    for pred in (lambda f: f["name"].lower() == "index.html", lambda f: f["lang"] == "html",
                 lambda f: f["lang"] == "svg"):  # fmt: skip
        for i, f in enumerate(files):
            if pred(f):
                return i
    return 0


def files_of(doc: dict | None) -> list[dict]:
    """The files of a code document, whichever shape it has (one ``text``, or ``files``)."""
    c = (doc or {}).get("code") or {}
    if isinstance(c.get("files"), list) and c["files"]:
        return [dict(f) for f in c["files"] if isinstance(f, dict)]
    lang = lang_of(c.get("lang"))
    return [{"name": DEFAULT_NAME.get(lang, "notes.txt"), "lang": lang, "text": str(c.get("text") or "")}]


def make_code(files: list[dict], open_name: str | None = None) -> dict:
    """The ``code`` field of a document, entry mirrored."""
    e = files[entry_index(files)]
    out = {"lang": e["lang"], "text": e["text"], "entry": e["name"], "files": [dict(f) for f in files]}
    if open_name:
        out["open"] = open_name
    return out


def normalize(c: object) -> dict:
    """The ``code`` field of a document that came back from the browser: every name, language and size checked.
    Raises ValueError on a shape that cannot be code."""
    if not isinstance(c, dict):
        raise ValueError("code")
    raw = c.get("files")
    if raw is None:
        lang = lang_of(c.get("lang"))
        text = str(c.get("text") or "")[:MAX_FILE]
        return make_code([{"name": DEFAULT_NAME.get(lang, "notes.txt"), "lang": lang, "text": text}])
    if not isinstance(raw, list) or not raw or len(raw) > MAX_FILES:
        raise ValueError("files")
    files, seen, total = [], set(), 0
    for f in raw:
        if not isinstance(f, dict):
            raise ValueError("file")
        name = safe_name(f.get("name"))
        if not name or name != str(f.get("name")) or name.lower() in seen:
            raise ValueError("file name")
        seen.add(name.lower())
        text = f.get("text")
        if not isinstance(text, str) or len(text) > MAX_FILE:
            raise ValueError("file text")
        total += len(text)
        if total > MAX_TOTAL:
            raise ValueError("files too large")
        lang = lang_of(f.get("lang")) if f.get("lang") else name_lang(name)
        files.append({"name": name, "lang": lang, "text": text})
    return make_code(files)


# ------------------------------------------------------------------ a patch turn


def prompt_files(files: list[dict], budget: int = PROMPT_BUDGET) -> tuple[str, set[str]]:
    """The files shown to the model on a patch turn, as fences with their names, and the names shown whole. A file
    that does not fit is named only: the model is told not to rewrite it (a cut file rewritten loses its end)."""
    parts, shown, left = [], set(), budget
    for f in files:
        if len(f["text"]) <= left:
            parts.append(f"```{f['lang']} {f['name']}\n{f['text']}\n```")
            shown.add(f["name"])
            left -= len(f["text"])
        else:
            parts.append(f"({f['name']} : {len(f['text'].splitlines())} lignes, non montré)")
    return "\n".join(parts), shown


def merge(base: list[dict], new: list[dict], shown: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """The files after a patch turn: each file the model wrote replaces the file of that name (an unnamed one, the
    only file of its language, or the entry for a page); a new name is added; files it did not write are kept. A
    rewrite of a file it was not shown whole is refused (listed in the second value)."""
    out = [dict(f) for f in base]
    refused = []
    by_name = {f["name"].lower(): i for i, f in enumerate(out)}
    for f in new:
        name = f["name"]
        key = name.lower()
        if key not in by_name and name == DEFAULT_NAME.get(f["lang"]):  # an unnamed fence: the file of its language
            same = [i for i, g in enumerate(out) if g["lang"] == f["lang"]]
            if len(same) == 1:
                key = out[same[0]]["name"].lower()
            elif f["lang"] == "html" and out:
                key = out[entry_index(out)]["name"].lower()
        if key in by_name:
            i = by_name[key]
            if shown is not None and out[i]["name"] not in shown:
                refused.append(out[i]["name"])
                continue
            out[i] = {"name": out[i]["name"], "lang": f["lang"] if f["lang"] != "text" else out[i]["lang"],
                      "text": f["text"]}  # fmt: skip
        elif len(out) < MAX_FILES:
            out.append(dict(f))
            by_name[key] = len(out) - 1
    return out, refused


def diff(old: list[dict], new: list[dict]) -> list[dict]:
    """Per file: {'name', 'status': added|changed|removed, 'plus', 'minus'} (lines, counted as multisets: a line
    moved is not counted). The browser computes the same numbers (canvas-code.js ``diffFiles``)."""
    a = {f["name"]: f["text"] for f in old}
    b = {f["name"]: f["text"] for f in new}
    out = []
    for name in list(b) + [n for n in a if n not in b]:
        x, y = Counter(a.get(name, "").splitlines()), Counter(b.get(name, "").splitlines())
        plus, minus = sum((y - x).values()), sum((x - y).values())
        status = "added" if name not in a else "removed" if name not in b else "changed"
        if status != "changed" or plus or minus:
            out.append({"name": name, "status": status, "plus": plus, "minus": minus})
    return out


def diff_text(changes: list[dict], fr: bool = True) -> str:
    if not changes:
        return "aucun fichier modifié" if fr else "no file changed"
    bits = []
    for c in changes[:6]:
        tag = {"added": " (nouveau)" if fr else " (new)", "removed": " (retiré)" if fr else " (removed)"}.get(
            c["status"], "")  # fmt: skip
        bits.append(f"{c['name']} +{c['plus']} −{c['minus']}{tag}")
    return ", ".join(bits)


def hints(files: list[dict]) -> dict:
    """What a page already has, for the next-step chips (deterministic, from the files only)."""
    web = [f for f in files if f["lang"] in WEB]
    css = "\n".join(f["text"] for f in files if f["lang"] in ("css", "html"))
    return {
        "web": bool(web),
        "lang": files[entry_index(files)]["lang"] if files else "text",
        "dark": "prefers-color-scheme" in css or bool(re.search(r"\b(?:dark|sombre)\b", css, re.I)),
        "mobile": bool(re.search(r"@media[^{]*(?:max|min)-width", css)),
        "js": any(f["lang"] == "js" for f in files) or "<script" in css,
        "files": len(files),
    }
