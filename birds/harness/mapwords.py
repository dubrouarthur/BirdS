"""Map asks read from the user's own words that the single-place parsers of intents.py do not cover:

- ``place_list``: several places or addresses on one map (« montre sur une carte : 10 rue de Rivoli Paris ; 5 place
  Bellecour Lyon », a pasted column of addresses, « nos agences de Lyon, Marseille et Lille », a CSV with an
  « adresse » column), up to MAX_ITEMS;
- ``distance``: two places and the distance between them (« c'est loin Lyon de Paris ? », « combien de km entre
  Nantes et Rennes », « how far is Lyon from Paris »);
- ``near_me``: « une pharmacie autour de moi »: Bird does not know where the user is (the browser never sends a
  position), so nothing is geocoded and the user is asked for a place;
- ``plan_of``: what to compute on a list (« dans quel ordre les visiter » -> an order, « distances entre » -> a matrix).

Pure functions, no I/O. Called by intents.places, which applies the same « never a person, a document or an office
notion » rules to every item.
"""

from __future__ import annotations

import re

MAX_ITEMS = 25

_BULLET = re.compile(r"^\s*(?:[-–—•*·▪►✓]+|\d{1,2}\s*[.)°]|\(?[a-z]\)|#\d+)\s*", re.I)
# words that ask for a map (strong cue): enough for « mets sur une carte Lyon, Marseille et Lille »
_STRONG = re.compile(
    r"\b(?:cartes?|maps?|situe[rz]?|localise[rz]?|positionne\w*|plac(?:e|er|ez)\s+(?:\S+\s+){0,8}?sur|"
    r"o[uù]\s+(?:sont|se\s+trouvent|se\s+situent)|dans\s+quel\s+ordre|ordre\s+de\s+visite|tourn[ée]e|"
    r"itin[ée]raire|trajet|distances?|visiter|where\s+are|locate|plot|pin|route|optimi[sz]e\w*)\b",
    re.I,
)
# nouns of a list of places (weak cue): enough before a colon or a pasted column (« nos agences : … »)
_NOUNS = re.compile(
    r"\b(?:adresses?|addresses|sites|lieux|agences|bureaux|magasins|boutiques|villes|implantations|entrep[ôo]ts|"
    r"succursales|antennes|filiales|usines|points\s+de\s+vente|locations|offices|stores|places|cities|branches|"
    r"warehouses|stops|[ée]tapes)\b",
    re.I,
)


def _cue(text: str) -> bool:
    return bool(_STRONG.search(text or "") or _NOUNS.search(text or ""))


_LIST_NOUN = (
    r"(?:sites?|adresses?|lieux|agences?|bureaux|magasins?|boutiques?|villes?|implantations?|entrep[ôo]ts?|clients?|"
    r"succursales?|antennes?|filiales?|usines?|points?\s+de\s+vente|addresses|locations|offices|stores|places|cities|"
    r"branches|sites|warehouses)"
)
# the verbs and phrases of the ask, removed to leave the items (« mets sur une carte Lyon, Marseille et Lille »)
_ASK_WORDS = re.compile(
    r"(?:\b(?:peux-tu|pouvez-vous|tu\s+peux|est-ce\s+que\s+tu\s+peux|can\s+you|could\s+you|please|stp|svp|"
    r"s'il\s+te\s+pla[iî]t|s'il\s+vous\s+pla[iî]t|merci|voici|voil[àa]|here\s+are)\b|"
    r"\b(?:montre|affiche|mets|place|situe|localise|positionne|pointe|marque|show|put|map|plot|pin|locate)"
    r"(?:-(?:moi|les|nous|them))?\b(?:\s+(?:moi|les|them|these|those|ces|les))?|"
    r"\b(?:sur|on)\s+(?:une|la|a|the)\s+(?:carte|map)\b|\bune\s+carte\s+(?:avec|de|des|du)\b|"
    r"\bplacer\b|\bmettre\b|\bafficher\b|\bo[uù]\s+(?:sont|se\s+trouvent|se\s+situent)\b|\bwhere\s+are\b|"
    r"\bitin[ée]raire\b|\btrajet\b|\bdistances?\s+entre\b|\bdistances?\s+between\b|"
    r"\bdans\s+quel\s+ordre\s+(?:les\s+)?visiter\b|\boptimise\s+(?:ma|la|notre)\s+tourn[ée]e\b|"
    r"\bcarte\b|\bmap\b)",
    re.I,
)
_ARTICLE = re.compile(r"^(?:la|le|les|l'|the|un|une|des)\s*(?=\S)", re.I)
_SPLIT = re.compile(r"\s*;\s*|\s*,\s+|\s*,(?=\D)|\s+(?:et|and|puis|then)\s+|\s+&\s+|\s+/\s+")
_ADDR_HEAD = re.compile(r"^(?:adresses?|address(?:es)?|lieux?|location|localisation|emplacement)$", re.I)
_TOWN_HEAD = re.compile(r"^(?:villes?|city|cities|site|commune|town)$", re.I)
_ORDER = re.compile(
    r"\b(?:dans\s+quel\s+ordre|ordre\s+(?:de\s+visite|optimal|id[ée]al)|meilleur\s+ordre|optimi[sz]\w*|tourn[ée]e|"
    r"best\s+order|which\s+order|what\s+order|in\s+what\s+order|round\s+trip|circuit)\b",
    re.I,
)
_MATRIX = re.compile(
    r"\b(?:distances?|combien\s+de\s+(?:km|kilom[eè]tres)|how\s+far|matrice|kilom[ée]trage|[ée]loign[ée]e?s?)\b", re.I
)


