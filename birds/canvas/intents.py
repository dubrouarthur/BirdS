"""When the canvas opens, from the user's own words only (never the model's): a deck, a document, a web page or
visual code, a diagram. And on a later turn, whether the words ask to change the artifact already open.

Deterministic and conservative: an ordinary office prompt (« rédige un mail », « résume ce document »,
« comment ajouter une diapo dans PowerPoint ? ») never opens it. A how-to question is not a request for a file.
"""

from __future__ import annotations

import re

# Creation verbs only. A request opener (« peux-tu », « can you », « il me faut ») is not one: « peux-tu vérifier ce
# rapport ? » asks about a document, it does not ask for one. A verb right after a determiner is a noun (« le code »).
_MAKE = (
    r"(?<![\w’'-])(?<!\ble )(?<!\bla )(?<!\bun )(?<!\bune )(?<!\bdu )(?<!\bce )(?<!\bmon )(?<!\bton )(?<!\bthe )"
    r"(?<!\bmy )(?<!\ba )"
    r"(?:fai[st]|faire|faites|cr[ée]e[rz]?|pr[ée]pare[rz]?|g[ée]n[èe]re[rz]?|r[ée]dige[rz]?|[ée]cri[st]|[ée]crire|"
    r"[ée]crivez|monte[rz]?|construi[st]|con[cç]oi[st]|produi[st]|d[ée]veloppe[rz]?|code[rz]?|programme[rz]?|"
    r"dessine[rz]?|r[ée]alise[rz]?|propose[rz]?|mets?(?:-moi|-nous)? en forme|transforme[rz]?|"
    r"make|create|build|prepare|draft|write|design|generate|code|turn|draw)"
    r"(?:-(?:moi|nous|lui|en|le|la|les))?"
)
# Between the verb and the noun: determiners, numbers, a few adjectives, « pour lundi » — never another noun
# (« fais une LISTE des slides », « rédige une RÉPONSE au rapport », « prépare un DISCOURS de 2 minutes »).
_FILL = (
    r"(?:l['’]|(?:une?|des|du|le|la|les|mon|ma|mes|notre|nos|ton|ta|tes|votre|vos|ce|cet|cette|ces|a|an|the|my|"
    r"our|this|some|moi|nous|me|m['’]|vite|rapidement|\d{1,3}|deux|trois|quatre|cinq|six|sept|huit|dix|"
    r"petite?s?|courte?s?|nouvel(?:le)?s?|nouveaux?|belles?|beaux?|jolie?s?|vraie?s?|simples?|rapides?|"
    r"compl[eè]te?s?|short|new|quick|nice|simple|full|small|pour (?:demain|lundi|mardi|mercredi|jeudi|vendredi|"
    r"ce soir|la r[ée]union|le comit[ée])|for (?:tomorrow|monday|the meeting))\s+)"
)
_DECK = (r"(?:pr[ée]sentations?|diaporamas?|diapos?(?:itives?)?|slides?|decks?|pitch(?:\s+deck)?|keynote|"
         r"powerpoint|power\s?point|pptx|support(?:s)? de pr[ée]sentation|transparents|presentation)")  # fmt: skip
# Nouns that name a written document. Ambiguous ones are left out (« un discours de 2 MINUTES », « la POLITIQUE de
# remboursement en deux phrases », « un BRIEF pour le photographe en 3 lignes », « un DOSSIER de retraite »).
_DOC = (r"(?:documents?(?:\s+word)?|rapports?|report|note de synth[èe]se|note d['’]information|notes? de cadrage|"
        r"compte[- ]rendus?|comptes[- ]rendus|m[ée]mos?|memo|livre blanc|white ?paper|guide (?:pratique|utilisateur|"
        r"d['’]utilisation|de bonnes pratiques|d['’]accueil)|cahier des charges|proposition commerciale|"
        r"business plan|plan d['’]action|dossier de presse|fiche (?:projet|produit|de poste|technique|pratique)|"
        r"charte|r[èe]glement int[ée]rieur|one[- ]pager|word|docx)")  # fmt: skip
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
# A question anywhere in the sentence (« … des conseils pour le stress ? », « … dure combien de temps ? »).
_QUESTION = re.compile(
    r"\b(?:conseils?(?! (?:municipal|communautaire|d['’]administration|de (?:classe|quartier|direction|surveillance|"
    r"l['’]ordre|d[ée]veloppement)|r[ée]gional|d[ée]partemental|scientifique|syndical|des ministres))|astuces?|tips|advice|avis|combien|c['’]est quoi|qu['’]est-ce|est-ce que|est-il|est-elle|"
    r"faut-il|dois-je|should i|what does|que dit|quels? sont|quelles? sont|(?<!sur )(?<!about )pourquoi|"
    r"(?<!sur )(?<!about )comment (?:faire|on|je|puis|r[ée]ussir))\b",
    re.I,
)
_NOT = re.compile(
    r"\b(?:r[ée]sume[rz]?|r[ée]sum[ée]|traduis|tradui[st]|traduction|translate|relis|relire|corrige ce|"
    r"convertis|convertir|en pdf|lis ce|analyse ce|explique|mail|e-mail|email|courriel|lettre|post linkedin|tweet|"
    r"message|r[ée]ponse (?:au|[àa] la|aux)|reply to|answer to|dire ce que|extrai[rst]e?|compare[rz]?|v[ée]rifie[rz]?|"
    r"check|discours|speech|orale?|je dois (?:faire|pr[ée]senter|donner)|je vais (?:faire|pr[ée]senter)|"
    r"i have to (?:give|make|present))\b",
    re.I,
)
# A short text asked for (« en 3 lignes », « en deux phrases »): an answer in the chat, not a document.
_SHORT = re.compile(r"\ben (?:\d{1,2}|une|deux|trois|quatre|cinq|quelques) (?:lignes?|phrases?|mots)\b|"
                    r"\bin (?:\d{1,2}|one|two|three|a few) (?:lines?|sentences?|words)\b", re.I)  # fmt: skip
