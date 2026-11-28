"""Rich result widgets of an answer: ``build_widgets`` (places, company, fx, weather, world clock, event) and
``enrich_sources`` (link previews). Widget data come from tool results (``Step.info["widget"]``), from the harness
(the world clock) or from the user's own words, never from the model's text: a hallucination cannot become a map
pin, a SIREN, a rate, a temperature or a time.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from birds.harness import geo, when

from . import (
    mapimg,
    opendata_widgets,  # open data
)

# cards the harness computes itself (birds.harness.calc, birds.harness.research), kept from ``extra`` as they are
HARNESS_CARDS = ("calc", "research", "graph", "timeline", "matrix", "checklist", "report", "figures", "proscons",
                 "glossary", "sourcecards")
MAX_WIDGET_BYTES = 8_000
MAX_LIST_BYTES = 16_000  # a map of up to 25 places (« montre sur une carte : a ; b ; c … »)
MAX_REPORT_BYTES = 16_000  # the full deep research report (birds.harness.research_report.REPORT_BYTES)
MAX_TOTAL_BYTES = 48_000  # a deep research: its card, graph, timeline, matrix and report
DEFAULT_TZ = "Europe/Paris"

_TITLE = re.compile(
    r"\b(?P<noun>r[ée]union|rdv|rendez-vous|call|point|d[ée]jeuner|d[îi]ner|meeting|visio|entretien|atelier|lunch|"
    r"dinner)\s+(?:avec|with)\s+(?P<who>[^,.;:!?\n]{2,40}?)(?=\s+(?:le|la|les|demain|aujourd|apr[eè]s(?:-demain)?|"
    r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|next|this|on|at|à|a|au|(?:de|du)\s+(?=\d)|dans|in|pour|for|et|"
    r"and|to|chez|sur|via|en|tomorrow|today|\d)\b|[,.;:!?\n]|$)",
    re.I,
)
_NOUN = re.compile(
    r"\b(r[ée]union|rendez-vous|rdv|meeting|call|visio|entretien|d[ée]jeuner|d[îi]ner|webinaire|webinar|"
    r"s[ée]minaire|formation|atelier|lunch|dinner)\b",
    re.I,
)
_LOC = re.compile(
    r"\b(?:r[ée]union|rdv|d[ée]jeuner|d[îi]ner|meeting|lunch|dinner|point|atelier|formation|s[ée]minaire)\b[^.;\n]{0,60}?"
    r"\b(?:chez|at|au|à la|à l')\s+(?P<loc>[A-ZÀ-Ý][^,.;:!?\n]{2,50}?)(?=\s+(?:le|à|a|de|à\s+\d|demain|lundi|mardi|"
    r"mercredi|jeudi|vendredi|et|and|on|at)\b|[,.;:!?\n]|$)"
)
_VISIO = re.compile(r"\b(?:visio\w*|teams|zoom|google meet|meet|call|webinaire|webinar)\b", re.I)
_TITLES_FR = {"rdv": "Rendez-vous", "rendez-vous": "Rendez-vous", "call": "Appel", "visio": "Visio",
              "lunch": "Déjeuner", "dinner": "Dîner", "meeting": "Réunion"}  # fmt: skip


def _size(w: dict) -> int:
    return len(json.dumps(w, ensure_ascii=False, separators=(",", ":")))


def tz_or_default(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name and len(name) <= 64 and re.fullmatch(r"[A-Za-z0-9_+\-/]+", name) else ZoneInfo(
            DEFAULT_TZ)  # fmt: skip
    except (ValueError, KeyError, OSError):
        return ZoneInfo(DEFAULT_TZ)


def _title(text: str, lang: str) -> str:
    m = _TITLE.search(text)
    if m:
        noun = m["noun"].lower()
        label = (_TITLES_FR.get(noun) or noun.capitalize()) if lang == "fr" else {
            "réunion": "Meeting", "reunion": "Meeting", "rdv": "Appointment", "rendez-vous": "Appointment",
            "déjeuner": "Lunch", "dejeuner": "Lunch", "dîner": "Dinner", "diner": "Dinner"}.get(noun, noun.capitalize())  # fmt: skip
        who = m["who"].strip()
        return f"{label} {'avec' if lang == 'fr' else 'with'} {who}"[:80]
    m = _NOUN.search(text)
    if m:
        noun = m.group(1).lower()
        return (_TITLES_FR.get(noun) or noun.capitalize()) if lang == "fr" else noun.capitalize()
    return "Réunion" if lang == "fr" else "Meeting"


def event_widget(text: str, now: datetime, lang: str, *, draft: dict | None = None, place: dict | None = None,
                 holidays=None) -> dict | None:  # fmt: skip
    """The event card for an ask such as « réunion avec Paul jeudi à 14h », or None (no day written: no card)."""
    words = " ".join((text or "").split())
    if not when.event_words(words):
        return None
    got = when.event_ask(words, now, lang)
    if got is None and draft and when.parse(words, now, lang) is None:
        # the draft's subject and body as a second source; the user's words win
        got = when.parse(f"{draft.get('subject', '')} {draft.get('body', '')}", now, lang)
    if got is None:
        return None
    location = ""
    if place:
        location = ", ".join(x for x in (place.get("name"), place.get("address")) if x)[:120]
    else:
        m = _LOC.search(words)
        if m:
            location = m["loc"].strip()[:80]
        elif _VISIO.search(words):
            location = "Visio" if lang == "fr" else "Video call"
    desc = ""
    if draft and draft.get("to"):
        to = draft["to"] if isinstance(draft["to"], str) else ", ".join(map(str, draft["to"]))
        desc = (("Participants : " if lang == "fr" else "Participants: ") + to)[:300]
    day = got["start"].date()
    warnings = []
    if day.weekday() >= 5:
        warnings.append({"kind": "weekend", "label": "samedi" if day.weekday() == 5 else "dimanche"}
                        if lang == "fr" else {"kind": "weekend", "label": day.strftime("%A")})  # fmt: skip
    table: dict[str, str] = {}
    if holidays:
        for year in sorted({day.year, day.year + 1 if day.month == 12 else day.year}):
            try:
                names = holidays(year) or {}
            except Exception:  # noqa: BLE001 - a missing holiday list only removes a warning
                names = {}
            table.update({str(k): str(v)[:60] for k, v in names.items() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(k))})
        if day.isoformat() in table:
            warnings.append({"kind": "holiday", "label": table[day.isoformat()], "date": day.isoformat()})
    for w in warnings:
        w.setdefault("date", day.isoformat())
    return {
        "type": "event",
        "v": 1,
        "title": _title(words, lang),
        "start": got["start"].isoformat(),
        "end": got["end"].isoformat(),
        "all_day": got["all_day"],
        "tz": str(now.tzinfo),
        "location": location,
        "description": desc,
        "assumptions": got["assumptions"],
        "warnings": warnings,
        "holidays": table,  # the card re-checks the day when the user changes it
        "matched": got["matched"][:120],
    }


def weather_hint(widgets: list[dict], ev: dict) -> dict | None:
    """One line for the event card when a forecast of the same day is on the answer: {place, icon, label, min,
    max, rain}. Only MET's figures for that very day; nothing otherwise."""
    day = str(ev.get("start", ""))[:10]
    for w in widgets:
        if w.get("type") != "weather":
            continue
        t = next((t for t in w.get("days", []) if t.get("d") == day), None)
        if t:
            return {"place": w["place"]["name"], "icon": t.get("icon", ""), "label": t.get("label", ""),
                    "min": t.get("min"), "max": t.get("max"), "rain": t.get("rain")}  # fmt: skip
    return None


