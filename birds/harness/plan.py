"""The task plan: the deliverables a request asks for, read from the user's own words, and checked before the
final answer.

A 4B model given « fais un tableau des lignes avec les totaux, puis prépare un mail » often makes the table and
stops: it forgets the totals and the mail. The harness therefore extracts a checklist deterministically (no model
call), shows it compactly to the model, ticks it from what really happened (tool steps that succeeded, the text of
the answer and of the files), and before the final answer reminds the model ONCE of what is still missing. What
cannot be done is reported plainly (« partiellement fait : mail manque »), never claimed.

Only deliverables named with a verb of making or an indefinite article count (« prépare un mail », « et un
tableur »): « résume ce mail » or « d'après le tableau » name an input, not a deliverable. Two kinds are enforced
even alone, because answering without them is answering before the result: reading an attached document, and an
explicit « cherche ». Any other plan is used only when it has two items or more; an ordinary one-deliverable turn
keeps its prompt byte for byte.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_CREATE = (
    r"(?:fai[st]e?s?|faire|faites|refai\w*|cr[ée]\w*|g[ée]n[èée]r\w*|pr[ée]par\w*|r[ée]dig\w*|[ée]cri(?:s|re|vez|t)|"
    r"produi\w*|mont\w*|construi\w*|dress\w*|[ée]tabli\w*|mets|mettre|mettez|mets-les|ajout\w*|envoi\w*|envoy\w*|"
    r"propos\w*|sors|sortir|transform\w*|convert\w*|make|create|generate|prepare|draft|write|build|produce|put|add|"
    r"send|compose|turn|give\s+me|donne[sz]?(?:-moi)?)"
)
# a noun preceded by these is an input (« résume ce mail », « à partir du document »), not a deliverable
_INPUT_BEFORE = re.compile(
    r"(?:\b(?:de|du|des|d['’]|dans|from|of|in|sur|selon|d'après|ce|cet|cette|ces|this|that|these|those|mon|ma|mes|"
    r"votre|vos|notre|nos|your|our|my|joint|jointe|attached)\s+(?:(?:le|la|les|l['’]|the|ce|cette|ces)\s*)?)$",
    re.I,
)
_INDEF = re.compile(r"(?:\b(?:un|une|des|a|an|some|deux|trois|quatre|two|three)\s+(?:\w+\s+){0,2})$", re.I)
_BREAK = re.compile(r"[.!?\n]")

KINDS = {  # kind -> (noun pattern, tools that make it, FR label, EN label)
    "mail": (r"e-?mails?|mails?|courriels?|messages?(?=\s+(?:à|a|au|aux|pour|to|for)\b)|r[ée]ponses?(?=\s+(?:à|au)\b)",
             ("draft_email",), "mail", "email"),
    "slides": (r"pr[ée]sentations?|diaporamas?|diapo\w*|(?:\d+-)?slides?|decks?|powerpoints?|pptx",
               ("make_slides",), "présentation", "slides"),
    "document": (r"documents?(?:\s+word)?|docx|compte[- ]rendus?|comptes[- ]rendus|rapports?|reports?|"
                 r"notes?\s+de\s+(?:synth[èe]se|cadrage|service|frais)|proc[ée]dures?|m[ée]mos?|minutes|"
                 r"word\b", ("make_document",), "document", "document"),
    "sheet": (r"tableurs?|excel|xlsx|spreadsheets?|feuilles?\s+de\s+calcul|classeurs?",
              ("make_sheet",), "tableur", "spreadsheet"),
    "table": (r"tableaux?(?!\s+de\s+bord)|tables?(?!\s+ronde)", (), "tableau", "table"),
}  # fmt: skip
_ANY_NOUN = re.compile(r"\b(?:" + "|".join(n for n, *_ in KINDS.values()) + r")\b", re.I)
_TOTALS = re.compile(r"\b(?:totaux|totals?|sous-totaux|subtotals?|total\s+(?:ttc|ht|g[ée]n[ée]ral)|le\s+total|"
                     r"du\s+total|les\s+totaux|the\s+total|somme\s+(?:des|totale))\b", re.I)  # fmt: skip
_SUMMARY = re.compile(r"\b(?:r[ée]sum\w*|synth[èe]se|synth[ée]tis\w*|summar\w*|tl;?dr)\b", re.I)
_COMPARE = re.compile(r"\b(?:compar\w*|versus)\b", re.I)
_SEARCH = re.compile(
    r"(?<!\bla )(?<!\bune )(?<!\bde )(?<!\bma )(?<!\bta )(?<!\bsa )(?<!\bnotre )(?<!\bvotre )(?<!\bthe )"
    r"\b(?:cherche|cherchez|chercher|recherche|recherchez|rechercher|search|look\s+up|trouve(?:z)?\s+sur\s+"
    r"(?:le\s+web|internet))\b",
    re.I,
)
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_ATTACHED = re.compile(r"\[(?:Fichier joint|Attached file)\s*:\s*([^\]\n]+)\]")

LABELS = {
    "totals": ("totaux", "totals"),
    "summary": ("synthèse", "summary"),
    "compare": ("comparaison", "comparison"),
    "search": ("recherche web", "web search"),
    "page": ("lecture de la page", "reading the page"),
    "read": ("lecture de {name}", "reading {name}"),
    "chart": ("graphique", "chart"),
}
TOOLS_OF = {
    # a lookup tool answers « cherche … » too: « je cherche un garage à Versailles » is answered by find_places
    "search": ("web_search", "read_page", "find_places", "find_company", "convert_currency", "get_weather"),
    "page": ("read_page",),
    "read": ("read_file",),
    "chart": ("make_chart",),
}
# shown to the model, after a tool result, when the plan has two items or more
WHAT_TO_DO = {
    "mail": "call draft_email",
    "slides": "call make_slides",
    "document": "call make_document",
    "sheet": "call make_sheet",
    "chart": "call make_chart",
    "table": "write it as a Markdown table in your answer (or put it in the file you make)",
    "totals": "write the totals with their exact figures",
    "summary": "write it in your answer",
    "compare": "write it in your answer",
    "search": "call web_search first; do not answer from memory",
    "page": "call read_page on the link first",
    "read": "call read_file on the attached file first; do not answer before reading it",
}
ENFORCED_ALONE = {"read", "search", "page"}


@dataclass
class Item:
    kind: str
    label: str
    at: int  # where the request names it (the checklist follows the request's order)
    path: str = ""  # read: the attached file


_COORD = re.compile(r"(?:\bet|\bpuis|\bainsi\s+qu['’]?e?|\band|\bthen|\bplus|\bavec|\bwith)\s+"
                    r"(?:(?:un|une|des|le|la|les|l['’]|a|an|the)\s*)?(?:\w+\s+){0,2}$", re.I)  # fmt: skip


def _deliverable(text: str, start: int, kind: str) -> bool:
    """The noun at ``start`` is asked for: an indefinite article right before it, or a verb of making shortly
    before it in the same sentence, and it is not introduced as an input (« de ce mail »). A verb that already
    governs another deliverable (« crée un tableur avec les colonnes nom, prénom, email ») needs « et / puis /
    avec » before this one; « envoie / envoyer » only makes a mail (« envoyer le compte rendu » sends a file)."""
    before = text[max(0, start - 70) : start]
    cut = max((m.end() for m in _BREAK.finditer(before)), default=0)
    before = before[cut:]
    if _INPUT_BEFORE.search(before):
        return False
    if _INDEF.search(before):
        return True
    verbs = list(re.finditer(r"\b" + _CREATE + r"\b", before, re.I))
    if not verbs:
        return False
    verb = verbs[-1]
    if re.match(r"envo", verb.group(0), re.I) and kind != "mail":
        return False
    gap = before[verb.end() :]
    if _ANY_NOUN.search(gap):
        return bool(_COORD.search(gap))
    return True


def extract(request: str, lang: str = "fr", message: str = "", chart: bool = False) -> list[Item]:
    """The checklist of ``request`` (the user's own words). ``message`` is the text the model gets (attachment
    notes); ``chart`` says the harness already reads a clear chart ask (agent.chart_ask)."""
    text = " ".join((request or "").split())
    en = lang == "en"
    items: dict[str, Item] = {}

    def add(kind: str, at: int, label: str | None = None, path: str = "") -> None:
        if kind not in items:
            items[kind] = Item(kind, label or LABELS[kind][en], at, path)

    for kind, (noun, _tools, fr, eng) in KINDS.items():
        for m in re.finditer(r"\b(?:" + noun + r")\b", text, re.I):
            if _deliverable(text, m.start(), kind):
                add(kind, m.start(), eng if en else fr)
                break
    if "sheet" in items:
        items.pop("table", None)  # « un tableau dans un tableur / Excel »: the spreadsheet is the table
    if chart:
        m = re.search(r"graph\w*|courbe|diagramme|camembert|histogramme|chart|plot|visuali\w*", text, re.I)
        add("chart", m.start() if m else len(text))
    m = _TOTALS.search(text)
    if m:
        add("totals", m.start())
    m = _SUMMARY.search(text)
    if m and not re.search(r"notes?\s+de\s+synth[èe]se", text, re.I):
        add("summary", m.start())
    m = _COMPARE.search(text)
    if m:
        add("compare", m.start())
    m = _SEARCH.search(text)
    if m:
        add("search", m.start())
    m = _URL.search(text)
    if m:
        add("page", m.start())
    names = [n.strip() for n in _ATTACHED.findall(message or "")]
    if names:
        short = names[0].rsplit("/", 1)[-1]
        add("read", -1, LABELS["read"][en].format(name=short), names[0])
    return sorted(items.values(), key=lambda i: i.at)


def active(items: list[Item]) -> bool:
    """The checklist is shown and checked as a whole only for two items or more."""
    return len(items) >= 2


# ---------------------------------------------------------------- ticking


def _table(text: str) -> bool:
    return len(re.findall(r"(?m)^\s*\|.*\|\s*$", text or "")) >= 3


def _totals(text: str) -> bool:
    return bool(re.search(r"(?is)\b(?:tota\w*|somme|sum)\b.{0,40}?\d|\d[^\n]{0,30}\b(?:au\s+)?total\b", text or ""))


def status(items: list[Item], steps, text: str, offered: set[str], figures_ok: bool = True) -> list[dict]:
    """[{kind, label, status}] with status done / todo / failed (the tool ran and failed) / unavailable (the tool
    is not offered on this turn). ``text`` is the answer plus the content of drafts and files made in the run."""
    ok = {s.tool for s in steps if not s.error and s.decision in ("allow", "confirmed")}
    tried = {s.tool for s in steps}
    made = any(t.startswith("make_") and t != "make_chart" for t in ok) or "draft_email" in ok
    out = []
    for it in items:
        tools = KINDS[it.kind][1] if it.kind in KINDS else TOOLS_OF.get(it.kind, ())
        if tools:
            if any(t in ok for t in tools):
                st = "done"
            elif it.kind == "table" and (_table(text) or "make_sheet" in ok):
                st = "done"
            elif any(t in tried for t in tools):
                st = "failed"
            elif not any(t in offered for t in tools):
                st = "unavailable"
            else:
                st = "todo"
        elif it.kind == "table":
            st = "done" if _table(text) or "make_sheet" in ok else "todo"
        elif it.kind == "totals":
            st = "done" if _totals(text) and figures_ok else "todo"
        else:  # summary, compare: written in the answer; never a reason for a reminder on their own
            st = "done" if text.strip() or made else "todo"
        out.append({"kind": it.kind, "label": it.label, "status": st})
    return out


def missing(statuses: list[dict], enforced_only: bool = False) -> list[dict]:
    return [s for s in statuses if s["status"] == "todo" and (not enforced_only or s["kind"] in ENFORCED_ALONE)]


def note(items: list[Item], lang: str) -> str:
    """Appended to the user's message for the model, when the plan is active."""
    steps = " ; ".join(f"{i}. {it.label}" for i, it in enumerate(items, 1))
    if lang == "en":
        return f"\n\n(Bird's note: this request asks for {len(items)} things: {steps}. Do all of them in this turn.)"
    return f"\n\n(Note de Bird : cette demande comporte {len(items)} éléments : {steps}. Fais-les tous dans ce tour.)"