_MAKE_RX = re.compile(_MAKE, re.I)
# With files attached, the turn is about them unless it starts with a creation verb (« Fais une présentation de ce
# rapport »), possibly after a polite opener or a first clause (« À partir de ce document, rédige une note … »).
_LEADS = re.compile(
    rf"(?:^|[,.;:]\s*)\W*(?:(?:peux-tu|pourrais-tu|pouvez-vous|pourriez-vous|tu peux|can you|could you|please|"
    rf"merci de|stp)\s+(?:me\s+|m['’]|nous\s+)?)?{_MAKE}\b",
    re.I,
)


def _near(words: str, noun: str, lead: bool = True) -> bool:
    """A creation verb right before the noun, with only determiners, numbers and a few adjectives between
    (« prépare-moi pour lundi une présentation »), or the noun as the first words of the message, then its subject
    (« Une présentation sur le télétravail, 5 slides »). Several needs (« j'ai besoin d'une présentation sur … »)
    name the noun right after."""
    if re.search(rf"{_MAKE}\s+{_FILL}{{0,4}}{noun}\b", words, re.I):
        return True
    if re.search(rf"\b(?:j['’]ai besoin d['’]|il me faut|i need|we need)\s*(?:une?|a|an)\s+{noun}\b"
                 rf"\s+(?:sur|de|about|on|pour|for)\s", words, re.I):  # fmt: skip
        return True
    return lead and bool(
        re.match(
            rf"^\s*(?:une?|des|a|an)?\s*{noun}\b.{{0,24}}?\b(?:sur|about|on|pour|for|:)\s",
            words,
            re.I,
        )
    )


_FILE_FORMAT = re.compile(
    r"\b(?:pptx|docx|xlsx|\.ppt|fichier (?:powerpoint|word|excel|pptx|docx)|(?:en|au) format (?:powerpoint|word|pptx|"
    r"docx)|document word|word document|un word|un powerpoint|a powerpoint|powerpoint file|word file)\b",
    re.I,
)


_WORD_FILE = re.compile(r"\b(?:docx|word|fichier word|format word|document word|word document|word file)\b", re.I)
_OTHER_FILE = re.compile(r"\b(?:pptx|xlsx|\.ppt|powerpoint|power point|excel|tableur|spreadsheet|slides?|diapos?)\b",
                         re.I)  # fmt: skip
_LETTER = re.compile(r"(?:lettres?|courriers?|letters?)", re.I)


