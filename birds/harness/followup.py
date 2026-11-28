"""Short follow-ups that re-use the previous turn's rich result: « et à Lyon ? », « et demain ? », « et en livres ? ».

The previous turn's widget is read from the memo the SERVER wrote after it (``history.memo``: « contexte :
get_weather {"place": "Lyon"} »), never from the model's text: the web app strips any memo the model imitates
(``strip_memo``) and only a memo that ends the assistant message is read. Its arguments are checked again here
(known tool, known keys, plain short strings, ISO currency codes), then only the slots the user's own words name
are replaced. A follow-up is short and made only of slots and filler words: « et à Lyon, combien de salariés ? »
leaves words unexplained and is not one. Pure functions, no I/O: see tests/test_followup.py.
"""

from __future__ import annotations

import json
import re

from birds.harness import intents

TOOLS = ("get_weather", "find_places", "convert_currency", "find_company", "clock", "images")
LABEL = {"fr": "contexte", "en": "context"}
_KEYS = {
    "get_weather": ("place", "day"),
    "find_places": ("query", "near"),
    "convert_currency": ("from", "to", "amount"),
    "find_company": ("name",),
    "clock": ("cities", "mode"),
    "images": ("subject", "page", "size"),  # the pictures asked last turn (Agent.run's pictures), never a result
}
_CTX = re.compile(r"(?:^|\|)\s*(?:contexte|context) : (?P<tool>[a-z_]+) (?P<args>\{[^|]*\})\s*(?:$|\|)")
_SAFE = re.compile(r"[^\[\]|<>{}\\\n\r\t\"]{1,80}")


def _clean_args(tool: str, args: object) -> dict | None:
    """Only known keys with plain values: anything else and the context is dropped whole."""
    if tool not in _KEYS or not isinstance(args, dict) or set(args) - set(_KEYS[tool]):
        return None
    out: dict = {}
    for k, v in args.items():
        if k == "amount":
            if not isinstance(v, int | float) or isinstance(v, bool) or not 0 < v < 1e13:
                return None
            out[k] = v
        elif k in ("from", "to"):
            if v not in intents.CURRENCIES:
                return None
            out[k] = v
        elif k == "cities":
            if not isinstance(v, list) or not 1 <= len(v) <= 4 or not all(isinstance(c, str) and _SAFE.fullmatch(c)
                                                                        for c in v):  # fmt: skip
                return None
            out[k] = list(v)
        elif k == "mode":
            if v not in ("time", "offset", "slot"):
                return None
            out[k] = v
        elif k == "page":
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 20:
                return None
            if v:
                out[k] = v
        elif k == "size":
            if v != "large":
                return None
            out[k] = v
        else:
            if not isinstance(v, str) or not _SAFE.fullmatch(v):
                return None
            out[k] = v
    return out or None


def memo_part(context: dict | None, lang: str) -> str:
    """« contexte : get_weather {"place": "Lyon"} » for history.memo, or ''."""
    if not context or context.get("tool") not in TOOLS:
        return ""
    args = _clean_args(context["tool"], context.get("args"))
    if not args:
        return ""
    return f"{LABEL['en' if lang == 'en' else 'fr']} : {context['tool']} {json.dumps(args, ensure_ascii=False)}"


def context_of(steps, widgets=None, pictures=None) -> dict | None:
    """The rich result a follow-up can lean on: the pictures the harness searched (``pictures``, Run.pictures), the
    last successful widget tool call of the turn, else the world clock the harness computed. Arguments only (never
    a tool result)."""
    if isinstance(pictures, dict) and pictures.get("shown"):
        got = _clean_args("images", {k: pictures[k] for k in _KEYS["images"] if pictures.get(k) not in (None, "")})
        if got and got.get("subject"):
            return {"tool": "images", "args": got}
    for s in reversed(list(steps or [])):
        tool = getattr(s, "tool", None) or (s.get("tool") if isinstance(s, dict) else None)
        err = getattr(s, "error", None) if not isinstance(s, dict) else s.get("error")
        args = getattr(s, "arguments", None) if not isinstance(s, dict) else s.get("arguments")
        if tool in _KEYS and tool != "clock" and not err and isinstance(args, dict):
            keep = {k: v for k, v in args.items() if k in _KEYS[tool] and v not in (None, "")}
            got = _clean_args(tool, keep)
            if got:
                return {"tool": tool, "args": got}
    for w in reversed(list(widgets or [])):
        if isinstance(w, dict) and w.get("type") == "ask_place" and w.get("kind") in _KIND_KEYS:
            # « une pharmacie autour de moi » was answered with « près de quel lieu ? »: the reply is that place
            return {"tool": "find_places", "args": {"query": w["kind"]}}
        if isinstance(w, dict) and w.get("type") == "clock":
            names = [
                str(r.get("name") or "") for r in w.get("cities") or [] if isinstance(r, dict) and not r.get("user")
            ]
            got = _clean_args("clock", {"cities": names[:4], "mode": w.get("mode") or "time"})
            if got:
                return {"tool": "clock", "args": got}
    return None


