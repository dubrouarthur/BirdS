"""When the canvas opens, from the user's own words only (never the model's): a deck, a document, a web page or
visual code, a diagram. And on a later turn, whether the words ask to change the artifact already open.

Deterministic and conservative: an ordinary office prompt (« rédige un mail », « résume ce document »,
« comment ajouter une diapo dans PowerPoint ? ») never opens it. A how-to question is not a request for a file.
"""

from __future__ import annotations

import re

_MAKE = (
    r"(?:fai[st]|faire|fais-moi|faites|cr[ée]e[rz]?|cr[ée]ation|pr[ée]pare[rz]?|g[ée]n[èe]re[rz]?|r[ée]dige[rz]?|"
    r"[ée]cri[st]|[ée]crire|monte[rz]?|construi[st]|con[cç]oi[st]|produi[st]|d[ée]veloppe[rz]?|code[rz]?|"
    r"programme[rz]?|dessine[rz]?|r[ée]alise[rz]?|propose[rz]?|mets?(?:-moi)? en forme|transforme[rz]?|"
    r"make|create|build|prepare|draft|write|design|generate|code|turn|draw|"
    r"j['’]ai besoin d['’]|il me faut|i need|we need|peux-tu|pourrais-tu|pouvez-vous|pourriez-vous|can you|could you)"
)
_DECK = (r"(?:pr[ée]sentations?|diaporamas?|diapos?(?:itives?)?|slides?|decks?|pitch(?:\s+deck)?|keynote|"
         r"powerpoint|power\s?point|pptx|support(?:s)? de pr[ée]sentation|transparents|presentation)")  # fmt: skip
_DOC = (r"(?:documents?(?:\s+word)?|rapports?|report|note de synth[èe]se|note d['’]information|notes? de cadrage|"
        r"compte[- ]rendus?|comptes[- ]rendus|minutes|m[ée]mos?|memo|livre blanc|white ?paper|guide|proc[ée]dure|"
        r"cahier des charges|proposition commerciale|business plan|plan d['’]action|dossier|fiche (?:projet|produit|"
        r"de poste|technique|pratique)|charte|r[èe]glement|politique|brief|one[- ]pager|word|docx)")  # fmt: skip
_WEB = (r"(?:page (?:web|html|d['’]accueil)|landing(?: page)?|site (?:web|vitrine)|website|web ?page|html|css|"
        r"formulaire html|maquette (?:html|web)|prototype (?:html|web)|composant (?:html|web|react)|"
        r"svg|logo svg|ic[ôo]ne svg|animation css|mini[- ]jeu|jeu (?:en|html|javascript|js)|calculatrice|"
        r"compte [àa] rebours|countdown|horloge (?:en|html|js)|widget (?:html|web)|"
        r"visualisation interactive|tableau de bord html|dashboard html|javascript|\bjs\b)")  # fmt: skip
_DIAGRAM = (r"(?:sch[ée]ma(?:\s+(?:de|du|des)\s+(?:processus|fonctionnement|flux|d[ée]cision|architecture|"
            r"principe))?|organigramme|logigramme|diagramme (?:de flux|de processus|de d[ée]cision|d['’]activit[ée]|"
            r"de s[ée]quence)|flow ?chart|flowchart|mind ?map|carte mentale|arbre de d[ée]cision|mermaid|"
            r"process(?:us)? map|cartographie (?:du|des) processus)")  # fmt: skip
_PY = r"(?:script|programme|program|application|outil|tool)\s+(?:en\s+|in\s+)?python|python\s+(?:script|program)"
_HOWTO = re.compile(
    r"^\s*(?:comment|how|pourquoi|why|o[uù] |where|quand|when|est-ce qu|qu['’]est-ce|c['’]est quoi|what is|"
    r"quel(?:le)?s? (?:est|sont)|quels? conseils|des conseils|tips)\b|\b(?:how (?:do|can|to|should)|"
    r"comment (?:faire|on|je|puis|peut|r[ée]ussir|ajouter|ins[ée]rer|cr[ée]er|mettre))\b",
    re.I,
)
_NOT = re.compile(
    r"\b(?:r[ée]sume[rz]?|r[ée]sum[ée]|traduis|tradui[st]|traduction|translate|relis|relire|corrige ce|"
    r"convertis|convertir|en pdf|lis ce|analyse ce|explique|mail|e-mail|email|courriel|lettre|post linkedin|tweet)\b",
    re.I,
)
_MAKE_RX = re.compile(_MAKE, re.I)


def _near(words: str, noun: str, span: int = 60, lead: bool = True) -> bool:
    """A creation verb before the noun, within ``span`` characters (« prépare-moi pour lundi une présentation »),
    or the noun as the first words of the message (« Une présentation sur le télétravail, 5 slides »)."""
    if re.search(rf"{_MAKE}.{{0,{span}}}?\b{noun}", words, re.I | re.S):
        return True
    return lead and bool(
        re.match(
            rf"^\s*(?:une?|des|la|le|mon|ma|notre|a|an)?\s*{noun}\b.{{0,24}}?\b(?:sur|de|about|on|pour|for|:)\s",
            words,
            re.I,
        )
    )