def plan_of(text: str) -> str:
    """'order' (visit order asked), 'distances' (the distances between the places), or ''."""
    t = text or ""
    if _ORDER.search(t):
        return "order"
    if _MATRIX.search(t):
        return "distances"
    return ""


def _clean_item(item: str) -> str:
    t = _BULLET.sub("", item.strip())
    # « … ; Chambéry, dans quel ordre les visiter ? »: the ask that follows the last place is not part of it
    # (after a comma or a colon; with no separator only « dans quel ordre »: « rue du Circuit » stays whole)
    tail = re.search(
        r"\s*[,:–-]\s*(?=(?:" + _ORDER.pattern + r"|" + _MATRIX.pattern + r"))"
        r"|\s+(?=\b(?:dans\s+quel\s+ordre|in\s+(?:what|which)\s+order)\b)",
        t,
        re.I,
    )
    if tail and tail.start() > 0:
        t = t[: tail.start()]
    t = re.sub(r"^\*\*(.+)\*\*$", r"\1", t)
    t = " ".join(t.split()).strip(" .:?!\"'«»“”")
    import unicodedata

    from birds.harness.intents import KNOWN_PLACES

    # « la tour Eiffel » -> « tour Eiffel », but « Le Havre », « La Rochelle », « le mans » keep their article
    folded = re.sub(r"\s+", "-", unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower())
    if folded not in KNOWN_PLACES and not re.match(r"^(?:Le|La|Les)\s+[A-ZÀ-Ý]", t):
        t = _ARTICLE.sub("", t) if not re.match(r"^l'", t, re.I) else t[2:]
    return t.strip(" ,")


def _csv_column(lines: list[str]) -> list[str] | None:
    """The address column of a pasted table (« nom;adresse » header, or the one cell of each row that is an address)."""
    from birds.harness.geo import looks_like_address

    for sep in ("\t", ";", "|", ","):
        rows = [[c.strip() for c in ln.strip("|").split(sep)] for ln in lines]
        if len(rows) < 2 or not all(len(r) >= 2 for r in rows):
            continue
        width = len(rows[0])
        if not all(len(r) == width for r in rows):
            continue
        head = [c.lower() for c in rows[0]]
        col = next((i for i, c in enumerate(head) if _ADDR_HEAD.match(c)), None)
        if col is None:
            col = next((i for i, c in enumerate(head) if _TOWN_HEAD.match(c)), None)
        if col is not None:
            return [r[col] for r in rows[1:] if r[col]]
        cols = [i for i in range(width) if all(looks_like_address(r[i]) for r in rows)]
        if cols:
            return [r[cols[0]] for r in rows]
    return None