def ask(words: str, attached: bool = False) -> str | None:
    """'deck' | 'doc' | 'code' | 'diagram' | None, from the user's own words. A hint, never the last word: when it
    says None the turn is an ordinary one, where the model may still call its trained make_slides / make_document
    tool (the canvas adopts the file). ``attached``: files came with the message; the canvas then needs a creation
    verb in the lead (« fais une présentation de ce rapport »), never a question about them."""
    w = (words or "").strip()
    if not w or len(w) > 4000 or _HOWTO.search(w[:160]):
        return None
    head = w[:400]
    if _QUESTION.search(head) or _SHORT.search(head):
        return None
    if attached and not _LEADS.search(head[:160]):
        return None
    if _near(head, _DIAGRAM):
        return "diagram"
    if _near(head, _WEB) or (
        _MAKE_RX.search(head) and re.search(r"\b(?:page|site)\b.{0,30}\b(?:html|css|javascript)\b", head, re.I)
    ):
        return "code"
    if re.search(_PY, head, re.I) and _MAKE_RX.search(head):
        return "code"
    if _WORD_FILE.search(head) and not _OTHER_FILE.search(head) and not _NOT.search(_LETTER.sub(" ", head)):
        # a Word document (« rédige un document Word », « une lettre en Word »): the canvas is the document and
        # its card downloads the .docx — one deliverable, one card (the trained tool's file would be a second one)
        if _near(head, _DOC, lead=False) or _near(head, _LETTER.pattern, lead=False):
            return "doc"
    veto = _NOT.search(head)
    if veto and re.match(r"compar|expli", veto.group(0), re.I) and _near(head, _DECK):
        noun = re.search(_DECK, head, re.I)
        if noun and veto.start() > noun.end():
            veto = None  # « une présentation qui compare A et B »: what the deck does, not a request to compare
    if veto or _FILE_FORMAT.search(head):
        return None  # a named file format (« une présentation pptx ») is a file: the trained tool makes it
    if _near(head, _DECK):
        return "deck"
    if _near(head, _DOC, lead=False):
        return "doc"
    return None


_EDIT = re.compile(
    r"\b(?:ajoute[rz]?|rajoute[rz]?|ins[èe]re[rz]?|remplace[rz]?|modifie[rz]?|change[rz]?|supprime[rz]?|enl[èe]ve[rz]?|"
    r"retire[rz]?|efface[rz]?|raccourci[st]?|r[ée]dui[st]|all[èe]ge[rz]?|condense[rz]?|d[ée]veloppe[rz]?|"
    r"approfondi[st]|compl[èe]te[rz]?|enrichi[st]|reformule[rz]?|r[ée][ée]cri[st]|retravaille[rz]?|am[ée]liore[rz]?|"
    r"simplifie[rz]?|corrige[rz]?|r[ée]pare[rz]?|ajuste[rz]?|mets?|mettre|d[ée]place[rz]?|inverse[rz]?|passe[rz]?|"
    r"renomme[rz]?|duplique[rz]?|traduis|tradui[st]|illustre[rz]?|colore[rz]?|agrandi[st]|centre[rz]?|rends|"
    r"add|insert|replace|change|remove|delete|shorten|expand|rewrite|improve|simplify|fix|move|swap|rename|"
    r"translate|make it|plus (?:court|long|concis|clair|simple|visuel|pro|formel|d[ée]taill[ée]|percutant)e?s?|"
    r"moins (?:long|de texte|technique)|shorter|longer|more|less)\b",
    re.I,
)
# What names a part of the artifact, per kind: « la slide 3 », « le titre », « le bouton », « la colonne B ».
_ABOUT_COMMON = (r"blocs?|block|titres?|sous-titres?|images?|photos?|illustrations?|th[èe]mes?|couleurs?|style|polices?|"
                 r"title|picture|theme|colou?rs?|font|b\d{1,3}")  # fmt: skip
_ABOUT = {
    "deck": re.compile(
        rf"\b(?:{_ABOUT_COMMON}|slides?|diapos?(?:itives?)?|transparents?|pr[ée]sentation|deck|graphiques?|"
        r"tableaux?|chiffres|conclusion|introduction|intro|sommaire|points?|puces?|citations?|chart|table|"
        r"bullets?|quote)\b",
        re.I,
    ),
    "doc": re.compile(
        rf"\b(?:{_ABOUT_COMMON}|sections?|parties|partie|paragraphes?|chapitres?|document|rapport|note|"
        r"graphiques?|tableaux?|chiffres|conclusion|introduction|intro|sommaire|encadr[ée]s?|listes?|chart|table|"
        r"section|paragraph|report)\b",
        re.I,
    ),
    "code": re.compile(
        rf"\b(?:{_ABOUT_COMMON}|code|bouton|boutons|page|formulaire|script|fonction|erreur|bug|pied de page|"
        r"en-t[êe]te|menu|fond|marges?|n[œo]uds?|[ée]tapes?|fl[èe]ches?|sch[ée]ma|button|form|function|error|"
        r"footer|header|background|node|diagram)\b",
        re.I,
    ),
    "sheet": re.compile(
        rf"\b(?:{_ABOUT_COMMON}|cellules?|colonnes?|lignes?|tableau|formules?|totaux|total|cell|column|row|"
        r"formula|sheet)\b",
        re.I,
    ),
}
_NEW_SUBJECT = re.compile(r"\b(?:sur|about|concernant|à propos de)\b\s+(?!(?:la|le|les|cette|ce|this|the)\b)\w", re.I)
_LANGS = r"(?:anglais|fran[çc]ais|english|french|espagnol|spanish|allemand|german|italien|italian)"
# « Change rien, c'est bien », « Ne mets pas… », « Non attends, laisse »: not a change of a short, unnamed thing
_HOLD = re.compile(r"\b(?:ne|n['’]|rien|pas|aucun|non|attends?|laisse|nothing|don['’]?t|no need|never mind|"
                   r"c['’]est (?:bien|bon|parfait)|it['’]s (?:fine|good))\b|\?", re.I)  # fmt: skip


