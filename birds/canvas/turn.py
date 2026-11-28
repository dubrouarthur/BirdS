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

from . import code as codefiles
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
            "---\ntitle: <titre>\nsubtitle: <sous-titre court>\nimage: <2 à 4 mots en anglais pour la photo de couverture>\n---\n"
            "# <titre de la diapositive>\n- point court\n- autre point\n\n"
            "# <titre d'une diapositive illustrée>\n- point court\n- autre point\n"
            '::: image query="<2 à 4 mots en anglais : ce que la photo montre>"\n:::\n\n'
            "Varie les diapositives : un bloc au plus par diapositive, choisi selon le contenu :\n"
            "::: kpi\n<chiffre> | <ce qu'il mesure>\n:::\n"
            '::: chart type=bar unit="<unité>"\n<libellé>: <nombre donné dans la demande>\n:::\n<message clé en une phrase>\n'
            "::: timeline\n<date> : <étape>\n:::\n"
            "::: steps\n<étape> : <ce qu'on y fait>\n:::\n"
            "::: compare\n<option A> | <option B>\n<point A> | <point B>\n:::\n"
            "::: cards\n<nom> : <description courte>\n:::\n"
            '::: image query="<2 à 4 mots en anglais pour chercher une photo>"\n:::\n'
            "> « citation » — auteur\n\n"
            "Une diapositive avec un titre seul ouvre une partie. "
            "Règles : 5 à 8 diapositives, 3 à 5 points courts par diapositive, une image sur 2 ou 3 diapositives "
            "quand une photo aide. N'invente aucun chiffre : seulement ceux de la demande ou des sources lues ; s'il en "
            "manque, écris quand même la présentation, avec « à compléter » à la place du chiffre."
        ),
        "en": (
            "[Canvas] Write the deck directly in your answer, in this format (no tool, no JSON):\n"
            "---\ntitle: <title>\nsubtitle: <short subtitle>\nimage: <2 to 4 words for the cover photo>\n---\n"
            "# <slide title>\n- short point\n- another point\n\n"
            "# <title of an illustrated slide>\n- short point\n- another point\n"
            '::: image query="<2 to 4 words: what the photo shows>"\n:::\n\n'
            "Vary the slides: at most one block per slide, chosen from the content:\n"
            "::: kpi\n<figure> | <what it measures>\n:::\n"
            '::: chart type=bar unit="<unit>"\n<label>: <number given in the request>\n:::\n<key message in one sentence>\n'
            "::: timeline\n<date>: <step>\n:::\n"
            "::: steps\n<step>: <what happens>\n:::\n"
            "::: compare\n<option A> | <option B>\n<point A> | <point B>\n:::\n"
            "::: cards\n<name>: <short description>\n:::\n"
            '::: image query="<2 to 4 words to search a photo>"\n:::\n'
            '> "quotation" — author\n\n'
            "A slide with a title only opens a part. "
            "Rules: 5 to 8 slides, 3 to 5 short points per slide, a picture on 2 or 3 slides when a photo helps. "
            "Invent no figure: only those of the request or of the sources read; if some are missing, still write "
            "the deck, with \"to be completed\" in place of the figure."
        ),
    },
    "doc": {
        "fr": (
            "[Canevas] Écris le document directement dans ta réponse, dans ce format (pas d'outil, pas de JSON) :\n"
            "---\ntitle: <titre>\nsubtitle: <sous-titre court>\n"
            "template: <cadrage | compte-rendu | rapport | proposition | procedure | lettre>\n---\n"
            "# <titre de section>\nParagraphes, listes (- point), tableaux (| a | b |), sous-titres (## …).\n\n"
            "Blocs facultatifs :\n"
            "::: cle\n<à retenir>\n:::\n"
            "::: attention\n<un risque ou une mise en garde>\n:::\n"
            "::: note\n<une information utile>\n:::\n"
            '::: image query="<2 à 4 mots pour chercher une photo>" caption="<légende>"\n:::\n'
            "Une source : [^1] dans le texte, puis la ligne « [^1]: <la source> ».\n\n"
            "Règles : choisis le modèle (template) qui convient ; d'abord les sections demandées, 3 à 7 sections ; "
            "une lettre : des paragraphes sans sous-titres, puis la formule de politesse. « author: » seulement si "
            "la demande donne un nom. N'invente aucun chiffre ni aucun nom."
        ),
        "en": (
            "[Canvas] Write the document directly in your answer, in this format (no tool, no JSON):\n"
            "---\ntitle: <title>\nsubtitle: <short subtitle>\n"
            "template: <brief | minutes | report | proposal | procedure | letter>\n---\n"
            "# <section title>\nParagraphs, lists (- point), tables (| a | b |), sub-headings (## …).\n\n"
            "Optional blocks:\n"
            "::: key\n<key takeaway>\n:::\n"
            "::: warning\n<a risk or a caution>\n:::\n"
            "::: note\n<useful information>\n:::\n"
            '::: image query="<2 to 4 words to search a photo>" caption="<caption>"\n:::\n'
            "A source: [^1] in the text, then the line \"[^1]: <the source>\".\n\n"
            "Rules: pick the template that fits; the sections asked for first, 3 to 7 sections; a letter: paragraphs "
            "without sub-headings, then the closing. \"author:\" only if the request gives a name. Invent no figure "
            "and no name."
        ),
    },
    "code": {
        "fr": (
            "[Canevas] Écris le code dans ta réponse, chaque fichier dans son propre bloc, son nom après le "
            "langage :\n```html index.html\n…\n```\nPage ou petite application web : index.html, et si utile "
            "style.css et script.js (reliés par <link rel=\"stylesheet\" href=\"style.css\"> et <script "
            "src=\"script.js\"></script> en fin de body) ; une page simple tient dans index.html. Code complet et "
            "fonctionnel, mise en page responsive, aucune ressource externe (pas de CDN, ni police ni image en "
            "ligne). Autre langage : un seul fichier (```python main.py). Puis une phrase d'explication."
        ),
        "en": (
            "[Canvas] Write the code in your answer, each file in its own block, its name after the language:\n"
            "```html index.html\n…\n```\nWeb page or small web app: index.html, and if useful style.css and "
            "script.js (linked by <link rel=\"stylesheet\" href=\"style.css\"> and <script src=\"script.js\">"
            "</script> at the end of body); a simple page fits in index.html. Complete, working code, responsive "
            "layout, no external resource (no CDN, no online font or image). Another language: one file (```python "
            "main.py). Then one sentence of explanation."
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
VARIANTS = {
    "fr": "[Canevas] La section à retravailler :\n{block}\nÉcris deux variantes complètes de cette section, dans le "
          "même format, chacune précédée de sa ligne : « @variante 1 », puis « @variante 2 ». Rien d'autre.",
    "en": "[Canvas] The section to rework:\n{block}\nWrite two complete variants of this section, in the same format, "
          "each after its own line: \"@variant 1\", then \"@variant 2\". Nothing else.",
}  # fmt: skip
_VARIANT_LINE = re.compile(r"(?im)^[ \t>*_#@]*(?:variante|variant|version|option|proposition)\s*(?:n°\s*)?([12ab])\b"
                           r"[^\n]*$")  # fmt: skip


def parse_variants(text: str, base_block: dict, lang: str = "fr", repairs: list[str] | None = None) -> list[dict]:
    """The rewrites of one section the model wrote (« @variante 1 » … « @variante 2 » …), as blocks with the
    section's id: 0, 1 or 2 of them. Lenient: a missing heading takes the section's title, and a variant marker
    written as a heading, in bold or with « Version B » is read the same."""
    repairs = repairs if repairs is not None else []
    src = str(text or "")
    marks = list(_VARIANT_LINE.finditer(src))
    chunks = [src[m.end() : (marks[i + 1].start() if i + 1 < len(marks) else len(src))] for i, m in enumerate(marks)]
    if not chunks:
        chunks = [src]
    out = []
    for chunk in chunks[:2]:
        body = chunk.strip("\n")
        if not re.search(r"(?m)^\s{0,3}#\s", body):
            body = f"# {base_block.get('title') or ''}\n" + body
        parsed = dsl.parse(body, "doc", lang, repairs)
        parts = [p for b in parsed["blocks"] for p in b["parts"]][: dsl.MAX_PARTS]
        if not parts:
            continue
        title = (parsed["blocks"][0].get("title") if parsed["blocks"] else "") or base_block.get("title") or ""
        out.append({"id": base_block["id"], "title": title, "parts": parts, "notes": base_block.get("notes") or ""})
    if len(marks) < 2:
        repairs.append(f"variants: {len(marks)} marker(s), {len(out)} variant(s) read")
    return out


CODE_PATCH = {
    "fr": "[Canevas] Les fichiers ouverts :\n{files}\nRéécris seulement le ou les fichiers à changer, chacun en "
          "entier, dans un bloc ```<langage> <nom du fichier>. Ne réécris pas les autres. Aucune ressource externe.",
    "en": "[Canvas] The open files:\n{files}\nRewrite only the file or files to change, each one whole, in a "
          "```<language> <file name> block. Do not rewrite the others. No external resource.",
}  # fmt: skip
NAMES = {
    "deck": {"fr": "la présentation", "en": "the deck"},
    "doc": {"fr": "le document", "en": "the document"},
    "code": {"fr": "le code", "en": "the code"},
    "sheet": {"fr": "le tableau", "en": "the sheet"},
}
OF = {
    "deck": {"fr": "de la présentation", "en": "of the deck"},
    "doc": {"fr": "du document", "en": "of the document"},
    "code": {"fr": "du code", "en": "of the code"},
    "sheet": {"fr": "du tableau", "en": "of the sheet"},
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
    "chart": ("Graphique tracé avec vos chiffres, tels que vous les avez donnés.",
              "Chart drawn from your figures, exactly as you gave them."),
    "table": ("Tableau complété avec vos chiffres.", "Table completed with your figures."),
}


_CHART_WORD = re.compile(r"\b(?:graphi\w*|chart|diagramme|courbe|camembert|histogramme|barres?|bar chart|pie)\b", re.I)


def new_aid() -> str:
    return "a" + secrets.token_hex(6)


def _lang2(lang: str) -> str:
    return "en" if lang == "en" else "fr"


def code_doc(found: dict | None, lang: str, title: str = "", base: dict | None = None) -> dict | None:
    """The code document of a parsed answer (``code.parse_files``); on a patch turn (``base``), the files written
    replace those of the same name and the others are kept."""
    if not found or not found.get("files"):
        return None
    doc = dsl.empty("code", lang)
    doc.pop("blocks", None)
    doc["title"] = title
    files = found["files"]
    if base is not None:
        files, _ = codefiles.merge(codefiles.files_of(base), files, found.get("shown"))
    doc["code"] = codefiles.make_code(files, found.get("open"))
    return doc


def code_what(doc: dict, fr: bool) -> str:
    """« page web en 3 fichiers (index.html, style.css, script.js) », « script Python », « schéma »."""
    files = codefiles.files_of(doc)
    lang_ = files[codefiles.entry_index(files)]["lang"] if files else ""
    what = {"html": "page web" if fr else "web page", "svg": "image SVG" if fr else "SVG image",
            "mermaid": "schéma" if fr else "diagram", "python": "script Python" if fr else "Python script",
            "css": "feuille de style" if fr else "style sheet", "js": "script JavaScript" if fr else "JavaScript",
            }.get(lang_, "code")  # fmt: skip
    if len(files) > 1:
        names = ", ".join(f["name"] for f in files[:6])
        what += (f" en {len(files)} fichiers ({names})" if fr else f" in {len(files)} files ({names})")
    return what


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
              verb: str = "create", repairs: list[str] | None = None, version: int = 1,
              changes: list[dict] | None = None) -> str:  # fmt: skip
    """What the chat says about the artifact (the content itself is in the canvas, never pasted twice)."""
    fr = lang != "en"
    n = len(doc.get("blocks") or [])
    title = doc.get("title") or ""
    if kind == "deck":
        what = f"{n} diapositive{'s' if n > 1 else ''}" if fr else f"{n} slide{'s' if n != 1 else ''}"
    elif kind == "doc":
        what = f"{n} section{'s' if n > 1 else ''}" if fr else f"{n} section{'s' if n != 1 else ''}"
    else:
        what = code_what(doc, fr)
    name = NAMES.get(kind, NAMES["doc"])["fr" if fr else "en"]
    if kind == "code" and verb == "create":
        files = codefiles.files_of(doc)
        if files and files[codefiles.entry_index(files)]["lang"] == "html":
            name = "la page" if fr else "the page"
            names = ", ".join(f["name"] for f in files[:6])
            what = (f"{len(files)} fichiers ({names})" if fr else f"{len(files)} files ({names})") if len(files) > 1 \
                else (f"un fichier ({names})" if fr else f"one file ({names})")  # fmt: skip
    if kind == "doc":
        from . import templates

        tpl = templates.TEMPLATES.get(doc.get("template") or "")
        what = ", ".join(x for x in [(tpl.fr.lower() if fr else tpl.en.lower()) if tpl else "", what] if x)
        if tpl and tpl.letter:
            what = tpl.fr.lower() if fr else tpl.en.lower()
        if verb == "create":
            head = (f"Le document « {title} » est prêt dans le canevas : {what}." if fr and title
                    else f"Le document est prêt dans le canevas : {what}." if fr
                    else f"The document \"{title}\" is ready in the canvas: {what}." if title
                    else f"The document is ready in the canvas: {what}.")  # fmt: skip
            tip = ("Cliquez sur un texte pour le modifier ; ✦ sur une section la retravaille (deux variantes au "
                   "choix). Téléchargez-le en .docx ou en PDF depuis la carte." if fr else
                   "Click any text to edit it; ✦ on a section rewrites it (two variants to choose from). Download "
                   "it as .docx or PDF from the card.")  # fmt: skip
            parts = [head, tip]
        else:
            parts = [f"Version {version} du document ({what})." if fr else f"Version {version} of the document ({what})."]
    elif verb == "create":
        head = (f"{name[:1].upper() + name[1:]} « {title} » est dans le canevas : {what}." if fr and title
                else f"{name[:1].upper() + name[1:]} est dans le canevas : {what}." if fr
                else f"{name[:1].upper() + name[1:]} \"{title}\" is in the canvas: {what}." if title
                else f"{name[:1].upper() + name[1:]} is in the canvas: {what}.")  # fmt: skip
        unit = ("une diapositive" if fr else "a slide") if kind == "deck" else ("une section" if fr else "a section")
        tip = (f"Cliquez sur un bloc pour le modifier, ou demandez-moi un changement (« ajoute {unit} sur… », "
               "« plus court »)." if fr else
               f"Click a block to edit it, or ask me for a change (\"add {unit} on…\", \"shorter\").")  # fmt: skip
        if kind == "code":
            tip = ("L'aperçu l'exécute à part, sans réseau ; la console et « Corriger avec Bird » sont juste dessous."
                   if fr else "The preview runs it apart, with no network; the console and \"Fix with Bird\" are "
                   "right below.")  # fmt: skip
            files = codefiles.files_of(doc)
            entry_lang = files[codefiles.entry_index(files)]["lang"] if files else ""
            if entry_lang == "mermaid":
                tip = "L'onglet Aperçu dessine le schéma." if fr else "The Preview tab draws the diagram."
            elif entry_lang not in ("html", "svg", "js", "css", "markdown"):
                tip = ("Le code est affiché et vérifié, jamais exécuté : Bird n'a pas de bac à sable d'exécution."
                       if fr else "The code is shown and checked, never run: Bird has no execution sandbox.")  # fmt: skip
        parts = [head, tip]
    else:
        of = OF.get(kind, OF["doc"])["fr" if fr else "en"]
        if kind == "code" and changes is not None:
            sep = " : " if fr else ": "
            parts = [("Nouvelle version " if fr else "New version ") + of + sep + codefiles.diff_text(changes, fr) + "."]
        else:
            parts = [("Nouvelle version " if fr else "New version ") + of + f" ({what})."]
    if cut:
        parts.append("La réponse a été coupée par la limite de longueur : la fin peut manquer." if fr
                     else "The answer was cut by the length limit: the end may be missing.")  # fmt: skip
    lead = before if before and len(before) <= 300 and not re.match(r"(?i)^\s*(voici|voil[àa]|here is|here's|bien s[uû]r|"
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
        names = ", ".join(f["name"] for f in codefiles.files_of(doc))[:160]
        return f"[canvas code v{info.get('version', '?')} « {doc.get('title', '')[:80]} »: {names}]"
    return f"[canvas {doc.get('kind')} « {doc.get('title', '')[:80]} »]"


def photo_queries(doc: dict, repairs: list[str]) -> None:
    """A picture's search is the words of a real thing: the model's notation removed (« [Paris bike cargo 1] »), and
    a photo « of statistics » or « of a chart » dropped (a statistic is a chart from real data, never a photo)."""
    from . import images

    for b in doc.get("blocks") or []:
        keep = []
        for p in b.get("parts") or []:
            if p.get("t") == "image" and not p.get("media"):
                q = images.clean_query(p.get("query") or "")
                if not images.variants(q):
                    repairs.append(f"picture of a chart or a statistic dropped: {b.get('title', '')[:30]}")
                    continue
                p["query"] = q
                p["alt"] = images.clean_query(p.get("alt") or "") or q
            keep.append(p)
        b["parts"] = keep


def finish_doc(doc: dict, kind: str, words: str, lang: str, repairs: list[str] | None = None) -> dict:
    """Defaults the model left out: a title from the request, a theme from the subject, rich blocks from bullets.
    A document also gets its template (the model's choice when it is a known one, else a hint from the words), its
    date, and keeps an author or a recipient only when the user's words name them (never an invented name)."""
    from birds.harness import office

    repairs = repairs if repairs is not None else []
    if not doc.get("title"):
        doc["title"] = convert.subject(words) or ("Présentation" if kind == "deck" and lang != "en" else
                                                  "Presentation" if kind == "deck" else "Document")  # fmt: skip
    if kind in ("deck", "doc") and not doc.get("theme"):
        doc["theme"] = office.pick_theme(words + " " + doc["title"])
    photo_queries(doc, repairs)
    if kind == "deck":
        from . import layouts

        convert.enrich(doc)
        layouts.split(doc)  # a list and a cards / steps / comparison block on one slide: two slides, nothing lost
    if kind == "doc":
        from . import templates

        wrote = doc.get("template")
        doc["template"], how = templates.pick(wrote, words, doc.get("title") or "")
        doc["template_by"] = how
        if how != "model":
            repairs.append(f"template {'unknown' if wrote else 'missing'}: {doc['template']} ({how})")
        said = templates.fold(words)
        for key in ("author", "recipient"):
            name = str(doc.get(key) or "")
            tokens = [t for t in re.findall(r"\w{3,}", templates.fold(name))]
            if name and not (tokens and (all(t in said for t in tokens) if key == "author"
                                         else any(t in said for t in tokens if len(t) >= 4))):  # fmt: skip
                doc.pop(key, None)
                repairs.append(f"{key} not in the request dropped")
        doc["date"] = office._long_date(lang)
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
    variants: int = 0  # ✦ on a section: this many rewrites to choose from (2), none applied yet


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
        if shown:
            from . import figures

            # the figures of a chart that waits for them (« nous 34 %, Alpha 28 % … »): drawn as typed, no model
            ops = figures.fill_ops(words, doc, chart=bool(_CHART_WORD.search(words)))
            if ops:
                drew = any(x.get("t") == "chart" for x in ops[0]["block"].get("parts") or [])
                said = DIRECT_SAID["chart" if drew else "table"][0 if lang != "en" else 1]
                return Plan("direct", kind, canvas.get("aid") or new_aid(), doc, int(canvas.get("version") or 1),
                            None, ops, said)  # fmt: skip
            if kind in ("deck", "doc") and len(figures.pairs(words)) >= 2 and _CHART_WORD.search(words):
                # « voici les chiffres du graphique : pain 45 %, … » with no chart waiting: an edit of the open
                # deck (the model places the chart), not a chat answer that comments the figures
                return Plan("patch", kind, canvas.get("aid") or new_aid(), doc, int(canvas.get("version") or 1),
                            target)  # fmt: skip
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
            variants = 2 if target and canvas.get("variants") and kind == "doc" else 0
            return Plan("patch", kind, aid, doc, ver, target, variants=variants)
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
        shown, _ = codefiles.prompt_files(codefiles.files_of(doc))
        return user_sent + "\n\n" + CODE_PATCH[lg].format(files=shown)
    if p.target:
        b = next(x for x in doc.get("blocks") or [] if x.get("id") == p.target)
        if p.variants:
            return user_sent + "\n\n" + VARIANTS[lg].format(block=dsl.block_dsl(b, ids=False))
        return user_sent + "\n\n" + TARGET[lg].format(block=dsl.block_dsl(b, ids=True))
    return user_sent + "\n\n" + PATCH[lg].format(outline=dsl.outline(doc))


def compute_for(p: Plan, words: str, lang: str) -> Callable[[str], dict | None]:
    """The function that turns the model's text (partial or final) into the document it describes."""
    if p.kind in ("code", "diagram") or (p.base or {}).get("kind") == "code":
        want = "mermaid" if p.kind == "diagram" else None

        base = p.base if (p.base or {}).get("kind") == "code" else None
        shown = codefiles.prompt_files(codefiles.files_of(base))[1] if base else None

        def code(text: str) -> dict | None:
            found = codefiles.parse_files(text, want)
            if found is not None:
                found["shown"] = shown
            title = (p.base or {}).get("title") or convert.subject(words)
            return code_doc(found, lang, title, base)

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