def _items_of_line(text: str) -> list[str]:
    """The items of a one-line list once the ask words are removed (« les agences de Lyon, Marseille et Lille »)."""
    t = _ASK_WORDS.sub(" ", text)
    t = " ".join(t.split()).strip(" :,.?!")
    # « (nos) agences de Lyon, Marseille et Lille »: the list noun and its preposition introduce the towns
    t = re.sub(
        r"^(?:(?:nos|les|ces|des|mes|vos|our|the|these)\s+)?(?:\d+\s+|deux\s+|trois\s+|quatre\s+|cinq\s+|six\s+)?"
        + _LIST_NOUN
        + r"(?:\s+(?:suivant\w*|following))?\s*(?:(?:de|du|des|d'|à|a|au|aux|in|of|at)\s*|:\s*|$)",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"^(?:ces|les|nos|these|our)\s+", "", t, flags=re.I).strip(" :,")
    from birds.harness.intents import known_place

    out = []
    for part in (p for p in _SPLIT.split(t) if p and p.strip()):
        # « lyon marseille et lille »: towns one after the other with no comma, each a known town
        words = part.split()
        bare = "," not in t and ";" not in t
        out += words if bare and len(words) >= 2 and all(known_place(w) for w in words) else [part]
    return out


def place_list(text: str) -> list[str] | None:
    """The places or addresses of a list ask, in the order given (2..MAX_ITEMS kept), or None. The caller checks
    that each item is a place."""
    from birds.harness.geo import looks_like_address

    raw = (text or "").replace("’", "'").replace("\r", "")
    lines = [ln for ln in (x.strip() for x in raw.split("\n")) if ln]
    items: list[str] | None = None
    strong = bool(_STRONG.search(raw))
    if len(lines) >= 2:
        table = _csv_column(lines)
        if table is not None and len(table) >= 2:
            items = table
        else:
            head, body = lines[0], lines[1:]
            item_like = all(len(x) <= 120 and len(x.split()) <= 14 for x in body)
            head_is_item = looks_like_address(head) or (_BULLET.match(head) and _BULLET.sub("", head) != head)
            if item_like and head_is_item and all(looks_like_address(x) or _BULLET.match(x) for x in lines):
                items = lines
            elif item_like and len(head) <= 160 and (_cue(head) or _ADDR_HEAD.match(head.strip(" :"))):
                items = body  # « affiche ces adresses sur une carte : » then the list: the head is the ask
        if items is None:
            return None
    else:
        from birds.harness.geo import find_address

        line = lines[0] if lines else ""
        if len(line) > 1200:
            return None
        if ";" not in line and len(find_address(line)) >= 0.5 * len(line):
            return None  # « 1 place du Capitole, Toulouse »: one address with a comma, not a list
        m = re.match(r"^(?P<head>[^:]{1,160}):\s*(?P<list>.+)$", line)
        if m and _cue(m.group("head")):
            items = (
                [p for p in re.split(r"\s*;\s*", m.group("list"))]
                if ";" in m.group("list")
                else _items_of_line(m.group("list"))
            )
        elif ";" in line:
            parts = [p for p in re.split(r"\s*;\s*", line) if p.strip()]
            if not all(looks_like_address(p) for p in parts):
                if not strong:
                    return None  # « budget ; planning ; recrutement »: a list, but nothing says map
                first = _items_of_line(parts[0])
                parts = (first[-1:] if first else []) + parts[1:]
            items = parts
        elif strong:
            items = _items_of_line(line)
        else:
            return None
    items = [_clean_item(i) for i in items]
    items = [i for i in items if i]
    if len(items) < 2:
        return None
    return items[:MAX_ITEMS]


def list_cue(text: str) -> bool:
    return _cue(text)


# ---------------------------------------------------------------- distance between two places