# the artifact itself, or a numbered part of it: what a request must name to reopen a closed panel (« la slide 3 »,
# « le document », « ajoute une diapositive »), never a word any message uses (titre, style, chiffres, points)
_NAMED_PART = re.compile(
    r"\b(?:slides?|diapos?(?:itives?)?|transparents?|sections?|chapitres?|cellules?|colonnes?|b\d{1,3})\b|"
    r"\b(?:partie|paragraphe|ligne|[ée]tape)\s+\d+\b|"
    r"\b(?:la|le|les|l['’]|cette|ce|cet|ma|mon|the|this|my)\s*(?:pr[ée]sentation|deck|document|rapport|note|page|"
    r"code|script|sch[ée]ma|diagramme|tableur|feuille|landing|site|presentation|report|diagram|spreadsheet)\b",
    re.I,
)
# what an artifact of any kind is made of: a demonstrative or possessive before another noun (« ce mail », « ma
# réunion », « ce paragraphe » on a deck) points the edit at something else than the artifact
_THIS = re.compile(r"\b(?:ce|cet|cette|ces|mon|ma|mes|ton|ta|tes|son|sa|ses|notre|nos|votre|vos|this|that|my|your)"
                   r"\s+([\w-]+)", re.I)  # fmt: skip
_OF_ARTIFACT = re.compile(r"(?:texte|contenu|version|fichier|text|content|version|file)$", re.I)


def _foreign_object(w: str, kind: str) -> bool:
    """« Améliore le style de ce mail », « Change le titre de ma réunion »: the words name another object."""
    about = _ABOUT.get(_family(kind), _ABOUT["deck"])
    for m in _THIS.finditer(w):
        noun = m.group(1)
        if not (about.fullmatch(noun) or _NAMED_PART.search("la " + noun) or _OF_ARTIFACT.match(noun)):
            return True
    return False


def edit_ask(words: str, kind: str, targeted: bool = False, shown: bool = True) -> bool:
    """The words change the artifact already open: an edit verb about a part of it (a slide, a section, the picture,
    the theme, the button), or any instruction sent from a block (« Demander à Bird »). A short edit that names
    nothing (« plus court », « et en anglais ? ») counts only while the panel is shown: once it is closed, « mets un
    rappel lundi » is an ordinary turn (``shown``: the panel is shown, or the artifact was made or changed by the turn
    just before)."""
    w = (words or "").strip()
    if not w:
        return False
    if targeted:
        return True
    if len(w) > 1200 or _HOWTO.search(w[:120]) and not re.search(r"\b(?:peux-tu|can you)\b", w[:60], re.I):
        return False
    from birds.harness.router import own_words

    w = own_words(w) or w  # « améliore ce mail : Bonjour Paul, … »: the pasted text is not the instruction
    if _foreign_object(w, kind) and not _NAMED_PART.search(w):
        return False  # « améliore le style de ce mail », « change le titre de ma réunion de demain »
    if not shown and not _NAMED_PART.search(w):
        return False  # a closed panel reopens only for the artifact or a numbered part of it, by name
    lang_only = re.search(rf"^\W*(?:et\s+)?(?:en|in)\s+{_LANGS}\b", w, re.I)
    if not _EDIT.search(w) and not lang_only:
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
    about = _ABOUT.get(_family(kind), _ABOUT["deck"])
    if about.search(w):
        return True
    if not shown:
        return False
    if re.search(r"\b(?:plus|moins|shorter|longer)\b", w, re.I) and len(w.split()) <= 6 and not _HOLD.search(
        w.replace("?", "")
    ):
        return True  # « plus court », « un peu moins long »
    if re.search(r"[«\"“'‘].+[»\"”'’]", w) or _HOLD.search(w.rstrip(" ?") if lang_only else w):
        return False  # « traduis 'bonjour' en japonais »: its own object; « change rien, c'est bien »
    if re.search(rf"\b(?:en|in)\s+{_LANGS}\b", w, re.I):
        return len(w.split()) <= 6  # « et en anglais ? », « traduis-la en anglais »
    return len(w.split()) <= 4  # « raccourcis », « mets-le en bleu », « simplifie » while it is shown


def _family(kind: str) -> str:
    return {"diagram": "code"}.get(kind, kind)
