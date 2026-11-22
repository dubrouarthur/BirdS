"""Deterministic reading of the user's OWN words: does this request ask for places, a company or a conversion?

Bird S 4B was never trained on find_places / find_company / convert_currency. So the harness does the work: when
a parser below is confident it returns the tool call itself (``Intent.args``), which the agent runs before the
first generation ("prefill", tagged "automatic" in the UI); when it only sees a hint it returns ``args=None`` and
the tool is merely offered. Pure functions, no I/O: see tests/test_intents.py.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class Intent:
    tool: str  # "find_places" | "find_company" | "convert_currency"
    args: dict | None  # None: offer the tool, do not call it
    keep_web: bool = True  # False: web_search / read_page withdrawn for this turn
    mode: str = ""  # places: near | route | where | list | address


# ---------------------------------------------------------------- normalisation

_POLITE = re.compile(r"\b(?:s'il te pla[iî]t|s'il vous pla[iî]t|stp|svp|please|merci)\b", re.I)
_LEAD = re.compile(
    r"^(?:(?:est-ce que |pourrais-tu |peux-tu |pouvez-vous |tu peux |can you |could you )?"
    r"(?:montre(?:-moi)?|affiche(?:-moi)?|donne(?:-moi)?|trouve(?:-moi)?|cherche(?:-moi)?|indique(?:-moi)?|"
    r"liste(?:-moi)?|propose(?:-moi)?|conseille(?:-moi)?|recommande(?:-moi)?|je cherche|"
    r"show(?: me)?|find(?: me)?|give me|tell me|list|recommend|suggest)\b[\s,:]*)",
    re.I,
)


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").replace("’", "'")
    t = _POLITE.sub(" ", t)
    t = " ".join(t.split()).strip(" ?!.,;:")
    for _ in range(2):
        t = _LEAD.sub("", t).strip(" ?!.,;:")
    return t


# ---------------------------------------------------------------- places

# surface form (regex) -> Nominatim keyword
KINDS: list[tuple[str, str]] = [
    (r"restaurants?|restos?", "restaurant"),
    (r"caf[ée]s?|coffee shops?", "cafe"),
    (r"bars?|pubs?", "bar"),
    (r"h[ôo]tels?", "hotel"),
    (r"boulangeries?|bakery|bakeries", "bakery"),
    (r"pharmacies?|pharmacy", "pharmacy"),
    (r"parkings?|car parks?", "parking"),
    (r"banques?|banks?", "bank"),
    (r"distributeurs?(?: de billets)?|dab|atms?|cash machines?", "atm"),
    (r"supermarch[ée]s?|supermarkets?", "supermarket"),
    (r"stations?[- ]service|gas stations?|petrol stations?", "fuel"),
    (r"bornes? de recharge|charging stations?", "charging station"),
    (r"coworkings?|espaces? de coworking", "coworking"),
    (r"salles? de r[ée]union|meeting rooms?", "conference centre"),
    (r"bureaux? de poste|postes?|post offices?", "post office"),
    (r"gares?|train stations?", "train station"),
    (r"stations? de m[ée]tro|m[ée]tros?|subway stations?", "subway station"),
    (r"h[ôo]pitaux|h[ôo]pital|hospitals?", "hospital"),
    (r"m[ée]decins?|doctors?", "doctors"),
    (r"imprimeries?|copy ?shops?|print shops?", "copyshop"),
    (r"librairies?|bookshops?|bookstores?", "bookshop"),
    (r"mus[ée]es?|museums?", "museum"),
    (r"cin[ée]mas?|cinemas?", "cinema"),
    (r"salles? de sport|gyms?", "fitness centre"),
    (r"cr[èe]ches?|nurseries", "kindergarten"),
    (r"[ée]coles?|schools?", "school"),
    (r"brasseries?", "restaurant"),
    (r"pizzerias?", "pizza"),
    (r"fleuristes?|florists?", "florist"),
    (r"laveries?|laundrettes?", "laundry"),
]
_KIND = "(?P<kind>" + "|".join(f"(?:{k})" for k, _ in KINDS) + ")"
_NAME = r"(?P<{}>[^?!\n]{{2,80}})"

_NEAR_WORDS = (
    r"(?:près\s+d(?:e\s+|u\s+|es\s+|')|pres\s+d(?:e\s+|u\s+|es\s+|')|à\s+côté\s+d(?:e\s+|u\s+|es\s+|')|"
    r"a\s+cote\s+d(?:e\s+|u\s+|')|autour\s+d(?:e\s+|u\s+|es\s+|')|proches?\s+d(?:e\s+|u\s+|es\s+|')|"
    r"aux\s+alentours\s+d(?:e\s+|u\s+|es\s+|')|dans\s+le\s+quartier\s+d(?:e\s+|u\s+|es\s+|')|vers\s+|"
    r"near\s+|around\s+|close\s+to\s+|next\s+to\s+|by\s+)"
)
_ART = r"(?:la\s+|le\s+|l'|les\s+|the\s+)?"
_RX_NEAR = re.compile(
    r"(?:^|\b)(?:des\s+|les\s+|un\s+|une\s+|quelques\s+|bons?\s+|meilleurs?\s+|good\s+|some\s+|a\s+|the\s+)?"
    + _KIND
    + r"(?:\s+\w+){0,2}?\s+"
    + _NEAR_WORDS
    + _ART
    + _NAME.format("near"),
    re.I,
)
_RX_ROUTE = re.compile(
    r"(?:itin[ée]raire|trajet|comment\s+(?:aller|se\s+rendre)|directions?|route|how\s+(?:do\s+i\s+|to\s+)?get)"
    r"\s+(?:de\s+|du\s+|depuis\s+|from\s+)" + _ART + r"(?P<a>[^?!\n]{2,80}?)\s+(?:à\s+|a\s+|au\s+|jusqu'à\s+|"
    r"jusqu'au\s+|vers\s+|to\s+)" + _ART + _NAME.format("b"),
    re.I,
)
_RX_ROUTE1 = re.compile(
    r"(?:itin[ée]raire|trajet|comment\s+(?:aller|se\s+rendre)|directions?|how\s+(?:do\s+i\s+|to\s+)?get)"
    r"\s+(?:à\s+|au\s+|aux\s+|vers\s+|jusqu'à\s+|jusqu'au\s+|pour\s+(?:aller\s+(?:à\s+|au\s+))?|to\s+)"
    + _ART
    + _NAME.format("b"),
    re.I,
)
_RX_WHERE = re.compile(
    r"^(?:o[uù]\s+(?:se\s+trouve(?:nt)?|se\s+situe(?:nt)?|est|sont)|c'est\s+o[uù]|"
    r"(?:quelle\s+est\s+)?l?'?adresse\s+(?:de\s+|du\s+|des\s+|d')|localise(?:-moi)?|situe(?:-moi)?|"
    r"(?:une\s+)?carte\s+(?:de\s+|du\s+|des\s+|d')|(?:un\s+)?plan\s+(?:d'accès\s+)?(?:de\s+|du\s+|d'|des\s+)|"
    r"where(?:\s+is|'s|\s+are)|(?:the\s+)?address\s+of|(?:a\s+)?map\s+of|locate)(?:\s+|(?<=[\s']))"
    + _ART
    + _NAME.format("q"),
    re.I,
)
_LIST_NOUNS = (
    r"(?:sites|adresses|lieux|agences|bureaux|magasins|boutiques|villes|implantations|entrepôts|entrepots|"
    r"locations|offices|stores|places|cities|sites)"
)
_RX_LIST = re.compile(
    r"(?:compare|situe|place|localise|carte|map|mets\s+sur\s+(?:une|la)\s+carte|show\s+on\s+a\s+map)\s+"
    r"(?:ces\s+|les\s+|nos\s+|these\s+|our\s+)?(?:\d+\s+|deux\s+|trois\s+|quatre\s+|cinq\s+|two\s+|three\s+|"
    r"four\s+|five\s+)?" + _LIST_NOUNS + r"(?:\s+[^:\n]{0,60})?\s*:\s*(?P<list>.+)",
    re.I,
)
_PLACE_WORD = re.compile(
    r"\b(?:adresse|carte|plan|map|où|ou se|itin[ée]raire|trajet|localise|situe|aller|venir|accès|acces|address|"
    r"where|directions?)\b",
    re.I,
)
_HINT = re.compile(
    r"\b(?:carte|plan|map|itin[ée]raire|adresse|lieux?|o[uù] (?:se trouve|est)|près d|à côté d|near|nearby|where)\b",
    re.I,
)
_NEVER = re.compile(
    r"\b(?:fichier|dossier|document|bouton|menu|onglet|r[ée]glages?|param[èe]tres?|options?|projets?|tickets?|bugs?|"
    r"erreurs?|code|fonction|variable|cellule|colonne|e-?mails?|mail|courriel|adresse (?:ip|mac|e-?mail|mail|url|web)|"
    r"url|lien|site web|website|page|slides?|diapos?|en est|on en est|file|folder|button|setting|project|"
    r"spreadsheet|ip address|email address|"
    r"carte (?:graphique|de visite|bancaire|bleue|cadeau|son|m[èe]re|sim|vitale|grise|de fidélité)|"
    r"plan (?:d'action|de formation|de charge|comptable|marketing|projet|de financement|social|de table|"
    r"de travail|de communication|de continuit[ée])|business plan|action plan|graphics card|credit card)\b",
    re.I,
)
_HOWTO = re.compile(
    r"^\s*(?:comment (?:faire|ajouter|cr[ée]er|changer|modifier|ins[ée]rer)|how (?:do|can|to) "
    r"(?:i |you )?(?:add|create|change|insert|make))\b",
    re.I,
)


_DEICTIC = re.compile(
    r"(?:là|la|ici|là-bas|here|there|it|chez (?:lui|elle|eux|moi|nous)|cet endroit|ce lieu|cette adresse|"
    r"this place|that place)",
    re.I,
)


def _kind_of(word: str) -> str:
    for rx, key in KINDS:
        if re.fullmatch(rx, word.strip(), re.I):
            return key
    return ""


def _clean_name(text: str) -> str:
    t = re.split(
        r"\s+(?:et|and|puis|then|pour|for|avec|with)\s+(?:me\s+|moi\s+)?(?:fais|fait|donne|dis|"
        r"pr[ée]pare|écris|ecris|envoie|make|give|tell|write|send)\b",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    t = re.split(r"[?!.;\n]|\s+[-–—]\s+|,\s+(?:et|and|fais|donne|make|give)\b", t, maxsplit=1)[0]
    return " ".join(t.split()).strip(" ,:'\"")


def _ok(name: str) -> bool:
    return 2 <= len(name) <= 80 and not _NEVER.search(name)


def places(text: str, lang: str = "fr") -> Intent | None:
    raw = " ".join((text or "").split())
    if not raw or _NEVER.search(raw) or _HOWTO.search(raw):
        return None
    t = normalise(raw)
    m = _RX_LIST.search(t)
    if m:
        items = [
            i.strip(" .") for i in re.split(r"[,;\n]|\s+et\s+|\s+and\s+|\s+-\s+", m.group("list")) if i.strip(" .")
        ]
        items = [_clean_name(i) for i in items]
        items = [i for i in items if _ok(i)]
        if 2 <= len(items) <= 5:
            return Intent("find_places", {"query": " ; ".join(items)}, keep_web=True, mode="list")
    m = _RX_NEAR.search(t)
    if m:
        near = _clean_name(m.group("near"))
        kind = _kind_of(m.group("kind"))
        if kind and _DEICTIC.fullmatch(near):  # "près de là": the place is in the conversation, not in these words
            return Intent("find_places", None, keep_web=False)
        if kind and _ok(near):
            return Intent("find_places", {"query": kind, "near": near}, keep_web=False, mode="near")
    m = _RX_ROUTE.search(t)
    if m:
        a, b = _clean_name(m.group("a")), _clean_name(m.group("b"))
        if _ok(a) and _ok(b):
            return Intent("find_places", {"query": b, "near": a}, keep_web=False, mode="route")
    m = _RX_ROUTE1.search(t)
    if m:
        b = _clean_name(m.group("b"))
        if _ok(b):
            return Intent("find_places", {"query": b}, keep_web=False, mode="route")
    from birds.harness.geo import find_address

    addr = find_address(raw)  # a typed postal address wins over "où est ..." (BAN geocodes it exactly)
    if addr and _PLACE_WORD.search(raw):
        addr = re.sub(r"\s+(?:à|a|in)\s+(?=[A-ZÀ-Ý])", " ", addr)
        return Intent("find_places", {"query": addr}, keep_web=False, mode="address")
    m = _RX_WHERE.search(t)
    if m:
        q = _clean_name(m.group("q"))
        if _ok(q) and not re.fullmatch(r"(?:il|elle|ça|ca|it|they|là|la)", q, re.I):
            return Intent("find_places", {"query": q}, keep_web=False, mode="where")
    if _HINT.search(raw):
        return Intent("find_places", None, keep_web=True)
    return None


def split_near(query: str) -> tuple[str, str] | None:
    """'restaurants près de la gare de Lyon' -> ('restaurant', 'gare de Lyon'), for a model's call without near."""
    m = _RX_NEAR.search(normalise(query))
    if not m:
        return None
    kind, near = _kind_of(m.group("kind")), _clean_name(m.group("near"))
    return (kind, near) if kind and near else None