_A = r"(?P<a>[^?!\n]{2,80}?)"
_B = r"(?P<b>[^?!\n]{2,80}?)"
_ART = r"(?:la\s+|le\s+|les\s+|l'|the\s+)?"
_UNIT = r"(?:km|kms|kilom[eè]tres?|bornes|minutes|heures|temps|miles|kilometers|kilometres)"
_DIST = [
    # « (quelle est la) distance entre A et B », « le temps de trajet entre A et B »
    re.compile(
        r"^(?:quelle\s+est\s+la\s+|quel\s+est\s+le\s+|quelle\s+|la\s+|le\s+|what\s+is\s+the\s+|what's\s+the\s+|the\s+)?"
        r"(?:distance|temps\s+de\s+(?:trajet|route|parcours)|dur[ée]e\s+du\s+trajet|kilom[ée]trage|driving\s+distance)"
        r"\s+(?:entre|between|from)\s+" + _ART + _A + r"\s+(?:et|and|to|à|a)\s+" + _ART + _B + r"$",
        re.I,
    ),
    re.compile(
        r"^(?:quel\s+est\s+le\s+|le\s+)?temps\s+de\s+(?:trajet|route)\s+(?:de|du|depuis)\s+"
        + _ART
        + _A
        + r"\s+(?:à|a|au|jusqu'à|jusqu'au)\s+"
        + _ART
        + _B
        + r"$",
        re.I,
    ),  # fmt: skip
    # « (y a) combien de km entre A et B », « combien de km de A à B », « combien de temps pour aller de A à B »
    re.compile(
        r"^(?:il\s+y\s+a\s+|y\s+a\s+|ya\s+)?combien\s+de\s+" + _UNIT + r"\s+(?:y\s+a-t-il\s+|il\s+y\s+a\s+)?"
        r"(?:(?:pour\s+(?:aller|se\s+rendre|faire)|en\s+voiture|en\s+train|à\s+pied)\s+)?"
        r"(?:entre\s+"
        + _ART
        + _A
        + r"\s+et\s+"
        + _ART
        + _B
        + r"|(?:de|du|depuis|d')\s*"
        + _ART
        + r"(?P<a2>[^?!\n]{2,80}?)\s+(?:à|a|au|jusqu'à|jusqu'au|vers)\s+"
        + _ART
        + r"(?P<b2>[^?!\n]{2,80}?))$",
        re.I,
    ),  # fmt: skip
    # « c'est loin A de B », « c'est à combien (de km) A de B », « à quelle distance est A de B »
    re.compile(
        r"^(?:c'?\s?est|est-ce\s+que\s+c'est|c'est-il)\s+(?:loin|à\s+combien(?:\s+de\s+"
        + _UNIT
        + r")?)\s+"
        + r"(?!d'ici|d'?\s?ici)"
        + _ART
        + _A
        + r"\s+(?:de|du|des|d')\s*"
        + _ART
        + _B
        + r"$",
        re.I,
    ),
    re.compile(
        r"^(?:à|a)\s+quelle\s+distance\s+(?:est|se\s+trouve|sont)\s+"
        + _ART
        + _A
        + r"\s+(?:de|du|d')\s*"
        + _ART
        + _B
        + r"$",
        re.I,
    ),  # fmt: skip
    # « Nice est à combien de Cannes », « Versailles c'est loin de Paris ? »
    re.compile(
        r"^" + _ART + _A + r"\s+(?:est|c'est|c\s+est)\s+(?:loin|à\s+combien(?:\s+de\s+" + _UNIT + r")?)\s+"
        r"(?:de|du|d')\s*" + _ART + _B + r"$",
        re.I,
    ),
    # « Lyon Marseille c'est combien de km », « distance paris marseille »
    re.compile(
        r"^(?P<a>[^\W\d_][\w'-]+)\s+(?P<b>[^\W\d_][\w'-]+)\s+(?:c'est|ça\s+fait|ca\s+fait)\s+combien(?:\s+de\s+"
        + _UNIT
        + r")?$",
        re.I,
    ),  # fmt: skip
    re.compile(
        r"^(?:distance|km|kilom[eè]tres)\s+(?P<a>[^\W\d_][\w'-]+)\s+(?:-\s*|->\s*)?(?P<b>[^\W\d_][\w'-]+)$", re.I
    ),
    # English
    re.compile(r"^how\s+far\s+(?:is|are)\s+" + _ART + _A + r"\s+from\s+" + _ART + _B + r"$", re.I),
    re.compile(r"^how\s+far\s+(?:is\s+it\s+)?from\s+" + _ART + _A + r"\s+to\s+" + _ART + _B + r"$", re.I),
    re.compile(
        r"^how\s+(?:many|much)\s+(?:km|kms|kilometers|kilometres|miles|time)\s+(?:is\s+it\s+)?(?:from\s+"
        + _ART
        + _A
        + r"\s+to\s+"
        + _ART
        + _B
        + r"|between\s+"
        + _ART
        + r"(?P<a2>[^?!\n]{2,80}?)\s+and\s+"
        + _ART
        + r"(?P<b2>[^?!\n]{2,80}?))$",
        re.I,
    ),  # fmt: skip
]
_HERE = re.compile(r"^(?:c'?\s?est\s+loin\s+d'?\s?ici|is\s+it\s+far\s+from\s+here)\b", re.I)


