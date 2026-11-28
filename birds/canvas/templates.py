"""Document templates of the canvas (« note de cadrage », « compte rendu », « rapport », « proposition commerciale »,
« procédure », « lettre »): the page look each one gets (cover page, table of contents, numbered headings, letter
layout) and the sections its readers expect.

The MODEL picks the template (``template:`` in the front matter of the text format, see ``turn.SPEC``); the code only
reads its choice leniently (aliases, accents, English names), falls back to a hint from the user's own words when the
model wrote none, and checks the structure: which expected sections are there, which are missing. Nothing is added to
the document: a missing section becomes a next-step chip (« Ajouter la section Risques »), never invented content.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Section:
    fr: str
    en: str
    match: str  # regex on the folded section title (accents removed, lower case)
    required: bool = True


@dataclass(frozen=True)
class Template:
    id: str
    fr: str
    en: str
    aliases: tuple[str, ...]
    cover: bool  # a full cover page (title, subtitle, date, author), then the table of contents
    toc: bool  # a table of contents (when the document has 4 sections or more)
    numbered: bool  # « 1. Contexte », « 1.1 … »
    letter: bool = False  # sender, date, recipient, « Objet : … », the body without headings
    sections: tuple[Section, ...] = field(default_factory=tuple)


TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in (
        Template("cadrage", "Note de cadrage", "Project brief",
                 ("cadrage", "note de cadrage", "note-de-cadrage", "brief", "project brief", "project charter",
                  "charte projet", "cadrage projet"),
                 cover=True, toc=True, numbered=True,
                 sections=(Section("Contexte", "Context", r"contexte|enjeu|context|background|situation"),
                           Section("Objectifs", "Objectives", r"objectif|goal|objective|but"),
                           Section("Périmètre", "Scope", r"perimetre|scope|champ"),
                           Section("Livrables", "Deliverables", r"livrable|deliverable", required=False),
                           Section("Planning", "Schedule", r"planning|calendrier|jalon|echeanc|timeline|schedule|"
                                                           r"roadmap|feuille de route|etapes"),
                           Section("Risques", "Risks", r"risque|risk|vigilance"),
                           Section("Gouvernance", "Governance", r"gouvernance|organisation|equipe|role|pilotage|"
                                                               r"governance|team|budget|ressource", required=False))),
        Template("compte-rendu", "Compte rendu", "Meeting minutes",
                 ("compte-rendu", "compte rendu", "cr", "minutes", "meeting minutes", "proces-verbal", "pv",
                  "compte rendu de reunion", "report of meeting"),
                 cover=False, toc=False, numbered=False,
                 sections=(Section("Participants", "Attendees", r"participant|present|attendee|invite|absent"),
                           Section("Ordre du jour", "Agenda", r"ordre du jour|agenda|objet", required=False),
                           Section("Points abordés", "Discussion", r"point|echange|discussion|abord|sujet|debat|"
                                                                   r"resume|synthese", required=False),
                           Section("Décisions", "Decisions", r"decision|decide|arbitrage|validation"),
                           Section("Actions", "Action items", r"action|suite|prochaine|tache|next step|todo|a faire|"
                                                             r"responsable"))),
        Template("rapport", "Rapport", "Report",
                 ("rapport", "report", "note de synthese", "synthese", "note", "etude", "study", "analyse",
                  "livre blanc", "white paper", "memo"),
                 cover=True, toc=True, numbered=True,
                 sections=(Section("Synthèse", "Summary", r"synthese|resume|summary|executive|en bref|introduction|"
                                                         r"contexte|context"),
                           Section("Analyse", "Analysis", r"analyse|constat|etat des lieux|diagnostic|enjeu|"
                                                         r"analysis|findings|chiffres|situation|impact|pratique|"
                                                         r"levier|action|bonnes pratiques|mesure"),
                           Section("Recommandations", "Recommendations", r"recommand|preconis|proposition|piste|"
                                                                         r"plan d.action|recommendation|"
                                                                         r"next step|prochaine"),
                           Section("Conclusion", "Conclusion", r"conclusion|perspective|bilan|en resume|"
                                                               r"pour conclure", required=False),
                           Section("Sources", "Sources", r"source|reference|bibliograph|annexe", required=False))),
        Template("proposition", "Proposition commerciale", "Business proposal",
                 ("proposition", "proposition commerciale", "offre", "offre commerciale", "devis", "proposal",
                  "business proposal", "commercial proposal", "propale"),
                 cover=True, toc=True, numbered=True,
                 sections=(Section("Votre besoin", "Your needs", r"besoin|contexte|enjeu|need|context|"
                                                                r"situation|probleme|defi"),
                           Section("Notre solution", "Our solution", r"solution|offre|proposition|prestation|"
                                                                     r"approche|service|methodolog|approach"),
                           Section("Bénéfices", "Benefits", r"benefice|avantage|valeur|pourquoi|gain|benefit|"
                                                            r"why us", required=False),
                           Section("Planning", "Timeline", r"planning|calendrier|deroulement|mise en (?:oeuvre|place)"
                                                           r"|timeline|etapes", required=False),
                           Section("Tarifs", "Pricing", r"tarif|prix|budget|cout|investissement|devis|pricing|"
                                                        r"price|cost|formule"),
                           Section("Prochaines étapes", "Next steps", r"prochaine|etape suivante|conditions|"
                                                                      r"modalite|contact|next step|engagement"))),
        Template("procedure", "Procédure", "Procedure",
                 ("procedure", "process", "processus", "mode operatoire", "guide", "instruction", "checklist",
                  "how-to", "protocole", "marche a suivre"),
                 cover=False, toc=True, numbered=True,
                 sections=(Section("Objet", "Purpose", r"objet|objectif|but|purpose|introduction|pourquoi"),
                           Section("Champ d'application", "Scope", r"champ|perimetre|application|concerne|scope|"
                                                                    r"public|qui", required=False),
                           Section("Rôles", "Roles", r"role|responsab|acteur|intervenant|qui fait", required=False),
                           Section("Étapes", "Steps", r"etape|deroulement|mode operatoire|jour|semaine|avant|"
                                                      r"accueil|step|process|instruction|phase"),
                           Section("Points de vigilance", "Checks", r"vigilance|controle|attention|bonnes pratiques|"
                                                                    r"check|risque|a eviter", required=False))),
        Template("lettre", "Lettre", "Letter",
                 ("lettre", "letter", "courrier", "lettre de resiliation", "lettre de motivation", "cover letter",
                  "lettre officielle"),
                 cover=False, toc=False, numbered=False, letter=True),
    )
}  # fmt: skip
DEFAULT = "rapport"

# A hint from the user's own words when the model named no template (never over the model's own valid choice).
_HINTS = (
    ("compte-rendu", r"compte[- ]rendu|comptes[- ]rendus|proc[eè]s[- ]verbal|minutes"),
    ("cadrage", r"cadrage|project brief|charte projet"),
    ("proposition", r"proposition commerciale|offre commerciale|propale|business proposal|devis"),
    ("procedure", r"proc[ée]dure|mode op[ée]ratoire|marche [àa] suivre|process(?:us)? d['’]"),
    ("lettre", r"\blettre\b|\bcourrier\b|\bletter\b"),
    ("rapport", r"rapport|report|note de synth[èe]se|livre blanc|white ?paper|[ée]tude"),
)


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "").replace("’", "'").casefold())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


_ALIASES = {fold(a): t.id for t in TEMPLATES.values() for a in (t.id, t.fr, t.en, *t.aliases)}


def of(value: object) -> str | None:
    """The template a model wrote (« note de cadrage », « Compte-rendu », « proposal »…), or None."""
    key = fold(re.sub(r"[_]+", " ", str(value or ""))).strip(" .\"'«»")
    if not key:
        return None
    if key in _ALIASES:
        return _ALIASES[key]
    key2 = key.replace("-", " ")
    return _ALIASES.get(key2) or next((tid for a, tid in _ALIASES.items() if len(a) > 4 and a in key2), None)


def hint(words: str) -> str | None:
    w = str(words or "")
    return next((tid for tid, rx in _HINTS if re.search(rx, w, re.I)), None)


def pick(model_value: object, words: str, title: str = "") -> tuple[str, str]:
    """(template id, how): ``model`` when the model's choice is a known template, else ``hint`` (the user's words,
    then the title), else ``default``."""
    got = of(model_value)
    if got:
        return got, "model"
    h = hint(words) or hint(title)
    if h:
        return h, "hint"
    return DEFAULT, "default"


def check(doc: dict) -> dict:
    """The structure of a document against its template: expected sections found (by title or sub-heading), missing
    ones, and a completeness ratio over the required ones. Pure; the document is not changed."""
    tpl = TEMPLATES.get(doc.get("template") or "") or TEMPLATES[DEFAULT]
    titles = []
    for b in doc.get("blocks") or []:
        titles.append(fold(b.get("title") or ""))
        titles += [fold(p.get("text") or "") for p in b.get("parts") or [] if p.get("t") == "heading"]
    found, missing = [], []
    for s in tpl.sections:
        hit = any(re.search(rf"(?:^|\b){s.match}", t) for t in titles if t)
        (found if hit else missing).append(s)
    req = [s for s in tpl.sections if s.required]
    have = [s for s in req if s in found]
    lang = "en" if doc.get("lang") == "en" else "fr"
    letter_ok = tpl.letter and any(
        p.get("t") == "text" and len(p.get("text") or "") > 60 for b in doc.get("blocks") or [] for p in b["parts"]
    )
    return {
        "template": tpl.id,
        "expected": [getattr(s, lang) for s in tpl.sections],
        "found": [getattr(s, lang) for s in found],
        "missing": [getattr(s, lang) for s in missing if s.required],
        "optional_missing": [getattr(s, lang) for s in missing if not s.required],
        "complete": (1.0 if letter_ok else 0.0) if tpl.letter else round(len(have) / len(req), 2) if req else 1.0,
    }


def next_steps(doc: dict, lang: str = "fr") -> list[dict]:
    """2-3 concrete follow-ups for the document just shown: a missing expected section first, then what the
    document lacks (a summary table, a figure), then a lighter version. Each is a request the user could type."""
    fr = lang != "en"
    tpl = TEMPLATES.get(doc.get("template") or "") or TEMPLATES[DEFAULT]
    st = check(doc)
    out: list[dict] = []

    def add(label: str, prompt: str) -> None:
        if len(out) < 3 and all(x["prompt"] != prompt for x in out):
            out.append({"label": label[:60], "prompt": prompt[:200]})

    for name in st["missing"][:1] + st["optional_missing"][:1]:
        add(f"Ajouter « {name} »" if fr else f"Add “{name}”",
            f"Ajoute une section {name} au document" if fr else f"Add a {name} section to the document")  # fmt: skip
    kinds = {p.get("t") for b in doc.get("blocks") or [] for p in b.get("parts") or []}
    if tpl.letter:
        add("Plus formelle" if fr else "More formal",
            "Rends la lettre plus formelle" if fr else "Make the letter more formal")  # fmt: skip
        add("Plus courte" if fr else "Shorter", "Raccourcis la lettre" if fr else "Shorten the letter")
        return out
    if "table" not in kinds:
        what = {
            "compte-rendu": ("Tableau des actions", "Ajoute un tableau des actions (action, responsable, échéance)",
                             "Action table", "Add an action table (action, owner, due date)"),
            "cadrage": ("Tableau des risques", "Ajoute un tableau des risques (risque, impact, parade)",
                        "Risk table", "Add a risk table (risk, impact, mitigation)"),
            "proposition": ("Tableau des tarifs", "Ajoute un tableau des tarifs dans la section Tarifs",
                            "Pricing table", "Add a pricing table in the Pricing section"),
            "procedure": ("Tableau des étapes", "Ajoute un tableau des étapes (étape, qui, quand)",
                          "Steps table", "Add a steps table (step, who, when)"),
        }.get(tpl.id, ("Tableau de synthèse", "Ajoute un tableau de synthèse", "Summary table",
                       "Add a summary table"))  # fmt: skip
        add(what[0] if fr else what[2], what[1] if fr else what[3])
    if "image" not in kinds and tpl.id in ("rapport", "proposition", "cadrage"):
        add("Ajouter une image" if fr else "Add a picture",
            "Ajoute une image d'illustration dans la première section" if fr
            else "Add an illustration picture to the first section")  # fmt: skip
    add("Plus concis" if fr else "More concise", "Rends le document plus court" if fr else "Make the document shorter")
    return out
