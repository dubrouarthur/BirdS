"""A canvas turn: the model writes content, the harness builds, patches, illustrates and shows it.

Create (« fais une présentation sur … »): the trained make_slides / make_document tools are left out of the tool
block for this turn only, the user message carries the short format spec (``SPEC``), and the answer is parsed as
it streams: every new block appears in the canvas while the model writes. If the model still calls a trained
file tool (its training is strong), the call is captured (``canvas_sink``) and its arguments become the document.

Patch (« ajoute une slide sur les risques »): the words alone may say the change (``patch.direct_ops``, no model
call); else the model is given the outline with block ids and writes operations (``patch.parse_patch``).

Every result is a new VERSION of the same artifact; the browser keeps the versions.
"""

from __future__ import annotations

import dataclasses
import re
import secrets
import time
from collections.abc import Callable

from . import convert, dsl, intents, patch

FILE_TOOLS = ("make_slides", "make_document", "make_sheet")
STREAM_EVERY = 0.35  # seconds between two snapshots sent while the model writes
CANVAS_MAX_TOKENS = 2200  # a 8-slide deck in the text format is about 900 tokens; a web page up to ~2000
IMAGE_SECONDS = 20.0
IMAGE_LIMIT = 8  # a deck: the cover and up to seven slides (searches are cached, the time is capped)

