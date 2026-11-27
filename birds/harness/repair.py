"""Repairs between the model's output and a tool call, for the mistakes a 4B model makes in multi-step tasks.

Three layers, all deterministic, none calls the model:

* ``salvage_calls``: a call the trained parser (birds.parse) cannot read. The JSON form a small model falls back to
  (``<tool_call>{"name": …, "arguments": …}</tool_call>``, sometimes followed by text), a bare JSON call or a
  fenced one written inside prose, or a Python-style ``read_file(path="x")`` line. Only names of tools offered on
  this turn are taken, so a sentence that merely mentions a tool is never run.
* ``resolve_tool``: an invented tool name with an obvious meaning (``google_search``, ``send_email``,
  ``create_presentation``) becomes the offered tool; anything else stays unknown and is refused as before.
* ``repair_args``: argument names a model uses instead of the trained ones (``q``, ``link``, ``file``, ``recipient``,
  ``headers``…), a wrapper object (``{"arguments": {...}}``), a French tone (« formel »), and defaults the request
  makes obvious (an empty search query is the user's own words; a mail with no subject gets its first line).
  ``read_file`` on a name that is not in the workspace is matched to the one attached file it clearly means.

Every repair is a note on the step (``Step.repairs``), as for birds.harness.coerce; validation still runs after.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from pathlib import Path

from birds.harness.coerce import parse_json_like

# ---------------------------------------------------------------- tool names

# invented names seen on small models (and in other agent frameworks a model may have read about)
TOOL_ALIASES = {
    "web_search": "search google_search bing_search search_web websearch internet_search browse_search "
    "search_internet duckduckgo_search recherche recherche_web chercher",
    "read_page": "fetch fetch_url open_url browse read_url get_page read_webpage open_page visit_page scrape "
    "read_web_page browse_page lire_page",
    "read_file": "open_file read_document file_read read lire_fichier load_file get_file read_pdf read_attachment",
    "draft_email": "send_email email write_email compose_email create_email draft_mail send_mail mail "
    "create_draft envoyer_mail rediger_mail",
    "make_slides": "create_presentation make_presentation create_slides slides make_deck create_deck "
    "powerpoint make_pptx creer_presentation presentation",
    "make_document": "create_document write_document make_doc create_doc make_report write_report make_docx "
    "creer_document document",
    "make_sheet": "create_spreadsheet make_spreadsheet create_sheet make_table create_table make_excel "
    "make_xlsx spreadsheet creer_tableur excel",
    "make_chart": "create_chart make_graph create_graph plot draw_chart chart make_plot bar_chart line_chart",
    "run_python": "python execute_python run_code code_interpreter execute_code",
}
_ALIAS = {alt: real for real, alts in TOOL_ALIASES.items() for alt in alts.split()}


def resolve_tool(name: object, offered: set[str]) -> tuple[str, str | None]:
    """(tool name to run, repair note or None). Only maps onto a tool offered on this turn."""
    raw = str(name or "").strip()
    if raw in offered:
        return raw, None
    key = re.sub(r"[\s\-.]+", "_", raw.lower()).strip("_")
    key = re.sub(r"^(?:functions?|tools?)_", "", key)  # "functions.web_search"
    if key in offered:
        return key, f"tool '{raw}' read as '{key}'"
    real = _ALIAS.get(key)
    if real and real in offered:
        return real, f"tool '{raw}' read as '{real}'"
    return raw, None


# ---------------------------------------------------------------- calls the trained parser cannot read

_JSON_IN_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*(?:</tool_call>|$)", re.S)
_FENCE = re.compile(r"```(?:json|tool_call|tool)?\s*(\{.*?\})\s*```", re.S)
_PY_CALL = re.compile(r"(?m)^\s*`?(?P<name>[a-z_]{4,30})\((?P<args>[^()\n]*)\)`?\s*$")


def _json_call(blob: str) -> tuple[str, dict] | None:
    try:
        data = parse_json_like(blob)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("function"), dict):  # {"function": {"name", "arguments"}}
        data = data["function"]
    name = data.get("name") or data.get("tool") or data.get("tool_name")
    args = data.get("arguments", data.get("parameters", data.get("args", data.get("input", {}))))
    if isinstance(args, str):
        try:
            args = parse_json_like(args)
        except ValueError:
            return None
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    return name, args


def _objects(text: str) -> list[tuple[int, int]]:
    """(start, end) of each balanced top-level {...} in ``text``."""
    out, depth, start, in_str, esc = [], 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            esc = (not esc) and ch == "\\"
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth, start = depth + 1, i if depth == 0 else start
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                out.append((start, i + 1))
    return out


def _py_args(text: str) -> dict | None:
    """'path="x", max_results=3' or '{"path": "x"}' -> dict, else None."""
    s = text.strip()
    if not s:
        return {}
    if s.startswith("{"):
        try:
            v = parse_json_like(s)
        except ValueError:
            return None
        return v if isinstance(v, dict) else None
    try:
        node = ast.parse(f"f({s})", mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Call) or node.args:
        return None
    out = {}
    for kw in node.keywords:
        if kw.arg is None:
            return None
        try:
            out[kw.arg] = ast.literal_eval(kw.value)
        except ValueError:
            return None
    return out


def salvage_calls(text: str, offered: set[str]) -> tuple[list[dict], str, str]:
    """Tool calls in an output the trained parser found none in: ([{"name", "arguments"}], text before the first
    call, note). Empty list when there is nothing safe to run."""
    text = text or ""
    calls, cut = [], None
    for m in _JSON_IN_TAG.finditer(text):
        got = _json_call(m.group(1))
        if got and resolve_tool(got[0], offered)[0] in offered:
            calls.append({"name": got[0], "arguments": got[1]})
            cut = m.start() if cut is None else cut
    if calls:
        return calls, text[:cut].strip(), "tool call written as JSON read"
    for m in _FENCE.finditer(text):
        got = _json_call(m.group(1))
        if got and resolve_tool(got[0], offered)[0] in offered:
            calls.append({"name": got[0], "arguments": got[1]})
            cut = m.start() if cut is None else cut
    if calls:
        return calls, text[:cut].strip(), "tool call written in a code block read"
    for a, b in _objects(text):
        blob = text[a:b]
        if '"name"' not in blob and '"tool"' not in blob:
            continue
        got = _json_call(blob)
        if got and resolve_tool(got[0], offered)[0] in offered and ("arguments" in blob or "parameters" in blob):
            calls.append({"name": got[0], "arguments": got[1]})
            cut = a if cut is None else cut
    if calls:
        return calls, text[:cut].strip(), "tool call written as JSON in the text read"
    for m in _PY_CALL.finditer(text):
        name = resolve_tool(m.group("name"), offered)[0]
        args = _py_args(m.group("args"))
        if name in offered and args is not None and (args or m.group("args").strip() == ""):
            calls.append({"name": m.group("name"), "arguments": args})
            cut = m.start() if cut is None else cut
    if calls:
        return calls, text[:cut].strip(), "tool call written as code read"
    return [], text, ""


# ---------------------------------------------------------------- arguments

ARG_ALIASES = {  # tool -> {trained key: [names a model uses instead]}
    "web_search": {
        "query": ["q", "search", "search_query", "keywords", "keyword", "requete", "requête", "recherche", "terms",
                  "text", "question", "topic", "query_text"],
        "max_results": ["num_results", "n", "limit", "count", "k", "top_k", "results", "nb_results", "number"],
    },
    "read_page": {"url": ["link", "href", "page", "website", "site", "uri", "address", "adresse", "lien", "source",
                          "page_url", "web_url"]},
    "read_file": {"path": ["file", "filename", "file_name", "file_path", "filepath", "name", "fichier", "chemin",
                           "document", "attachment", "piece_jointe", "source"]},
    "draft_email": {
        "to": ["recipient", "recipients", "email", "emails", "destinataire", "destinataires", "address", "dest",
               "to_email", "mailto"],
        "subject": ["objet", "title", "titre", "sujet", "subject_line", "topic"],
        "body": ["content", "text", "message", "corps", "contenu", "texte", "email_body", "mail", "body_text"],
        "tone": ["ton", "style", "register"],
    },
    "make_slides": {"title": ["titre", "name", "nom", "deck_title", "presentation_title"],
                    "slides": ["pages", "diapositives", "diapos", "content", "items", "slide_list"]},
    "make_document": {"title": ["titre", "name", "nom", "document_title"],
                      "sections": ["parts", "chapters", "chapitres", "paragraphs", "contenu", "blocks"]},
    "make_sheet": {"title": ["titre", "name", "nom", "sheet_name", "sheet_title"],
                   "columns": ["headers", "header", "colonnes", "column_names", "cols", "fields", "entetes",
                               "en_tetes", "en-têtes"],
                   "rows": ["data", "lignes", "values", "valeurs", "records", "items", "table", "body"]},
    "run_python": {"code": ["script", "source", "python", "program", "source_code", "snippet"]},
}  # fmt: skip
_TONES = {
    "neutral": "neutre neutral normal standard",
    "formal": "formel formelle formal soutenu professionnel professionnelle professional courtois courtoise poli "
    "polie respectueux",
    "friendly": "amical amicale friendly chaleureux chaleureuse cordial cordiale sympathique informel informal "
    "decontracte warm casual",
    "firm": "ferme firm direct strict severe insistant",
}
_TONE = {w: k for k, ws in _TONES.items() for w in ws.split()}
_WRAPPERS = ("arguments", "parameters", "args", "input", "params", "kwargs")
_ATTACH_RX = re.compile(r"^\s*\[(?:Fichier joint|Attached file|Image jointe|Attached image)\s*:\s*(.+?)\]\s*$", re.I)


def _fold(s: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def workspace_files(workspace: Path) -> list[str]:
    """Readable files of the workspace (relative paths), never the harness's own outputs or logs."""
    root = Path(workspace)
    out = []
    try:
        for p in sorted(root.rglob("*"))[:400]:
            rel = p.relative_to(root).as_posix()
            if p.is_file() and not rel.startswith(("bird_out/", ".")) and not rel.endswith(".jsonl"):
                out.append(rel[:-4] if rel.endswith((".jpg.txt", ".jpeg.txt", ".png.txt", ".webp.txt")) else rel)
    except OSError:
        return []
    return out