def _map_for(points: list[tuple[float, float]], secret: bytes, single_kind: str = "", layer: str = "osm") -> dict:
    center, z = geo.fit(points, w=mapimg.MAP_W, h=mapimg.MAP_H, single=geo.single_zoom(single_kind))
    return mapimg.map_src(secret, center, z, layer)


def build_widgets(steps, request_text: str, lang: str, now: datetime, secret: bytes, *, draft: dict | None = None,
                  holidays=None, layer: str = "osm", geo_on: bool = True, extra=None) -> list[dict]:  # fmt: skip
    """``extra``: cards the harness computed itself without a tool (the world clock), kept as they are."""
    out: list[dict] = []
    for s in steps:
        info = getattr(s, "info", None) or {}
        w = info.get("widget")
        if getattr(s, "error", None) or not isinstance(w, dict):
            continue
        w = json.loads(json.dumps(w))  # a copy, plain JSON
        if info.get("auto"):
            w["auto"] = True
        if w.get("type") == "places" and geo_on:
            pts = [(p["lat"], p["lon"]) for p in w.get("places", [])]
            if w.get("center") and w.get("mode") in ("near", "route"):
                pts.append((w["center"]["lat"], w["center"]["lon"]))
            w["map"] = _map_for(pts, secret, w.get("single_kind", ""), layer) if pts else None
        elif w.get("type") == "company":
            ok = geo_on and w.get("lat") is not None and not w.get("natural_person")
            w["map"] = _map_for([(w["lat"], w["lon"])], secret, "", layer) if ok else None
        elif w.get("type") in opendata_widgets.TYPES:  # --- open data: signed picture and map (opendata_widgets.py)
            w = opendata_widgets.prepare(w, secret, layer, geo_on)
        elif w.get("type") not in ("fx", "weather"):
            continue
        out.append(w)
    for w in extra or []:
        if isinstance(w, dict) and (w.get("type") == "clock" or w.get("type") in HARNESS_CARDS):
            out.append(json.loads(json.dumps(w)))
    place = next((p for w in out if w["type"] == "places" for p in w.get("places", [])[:1]), None)
    ev = event_widget(request_text, now, lang, draft=draft, place=place, holidays=holidays)
    if ev:
        hint = weather_hint(out, ev)
        if hint:
            ev["weather"] = hint
        out.append(ev)
    # the small modules of the user's own data are built by the agent (« card », decided by the router):
    # they arrive in ``extra`` like the calculator
    kept, total = [], 0
    for w in out:  # caps of the history: each widget <= 8 KB (a list of places 16 KB), all <= 32 KB
        cap = MAX_LIST_BYTES if w.get("type") == "places" and w.get("mode") == "list" else MAX_WIDGET_BYTES
        cap = MAX_REPORT_BYTES if w.get("type") == "report" else cap
        n = _size(w)
        if n > cap and cap == MAX_LIST_BYTES:
            from birds.harness.tools.places import fit_list

            # the order, legs, total and route are computed again on the places kept; the others are named
            if fit_list(w, cap) and w.get("map"):
                w["map"] = _map_for([(p["lat"], p["lon"]) for p in w["places"]], secret, "", layer)
            n = _size(w)
        while n > cap and w.get("places") and len(w["places"]) > 1:
            w["places"] = w["places"][:-1]
            n = _size(w)
        if n <= cap and total + n <= MAX_TOTAL_BYTES:
            kept.append(w)
            total += n
    return kept