# ---------------------------------------------------------------- company


def luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


_SIRET = re.compile(r"(?<!\d)(\d{3}[  ]?\d{3}[  ]?\d{3}[  ]?\d{5})(?!\d)")
_SIREN = re.compile(r"(?<!\d)(\d{3}[  ]?\d{3}[  ]?\d{3})(?![\d])")
_SIREN_WORD = re.compile(r"\b(?:siren|siret|n° d'entreprise|num[ée]ro d'entreprise|registre|rcs)\b", re.I)
_COMPANY_ASK = re.compile(
    r"(?i:fiche|infos?|informations|renseignements|siren|siret|kbis|coordonn[ée]es|adresse|si[èe]ge|qui est|"
    r"c'est quoi|what is|about|tout sur|details? (?:on|of)|record|profile|look up|lookup)\s+(?:de\s+|sur\s+|du\s+|de la\s+|de l'|of\s+|on\s+)?"
    r"(?:la soci[ée]t[ée]|l'entreprise|la bo[iî]te|notre client|notre fournisseur|le client|le fournisseur|"
    r"the company|our client|our supplier|the supplier|the client)\s+"
    r"(?P<name>[A-Z0-9À-Ý][\w&'.\- ]{1,60})"
)
_COMPANY_HINT = re.compile(
    r"\b(?:soci[ée]t[ée]|entreprise|siren|siret|kbis|raison sociale|fournisseur|company register)\b", re.I
)