def _match_file(path: str, files: list[str]) -> str | None:
    """The one workspace file ``path`` clearly means: same name in another folder, or a close spelling."""
    want = _fold(Path(path).name)
    same = [f for f in files if _fold(Path(f).name) == want]
    if len(same) == 1:
        return same[0]
    stems = {f: _fold(Path(f).stem) for f in files}
    close = difflib.get_close_matches(_fold(Path(path).stem), list(stems.values()), n=2, cutoff=0.8)
    hits = [f for f, s in stems.items() if s in close]
    return hits[0] if len(hits) == 1 else None


def repair_args(tool: str, args, *, request: str = "", workspace: Path | None = None) -> tuple[object, list[str]]:
    """(arguments, notes). Unknown shapes are returned unchanged: validation refuses them afterwards."""
    notes: list[str] = []
    if isinstance(args, str):
        try:
            decoded = parse_json_like(args)
        except ValueError:
            decoded = None
        if isinstance(decoded, dict):
            args, _ = decoded, notes.append("arguments: JSON text decoded")
    if not isinstance(args, dict):
        return args, notes
    args = dict(args)
    # {"arguments": {...}} or {"parameters": "{...}"}: the call wrapped once more
    if len(args) == 1 and next(iter(args)) in _WRAPPERS and next(iter(args)) not in (ARG_ALIASES.get(tool) or {}):
        inner = next(iter(args.values()))
        if isinstance(inner, str):
            try:
                inner = parse_json_like(inner)
            except ValueError:
                inner = None
        if isinstance(inner, dict):
            args = dict(inner)
            notes.append("arguments: wrapper object removed")
    for want, alts in (ARG_ALIASES.get(tool) or {}).items():
        if want in args and args[want] not in (None, "", [], {}):
            continue
        alt = next((a for a in alts if a in args and a != want and args[a] not in (None, "")), None)
        if alt is not None:
            args[want] = args.pop(alt)
            notes.append(f"'{alt}' read as '{want}'")
    for k in [k for k, v in args.items() if v is None]:  # "max_results": null is "not given"
        args.pop(k)
        notes.append(f"{k}: null dropped")
    words = " ".join((request or "").split())
    if tool == "web_search" and not str(args.get("query") or "").strip() and words:
        args["query"] = words[:160]
        notes.append("query missing: the user's own words used")
    if tool == "read_page":
        url = str(args.get("url") or "").strip().strip("<>\"'")
        if url and not re.match(r"https?://", url, re.I) and re.match(r"(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/|$)", url):
            args["url"] = "https://" + url
            notes.append("url: https:// added")
        elif url != args.get("url") and url:
            args["url"] = url
    if tool == "read_file" and isinstance(args.get("path"), str):
        path = args["path"].strip().strip("\"'`")
        m = _ATTACH_RX.match(path)
        if m:
            path = m.group(1).strip()
            notes.append("path: attachment label removed")
        if workspace is not None and path:
            files = workspace_files(workspace)
            if path not in files and not (Path(workspace) / path).exists():
                hit = _match_file(path, files)
                if hit:
                    notes.append(f"path '{path}' read as '{hit}' (the file in the workspace)")
                    path = hit
        args["path"] = path
    if tool == "draft_email":
        tone = args.get("tone")
        if isinstance(tone, str) and tone not in _TONES:
            got = _TONE.get(_fold(tone).split()[0] if tone.strip() else "")
            if got:
                args["tone"] = got
                notes.append(f"tone '{tone}' read as '{got}'")
            else:
                args.pop("tone")
                notes.append(f"tone '{tone}' dropped (neutral)")
        if isinstance(args.get("to"), str) and not args["to"].strip():
            args["to"] = []
        if "to" not in args and isinstance(args.get("body"), str):
            args["to"] = []  # the card asks the user for the recipient (birds.harness.tools.actions.recipients)
            notes.append("to missing: left for the user to complete")
        if not str(args.get("subject") or "").strip() and isinstance(args.get("body"), str) and args["body"].strip():
            first = next((ln.strip(" ,.:;") for ln in args["body"].splitlines()
                          if ln.strip() and not re.match(r"(?i)^(?:bonjour|hello|hi|madame|monsieur|cher|chère|dear)\b",
                                                         ln.strip())), "")  # fmt: skip
            args["subject"] = (first[:70].rsplit(" ", 1)[0] if len(first) > 70 else first) or (
                "Message" if not words else words[:60]
            )
            notes.append("subject missing: taken from the body")
    if tool in ("make_slides", "make_document", "make_sheet") and not str(args.get("title") or "").strip():
        if args.get("slides") or args.get("sections") or args.get("rows"):
            args["title"] = (words[:60].rsplit(" ", 1)[0] if len(words) > 60 else words) or "Bird"
            notes.append("title missing: taken from the request")
    if tool == "make_document" and "sections" not in args and isinstance(args.get("content"), str):
        args["sections"] = [{"heading": str(args.get("title") or "Document"), "content": args.pop("content")}]
        notes.append("content text made one section")
    return args, notes


def canonical(tool: str, args) -> str:
    """Key of a call for the repeat guard: same tool, same arguments up to case, spacing and key order."""

    def norm(v):
        if isinstance(v, str):
            return " ".join(v.lower().split())
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items() if k != "max_results"}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v

    return tool + " " + json.dumps(norm(args), sort_keys=True, ensure_ascii=False, default=str)