# ---------------------------------------------------------------- link previews

_GOV = re.compile(r"(?:^|\.)(?:gouv\.fr|gouv|europa\.eu|service-public\.fr|data\.gouv\.fr|insee\.fr)$")


def source_kind(host: str) -> str:
    if _GOV.search(host):
        return "gov"
    if host.endswith("wikipedia.org"):
        return "wiki"
    if host.endswith("openstreetmap.org"):
        return "osm"
    return "web"


def enrich_sources(sources: list[dict], steps, secret: bytes, icons: bool = True) -> list[dict]:
    """Add ``domain``, ``kind``, ``icon`` (signed same-origin favicon URL), and for URLs that came from
    web_search the result's ``date`` and short ``snippet`` (never page text)."""
    found = {}
    for s in steps:
        if getattr(s, "tool", "") != "web_search":
            continue
        for r in (getattr(s, "info", None) or {}).get("results", []) or []:
            if r.get("url"):
                found.setdefault(str(r["url"]), r)
    out = []
    for src in sources:
        src = dict(src)
        try:
            host = (urlsplit(str(src.get("url"))).hostname or "").lower()
        except ValueError:
            host = ""
        if host and str(src.get("url", "")).startswith(("http://", "https://")):
            domain = host[4:] if host.startswith("www.") else host
            src["domain"] = domain
            src["kind"] = source_kind(host)
            if icons and mapimg._HOST.match(host):
                src["icon"] = mapimg.icon_src(secret, host)
            r = found.get(str(src.get("url")))
            if r:
                if r.get("snippet"):
                    src["snippet"] = str(r["snippet"])[:161]
                if r.get("date"):
                    src["date"] = str(r["date"])[:32]
        out.append(src)
    return out


# ---------------------------------------------------------------- holidays (calendrier.api.gouv.fr)


def holiday_lookup(ctx_factory, url_template: str, zone: str):
    """A function year -> {iso date: name}, cached 30 days, through the egress guard; failures give {}."""

    def lookup(year: int) -> dict:
        from birds.harness.guard import Blocked, ToolError

        if not re.fullmatch(r"[a-z-]{3,40}", zone or "") or not 2000 <= year <= 2100:
            return {}
        try:
            data = geo.get_json(ctx_factory(), url_template.format(zone=zone, year=year), cache_ttl=30 * 86400,
                                count=False)  # fmt: skip
        except (Blocked, ToolError):
            return {}
        return data if isinstance(data, dict) else {}

    return lookup