SPEC = {
    "deck": {
        "fr": (
            "[Canevas] Écris la présentation directement dans ta réponse, dans ce format (pas d'outil, pas de JSON) :\n"
            "---\ntitle: <titre>\nsubtitle: <sous-titre court>\nimage: <2 à 4 mots pour la photo de couverture>\n---\n"
            "# <titre de la diapositive>\n- point court\n- autre point\n\n"
            "Varie les diapositives : un bloc au plus par diapositive, choisi selon le contenu :\n"
            "::: kpi\n<chiffre> | <ce qu'il mesure>\n:::\n"
            '::: chart type=bar unit="%"\n<libellé>: <nombre>\n:::\n'
            "::: timeline\n<date> : <étape>\n:::\n"
            "::: steps\n<étape> : <ce qu'on y fait>\n:::\n"
            "::: compare\n<option A> | <option B>\n<point A> | <point B>\n:::\n"
            "::: cards\n<nom> : <description courte>\n:::\n"
            '::: image query="<2 à 4 mots pour chercher une photo>"\n:::\n'
            "> « citation » — auteur\n\n"
            "Une diapositive avec un titre seul ouvre une partie. "
            "Règles : 5 à 8 diapositives, 3 à 5 points courts par diapositive, une image sur 2 ou 3 diapositives "
            "quand une photo aide. N'invente aucun chiffre : seulement ceux de la demande ou des sources lues."
        ),
        "en": (
            "[Canvas] Write the deck directly in your answer, in this format (no tool, no JSON):\n"
            "---\ntitle: <title>\nsubtitle: <short subtitle>\nimage: <2 to 4 words for the cover photo>\n---\n"
            "# <slide title>\n- short point\n- another point\n\n"
            "Vary the slides: at most one block per slide, chosen from the content:\n"
            "::: kpi\n<figure> | <what it measures>\n:::\n"
            '::: chart type=bar unit="%"\n<label>: <number>\n:::\n'
            "::: timeline\n<date>: <step>\n:::\n"
            "::: steps\n<step>: <what happens>\n:::\n"
            "::: compare\n<option A> | <option B>\n<point A> | <point B>\n:::\n"
            "::: cards\n<name>: <short description>\n:::\n"
            '::: image query="<2 to 4 words to search a photo>"\n:::\n'
            '> "quotation" — author\n\n'
            "A slide with a title only opens a part. "
            "Rules: 5 to 8 slides, 3 to 5 short points per slide, a picture on 2 or 3 slides when a photo helps. "
            "Invent no figure: only those of the request or of the sources read."
        ),
    },
    "doc": {
        "fr": (
            "[Canevas] Écris le document directement dans ta réponse, dans ce format (pas d'outil, pas de JSON) :\n"
            "---\ntitle: <titre>\nsubtitle: <sous-titre court>\n---\n# <titre de section>\nParagraphes, listes "
            "(- point), tableaux (| a | b |).\n\nBlocs facultatifs :\n"
            "::: attention\n<un risque ou une mise en garde>\n:::\n"
            "::: note\n<à retenir>\n:::\n"
            '::: image query="<2 à 4 mots pour chercher une photo>"\n:::\n\n'
            "Règles : 3 à 7 sections. N'invente aucun chiffre ni aucun nom."
        ),
        "en": (
            "[Canvas] Write the document directly in your answer, in this format (no tool, no JSON):\n"
            "---\ntitle: <title>\nsubtitle: <short subtitle>\n---\n# <section title>\nParagraphs, lists (- point), "
            "tables (| a | b |).\n\nOptional blocks:\n"
            "::: warning\n<a risk or a caution>\n:::\n"
            "::: note\n<key takeaway>\n:::\n"
            '::: image query="<2 to 4 words to search a photo>"\n:::\n\n'
            "Rules: 3 to 7 sections. Invent no figure and no name."
        ),
    },
    "code": {
        "fr": (
            "[Canevas] Écris un seul fichier complet dans un bloc de code (```html pour une page, ```svg pour une "
            "image vectorielle, ```python pour un script). Page web : HTML, CSS et JavaScript dans le même fichier, "
            "aucune ressource externe (pas de CDN, pas de police ni d'image en ligne). Puis une phrase d'explication."
        ),
        "en": (
            "[Canvas] Write one complete file in one code block (```html for a page, ```svg for a vector image, "
            "```python for a script). Web page: HTML, CSS and JavaScript in the same file, no external resource (no "
            "CDN, no online font or image). Then one sentence of explanation."
        ),
    },
    "diagram": {
        "fr": (
            "[Canevas] Écris le schéma dans un bloc ```mermaid, au format :\nflowchart TD\n  A[Étape] --> B{Question ?}"
            "\n  B -->|oui| C[Étape]\n  B -->|non| D[Étape]\nDes libellés courts, 4 à 12 nœuds. Puis une phrase "
            "d'explication."
        ),
        "en": (
            "[Canvas] Write the diagram in one ```mermaid block, in this format:\nflowchart TD\n  A[Step] --> "
            "B{Question?}\n  B -->|yes| C[Step]\n  B -->|no| D[Step]\nShort labels, 4 to 12 nodes. Then one sentence "
            "of explanation."
        ),
    },
}
PATCH = {
    "fr": (
        "[Canevas] Le document ouvert (les repères [b1], [b2]… identifient ses blocs) :\n{outline}\n"
        "Écris seulement le changement demandé, une ligne d'opération avant chaque bloc (remplace <repère> par "
        "celui du bloc visé) :\n"
        "@after <repère>    puis le nouveau bloc (# Titre, puis son contenu) : pour ajouter\n"
        "@replace <repère>  puis le bloc complet réécrit : pour modifier, raccourcir ou développer\n"
        "@delete <repère>   seulement si la demande dit de supprimer\n"
        "Même format que le document. N'écris aucun bloc qui ne change pas."
    ),
    "en": (
        "[Canvas] The open document (the tags [b1], [b2]… identify its blocks):\n{outline}\n"
        "Write only the requested change, one operation line before each block (put the tag of the block in "
        "place of <tag>):\n"
        "@after <tag>    then the new block (# Title, then its content): to add\n"
        "@replace <tag>  then the complete rewritten block: to change, shorten or expand\n"
        "@delete <tag>   only if the request says to delete\n"
        "Same format as the document. Write no block that does not change."
    ),
}
TARGET = {
    "fr": "[Canevas] Le bloc à modifier :\n{block}\nRéécris uniquement ce bloc, complet, dans le même format.",
    "en": "[Canvas] The block to change:\n{block}\nRewrite only this block, complete, in the same format.",
}
CODE_PATCH = {
    "fr": "[Canevas] Le fichier ouvert :\n```{lang}\n{code}\n```\nRéécris le fichier complet, corrigé selon la demande, "
          "dans un seul bloc ```{lang}. Aucune ressource externe.",
    "en": "[Canvas] The open file:\n```{lang}\n{code}\n```\nRewrite the complete file, changed as asked, in one "
          "```{lang} block. No external resource.",
}  # fmt: skip
NAMES = {
    "deck": {"fr": "la présentation", "en": "the deck"},
    "doc": {"fr": "le document", "en": "the document"},
    "code": {"fr": "le code", "en": "the code"},
    "sheet": {"fr": "le tableau", "en": "the sheet"},
}
DIRECT_SAID = {
    "theme": ("Thème appliqué : {theme}.", "Theme applied: {theme}."),
    "delete": ("C'est supprimé.", "Removed."),
    "duplicate": ("C'est dupliqué, juste après l'original.", "Duplicated, right after the original."),
    "move": ("C'est déplacé.", "Moved."),
    "swap": ("Les deux sont inversées.", "Swapped."),
    "image": ("Je cherche une autre image.", "Looking for another picture."),
    "unimage": ("Image retirée.", "Picture removed."),
    "retitle": ("Titre modifié.", "Title changed."),
}


