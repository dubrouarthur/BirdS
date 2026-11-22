"""Read a day and a time in the user's own words (FR/EN), for the event card. Pure: no I/O, see tests/test_when.py.

``parse(text, now, lang)`` returns None when no DAY is written (never guessed), else
``{"start", "end", "all_day", "matched", "assumptions"}`` with timezone-aware datetimes in ``now``'s zone.
Rules: a bare weekday is its next occurrence strictly after today ("lundi" said on a Monday = in 7 days); "this
Friday" may be today; a past date without a year is next year's; a start without an end lasts 1 hour (said in
``assumptions``); "12/03" is 12 March in French, December 3 in English.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

MONTHS = {
    "janvier": 1, "janv": 1, "février": 2, "fevrier": 2, "févr": 2, "fevr": 2, "fév": 2, "mars": 3, "avril": 4,
    "avr": 4, "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "oct": 10, "novembre": 11, "nov": 11, "décembre": 12, "decembre": 12, "déc": 12, "dec": 12,
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "october": 10,
    "november": 11, "december": 12,
}  # fmt: skip
DAYS = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}  # fmt: skip
_NUM_WORDS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "one": 1,
              "two": 2, "three": 3, "four": 4, "five": 5, "a": 1, "an": 1}  # fmt: skip

_MONTH = "(?P<mon>" + "|".join(sorted(map(re.escape, MONTHS), key=len, reverse=True)) + r")\.?"
_DAY = "(?P<wd>" + "|".join(DAYS) + ")"
_B = r"(?<![\w/])"

RX_ISO = re.compile(_B + r"(?P<y>20\d\d)-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")
RX_SLASH = re.compile(_B + r"(?P<a>\d{1,2})[/.](?P<b>\d{1,2})(?:[/.](?P<y>\d{2}|\d{4}))?(?![\w/])")
RX_DMY = re.compile(
    _B + r"(?:" + _DAY + r"\s+)?(?P<d>\d{1,2})(?:er|st|nd|rd|th)?(?:\s+of)?\s+" + _MONTH + r"(?:\s+(?P<y>20\d\d))?\b",
    re.I,
)
RX_MDY = re.compile(
    _B + r"(?:" + _DAY + r",?\s+)?" + _MONTH + r"\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(?P<y>20\d\d))?", re.I
)
RX_REL = re.compile(
    r"\b(?P<w>après-demain|apres-demain|aujourd'hui|aujourd’hui|demain|ce soir|ce midi|ce matin|"
    r"the day after tomorrow|tomorrow|today|tonight)\b",
    re.I,
)
RX_IN_DAYS = re.compile(r"\b(?:dans|in)\s+(?P<n>\d{1,2}|" + "|".join(_NUM_WORDS) + r")\s+(?:jours?|days?)\b", re.I)
RX_WEEKDAY = re.compile(
    r"\b(?P<this>this\s+|ce\s+)?(?P<next>next\s+)?" + _DAY + r"(?P<after>\s+prochain|\s+qui vient)?"
    r"(?P<eight>\s+en\s+huit)?(?P<week>\s+de la semaine prochaine|\s+next week)?\b",
    re.I,
)

_H = r"(?:[01]?\d|2[0-3])"
_T = (  # "3:30pm" must be read as 15:30: the am/pm form is tried first
    r"(?:(?P<{p}ah>1[0-2]|0?[1-9])(?::(?P<{p}am>[0-5]\d))?\s*(?P<{p}ap>am|pm|a\.m\.|p\.m\.)|(?P<{p}h>"
    + _H
    + r")\s*(?:h|:)\s*(?P<{p}m>[0-5]\d)?(?!\d)|(?P<{p}noon>midi|noon|minuit|midnight))"
)
RX_RANGE = re.compile(
    r"\b(?:de\s+|from\s+|entre\s+|between\s+)?"
    + _T.format(p="s")
    + r"\s*(?:-|–|à|a|to|until|jusqu'à|et|and)\s*"
    + _T.format(p="e"),
    re.I,
)
RX_TIME = re.compile(r"(?:\b(?:à|a|at|vers|around|dès|from)\s+)?\b" + _T.format(p="s"), re.I)
RX_AMPM_RANGE = re.compile(r"\b(?P<a>1[0-2]|0?[1-9])\s*(?:-|–|to)\s*(?P<b>1[0-2]|0?[1-9])\s*(?P<ap>am|pm)\b", re.I)
RX_DUR = re.compile(
    r"\b(?:pendant|durant|pour|during|for|lasting|d'une durée de)\s+"
    r"(?:(?P<h>\d{1,2})\s*h(?:eures?)?\s*(?P<hm>[0-5]\d)?|(?P<m>\d{1,3})\s*(?:min|minutes?|mn)\b|"
    r"(?P<hw>une|un|an|one|two|deux|1|2)\s+(?:heures?|hours?)|(?P<half>une demi-heure|half an hour|une demi heure)|"
    r"(?P<hd>\d{1,2})\s+(?:hours?|heures?))",
    re.I,
)
RX_DUR_BARE = re.compile(r"\b(?P<m>15|20|30|45|60|90)\s*(?:min|minutes?|mn)\b", re.I)


def _clock(m: re.Match, p: str) -> time | None:
    g = m.groupdict()
    if g.get(p + "noon"):
        return time(0, 0) if g[p + "noon"].lower() in ("minuit", "midnight") else time(12, 0)
    if g.get(p + "h") is not None:
        return time(int(g[p + "h"]), int(g.get(p + "m") or 0))
    if g.get(p + "ah") is not None:
        h = int(g[p + "ah"]) % 12 + (12 if g[p + "ap"].lower().startswith("p") else 0)
        return time(h, int(g.get(p + "am") or 0))
    return None


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _future(today: date, m: int, d: int, y: int | None, notes: list) -> date | None:
    if y is not None:
        return _safe_date(y if y > 99 else 2000 + y, m, d)
    got = _safe_date(today.year, m, d)
    if got is not None and got < today:
        got = _safe_date(today.year + 1, m, d)
    return got


def find_day(text: str, today: date, lang: str = "fr") -> tuple[date, str] | None:
    """(the day, the words used) or None."""
    t = text or ""
    notes: list = []
    m = RX_ISO.search(t)
    if m:
        got = _safe_date(int(m["y"]), int(m["m"]), int(m["d"]))
        if got:
            return got, m.group(0)
    m = RX_DMY.search(t)
    if m:
        got = _future(today, MONTHS[m["mon"].lower().rstrip(".")], int(m["d"]), int(m["y"]) if m["y"] else None, notes)
        if got:
            return got, m.group(0).strip()
    m = RX_MDY.search(t)
    if m:
        got = _future(today, MONTHS[m["mon"].lower().rstrip(".")], int(m["d"]), int(m["y"]) if m["y"] else None, notes)
        if got:
            return got, m.group(0).strip()
    m = RX_SLASH.search(t)
    if m:
        a, b = int(m["a"]), int(m["b"])
        d, mo = (b, a) if lang == "en" else (a, b)
        got = _future(today, mo, d, int(m["y"]) if m["y"] else None, notes) if 1 <= mo <= 12 else None
        if got:
            return got, m.group(0)
    m = RX_REL.search(t)
    if m:
        w = m["w"].lower().replace("’", "'")
        delta = 2 if w in ("après-demain", "apres-demain", "the day after tomorrow") else 1 if w in (
            "demain", "tomorrow") else 0  # fmt: skip
        return today + timedelta(days=delta), m.group(0)
    m = RX_IN_DAYS.search(t)
    if m:
        n = int(m["n"]) if m["n"].isdigit() else _NUM_WORDS[m["n"].lower()]
        return today + timedelta(days=n), m.group(0)
    m = RX_WEEKDAY.search(t)
    if m:
        wd = DAYS[m["wd"].lower()]
        ahead = (wd - today.weekday()) % 7
        if m["this"] and m["this"].strip().lower() in ("this", "ce"):
            pass  # this Friday: today when today is Friday
        elif ahead == 0:
            ahead = 7
        if m["eight"]:
            ahead += 7
        if m["week"]:  # "mardi de la semaine prochaine": the Tuesday of next week
            ahead = (7 - today.weekday()) + wd
        return today + timedelta(days=ahead), m.group(0).strip()
    return None


def parse(text: str, now: datetime, lang: str = "fr") -> dict | None:
    t = " ".join((text or "").replace("’", "'").split())
    found = find_day(t, now.date(), lang)
    if not found:
        return None
    day, day_words = found
    rest = t.replace(day_words, " ", 1)
    matched, notes = [day_words], []
    start = end = None
    dur = None
    m = RX_DUR.search(rest)
    if m:
        if m["half"]:
            dur = timedelta(minutes=30)
        elif m["m"]:
            dur = timedelta(minutes=int(m["m"]))
        elif m["h"]:
            dur = timedelta(hours=int(m["h"]), minutes=int(m["hm"] or 0))
        elif m["hd"]:
            dur = timedelta(hours=int(m["hd"]))
        elif m["hw"]:
            dur = timedelta(hours=_NUM_WORDS.get(m["hw"].lower(), None) or int(m["hw"]))
        matched.append(m.group(0))
        rest = rest.replace(m.group(0), " ", 1)
    else:
        m = RX_DUR_BARE.search(rest)
        if m:
            dur = timedelta(minutes=int(m["m"]))
            matched.append(m.group(0))
            rest = rest.replace(m.group(0), " ", 1)
    m = RX_AMPM_RANGE.search(rest)
    if m:
        pm = m["ap"].lower() == "pm"
        a, b = int(m["a"]) % 12 + 12 * pm, int(m["b"]) % 12 + 12 * pm
        start, end = time(a), time(b)
        matched.append(m.group(0))
    else:
        m = RX_RANGE.search(rest)
        if m and _clock(m, "s") is not None and _clock(m, "e") is not None:
            start, end = _clock(m, "s"), _clock(m, "e")
            matched.append(m.group(0).strip())
        else:
            m = RX_TIME.search(rest)
            if m:
                start = _clock(m, "s")
                matched.append(m.group(0).strip())
    if start is None:
        low = rest.lower()
        if re.search(r"\bd[ée]jeuner\b|\blunch\b|\bce midi\b", low + " " + day_words.lower()):
            start = None  # a lunch with no time stays a whole-day event: never guess noon
    tz = now.tzinfo
    if start is None:
        return {
            "start": datetime.combine(day, time(0, 0), tz),
            "end": datetime.combine(day + timedelta(days=1), time(0, 0), tz),
            "all_day": True,
            "matched": " ".join(sorted(matched, key=t.find)),
            "assumptions": [],
        }
    s_dt = datetime.combine(day, start, tz)
    if end is not None:
        e_dt = datetime.combine(day, end, tz)
        if e_dt <= s_dt:
            e_dt += timedelta(days=1) if end < start and start.hour >= 18 else timedelta(0)
        if e_dt <= s_dt:
            e_dt, end = s_dt + timedelta(hours=1), None
            notes.append("default_duration")
    elif dur is not None:
        e_dt = s_dt + dur
    else:
        e_dt = s_dt + timedelta(hours=1)
        notes.append("default_duration")
    # a wall-clock time keeps its meaning across a DST change: rebuild from the local date and time
    return {
        "start": s_dt,
        "end": datetime.combine(e_dt.date(), e_dt.time(), tz),
        "all_day": False,
        "matched": " ".join(sorted((x for x in matched if x), key=t.find)),
        "assumptions": notes,
    }
# ---------------------------------------------------------------- is this an ask for a meeting/event?

EVENT_ASK = re.compile(
    r"\b(?:r[ée]unions?|rendez-vous|rdv|meeting|call|visio|visioconf[ée]rence|point|entretien|d[ée]jeuner|d[îi]ner|"
    r"webinaire|webinar|s[ée]minaire|formation|atelier|invitation|invite|planifie[rz]?|programme[rz]?|cale[rz]?|"
    r"organise[rz]?|schedule|book|set up a)\b",
    re.I,
)
_HOWTO = re.compile(
    r"^\s*(?:comment|how (?:do|can|to)|est-ce qu'on peut|peut-on|quelle est la (?:meilleure )?fa[çc]on)\b", re.I
)
_WEAK = {"point", "formation", "programme", "programmer", "invitation", "invite", "cale", "caler", "book", "call"}
_NOT_EVENT = re.compile(r"\b(?:actualit\w*|nouvelles|news|cherche\w*|recherche\w*|r[ée]sume\w*|summari[sz]e)\b", re.I)


def event_words(text: str) -> bool:
    """The words ask to set up a meeting or an event (not a how-to, not a search, not a summary)."""
    t = " ".join((text or "").split())
    return bool(t and EVENT_ASK.search(t) and not _HOWTO.search(t) and not _NOT_EVENT.search(t))


def event_ask(text: str, now: datetime, lang: str = "fr") -> dict | None:
    """``parse`` of an event ask, or None: no event word, no day, or a weak word ("point") with no time."""
    t = " ".join((text or "").split())
    if not event_words(t):
        return None
    got = parse(t, now, lang)
    weak = {m.group(0).lower() for m in EVENT_ASK.finditer(t)} <= _WEAK
    if got is not None and weak and got["all_day"]:
        return None  # "fais le point sur les ventes d'aujourd'hui": a weak word with no time is not a meeting
    return got