_FILE_FORMAT = re.compile(
    r"\b(?:pptx|docx|xlsx|\.ppt|fichier (?:powerpoint|word|excel|pptx|docx)|(?:en|au) format (?:powerpoint|word|pptx|"
    r"docx)|document word|word document|un word|un powerpoint|a powerpoint|powerpoint file|word file)\b",
    re.I,
)


def ask(words: str) -> str | None:
    """'deck' | 'doc' | 'code' | 'diagram' | None, from the user's own words."""
    w = (words or "").strip()
    if not w or len(w) > 4000 or _HOWTO.search(w[:160]):
        return None
    head = w[:400]
    if _near(head, _DIAGRAM):
        return "diagram"
    if _near(head, _WEB) or re.search(r"\b(?:page|site)\b.{0,30}\b(?:html|css|javascript)\b", head, re.I):
        return "code"
    if re.search(_PY, head, re.I) and _MAKE_RX.search(head):
        return "code"
    if _NOT.search(head) or _FILE_FORMAT.search(head):
        return None  # a named file format (« une présentation pptx ») is a file: the trained tool makes it
    if _near(head, _DECK):
        return "deck"
    if _near(head, _DOC, 40, lead=False):
        return "doc"
    return None


_EDIT = re.compile(
    r"\b(?:ajoute[rz]?|rajoute[rz]?|ins[èe]re[rz]?|remplace[rz]?|modifie[rz]?|change[rz]?|supprime[rz]?|enl[èe]ve[rz]?|"
    r"retire[rz]?|efface[rz]?|raccourci[st]?|r[ée]dui[st]|all[èe]ge[rz]?|condense[rz]?|d[ée]veloppe[rz]?|"
    r"approfondi[st]|compl[èe]te[rz]?|enrichi[st]|reformule[rz]?|r[ée][ée]cri[st]|retravaille[rz]?|am[ée]liore[rz]?|"
    r"simplifie[rz]?|corrige[rz]?|r[ée]pare[rz]?|ajuste[rz]?|mets?|mettre|d[ée]place[rz]?|inverse[rz]?|"
    r"renomme[rz]?|duplique[rz]?|traduis|tradui[st]|illustre[rz]?|colore[rz]?|agrandi[st]|centre[rz]?|"
    r"add|insert|replace|change|remove|delete|shorten|expand|rewrite|improve|simplify|fix|move|swap|rename|"
    r"translate|make it|plus (?:court|long|concis|clair|simple|visuel|pro|formel|d[ée]taill[ée])e?s?|"
    r"moins (?:long|de texte|technique)|shorter|longer|more|less)\b",
    re.I,
)
_ABOUT = re.compile(
    r"\b(?:slides?|diapos?(?:itives?)?|transparents?|pages?|sections?|parties|partie|paragraphes?|titres?|"
    r"sous-titres?|images?|photos?|illustrations?|graphiques?|tableaux?|th[èe]mes?|couleurs?|style|"
    r"pr[ée]sentation|document|rapport|deck|code|bouton|boutons|page|formulaire|script|fonction|erreur|bug|"
    r"chiffres|conclusion|introduction|intro|sommaire|plan|cellules?|colonnes?|lignes?|"
    r"slide|title|picture|chart|table|theme|button|error|column|row|b\d{1,3})\b",
    re.I,
)
_NEW_SUBJECT = re.compile(r"\b(?:sur|about|concernant|à propos de)\b\s+(?!(?:la|le|les|cette|ce|this|the)\b)\w", re.I)


def edit_ask(words: str, kind: str, targeted: bool = False) -> bool:
    """The words change the artifact already open: an edit verb that is about it (a slide, a section, the
    picture, the theme, the code), or any instruction sent from a block (« Demander à Bird »)."""
    w = (words or "").strip()
    if not w:
        return False
    if targeted:
        return True
    if len(w) > 1200 or _HOWTO.search(w[:120]) and not re.search(r"\b(?:peux-tu|can you)\b", w[:60], re.I):
        return False
    if not _EDIT.search(w) and not re.search(
        r"^\W*(?:et\s+)?(?:en|in)\s+(?:anglais|fran[çc]ais|english|french|"
        r"espagnol|spanish|allemand|german)\b",
        w,
        re.I,
    ):
        return False
    created = ask(w)
    if created and created != _family(kind) and _NEW_SUBJECT.search(w):
        return False  # « fais une présentation sur le vélo » while a document is open: a new artifact
    if (
        created == _family(kind)
        and _NEW_SUBJECT.search(w)
        and not re.search(
            r"\b(?:la|cette|this|the)\s+"
            r"(?:pr[ée]sentation|deck|page)",
            w,
            re.I,
        )
    ):
        return False  # « fais une autre présentation sur X »
    if _ABOUT.search(w) or re.search(r"\b(?:plus|moins|shorter|longer)\b", w, re.I):
        return True
    if re.search(r"\b(?:en|in)\s+(?:anglais|fran[çc]ais|english|french|espagnol|spanish|allemand|german)\b", w, re.I):
        return len(w) <= 80
    return len(w) <= 80  # « raccourcis », « en anglais », « mets-le en bleu » right after the artifact


def _family(kind: str) -> str:
    return {"diagram": "code"}.get(kind, kind)