_MARK = {"done": "✓", "todo": "☐", "failed": "✗", "unavailable": "–"}


def progress(statuses: list[dict]) -> str:
    """One line after a tool result: « [Bird checklist: ✓ 1. tableau · ☐ 2. totaux · ☐ 3. mail] »."""
    body = " · ".join(f"{_MARK[s['status']]} {i}. {s['label']}" for i, s in enumerate(statuses, 1))
    return f"\n\n[Bird checklist, not part of the result: {body}]"


def nudge(todo: list[dict], figures: str = "", read_path: str = "") -> str:
    """One reminder for everything still missing (tool message, English like the harness's other reminders)."""
    parts = []
    for s in todo:
        what = WHAT_TO_DO[s["kind"]]
        if s["kind"] == "totals" and figures:
            what += f" from the results: {figures}"
        if s["kind"] == "read" and read_path:
            what = f'call read_file with "path": "{read_path}" first; do not answer before reading it'
        parts.append(f"{s['label']}: {what}")
    return (
        "Not done yet. The user's request also asked for: " + " ; ".join(parts) + ". Do it now, in this turn, then "
        "answer briefly. Do not repeat what is already done."
    )


def to_dict(statuses: list[dict], lang: str, final: bool = False) -> dict:
    """For the UI (event « plan ») and Run.plan."""
    left = [s["label"] for s in statuses if s["status"] != "done"]
    out = {"items": [dict(s) for s in statuses], "done": sum(s["status"] == "done" for s in statuses),
           "total": len(statuses), "final": final}  # fmt: skip
    if final and left:
        out["missing"] = left
        out["partial"] = True
    return out


def item_dicts(items: list[Item]) -> list[dict]:
    return [asdict(i) for i in items]


# a reminder about these only asked for MORE: the answer given before it is still good and is kept
_ADDITIVE = {"mail", "slides", "document", "sheet", "chart", "table", "totals", "summary", "compare"}


def merged(earlier: str, final: str, reasons: set[str]) -> str:
    """The final answer after a reminder for a missing deliverable: the earlier answer (« Voici le tableau : … »)
    followed by the new one (« Le brouillon est prêt. »), so the table is not lost. Never after a reminder to read
    or search first, or about figures or language: then the earlier answer was the problem."""
    e, f = (earlier or "").strip(), (final or "").strip()
    substance = len(e) >= 160 or bool(re.search(r"(?m)^\s*(?:\|.*\||[-*•]\s|\d+[.)]\s)", e))
    if not substance or not reasons or not reasons <= _ADDITIVE or e in f:
        return final
    return e + "\n\n" + f