def new_aid() -> str:
    return "a" + secrets.token_hex(6)


def _lang2(lang: str) -> str:
    return "en" if lang == "en" else "fr"


def code_doc(found: dict | None, lang: str, title: str = "") -> dict | None:
    if not found:
        return None
    doc = dsl.empty("code", lang)
    doc.pop("blocks", None)
    doc["title"] = title
    doc["code"] = {"lang": found["lang"], "text": found["text"]}
    return doc


class Stream:
    """Turns the text the model is writing into document snapshots for the canvas, at most every STREAM_EVERY s."""

    def __init__(self, compute: Callable[[str], dict | None], emit: Callable[[dict], None]):
        self.compute, self.emit = compute, emit
        self.text, self.last_t, self.last_sig = "", 0.0, None
        self.doc: dict | None = None

    def feed(self, piece: str) -> None:
        self.text += piece
        now = time.monotonic()
        if now - self.last_t < STREAM_EVERY and "\n" not in piece:
            return
        self.flush(now)

    def flush(self, now: float | None = None) -> None:
        try:
            doc = self.compute(self.text)
        except Exception:  # noqa: BLE001 - a snapshot that fails is skipped; the final parse decides
            return
        if doc is None:
            return
        sig = (len(doc.get("blocks") or []), len(dsl.to_dsl(doc, ids=False)))
        if sig == self.last_sig:
            return
        self.last_sig, self.last_t, self.doc = sig, now or time.monotonic(), doc
        self.emit(doc)

    def reset(self) -> None:
        self.text, self.last_sig = "", None


def chat_text(kind: str, doc: dict, lang: str, before: str = "", after: str = "", cut: bool = False,
              verb: str = "create", repairs: list[str] | None = None) -> str:  # fmt: skip
    """What the chat says about the artifact (the content itself is in the canvas, never pasted twice)."""
    fr = lang != "en"
    n = len(doc.get("blocks") or [])
    title = doc.get("title") or ""
    if kind == "deck":
        what = f"{n} diapositive{'s' if n > 1 else ''}" if fr else f"{n} slide{'s' if n != 1 else ''}"
    elif kind == "doc":
        what = f"{n} section{'s' if n > 1 else ''}" if fr else f"{n} section{'s' if n != 1 else ''}"
    else:
        lang_ = (doc.get("code") or {}).get("lang") or ""
        what = {"html": "page HTML" if fr else "HTML page", "svg": "image SVG" if fr else "SVG image",
                "mermaid": "schéma" if fr else "diagram", "python": "script Python" if fr else "Python script"}.get(
            lang_, "code")  # fmt: skip
    name = NAMES.get(kind, NAMES["doc"])["fr" if fr else "en"]
    if verb == "create":
        head = (f"{name[:1].upper() + name[1:]} « {title} » est dans le canevas : {what}." if fr and title
                else f"{name[:1].upper() + name[1:]} est dans le canevas : {what}." if fr
                else f"{name[:1].upper() + name[1:]} \"{title}\" is in the canvas: {what}." if title
                else f"{name[:1].upper() + name[1:]} is in the canvas: {what}.")  # fmt: skip
        unit = ("une diapositive" if fr else "a slide") if kind == "deck" else ("une section" if fr else "a section")
        tip = (f"Cliquez sur un bloc pour le modifier, ou demandez-moi un changement (« ajoute {unit} sur… », "
               "« plus court »)." if fr else
               f"Click a block to edit it, or ask me for a change (\"add {unit} on…\", \"shorter\").")  # fmt: skip
        if kind == "code":
            tip = ("L'onglet Aperçu l'exécute à part, sans accès au réseau." if fr
                   else "The Preview tab runs it apart, with no network access.")  # fmt: skip
            if (doc.get("code") or {}).get("lang") == "mermaid":
                tip = "L'onglet Aperçu dessine le schéma." if fr else "The Preview tab draws the diagram."
            elif (doc.get("code") or {}).get("lang") not in ("html", "svg", "js", "css", "markdown"):
                tip = ("Le code est affiché et vérifié, jamais exécuté." if fr
                       else "The code is shown and checked, never run.")  # fmt: skip
        parts = [head, tip]
    else:
        parts = [("Nouvelle version de " if fr else "New version of ") + name + f" ({what})."]
    if cut:
        parts.append("La réponse a été coupée par la limite de longueur : la fin peut manquer." if fr
                     else "The answer was cut by the length limit: the end may be missing.")  # fmt: skip
    lead = before if before and len(before) <= 300 and not re.match(r"(?i)^\s*(voici|here is|here's|bien s[uû]r|"
                                                                     r"d'accord|ok)\b", before) else ""  # fmt: skip
    if _EXCUSE.search(lead):
        lead = ""  # « je n'ai pas accès à vos données… » before a deck that is right there: the content speaks
    tail = after if after and len(after) <= 300 else ""
    return "\n\n".join(x for x in [lead, " ".join(parts), tail] if x)