def company_id(text: str) -> str:
    """A Luhn-valid SIRET (14 digits) or SIREN (9 digits) written in ``text``, digits only, or ''."""
    for rx in (_SIRET, _SIREN):
        for m in rx.finditer(text or ""):
            d = re.sub(r"\D", "", m.group(1))
            if luhn(d):
                return d
    return ""


def company(text: str, lang: str = "fr") -> Intent | None:
    raw = " ".join((text or "").replace("’", "'").split())
    if not raw or _HOWTO.search(raw):
        return None
    ident = company_id(raw)
    if ident and (_SIREN_WORD.search(raw) or _COMPANY_HINT.search(raw) or len(raw) < 40):
        return Intent("find_company", {"name": ident})
    m = _COMPANY_ASK.search(raw)
    if m:
        name = re.split(r"[?!.,;:]|\s+(?:et|and|pour|for|à|a|en|in)\s+", m.group("name"), maxsplit=1)[0].strip(" '")
        if 2 <= len(name) <= 60:
            return Intent("find_company", {"name": name})
    if _COMPANY_HINT.search(raw):
        return Intent("find_company", None)
    return None


# ---------------------------------------------------------------- currencies

CURRENCIES = (
    "EUR USD JPY BGN CZK DKK GBP HUF PLN RON SEK CHF ISK NOK TRY AUD BRL CAD CNY HKD IDR ILS INR KRW MXN MYR NZD "
    "PHP SGD THB ZAR"
).split()
_CUR_WORDS: list[tuple[str, str]] = [
    (r"€|euros?|eur", "EUR"),
    (r"\$|us\$|dollars?\s+(?:am[ée]ricains?|us)|dollars? us|us dollars?|dollars?|usd", "USD"),
    (r"£|livres?\s+sterling|livres?|pounds?\s+sterling|pounds?|sterling|gbp", "GBP"),
    (r"¥|yens?|jpy", "JPY"),
    (r"francs?\s+suisses?|swiss\s+francs?|chf", "CHF"),
    (r"yuans?|renminbi|cny|rmb", "CNY"),
    (r"couronnes?\s+su[ée]doises?|swedish\s+kron(?:a|or)|sek", "SEK"),
    (r"couronnes?\s+danoises?|danish\s+kron(?:e|er)|dkk", "DKK"),
    (r"couronnes?\s+norv[ée]giennes?|norwegian\s+kron(?:e|er)|nok", "NOK"),
    (r"couronnes?\s+tch[èe]ques?|czech\s+korun(?:a|y)|czk", "CZK"),
    (r"zlotys?|pln", "PLN"),
    (r"dollars?\s+canadiens?|canadian\s+dollars?|cad", "CAD"),
    (r"dollars?\s+australiens?|australian\s+dollars?|aud", "AUD"),
    (r"roupies?|rupees?|inr", "INR"),
    (r"r[ée]als?\s+br[ée]siliens?|reais|brl", "BRL"),
    (r"forints?|huf", "HUF"),
    (r"livres?\s+turques?|turkish\s+liras?|lires?\s+turques?|try", "TRY"),
]
_CUR = "(?:" + "|".join(w for w, _ in _CUR_WORDS) + "|" + "|".join(CURRENCIES) + ")"
_AMT = r"(?P<amt>\d[\d   .,]*(?:\s*(?:k|m|md|mds|million|millions|milliard|milliards|billion))?)"
_RX_FX = [
    re.compile(_AMT + r"\s*(?P<from>" + _CUR + r")\s+(?:en|in|to|into|vers|→|->)\s+(?P<to>" + _CUR + r")\b", re.I),
    re.compile(r"(?P<from>[€$£¥])\s*" + _AMT + r"\s+(?:en|in|to|into)\s+(?P<to>" + _CUR + r")\b", re.I),
    re.compile(
        r"(?:combien (?:vaut|valent|font|fait)|how much is|convertis(?:sez)?|convert)\s+"
        + _AMT
        + r"?\s*(?P<from>"
        + _CUR
        + r")\s+(?:en|in|to|into)\s+(?P<to>"
        + _CUR
        + r")\b",
        re.I,
    ),
    re.compile(
        r"(?:taux de change|cours|exchange rate)\s+(?:de l'|du |de |entre l'|entre le |entre |of |between |for )?"
        r"(?:the )?(?P<from>"
        + _CUR
        + r")\s*(?:et |en |contre |/|vs |and |to |against )?\s*(?:l'|le |la |the )?(?P<to>"
        + _CUR
        + r")\b",
        re.I,
    ),
    re.compile(r"\b(?P<from>[A-Z]{3})\s*/\s*(?P<to>[A-Z]{3})\b"),
]
_FX_HINT = re.compile(r"\b(?:taux de change|exchange rate|convertis|convert)\b", re.I)
_FX_KEEP_WEB = re.compile(
    r"\b(?:historique|[ée]volution|depuis|pr[ée]vision|forecast|history|trend|news|actualit)", re.I
)


