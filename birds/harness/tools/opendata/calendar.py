"""work_calendar: public holidays and working days. France (and its overseas zones, Alsace-Moselle) from
calendrier.api.gouv.fr (DINUM, Licence Ouverte 2.0); other countries from Nager.Date (MIT, free public API).

Three answers from one tool: the holidays of a year or a month with the number of working days (jours ouvrés:
Monday to Friday, holidays excluded; jours ouvrables: Monday to Saturday), the weekday of a date and whether it is
a holiday, or a deadline N working days after a date. Every holiday comes from the provider's table; the counting
is plain calendar arithmetic done here, never by the model.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from birds.harness.guard import ToolError

from . import http

FR_URL = "https://calendrier.api.gouv.fr/jours-feries/{zone}/{year}.json"
FR_PAGE = "https://calendrier.api.gouv.fr/jours-feries/"
FR_LICENSE = ("Licence Ouverte 2.0", "https://www.etalab.gouv.fr/licence-ouverte-open-licence/")
NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{cc}"
NAGER_PAGE = "https://date.nager.at/"
NAGER_LICENSE = ("MIT", "https://github.com/nager/Nager.Date/blob/main/LICENSE.md")
MAX_ADD = 400  # working days added to a date (more than a year and a half)

FR_ZONES = {
    "metropole": ("France métropolitaine", "Metropolitan France"),
    "alsace-moselle": ("Alsace-Moselle", "Alsace-Moselle"),
    "guadeloupe": ("Guadeloupe", "Guadeloupe"),
    "guyane": ("Guyane", "French Guiana"),
    "la-reunion": ("La Réunion", "Réunion"),
    "martinique": ("Martinique", "Martinique"),
    "mayotte": ("Mayotte", "Mayotte"),
    "nouvelle-caledonie": ("Nouvelle-Calédonie", "New Caledonia"),
    "polynesie-francaise": ("Polynésie française", "French Polynesia"),
    "saint-barthelemy": ("Saint-Barthélemy", "Saint Barthélemy"),
    "saint-martin": ("Saint-Martin", "Saint Martin"),
    "saint-pierre-et-miquelon": ("Saint-Pierre-et-Miquelon", "Saint Pierre and Miquelon"),
    "wallis-et-futuna": ("Wallis-et-Futuna", "Wallis and Futuna"),
}
# words of the user -> calendrier zone (folded, no accent)
_ZONE_WORDS = {
    "alsace": "alsace-moselle", "moselle": "alsace-moselle", "alsace-moselle": "alsace-moselle",
    "alsace moselle": "alsace-moselle", "guadeloupe": "guadeloupe", "guyane": "guyane",
    "french guiana": "guyane", "reunion": "la-reunion", "la reunion": "la-reunion", "martinique": "martinique",
    "mayotte": "mayotte", "nouvelle-caledonie": "nouvelle-caledonie", "nouvelle caledonie": "nouvelle-caledonie",
    "new caledonia": "nouvelle-caledonie", "polynesie": "polynesie-francaise", "tahiti": "polynesie-francaise",
    "saint-barthelemy": "saint-barthelemy", "saint-pierre-et-miquelon": "saint-pierre-et-miquelon",
    "wallis": "wallis-et-futuna", "metropole": "metropole", "france": "metropole", "france metropolitaine": "metropole",
}  # fmt: skip
# Nager.Date countries Bird names (FR, EN): ISO 3166-1 alpha-2
COUNTRIES = {
    "DE": ("Allemagne", "Germany", ("allemagne", "germany", "allemand", "allemands")),
    "BE": ("Belgique", "Belgium", ("belgique", "belgium", "belge", "belges")),
    "ES": ("Espagne", "Spain", ("espagne", "spain", "espagnol", "espagnols")),
    "IT": ("Italie", "Italy", ("italie", "italy", "italien", "italiens")),
    "CH": ("Suisse", "Switzerland", ("suisse", "switzerland")),
    "GB": ("Royaume-Uni", "United Kingdom", ("royaume-uni", "royaume uni", "united kingdom", "uk", "angleterre",
                                             "england", "grande-bretagne", "britain")),
    "PT": ("Portugal", "Portugal", ("portugal",)),
    "NL": ("Pays-Bas", "Netherlands", ("pays-bas", "pays bas", "netherlands", "hollande", "holland")),
    "LU": ("Luxembourg", "Luxembourg", ("luxembourg",)),
    "IE": ("Irlande", "Ireland", ("irlande", "ireland")),
    "AT": ("Autriche", "Austria", ("autriche", "austria")),
    "PL": ("Pologne", "Poland", ("pologne", "poland")),
    "SE": ("Suède", "Sweden", ("suede", "sweden")),
    "DK": ("Danemark", "Denmark", ("danemark", "denmark")),
    "NO": ("Norvège", "Norway", ("norvege", "norway")),
    "FI": ("Finlande", "Finland", ("finlande", "finland")),
    "CZ": ("Tchéquie", "Czechia", ("tchequie", "republique tcheque", "czechia", "czech republic")),
    "GR": ("Grèce", "Greece", ("grece", "greece")),
    "RO": ("Roumanie", "Romania", ("roumanie", "romania")),
    "HU": ("Hongrie", "Hungary", ("hongrie", "hungary")),
    "US": ("États-Unis", "United States", ("etats-unis", "etats unis", "usa", "united states", "us", "amerique")),
    "CA": ("Canada", "Canada", ("canada", "quebec")),
    "MA": ("Maroc", "Morocco", ("maroc", "morocco")),
    "TN": ("Tunisie", "Tunisia", ("tunisie", "tunisia")),
    "JP": ("Japon", "Japan", ("japon", "japan")),
    "CN": ("Chine", "China", ("chine", "china")),
    "BR": ("Brésil", "Brazil", ("bresil", "brazil")),
    "MX": ("Mexique", "Mexico", ("mexique", "mexico")),
    "AU": ("Australie", "Australia", ("australie", "australia")),
}  # fmt: skip
_COUNTRY_WORDS = {w: cc for cc, (_, _, words) in COUNTRIES.items() for w in words}

MONTHS_FR = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()
MONTHS_EN = "January February March April May June July August September October November December".split()
DOW_FR = "lundi mardi mercredi jeudi vendredi samedi dimanche".split()
DOW_EN = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
_MONTH_WORDS = {
    **{m: i for i, m in enumerate(("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
                                   "septembre", "octobre", "novembre", "decembre"), 1)},
    **{m.lower(): i for i, m in enumerate(MONTHS_EN, 1)},
    "janv": 1, "fev": 2, "fevr": 2, "avr": 4, "juil": 7, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
}  # fmt: skip


def fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("’", "'").split())


def today_paris() -> date:
    return datetime.now(ZoneInfo("Europe/Paris")).date()


# ---------------------------------------------------------------- zone and period


def zone_of(word: str) -> str:
    """'metropole', another calendrier zone, an ISO country code, or '' (unknown)."""
    w = fold(word).strip(" .?!")
    if not w:
        return "metropole"
    if w.upper() in COUNTRIES:
        return w.upper()
    if w.upper() == "FR":
        return "metropole"
    if w in FR_ZONES:
        return w
    if w in _ZONE_WORDS:
        return _ZONE_WORDS[w]
    if w in _COUNTRY_WORDS:
        return _COUNTRY_WORDS[w]
    w2 = re.sub(r"^(?:en|au|aux|a|in|the|l'|la|le|les)\s+", "", w)
    return _ZONE_WORDS.get(w2) or _COUNTRY_WORDS.get(w2, "")


def zone_label(zone: str, lang: str) -> str:
    if zone in FR_ZONES:
        return FR_ZONES[zone][0 if lang == "fr" else 1]
    c = COUNTRIES.get(zone)
    return (c[0] if lang == "fr" else c[1]) if c else zone


_RX_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_RX_DMY = re.compile(r"^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?$")
_RX_WORDS = re.compile(r"^(?:le\s+|the\s+)?(?:(\d{1,2})(?:er|st|nd|rd|th)?\s+)?([a-z]{3,9})\.?(?:\s+(\d{4}))?$")
_RX_WORDS_EN = re.compile(r"^([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?$")


def parse_period(text: str, today: date) -> tuple[str, int, int | None, date | None]:
    """('year' | 'month' | 'day', year, month, day) from '2027', '2027-05', '2027-05-08', 'mai 2027', '8 mai',
    '20/04', 'May 8, 2027'. A day or month without a year is the next one to come (today counts). Raises
    ToolError when it cannot be read."""
    t = fold(text).strip(" .?!,")
    t = {"cette annee": str(today.year), "this year": str(today.year), "l'an prochain": str(today.year + 1),
         "l'annee prochaine": str(today.year + 1), "next year": str(today.year + 1),
         "ce mois-ci": f"{today.year}-{today.month}", "ce mois": f"{today.year}-{today.month}",
         "this month": f"{today.year}-{today.month}", "aujourd'hui": today.isoformat(),
         "today": today.isoformat(), "demain": (today + timedelta(days=1)).isoformat(),
         "tomorrow": (today + timedelta(days=1)).isoformat()}.get(t, t)  # fmt: skip
    if t in ("le mois prochain", "mois prochain", "next month"):
        m = today.month % 12 + 1
        t = f"{today.year + (today.month == 12)}-{m}"
    if not t:
        return "year", today.year, None, None
    m = _RX_ISO.match(t)
    if m:
        y, mo, d = int(m.group(1)), m.group(2), m.group(3)
        try:
            if d:
                return "day", y, int(mo), date(y, int(mo), int(d))
            if mo:
                if not 1 <= int(mo) <= 12:
                    raise ValueError
                return "month", y, int(mo), None
        except ValueError:
            raise ToolError(f"not a valid date: {text}") from None
        return "year", y, None, None
    m = _RX_DMY.match(t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        return _day(d, mo, (int(y) + (2000 if len(y) == 2 else 0)) if y else None, today, text)
    m = _RX_WORDS.match(t) or _RX_WORDS_EN.match(t)
    if m:
        if _RX_WORDS.match(t):
            d, word, y = m.group(1), m.group(2), m.group(3)
        else:
            word, d, y = m.group(1), m.group(2), m.group(3)
        mo = _MONTH_WORDS.get(word)
        if mo:
            if d:
                return _day(int(d), mo, int(y) if y else None, today, text)
            year = int(y) if y else (today.year if mo >= today.month else today.year + 1)
            return "month", year, mo, None
    raise ToolError(f"cannot read the period '{text}': give a year (2027), a month (2027-05) or a date (2027-05-08)")


def _day(d: int, mo: int, y: int | None, today: date, text: str):
    try:
        if y is None:
            got = date(today.year, mo, d)
            if got < today:
                got = date(today.year + 1, mo, d)
        else:
            got = date(y, mo, d)
    except ValueError:
        raise ToolError(f"not a valid date: {text}") from None
    return "day", got.year, got.month, got


# ---------------------------------------------------------------- holiday tables


def holidays(ctx, zone: str, year: int) -> tuple[dict[str, dict], str]:
    """({iso date: {'name', 'regional'}}, source page) for a zone or country and a year."""
    if not 1950 <= year <= 2100:
        raise ToolError("year out of range (1950-2100)")
    if zone in FR_ZONES:
        data = http.get(ctx, FR_URL.format(zone=zone, year=year))
        if not isinstance(data, dict):
            raise ToolError("the holiday service returned no table")
        out = {str(k): {"name": http.clean(v, 60), "regional": False} for k, v in data.items()
               if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(k))}  # fmt: skip
        return out, FR_PAGE
    if zone not in COUNTRIES:
        raise ToolError(f"no holiday table for '{zone}'")
    data = http.get(ctx, NAGER_URL.format(year=year, cc=zone))
    if not isinstance(data, list):
        raise ToolError("the holiday service returned no table")
    out: dict[str, dict] = {}
    for h in data:
        if not isinstance(h, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(h.get("date", ""))):
            continue
        types = h.get("types") or []
        if types and "Public" not in types:  # bank-only or observance days are not days off for everyone
            continue
        regional = h.get("global") is False or bool(h.get("counties"))
        name = http.clean(h.get("localName") or h.get("name"), 60)
        en = http.clean(h.get("name"), 60)
        prev = out.get(h["date"])
        if prev and not prev["regional"]:
            continue
        out[h["date"]] = {"name": name, "en": en, "regional": regional,
                          "where": len(h.get("counties") or []) if regional else 0}  # fmt: skip
    return out, NAGER_PAGE


def workday(d: date, table: dict) -> bool:
    h = table.get(d.isoformat())
    return d.weekday() < 5 and not (h and not h["regional"])


def counts(first: date, last: date, table: dict) -> dict:
    """Days of [first, last]: jours ouvrés (Mon-Fri, holidays off), ouvrables (Mon-Sat, holidays off)."""
    ouvres = ouvrables = weekend = off = 0
    d = first
    while d <= last:
        h = table.get(d.isoformat())
        national = bool(h and not h["regional"])
        if d.weekday() < 5 and not national:
            ouvres += 1
        if d.weekday() < 6 and not national:
            ouvrables += 1
        if d.weekday() >= 5:
            weekend += 1
        elif national:
            off += 1
        d += timedelta(days=1)
    return {"days": (last - first).days + 1, "workdays": ouvres, "workable": ouvrables, "weekend": weekend,
            "holidays_weekday": off}  # fmt: skip


def add_workdays(start: date, n: int, table_for) -> tuple[date, list[dict]]:
    """The date ``n`` working days after ``start`` (start itself not counted) and the holidays skipped."""
    d, left, skipped = start, n, []
    while left > 0:
        d += timedelta(days=1)
        table = table_for(d.year)
        h = table.get(d.isoformat())
        if d.weekday() < 5 and h and not h["regional"]:
            skipped.append({"d": d.isoformat(), "name": h["name"]})
            continue
        if d.weekday() < 5:
            left -= 1
    return d, skipped


# ---------------------------------------------------------------- the tool


def _dname(d: date, lang: str) -> str:
    if lang == "fr":
        return f"{DOW_FR[d.weekday()]} {d.day}{'er' if d.day == 1 else ''} {MONTHS_FR[d.month - 1]} {d.year}"
    return f"{DOW_EN[d.weekday()]} {d.day} {MONTHS_EN[d.month - 1]} {d.year}"


def work_calendar(args: dict, ctx) -> str:
    lang = http.lang_of(ctx)
    today = getattr(ctx, "today", None) or today_paris()
    zone = zone_of(str(args.get("zone") or ""))
    if not zone:
        raise ToolError(f"no holiday table for '{args.get('zone')}': give a French zone or a country; say so")
    kind, year, month, day = parse_period(str(args.get("period") or ""), today)
    add = args.get("add_days")
    add = None if add in (None, "") else int(float(add))
    if add is not None and not 0 < add <= MAX_ADD:
        raise ToolError(f"add_days must be between 1 and {MAX_ADD}")
    cache: dict[int, dict] = {}

    def table_for(y: int) -> dict:
        if y not in cache:
            cache[y] = holidays(ctx, zone, y)[0]
        return cache[y]

    table, page = holidays(ctx, zone, year)
    cache[year] = table
    fr_side = zone in FR_ZONES
    src = {"label": "calendrier.api.gouv.fr" if fr_side else "Nager.Date", "url": page}
    lic = dict(zip(("label", "url"), FR_LICENSE if fr_side else NAGER_LICENSE, strict=True))
    n_src = http.cite(ctx, page)
    w: dict = {"type": "calendar", "v": 1, "zone": {"code": zone, "label": zone_label(zone, lang), "fr": fr_side},
               "year": year, "source": src, "license": lic}  # fmt: skip

    def rows(first: date, last: date) -> list[dict]:
        out = []
        for y in range(first.year, last.year + 1):
            for k, h in sorted(table_for(y).items()):
                d = date.fromisoformat(k)
                if first <= d <= last:
                    alt = h.get("en", "") if h.get("en") and h.get("en") != h["name"] else ""
                    out.append({"d": k, "name": h["name"], "alt": alt, "wd": d.weekday(), "regional": h["regional"]})
        return out[:40]

    if add is not None:
        start = day or (date(year, month, 1) if month else today)
        end, skipped = add_workdays(start, add, table_for)
        w |= {"mode": "deadline", "year": end.year, "month": end.month,
              "deadline": {"start": start.isoformat(), "days": add, "end": end.isoformat(), "skipped": skipped},
              "holidays": rows(date(end.year, end.month, 1), _month_end(end.year, end.month)),
              "counts": counts(start + timedelta(days=1), end, {**table_for(start.year), **table_for(end.year)})}  # fmt: skip
        sk = ", ".join(f"{s['name']} ({s['d']})" for s in skipped)
        facts = ((f"{add} jours ouvrés après le {_dname(start, lang)} : {_dname(end, lang)}"
                  + (f" (jours fériés sautés : {sk})" if sk else " (aucun jour férié sur la période)"))
                 if lang == "fr" else
                 (f"{add} working days after {_dname(start, lang)}: {_dname(end, lang)}"
                  + (f" (holidays skipped: {sk})" if sk else " (no holiday in between)")))  # fmt: skip
    elif kind == "day":
        h = table.get(day.isoformat())
        w |= {"mode": "day", "month": day.month,
              "day": {"d": day.isoformat(), "wd": day.weekday(), "holiday": h["name"] if h else None,
                      "regional": bool(h and h["regional"]), "workday": workday(day, table)},
              "holidays": rows(date(year, day.month, 1), _month_end(year, day.month))}  # fmt: skip
        if lang == "fr":
            facts = f"Le {day.day}{'er' if day.day == 1 else ''} {MONTHS_FR[day.month - 1]} {year} est un {DOW_FR[day.weekday()]}" + (
                f", jour férié ({h['name']}{', régional' if h['regional'] else ''})" if h else ", pas un jour férié") + (
                " ; jour ouvré" if workday(day, table) else " ; pas un jour ouvré")  # fmt: skip
        else:
            facts = f"{MONTHS_EN[day.month - 1]} {day.day}, {year} is a {DOW_EN[day.weekday()]}" + (
                f", a public holiday ({h.get('en') or h['name']}{', regional' if h['regional'] else ''})" if h else
                ", not a public holiday") + ("; a working day" if workday(day, table) else "; not a working day")  # fmt: skip
    elif kind == "month":
        first, last = date(year, month, 1), _month_end(year, month)
        c = counts(first, last, table)
        w |= {"mode": "month", "month": month, "holidays": rows(first, last), "counts": c}
        hs = "; ".join(f"{r['d']} {r['name']}" for r in w["holidays"]) or ("aucun" if lang == "fr" else "none")
        mname = (MONTHS_FR if lang == "fr" else MONTHS_EN)[month - 1]
        facts = (f"{mname} {year} ({w['zone']['label']}) : {c['workdays']} jours ouvrés (lundi-vendredi hors fériés), "
                 f"{c['workable']} jours ouvrables (lundi-samedi hors fériés) ; jours fériés : {hs}"
                 if lang == "fr" else
                 f"{mname} {year} ({w['zone']['label']}): {c['workdays']} working days (Monday-Friday, holidays "
                 f"excluded); public holidays: {hs}")  # fmt: skip
    else:
        first, last = date(year, 1, 1), date(year, 12, 31)
        c = counts(first, last, table)
        w |= {"mode": "year", "holidays": rows(first, last), "counts": c}
        hs = "; ".join(f"{r['d']} ({(DOW_FR if lang == 'fr' else DOW_EN)[r['wd']][:3]}.) {r['name']}"
                       + (" [régional]" if r["regional"] and lang == "fr" else " [regional]" if r["regional"] else "")
                       for r in w["holidays"])  # fmt: skip
        facts = (f"Jours fériés {year} ({w['zone']['label']}) : {hs}. {c['workdays']} jours ouvrés dans l'année"
                 if lang == "fr" else
                 f"Public holidays {year} ({w['zone']['label']}): {hs}. {c['workdays']} working days in the year")  # fmt: skip
    ctx.step_info = {"widget": w, "label": src["label"], "found": len(w.get("holidays", []))}
    if lang == "fr":
        return (
            f"{facts}. Source : {src['label']} [{n_src}]. Une fiche calendrier est affichée sous ta réponse : "
            "donne la réponse exacte en 1 ou 2 phrases, sans recopier toute la liste ni recalculer."
        )
    return (
        f"{facts}. Source: {src['label']} [{n_src}]. A calendar card is shown under your answer: give the exact "
        "answer in 1 or 2 sentences, without copying the whole list or computing again."
    )


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