_EXCUSE = re.compile(r"(?i)\b(?:je n['’]ai pas (?:acc[èe]s|les donn[ée]es)|je ne (?:peux|suis) pas|"
                     r"je ne dispose pas|i (?:don['’]t|do not) have access|i cannot|i can['’]t)\b")


def memo_line(info: dict | None, lang: str = "fr") -> str:
    """One line for the turn memo (the history the model sees next): what is in the canvas, by block id."""
    if not info:
        return ""
    doc = info.get("doc") or {}
    if doc.get("kind") in ("deck", "doc"):
        heads = "; ".join(f"{b['id']} {b.get('title') or ''}"[:50] for b in (doc.get("blocks") or [])[:14])
        return f"[canvas {doc.get('kind')} v{info.get('version', '?')} « {doc.get('title', '')[:80]} »: {heads}]"
    if doc.get("kind") == "code":
        return f"[canvas code {(doc.get('code') or {}).get('lang', '')} « {doc.get('title', '')[:80]} »]"
    return f"[canvas {doc.get('kind')} « {doc.get('title', '')[:80]} »]"


def finish_doc(doc: dict, kind: str, words: str, lang: str) -> dict:
    """Defaults the model left out: a title from the request, a theme from the subject, rich blocks from bullets."""
    from birds.harness import office

    if not doc.get("title"):
        doc["title"] = convert.subject(words) or ("Présentation" if kind == "deck" and lang != "en" else
                                                  "Presentation" if kind == "deck" else "Document")  # fmt: skip
    if kind in ("deck", "doc") and not doc.get("theme"):
        doc["theme"] = office.pick_theme(words + " " + doc["title"])
    if kind == "deck":
        convert.enrich(doc)
        from . import layouts

        layouts.split(doc)  # a list and a cards / steps / comparison block on one slide: two slides, nothing lost
    return doc


@dataclasses.dataclass
class Plan:
    """What this turn does with the canvas, decided before any generation."""

    mode: str  # "create" | "patch" | "direct" | "reopen" (an edit asked while the panel is closed)
    kind: str  # deck | doc | code | diagram | sheet
    aid: str
    base: dict | None = None  # the current document (patch, direct)
    version: int = 0  # its version number in the browser
    target: str | None = None  # « Demander à Bird » on one block
    ops: list[dict] | None = None  # direct operations
    said: str = ""


def plan(words: str, canvas: dict | None, lang: str, enabled: bool = True, attached: bool = False) -> Plan | None:
    """The canvas plan for this turn, or None for an ordinary turn. ``canvas`` is what the browser sent of the
    artifact it shows ({'aid', 'version', 'doc', 'target'}), already validated. ``attached``: files came with the
    message (a question about them is never a creation)."""
    if not enabled:
        return None
    if canvas and canvas.get("ref"):  # the panel is closed: only an explicit edit of a part of it reopens it
        kind = canvas.get("kind") or "deck"
        if intents.edit_ask(words, kind, shown=False):
            name = NAMES.get(kind, NAMES["doc"])[_lang2(lang)]
            said = (f"J'ai rouvert {name} dans le canevas : redemandez la modification et je l'applique." if lang != "en"
                    else f"I opened {name} again in the canvas: ask for the change again and I will make it.")  # fmt: skip
            return Plan("reopen", kind, canvas["aid"], None, int(canvas.get("version") or 1), said=said)
        canvas = None
    if canvas and isinstance(canvas.get("doc"), dict):
        doc = canvas["doc"]
        kind = doc.get("kind")
        target = canvas.get("target") if isinstance(canvas.get("target"), str) else None
        if target and patch._index(doc, target) < 0:
            target = None
        # a short unnamed edit (« plus court ») counts while the panel is shown, or on the turn right after the
        # artifact was made or changed (a phone closes its full-screen sheet to type)
        shown = canvas.get("open") is not False or bool(canvas.get("fresh"))
        if intents.edit_ask(words, kind or "deck", targeted=bool(target), shown=shown):
            aid = canvas.get("aid") or new_aid()
            ver = int(canvas.get("version") or 1)
            if not target:
                found = patch.direct_ops(words, doc)
                if found:
                    ops, what = found
                    said = DIRECT_SAID.get(what, ("C'est fait.", "Done."))[0 if lang != "en" else 1]
                    if what == "theme":
                        from birds.harness.office import THEME_NAMES

                        name = THEME_NAMES.get(ops[0]["theme"], {}).get(_lang2(lang), ops[0]["theme"])
                        said = said.format(theme=name)
                    return Plan("direct", kind, aid, doc, ver, None, ops, said)
            return Plan("patch", kind, aid, doc, ver, target)
    kind = intents.ask(words, attached=attached)
    if kind is None:
        return None
    return Plan("create", kind, new_aid())