def previous(history: list[dict] | None) -> dict | None:
    """The context of the LAST assistant message, read from the memo that ends it (or its ``memo`` field)."""
    last = next((m for m in reversed(history or []) if m.get("role") in ("assistant", "user")), None)
    if not last or last.get("role") != "assistant":
        return None
    for text in (last.get("memo"), last.get("content")):
        text = str(text or "").rstrip()
        start = max(text.rfind("[Mémo de ce tour —"), text.rfind("[Memo of this turn —"))
        if start < 0 or not text.endswith("]"):
            continue
        c = _CTX.search(text[start + 1 : -1].split("—", 1)[1])
        if not c:
            return None
        try:
            args = json.loads(c.group("args"))
        except ValueError:
            return None
        got = _clean_args(c.group("tool"), args)
        return {"tool": c.group("tool"), "args": got} if got else None
    return None


# ---------------------------------------------------------------- reading the follow-up

_LEAD = re.compile(
    r"^(?:(?:ok|okay|d'accord|merci|super|parfait|top|thanks|great|cool)[\s,!.]+)?"
    r"(?:et\s+(?:pour|sinon|si|avec|du\s+coup)?|and\s+(?:for|what\s+about|how\s+about|with|in|if)?|"
    r"(?:pareil|idem|m[êe]me\s+chose|la\s+m[êe]me)\s+(?:pour|avec|à|a|en)?|same\s+(?:thing\s+)?for|"
    r"what\s+about|how\s+about|sinon|plut[ôo]t|maintenant|now|aussi)\b\s*",
    re.I,
)
_FILL = frozenset(
    """à a au aux en in at for sur on de du des d' la le les l' the pour vers avec with alors plutôt plutot aussi
    sinon donc maintenant now too also instead then please stp svp merci ça ca quoi là-bas la-bas there là
    y fait il fera what how about pareil idem""".split()
)
_AROUND = re.compile(
    r"\b(?:autour(?:\s+d[eu']?)?|à\s+c[ôo]t[ée](?:\s+d[eu']?)?|pr[eè]s(?:\s+d[eu']?)?|pas\s+loin(?:\s+d[eu']?)?|"
    r"proches?(?:\s+d[eu']?)?|dans\s+le\s+coin|du\s+coin|à\s+proximit[ée](?:\s+d[eu']?)?|aux\s+alentours|"
    r"around(?:\s+there|\s+it)?|nearby|near\s+(?:there|it|by)|close\s+by|next\s+to\s+it|sur\s+place)",
    re.I,
)
_WX_WORD = re.compile(r"\b(?:la\s+)?(?:m[ée]t[ée]o|weather|forecast|temps|pr[ée]visions?)\b", re.I)
_KIND_ANY = re.compile(
    r"\b(?:(?:des|les|un|une|quelques|some|any|the|a)\s+)?(?:bons?\s+|good\s+)?" + intents._KIND + r"\b", re.I
)
_CUR_TO = re.compile(r"\b(?:en|in|to|into|vers)\s+(?P<to>" + intents._CUR + r")(?!\w)", re.I)
_AMOUNT = re.compile(r"(?<![\w.,])" + intents._AMT + r"(?:\s*(?P<cur>" + intents._CUR + r")(?!\w))?", re.I)
_CUR_ALONE = re.compile(r"^(?:les\s+|le\s+|la\s+|the\s+)?(?P<to>" + intents._CUR + r")$", re.I)


def _strip(text: str) -> str:
    t = " ".join(intents._POLITE.sub(" ", (text or "").replace("’", "'")).split()).strip(" ?!.,;:")
    for _ in range(2):
        t = _LEAD.sub("", t).strip(" ?!.,;:")
    return t