def currency_code(word: str) -> str:
    w = " ".join((word or "").strip().lower().split())
    if w.upper() in CURRENCIES:
        return w.upper()
    for rx, code in _CUR_WORDS:
        if re.fullmatch(rx, w, re.I):
            return code
    return ""


def parse_amount(text: str) -> float | None:
    """'1 200' -> 1200, '1,5 M' -> 1500000, '12.50' -> 12.5, '1.200,50' -> 1200.5."""
    s = (text or "").strip().lower().replace(" ", " ").replace(" ", " ")
    mult = 1.0
    m = re.search(r"\s*(k|md|mds|milliards?|billion|m|millions?)$", s)
    if m:
        mult = {"k": 1e3, "m": 1e6, "million": 1e6, "millions": 1e6}.get(m.group(1), 1e9)
        s = s[: m.start()]
    s = s.replace(" ", "")
    if not s or not re.fullmatch(r"\d[\d.,]*", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 and head else s.replace(",", ".")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.rpartition(".")[2]) == 3 and mult == 1.0):
        s = s.replace(".", "")
    try:
        return float(s) * mult
    except ValueError:
        return None


def fx(text: str, lang: str = "fr") -> Intent | None:
    raw = " ".join((text or "").replace("’", "'").split())
    if not raw:
        return None
    keep = bool(_FX_KEEP_WEB.search(raw))
    for rx in _RX_FX:
        m = rx.search(raw)
        if not m:
            continue
        a, b = currency_code(m.group("from")), currency_code(m.group("to"))
        if not a or not b or a == b:
            continue
        amt = parse_amount(m.groupdict().get("amt") or "") if m.groupdict().get("amt") else None
        args = {"from": a, "to": b}
        if amt is not None:
            args["amount"] = amt
        return Intent("convert_currency", args, keep_web=keep)
    if _FX_HINT.search(raw):
        return Intent("convert_currency", None)
    return None


# ---------------------------------------------------------------- all together


def detect(text: str, attached: bool = False, lang: str = "fr") -> list[Intent]:
    """At most two intents, the prefilled one first. ``text`` = the user's own words (never attachment text)."""
    out: list[Intent] = []
    c = company(text, lang)
    p = places(text, lang)
    f = fx(text, lang)
    if attached:  # an address inside a document is never geocoded: only an explicit ask in the user's words
        p = p if p and p.args and p.mode != "address" else (Intent("find_places", None) if p else None)
    if c and c.args:  # the register's address is authoritative: company wins the prefill, places is offered
        out.append(c)
        if p:
            out.append(Intent("find_places", None, keep_web=True))
    elif f and f.args:
        out.append(f)
    elif p and p.args:
        out.append(p)
        if c:
            out.append(c)
    else:
        out += [i for i in (p, c, f) if i]
    return out[:2]