_LANDMARK_START = re.compile(
    r"(?:tour|gare|place|mus[ée]e|ch[âa]teau|a[ée]roport|stade|parc|pont|cath[ée]drale|basilique|op[ée]ra|palais|"
    r"mairie|h[ôo]tel\s+de\s+ville|arc|jardin|port|quai|rue|avenue|boulevard|universit[ée]|campus)\b",
    re.I,
)
# « itinéraire gare de lyon tour eiffel »: two named places typed one after the other
_BARE2 = re.compile(r"^(?:itin[ée]raire|trajet|distance)\s+(?P<a>.+?)\s+(?:(?:->|[-–>→])\s*)?(?P<b>\S.+)$", re.I)


def distance(t: str) -> tuple[str, str] | str | None:
    """(a, b) for « distance between a and b » in ``t`` (normalised), 'here' for « c'est loin d'ici … », or None."""
    if _HERE.match(t):
        return "here"
    for rx in _DIST:
        m = rx.match(t)
        if m:
            g = m.groupdict()
            a, b = (g.get("a") or g.get("a2") or ""), (g.get("b") or g.get("b2") or "")
            a, b = a.strip(" ,"), b.strip(" ,")
            # « c'est loin la gare de Lyon de la tour Eiffel »: the second place is the one after « de la »
            cut = re.search(r"\s+(?:de\s+la|de\s+l'|du|de\s+le)\s+(?=\S)", b)
            if (
                cut
                and " de " in f" {b} "
                and re.search(r"\b(?:de|du|d')\s*$", t[: m.start("b")] if m.start("b") > 0 else "")
            ):
                a, b = f"{a} de {b[: cut.start()]}", b[cut.end() :]
            if a and b and a.lower() != b.lower() and "," not in a + b:
                return a, b
    m = _BARE2.match(t)
    if m:
        whole = f"{m.group('a')} {m.group('b')}"
        # split before the second landmark word: « gare de lyon | tour eiffel »
        for x in _LANDMARK_START.finditer(whole):
            if x.start() > 0:
                a, b = whole[: x.start()].strip(" ->–→"), whole[x.start() :]
                if _LANDMARK_START.match(a) and a and b:
                    return a, b
    return None


# ---------------------------------------------------------------- « autour de moi »

_ME = re.compile(
    r"\b(?:(?:autour|pr[eè]s|[àa]\s+c[ôo]t[ée]|pas\s+(?:trop\s+)?loin|[àa]\s+proximit[ée]|proches?|aux\s+alentours)\s+"
    r"(?:de\s+(?:moi|nous|chez\s+(?:moi|nous)|ma\s+position|l[àa]\s+o[uù]\s+je\s+suis)|d'ici)|"
    r"(?:du|dans\s+le)\s+coin|dans\s+mon\s+quartier|ici\s+m[êe]me|"
    r"near\s+(?:me|here|us|my\s+location)|nearby|around\s+(?:me|here)|close\s+(?:to\s+me|by))\b"
    r"|\b(?:la|le)\s+plus\s+proches?(?:\s+(?:d'ici|de\s+moi|de\s+chez\s+moi))?\s*[?!.]*$"
    r"|^(?:the\s+|a\s+)?(?:nearest|closest)\s+(?:[\w-]+\s*){1,3}[?!.]*$|\b(?:nearest|closest)\s*[?!.]*$",
    re.I,
)


def near_me(t: str) -> bool:
    """« une pharmacie autour de moi », « la boulangerie la plus proche », « coffee shops near me »."""
    return bool(_ME.search(t or ""))