def _leftover(t: str) -> str:
    words = [w for w in re.split(r"\s+", t.strip(" ?!.,;:")) if w]
    while words and words[0].lower().strip(",") in _FILL:
        words.pop(0)
    while words and words[-1].lower().strip(",") in _FILL:
        words.pop()
    return " ".join(words).strip(" ,'")


def _named(place: str) -> bool:
    """A town or a named place, never a person, a document or an office notion."""
    if not place or len(place) > 60 or len(place.split()) > 4 or intents._NEVER.search(place):
        return False
    if intents._not_a_place(place) or all(w.lower() in intents.FIRST_NAMES for w in place.split()):
        return False
    if re.search(r"[\d,;:?!]", place) or all(w.lower() in _FILL for w in place.split()):
        return False
    # a proper name (« New York », « Aix-en-Provence », « Saint-Denis »), a known town typed in lowercase, or a
    # landmark of a named place (« gare de Lyon »): « Lyon combien de salariés » is none of them
    return bool(_PROPER.fullmatch(place)) or intents.known_place(place) or bool(
        intents._LANDMARK.match(place) and _PROPER.search(place) and len(place.split()) <= 4
        and re.fullmatch(r"[\wÀ-ÿ'-]+(?:\s+(?:de|du|des|d'|la|le|l')?\s*[A-ZÀ-Ý][\wÀ-ÿ'-]*)+", place)
    )


_PROPER = re.compile(r"[A-ZÀ-Ý][\wÀ-ÿ'-]*(?:\s+(?:(?:de|du|des|la|le|les|sur|en|d'|l'|of|the|upon)\s+)*[A-ZÀ-Ý][\wÀ-ÿ'-]*)*")


_KIND_KEYS = frozenset(k for _, k in intents.KINDS)


def _place_of(prev: dict) -> str:
    a = prev["args"]
    if prev["tool"] == "get_weather":
        return a.get("place", "")
    if prev["tool"] == "find_places":
        if a.get("near") and a.get("query", "").lower() in _KIND_KEYS:
            return a["near"]
        if a.get("near") or " ; " in a.get("query", "") or a.get("query", "").lower() in _KIND_KEYS:
            return ""  # a route, a list, or a kind with no place yet (« autour de moi »)
        return a.get("query", "")
    return ""