def turn_message(p: Plan, user_sent: str, lang: str) -> str:
    """The user message the model gets on a canvas turn: the user's words, then the format or the outline."""
    lg = _lang2(lang)
    if p.mode == "create":
        return user_sent + "\n\n" + SPEC["diagram" if p.kind == "diagram" else p.kind][lg]
    doc = p.base or {}
    if doc.get("kind") == "code":
        c = doc.get("code") or {}
        return user_sent + "\n\n" + CODE_PATCH[lg].format(lang=c.get("lang") or "", code=(c.get("text") or "")[:12000])
    if p.target:
        b = next(x for x in doc.get("blocks") or [] if x.get("id") == p.target)
        return user_sent + "\n\n" + TARGET[lg].format(block=dsl.block_dsl(b, ids=True))
    return user_sent + "\n\n" + PATCH[lg].format(outline=dsl.outline(doc))


def compute_for(p: Plan, words: str, lang: str) -> Callable[[str], dict | None]:
    """The function that turns the model's text (partial or final) into the document it describes."""
    if p.kind in ("code", "diagram") or (p.base or {}).get("kind") == "code":
        want = "mermaid" if p.kind == "diagram" else None

        def code(text: str) -> dict | None:
            found = dsl.parse_code(text, want)
            title = (p.base or {}).get("title") or convert.subject(words)
            return code_doc(found, lang, title)

        return code
    if p.mode == "create":
        kind = p.kind

        def create(text: str) -> dict | None:
            _, content, _ = dsl.split_answer(text)
            doc = dsl.parse(content, kind, lang)
            return doc if doc["blocks"] else None

        return create

    def patched(text: str) -> dict | None:
        ops, _ = patch.parse_patch(text, p.base, words, p.target)
        if not ops:
            return None
        return patch.apply_all(p.base, ops)[0]

    return patched


def sink_for(captured: list[dict]):
    """The ``canvas_sink`` set on the turn's config: a trained file tool called anyway is captured here (its
    arguments become the document) instead of writing a file."""

    def sink(tool: str, args: dict, ctx) -> str:
        captured.append({"tool": tool, "args": dict(args)})
        n = len(args.get("slides") or args.get("sections") or args.get("rows") or [])
        return (f"The content ({n} items) is now shown to the user in the canvas beside the chat, where they can "
                "edit and download it. Do not repeat it: answer in one or two sentences.")  # fmt: skip

    return sink


def derive_agent(agent, hooks, sink, hide: tuple[str, ...] = (), max_tokens: int = CANVAS_MAX_TOKENS,
                 keep_only: set[str] | None = None, kind: str = ""):  # fmt: skip
    """A copy of the turn's agent for a canvas turn: same model, network and limits, a larger answer budget,
    the file tools captured by ``sink`` and the ``hide`` tools left out of the tool block."""
    from birds.harness import Agent

    cfg = dataclasses.replace(agent.cfg, max_tokens=max(agent.cfg.max_tokens, max_tokens))
    cfg.canvas_sink = sink  # read by the file tools (tools/files.py) and by the agent's file reminders
    cfg.canvas_kind = kind  # read by the task plan (plan.for_canvas): the canvas is the deliverable
    a = Agent(agent.llm, agent.tok, cfg, confirm=agent.confirm, http=agent.http, search=agent.search, hooks=hooks)
    a.tools = [t for t in a.tools if t["function"]["name"] not in hide
               and (keep_only is None or t["function"]["name"] in keep_only)]  # fmt: skip
    return a