def resolve(text: str, prev: dict | None, lang: str = "fr") -> intents.Intent | None:
    """The call a short follow-up asks for, given the previous turn's context, or None. For the world clock the
    Intent is ``clock`` with ``args = {"text": <a complete clock ask>}`` that the harness reads like the user's."""
    if not prev or prev.get("tool") not in TOOLS or prev.get("tool") == "images":
        return None  # pictures: ``pictures`` below
    raw = " ".join((text or "").split())
    if not raw or len(raw) > 80 or "\n" in (text or ""):
        return None
    t = _strip(raw)
    if not t or len(t.split()) > 7:
        return None
    tool, a = prev["tool"], dict(prev["args"])
    # slots in the user's words, each removed as it is read; whatever is left must be a place or nothing
    kind = ""
    # the reply to « près de quel lieu ? » (after « une pharmacie autour de moi ») is the place, whole: « à la gare
    # de Lyon » is not a search for stations
    asked = tool == "find_places" and not a.get("near") and a.get("query", "").lower() in _KIND_KEYS
    m = None if asked else _KIND_ANY.search(t)
    if m:
        kind = intents._kind_of(m.group("kind"))
        t = (t[: m.start()] + " " + t[m.end() :]).strip()
    around = bool(_AROUND.search(t))
    t = _AROUND.sub(" ", t)
    wx = bool(_WX_WORD.search(t))
    t = _WX_WORD.sub(" ", t)
    day = ""
    d = intents._WX_DAY.search(t)
    if d:
        day = " ".join(d.group(0).split())
        t = (t[: d.start()] + " " + t[d.end() :]).strip()
    to = amount = cur = ""
    c = _CUR_TO.search(t)
    if c:
        to = intents.currency_code(c.group("to"))
        t = (t[: c.start()] + " " + t[c.end() :]).strip()
    elif tool == "convert_currency" and _CUR_ALONE.match(_leftover(t)):
        to = intents.currency_code(_CUR_ALONE.match(_leftover(t)).group("to"))
        t = ""
    n = _AMOUNT.search(t) if tool == "convert_currency" else None
    if n:
        amount = intents.parse_amount(n.group("amt"))
        cur = intents.currency_code(n.group("cur") or "")
        t = (t[: n.start()] + " " + t[n.end() :]).strip()
    place = _leftover(t)
    if place and not _named(place):
        return None  # words that are not slots: an ordinary request, never a follow-up
    if tool == "convert_currency":
        if kind or day or wx or around or place or not (to or amount):
            return None
        args = dict(a)
        if amount:
            args["amount"] = amount
        if cur:
            args["from"] = cur
        if to:
            args["to"] = to
        if args["from"] == args["to"]:
            args["to"] = a["from"] if a["from"] != args["from"] else ("EUR" if args["from"] != "EUR" else "USD")
        return intents.Intent("convert_currency", args, keep_web=False) if args != a else None
    if to or amount:
        return None
    if tool == "clock":
        if kind or day or wx or around or not place:
            return None
        cities = [c for c in a.get("cities", []) if c.lower() != place.lower()]
        if a.get("mode") == "slot":
            ask = f"créneau commun entre {', '.join(cities[:3])} et {place}" if cities else f"heure locale à {place}"
        elif a.get("mode") == "offset":
            ask = f"décalage horaire avec {place}"
        else:
            ask = f"quelle heure est-il à {place}"
        return intents.Intent("clock", {"text": ask}, keep_web=False)
    if tool == "find_company":
        if kind or day or wx or around or not place or intents.known_place(place) or not place[:1].isupper():
            return None
        return intents.Intent("find_company", {"name": place}, keep_web=False)
    where = place or _place_of(prev)
    if kind:  # « et des restaurants autour ? », « et les hôtels à Lyon ? »
        if day or wx or not where or (not place and not around and tool != "find_places"):
            return None
        return intents.Intent("find_places", {"query": kind, "near": where}, keep_web=False, mode="near")
    if tool == "get_weather" or wx:
        if around or not where or not (place or day or (wx and tool != "get_weather")):
            return None
        args = {"place": where}
        day = day or (a.get("day", "") if tool == "get_weather" and place else "")
        if day and not re.fullmatch(r"(?:aujourd'hui|today)", day, re.I):
            args["day"] = day
        return intents.Intent("get_weather", args, keep_web=False)
    # find_places: « et à Lyon ? » moves the same search; « et la tour Eiffel ? » looks up a new place
    if day or around or not place:
        return None
    if a.get("query", "").lower() in _KIND_KEYS:  # « et à Lyon ? » after « pharmacies près de … » or « … de moi »
        return intents.Intent("find_places", {"query": a["query"], "near": place}, keep_web=False, mode="near")
    if a.get("near") or " ; " in a.get("query", ""):
        return None  # a route or a list: « et à Lyon ? » is ambiguous
    return intents.Intent("find_places", {"query": place}, keep_web=False, mode="where")


# ---------------------------------------------------------------- « une image », « une autre », « en plus grand »
# A short message that asks for pictures without naming what of: the subject is the conversation's. These words are
# the parsers' hint and fallback; the router reads the same previous turn and decides (router.previous_summary).

_PIC = r"(?:photos?|photographies?|images?|illustrations?|pictures?|pics?|photographs?|visuels?)"
_PIC_ASK = re.compile(
    r"^(?:(?:et|ok|alors|du\s+coup|and|so)\s+)?(?:(?:est-ce\s+que\s+)?(?:tu\s+(?:as|aurais|peux|pourrais)|t'as|"
    r"vous\s+(?:avez|auriez|pouvez)|peux-tu|pourrais-tu|avez-vous|y\s+a-t-il|il\s+y\s+a|do\s+you\s+have|can\s+you|"
    r"could\s+you|got)\s+)?(?:me\s+)?(?:(?:montre[rz]?|affiche[rz]?|trouve[rz]?|donne[rz]?|envoie[rz]?|cherche[rz]?)"
    r"(?:[- ](?:moi|nous))?|show(?:\s+me)?|find(?:\s+me)?|send(?:\s+me)?|give(?:\s+me)?|see|voir)?\s*"
    r"(?:(?:une?|des|la|les|quelques|deux|trois|a|an|some|any|the|a\s+few)\s+)?(?:(?:belles?|jolies?|nice)\s+)?"
    r"(?:" + _PIC + r"(?:\s+(?:de\s+(?:lui|elle|[çc]a|cela)|of\s+(?:it|them|that)))?|en\s+images?|"
    r"(?:(?:à|a)\s+quoi\s+(?:il|elle|[çc]a|cela|ils|elles)\s+ressembl(?:e|ent))|"
    r"what\s+(?:it|they|that)\s+looks?\s+like|what\s+does\s+(?:it|that)\s+look\s+like)?$",
    re.I,
)
_PIC_MORE = re.compile(
    r"^(?:(?:et|ok|alors|and|so)\s+)?(?:(?:montre[rz]?|donne[rz]?|affiche[rz]?)(?:[- ]moi)?\s+|show\s+me\s+)?"
    r"(?:(?:une|un)\s+autre|d'autres|encore(?:\s+une?)?|plus|another(?:\s+one)?|more|other\s+ones|others|"
    r"la\s+suivante|les\s+suivantes|next)(?:\s+" + _PIC + r")?(?:\s+(?:encore|again|please|stp|svp))?$",
    re.I,
)
_PIC_LARGE = re.compile(
    r"^(?:(?:et|ok|alors|and|so)\s+)?(?:(?:montre[rz]?|affiche[rz]?|mets)(?:[- ](?:la|le|les|moi))*\s+|"
    r"(?:show|make)(?:\s+(?:it|me|them))?\s+)?(?:(?:en|in)\s+)?(?:plus\s+grande?s?|grande?\s+taille|grand|"
    r"agrandi[st]?(?:[- ](?:la|le|les))?|zoom(?:e[rz]?)?|bigger|larger|full[- ]size|full\s+screen|plein\s+[ée]cran)"
    r"(?:\s+(?:please|stp|svp))?$",
    re.I,
)
# « et de nuit ? », « et en hiver ? », « vue du ciel ? »: the same subject, with a qualifier the user names
_PIC_QUAL = re.compile(
    r"^(?:et\s+|and\s+)?(?P<q>(?:de|en|sous|au|vue?s?|depuis|pendant|la|le|at|in|from|by|during|under)\s+"
    r"[\wÀ-ÿ'-]+(?:\s+[\wÀ-ÿ'-]+){0,3})$",
    re.I,
)
# what the previous request was about, in the user's own words: « parle-moi du cheval tigré », « c'est quoi un
# okapi ? », « raconte-moi l'histoire du Mont-Saint-Michel », or a bare noun phrase (« le cheval tigré »)
_TOPIC_LEAD = re.compile(
    r"^(?:(?:bonjour|salut|hello|hi)[\s,!]+)?(?:(?:parle|raconte|dis|explique|pr[ée]sente|d[ée]cri[st])[- ](?:moi|nous)"
    r"(?:\s+(?:tout|un\s+peu|rapidement|en\s+bref))?(?:\s+(?:de|du|des|d'|sur|à\s+propos\s+d[eu']?))?|"
    r"(?:c'est\s+quoi|qu'est-ce\s+que\s+c'est\s+que|qu'est-ce\s+qu(?:e|')|qui\s+est|que\s+sais-tu\s+(?:de|du|des|sur))|"
    r"(?:tell\s+me\s+(?:about|more\s+about)|what\s+(?:is|are)|what's|who\s+(?:is|was)|explain|describe))\s*",
    re.I,
)
_TOPIC_HEAD = re.compile(
    r"^(?:(?:l'histoire|l'origine|les\s+origines|la\s+vie|le\s+r[ôo]le|the\s+history|the\s+origins?)\s+"
    r"(?:de|du|des|d'|of)\s*)",
    re.I,
)


def _ask_text(text: str) -> str:
    return " ".join(intents._POLITE.sub(" ", (text or "").replace("’", "'")).split()).strip(" ?!.,;:")


def topic_of(history: list[dict] | None) -> str:
    """The subject of the previous request, from the user's OWN words (never the model's text), or ''."""
    prev = [m for m in history or [] if m.get("role") == "user" and isinstance(m.get("content"), str)]
    if not prev:
        return ""
    raw = prev[-1]["content"].split("\n\n[", 1)[0]  # never an attachment note or an image transcription
    got = intents.images(raw)
    if got is not None:
        return str(got.args["query"])
    t = _ask_text(raw)
    if not t or len(t) > 160:
        return ""
    m = _TOPIC_LEAD.match(t)
    if m:
        t = t[m.end() :]
    elif len(t.split()) > 5:
        return ""  # a longer request that is not « parle-moi de X »: its subject is the router's to read
    t = _TOPIC_HEAD.sub("", t)
    t = re.sub(r"^(?:(?:la|le|les|une?|des|the|a|an)\s+|l')", "", t, flags=re.I).strip(" '\"")
    t = re.split(r"\s*(?:[?!.;:,]|\s(?:et|and|pour|for|en\s+\d|in\s+\d)\s)", t, maxsplit=1)[0].strip()
    if not (2 <= len(t) <= 60) or len(t.split()) > 6 or intents._IMG_NOT_SUBJECT.match(t):
        return ""
    if intents._NEVER.search(t) or intents._not_a_place(t) or intents._person(t) or intents._IMG_MAKE.search(t):
        return ""
    return t


def pictures(text: str, prev: dict | None, history: list[dict] | None, lang: str = "fr") -> intents.Intent | None:
    """The picture search a short follow-up asks for, or None. After pictures (``prev`` = images context):
    « une autre » (next page), « en plus grand » (large view), « et de nuit ? » (the subject, qualified). After any
    other answer: « une image », « tu as une photo ? », « montre-moi à quoi il ressemble » take the subject of the
    previous request (``topic_of``)."""
    raw = " ".join((text or "").split())
    if not raw or len(raw) > 80 or "\n" in (text or "") or intents._IMG_MAKE.search(raw):
        return None
    t = _ask_text(raw)
    if not t or len(t.split()) > 9:
        return None
    shown = prev.get("args") if prev and prev.get("tool") == "images" else None
    if shown:
        subject, page = shown["subject"], int(shown.get("page") or 0)
        if _PIC_MORE.match(t):
            return intents.Intent("web_search", {"query": subject}, keep_web=True, mode="images",
                                  view={"page": min(page + 1, 20)})  # fmt: skip
        if _PIC_LARGE.match(t):
            return intents.Intent("web_search", {"query": subject}, keep_web=True, mode="images",
                                  view={"page": page, "size": "large"})  # fmt: skip
        q = _PIC_QUAL.match(t)
        if q and not _named(_leftover(q.group("q"))) and len(subject) + len(q.group("q")) < 60:
            return intents.Intent("web_search", {"query": f"{subject} {q.group('q')}"}, keep_web=True, mode="images")
        if _PIC_ASK.match(t) and t.strip():
            return intents.Intent("web_search", {"query": subject}, keep_web=True, mode="images",
                                  view={"page": min(page + 1, 20)})  # fmt: skip
        return None
    if not _PIC_ASK.match(t) or not re.search(_PIC + r"|ressembl|look|\bmontre|\bshow|en\s+images?", t, re.I):
        return None
    subject = topic_of(history)
    return intents.Intent("web_search", {"query": subject}, keep_web=True, mode="images") if subject else None


# ---------------------------------------------------------------- « en camembert plutôt » after a chart

_CHART_TYPE = re.compile(
    r"^(?:(?:et|and|ok|plut[ôo]t|maintenant|now|instead|alors)\s+)*(?:(?:refais|refaites|remets|mets|passe|"
    r"transforme|redo|make|show|turn)(?:[- ](?:le|la|les|moi|it|that))?\s+)?(?:(?:le|la|ce|it|that|this)\s+)?"
    r"(?:(?:en|in|as|into|sous\s+forme\s+(?:de|d')|version|format)\s+)?(?:(?:un|une|a|an)\s+)?"
    r"(?:graphique\s+|chart\s+|graph\s+|diagramme\s+)?(?:en\s+)?"
    r"(?P<kind>courbes?|lignes?|barres?|b[âa]tons|camemberts?|secteurs|histogrammes?|donuts?|anneau|lines?|bars?|"
    r"pies?|columns?|colonnes)(?:\s+(?:chart|graph))?(?:\s+(?:plut[ôo]t|instead|alors|maintenant|now|stp|svp|"
    r"please|merci))*$",
    re.I,
)


def chart_retype(text: str) -> bool:
    """« en camembert plutôt », « et en courbe ? », « plutôt en barres », « as a pie chart »: only a chart type."""
    t = " ".join(intents._POLITE.sub(" ", (text or "").replace("’", "'")).split()).strip(" ?!.,;:")
    return bool(t) and len(t) <= 60 and bool(_CHART_TYPE.match(t))
