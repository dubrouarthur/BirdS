"""get_weather: a forecast from MET Norway (api.met.no, Locationforecast 2.0 compact, free, CC BY 4.0).

The place is geocoded with birds.harness.geo (the most important town of that name), then MET Norway is asked for
lat/lon rounded to 4 decimals, as its terms require, with an identifying User-Agent and HTTP caching (``Expires``
honoured, ``If-Modified-Since`` on revalidation). The model gets a compact text; the card payload goes to
``ctx.step_info["widget"]``. Every figure is MET's: nothing is invented, and every label says « prévision ».
Times are local to the place when its zone is known for sure (a city of the clock table, a single-zone country,
metropolitan France), else UTC, labelled as such.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from birds.harness import clock, geo, guard, when
from birds.harness.guard import ToolError

DOC_URL = "https://api.met.no/weatherapi/locationforecast/2.0/documentation"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
MIN_TTL, MAX_TTL, KEEP = 60.0, 6 * 3600.0, 24 * 3600.0
MAX_BYTES = 1_500_000
DAYS_SHOWN = 7

# ---------------------------------------------------------------- MET symbol codes -> 12 inline icons + a label

_PHENOMENA = {"rain": ("pluie", "rain"), "sleet": ("neige fondue", "sleet"), "snow": ("neige", "snow")}
_SKY = {
    "clearsky": ("Ciel dégagé", "Clear sky"),
    "fair": ("Beau temps", "Fair"),
    "partlycloudy": ("Partiellement nuageux", "Partly cloudy"),
    "cloudy": ("Nuageux", "Cloudy"),
    "fog": ("Brouillard", "Fog"),
}
ICONS = ("sun", "moon", "partly_day", "partly_night", "cloud", "fog", "drizzle", "rain", "showers", "sleet", "snow",
         "thunder")  # fmt: skip


def sky(code: str) -> dict:
    """{'icon', 'fr', 'en'} for a MET symbol_code such as 'lightrainshowersandthunder_day' (unknown: cloud)."""
    c = str(code or "").lower()
    night = c.endswith("_night")
    base = re.sub(r"_(?:day|night|polartwilight)$", "", c)
    thunder = base.endswith("andthunder")
    base = base.removesuffix("andthunder")
    if base in _SKY:
        icon = {"clearsky": "moon" if night else "sun", "fair": "moon" if night else "sun",
                "partlycloudy": "partly_night" if night else "partly_day", "cloudy": "cloud", "fog": "fog"}[base]  # fmt: skip
        fr, en = _SKY[base]
        if thunder:
            icon, fr, en = "thunder", fr + " et orage", en + " and thunder"
        return {"icon": icon, "fr": fr, "en": en}
    m = re.fullmatch(r"(light|heavy)?(rain|sleet|snow)(showers)?", base)
    if not m:
        return {"icon": "cloud", "fr": "Nuageux", "en": "Cloudy"}
    level, what, showers = m.groups()
    fr_noun, en_noun = _PHENOMENA[what]
    if showers:
        fr = {"rain": "Averses", "sleet": "Averses de neige fondue", "snow": "Averses de neige"}[what]
        en = {"rain": "Showers", "sleet": "Sleet showers", "snow": "Snow showers"}[what]
    else:
        fr, en = fr_noun.capitalize(), en_noun.capitalize()
    if level == "light":
        fr, en = fr + (" faibles" if showers else " faible"), "Light " + en.lower()
    elif level == "heavy":
        fr, en = ("Fortes " + fr.lower()) if showers else (fr + " forte"), "Heavy " + en.lower()
    if what == "snow":
        icon = "snow"
    elif what == "sleet":
        icon = "sleet"
    elif showers and not night:
        icon = "showers"
    else:
        icon = "drizzle" if level == "light" else "rain"
    if thunder:
        icon, fr, en = "thunder", fr + " et orage", en + " and thunder"
    return {"icon": icon, "fr": fr, "en": en}


# ---------------------------------------------------------------- MET answer -> points


def parse_met(data) -> tuple[list[dict], str]:
    """(points, updated_at) from a Locationforecast 2.0 GeoJSON answer. Each point: {t (UTC), temp, wind (m/s),
    rain1, sym1, rain6, sym6, sym12, prob1, prob6}; a missing value is None. No usable point: ToolError."""
    try:
        props = data["properties"]
        series = props["timeseries"]
    except (KeyError, TypeError) as e:
        raise ToolError("the weather service returned no forecast") from e
    out = []
    for item in series if isinstance(series, list) else []:
        try:
            t = datetime.strptime(str(item["time"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            d = item.get("data") or {}
            inst = (d.get("instant") or {}).get("details") or {}
            temp = inst.get("air_temperature")
            if not isinstance(temp, (int, float)):
                continue
        except (KeyError, TypeError, ValueError):
            continue

        def nxt(key, d=d):
            part = d.get(key) or {}
            det = part.get("details") or {}
            amt = det.get("precipitation_amount")
            prob = det.get("probability_of_precipitation")
            return (
                (part.get("summary") or {}).get("symbol_code"),
                float(amt) if isinstance(amt, (int, float)) else None,
                float(prob) if isinstance(prob, (int, float)) else None,
            )

        s1, r1, p1 = nxt("next_1_hours")
        s6, r6, p6 = nxt("next_6_hours")
        s12, _, _ = nxt("next_12_hours")
        wind = inst.get("wind_speed")
        out.append({"t": t, "temp": float(temp), "wind": float(wind) if isinstance(wind, (int, float)) else None,
                    "rain1": r1, "sym1": s1, "prob1": p1, "rain6": r6, "sym6": s6, "prob6": p6, "sym12": s12})  # fmt: skip
    if not out:
        raise ToolError("the weather service returned no forecast")
    out.sort(key=lambda p: p["t"])
    return out, str((props.get("meta") or {}).get("updated_at") or "")[:20]


def rain_periods(points: list[dict]) -> list[tuple[datetime, int, float, float | None]]:
    """(start, hours, mm, probability) periods covering the forecast once: hourly where MET gives hours, then
    6-hour blocks. A 6-hour block that would overlap hours already counted is skipped (no double counting)."""
    out, covered = [], None
    for p in points:
        if covered is not None and p["t"] < covered:
            continue
        if p["rain1"] is not None:
            out.append((p["t"], 1, p["rain1"], p["prob1"]))
            covered = p["t"] + timedelta(hours=1)
        elif p["rain6"] is not None:
            out.append((p["t"], 6, p["rain6"], p["prob6"]))
            covered = p["t"] + timedelta(hours=6)
    return out


def _r1(x: float | None) -> float | None:
    return None if x is None else round(x + 0.0, 1)


def _kmh(ms: float | None) -> int | None:
    return None if ms is None else int(round(ms * 3.6))


def day_symbol(points: list[dict], zone: ZoneInfo, d: date) -> str:
    """The symbol that best describes the daytime of ``d``: the 6-hour (else 1-hour) symbol nearest local noon."""
    best, score = "", None
    for p in points:
        loc = p["t"].astimezone(zone)
        if loc.date() != d:
            continue
        sym = p["sym6"] or p["sym1"] or p["sym12"]
        if not sym:
            continue
        # a 6-hour symbol describes the 6 hours after its time: centre it
        mid = loc + timedelta(hours=3 if p["sym6"] else 0.5)
        s = abs((mid.hour + mid.minute / 60) - 12.5) + (0 if p["sym6"] else 0.25)
        if score is None or s < score:
            best, score = sym, s
    return best


def days(points: list[dict], zone: ZoneInfo, first: date, n: int = DAYS_SHOWN) -> list[dict]:
    """Daily tiles from ``first``: min, max, rain (mm), icon. A day with no daytime point is left out (partial)."""
    periods = rain_periods(points)
    out = []
    for i in range(n + 3):
        d = first + timedelta(days=i)
        pts = [p for p in points if p["t"].astimezone(zone).date() == d]
        if len(pts) < 2 or not any(9 <= p["t"].astimezone(zone).hour <= 16 for p in pts):
            if i == 0 and pts:
                pass  # today in the evening: what remains of it still counts
            else:
                continue
        temps = [p["temp"] for p in pts]
        rain = sum(mm for t, _, mm, _ in periods if t.astimezone(zone).date() == d)
        probs = [pr for t, _, _, pr in periods if t.astimezone(zone).date() == d and pr is not None]
        sym = day_symbol(points, zone, d)
        sk = sky(sym)
        winds = [p["wind"] for p in pts if p["wind"] is not None]
        out.append({
            "d": d.isoformat(), "min": round(min(temps)), "max": round(max(temps)), "rain": _r1(rain),
            "prob": round(max(probs)) if probs else None, "icon": sk["icon"], "symbol": sym,
            "label_fr": sk["fr"], "label_en": sk["en"], "wind": _kmh(max(winds)) if winds else None,
        })  # fmt: skip
        if len(out) >= n:
            break
    return out


def hours(points: list[dict], zone: ZoneInfo, start: datetime, span_h: int = 24) -> list[dict]:
    """The hourly strip: points in [start, start + span), each with the rain of the period it opens."""
    end = start + timedelta(hours=span_h)
    out = []
    covered = None
    for p in points:
        if not start <= p["t"] < end:
            continue
        step, rain, sym = 1, p["rain1"], p["sym1"]
        if rain is None and p["rain6"] is not None:
            step, rain, sym = 6, p["rain6"], p["sym6"]
        if covered is not None and p["t"] < covered:
            rain = None  # inside a 6-hour block already drawn
        elif rain is not None:
            covered = p["t"] + timedelta(hours=step)
        out.append({"t": p["t"].astimezone(zone).strftime("%Y-%m-%dT%H:%M"), "temp": round(p["temp"], 1),
                    "rain": _r1(rain), "step": step, "icon": sky(sym or p["sym12"])["icon"] if (sym or p["sym12"]) else ""})  # fmt: skip
    return out


# ---------------------------------------------------------------- time zone of a place

_FR_METRO = (41.2, 51.2, -5.3, 9.7)  # lat/lon box of metropolitan France and Corsica


def zone_of(place: geo.Place, query: str) -> tuple[str, str]:
    """(IANA zone, label) for the place: a clock-table city, a single-zone country, metropolitan France; else UTC."""
    for name in (query, place.name):
        c = clock._ALIAS.get(clock.fold(name))
        if c and (not place.country_code or c["cc"] == place.country_code):
            return c["zone"], c["zone"]
    cc = place.country_code
    if cc == "FR" and _FR_METRO[0] <= place.lat <= _FR_METRO[1] and _FR_METRO[2] <= place.lon <= _FR_METRO[3]:
        return "Europe/Paris", "Europe/Paris"
    z = clock.zone_for_country(cc)
    if z:
        return z, z
    return "UTC", "UTC"


# ---------------------------------------------------------------- HTTP: MET's caching rules


def _http_date(value: str | None) -> float | None:
    try:
        return parsedate_to_datetime(value).timestamp() if value else None
    except (TypeError, ValueError):
        return None


def forecast_url(cfg, lat: float, lon: float) -> str:
    # MET's terms: at most 4 decimals (more is refused with 403 and wastes their cache)
    return f"{cfg.met_url}?lat={round(lat, 4):.4f}&lon={round(lon, 4):.4f}"


def fetch(ctx, lat: float, lon: float):
    """MET's answer for lat/lon: from the cache while ``Expires`` is in the future, else a conditional GET
    (``If-Modified-Since``: a 304 keeps the cached forecast). Counts against the per-answer lookup cap."""
    cfg = ctx.config
    url = forecast_url(cfg, lat, lon)
    recorded = getattr(ctx, "recorded", None)
    if recorded is not None:
        return recorded(url)
    disk = getattr(cfg, "geo_cache_dir", None)
    key = geo.Policy.key("met", url)
    entry = geo.POLICY.get(key, disk)
    now = geo.POLICY.wall()
    if isinstance(entry, dict) and entry.get("exp", 0) > now and entry.get("data") is not None:
        return entry["data"]
    if ctx.geo_calls >= geo.MAX_LOOKUPS_PER_RUN:
        raise ToolError("lookup limit of this answer reached")
    ctx.geo_calls += 1
    headers = {}
    if isinstance(entry, dict) and entry.get("lm"):
        headers["If-Modified-Since"] = entry["lm"]
    geo.POLICY.wait_turn(geo.httpx_host(url))
    status, _, body, hdrs = guard.fetch_bytes(
        ctx.http, cfg, url, accept="application/json", types=("application/json",), max_bytes=MAX_BYTES,
        user_agent=getattr(cfg, "met_user_agent", None) or "BirdHarness/0.1 (+https://bird-s.vercel.app)",
        headers=headers,
    )  # fmt: skip
    h = {str(k).lower(): v for k, v in (hdrs or {}).items()}
    if status == 304 and isinstance(entry, dict) and entry.get("data") is not None:
        data = entry["data"]
    else:
        try:
            data = json.loads(body)
        except ValueError as e:
            raise ToolError("the weather service returned invalid JSON") from e
        ctx.bytes_fetched += len(body)
    exp = _http_date(h.get("expires"))
    fresh = min(MAX_TTL, max(MIN_TTL, (exp - now) if exp else 1800.0))
    lm = h.get("last-modified") or (entry.get("lm") if isinstance(entry, dict) else "")
    geo.POLICY.put(key, {"data": data, "exp": now + fresh, "lm": lm}, KEEP, disk)
    return data


# ---------------------------------------------------------------- the tool

_WEEKEND = re.compile(r"\b(?:ce\s+)?(?:week-?end|weekend|this weekend|samedi et dimanche)\b", re.I)


def resolve_day(text: str, today: date, lang: str) -> date | None:
    t = " ".join(str(text or "").split())
    if not t or re.fullmatch(r"(?:aujourd'hui|aujourd’hui|today|maintenant|now|ce soir|tonight|ce matin|"
                             r"cet après-midi|this (?:morning|afternoon|evening))", t, re.I):  # fmt: skip
        return today
    if _WEEKEND.search(t):
        return today if today.weekday() >= 5 else today + timedelta(days=5 - today.weekday())
    got = when.find_day(t, today, lang)
    return got[0] if got else None


_DOW = {"fr": "lundi mardi mercredi jeudi vendredi samedi dimanche".split(),
        "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()}  # fmt: skip
_MON = {"fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),
        "en": "January February March April May June July August September October November December".split()}  # fmt: skip


def _day_name(d: date, lang: str) -> str:
    return f"{_DOW[lang][d.weekday()]} {d.day} {_MON[lang][d.month - 1]}"


def _num(x, lang: str) -> str:
    s = f"{x:g}" if isinstance(x, float) else str(x)
    return s.replace(".", ",") if lang == "fr" else s


def get_weather(args: dict, ctx) -> str:
    lang = ctx.lang if ctx.lang in ("fr", "en") else "fr"
    place_q = " ".join(str(args.get("place") or "").split())[:120]
    day_q = " ".join(str(args.get("day") or "").split())[:60]
    if not place_q:
        raise ToolError("place is empty: ask the user which town")
    if getattr(ctx, "attached", False):
        from birds.harness.tools.places import own_words

        if not own_words(place_q, ctx.request):  # a town read in an attached file is never looked up
            raise ToolError("a place read in an attached file is never looked up; ask the user to type the town")
    hits = geo.Geocoder(ctx).search(place_q, limit=5, lang=lang)
    if not hits:
        ctx.step_info = {"found": 0}
        return (f"Aucun lieu trouvé pour « {place_q} ». Demande à l'utilisateur de préciser la ville ; n'invente "
                "aucune météo." if lang == "fr" else
                f"No place found for '{place_q}'. Ask the user which town; do not invent any weather.")  # fmt: skip
    # « Valence », « Aix »: several places match; the most important (a city before villages) is the likely meaning
    place = sorted(hits, key=lambda h: -(h.importance or 0.0))[0]
    zone_name, tz_label = zone_of(place, place_q)
    zone = ZoneInfo(zone_name)
    now = (getattr(ctx, "now", None) or datetime.now(UTC)).astimezone(zone)
    today = now.date()
    day = resolve_day(day_q, today, lang) if day_q else today
    if day is None:
        day = today
    if day < today:
        raise ToolError("that day is in the past: a forecast only covers the coming days; say so")
    data = fetch(ctx, place.lat, place.lon)
    points, updated = parse_met(data)
    points = [p for p in points if p["t"] >= now.astimezone(UTC) - timedelta(hours=1)] or points
    last = points[-1]["t"].astimezone(zone).date()
    if day > last:
        raise ToolError(
            f"MET Norway's forecast for {place.name} runs until {last.isoformat()}: there is no forecast yet for "
            f"{day.isoformat()}; say so and offer to look again closer to the day"
        )
    tiles = days(points, zone, today)
    tile = next((t for t in tiles if t["d"] == day.isoformat()), None)
    if day == today:
        first = points[0]
        sym = first["sym1"] or first["sym6"] or first["sym12"] or ""
        sk = sky(sym)
        rain_next = first["rain1"] if first["rain1"] is not None else first["rain6"]
        summary = {
            "kind": "now", "temp": round(first["temp"], 1), "icon": sk["icon"], "symbol": sym,
            "label": sk[lang], "wind_kmh": _kmh(first["wind"]),
            "rain_mm": tile["rain"] if tile else _r1(rain_next), "rain_prob": tile["prob"] if tile else None,
            "min": tile["min"] if tile else None, "max": tile["max"] if tile else None,
            "at": first["t"].astimezone(zone).strftime("%Y-%m-%dT%H:%M"),
        }  # fmt: skip
        strip = hours(points, zone, first["t"], 24)
    else:
        sym = (tile or {}).get("symbol") or day_symbol(points, zone, day)
        sk = sky(sym)
        summary = {
            "kind": "day", "temp": tile["max"] if tile else None, "icon": sk["icon"], "symbol": sym,
            "label": sk[lang], "wind_kmh": (tile or {}).get("wind"), "rain_mm": (tile or {}).get("rain"),
            "rain_prob": (tile or {}).get("prob"), "min": (tile or {}).get("min"), "max": (tile or {}).get("max"),
        }  # fmt: skip
        midnight = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)
        strip = hours(points, zone, midnight, 24)
    name = place.name
    alias = clock._ALIAS.get(clock.fold(place_q))
    if alias and (not place.country_code or alias["cc"] == place.country_code):
        name = alias.name(lang)  # « London » asked in French: « Londres », not OSM's « Grand Londres »
    region = ", ".join(x for x in (place.region if place.region != name else "", place.country) if x)
    if DOC_URL not in ctx.sources:
        ctx.sources.append(DOC_URL)
    n_src = ctx.sources.index(DOC_URL) + 1
    kind = "today" if day == today else "tomorrow" if day == today + timedelta(days=1) else "date"
    widget = {
        "type": "weather",
        "v": 1,
        "place": {"name": name, "region": region[:120], "lat": round(place.lat, 4), "lon": round(place.lon, 4)},
        "tz": zone_name,
        "tz_label": tz_label,
        "day": day.isoformat(),
        "day_kind": kind,
        "summary": summary,
        "hours": strip,
        "days": [
            {k: v for k, v in t.items() if k not in ("label_fr", "label_en", "symbol")} | {"label": t["label_" + lang]}
            for t in tiles
        ],  # fmt: skip
        "updated": updated,
        "source": {"label": "MET Norway", "url": DOC_URL},
        "license": {"label": "CC BY 4.0", "url": LICENSE_URL},
    }
    ctx.step_info = {"widget": widget, "label": "MET Norway", "found": 1}
    return _text(widget, lang, n_src)


def _text(w: dict, lang: str, n_src: int) -> str:
    s, p = w["summary"], w["place"]
    d = date.fromisoformat(w["day"])
    where = p["name"] + (f" ({p['region']})" if p["region"] else "")
    tz = ("heure locale" if lang == "fr" else "local time") if w["tz"] != "UTC" else "UTC"
    bits = [s["label"].lower()]
    if s["kind"] == "now" and s["temp"] is not None:
        bits.append(f"{_num(s['temp'], lang)} °C maintenant" if lang == "fr" else f"{_num(s['temp'], lang)} °C now")
    if s["min"] is not None and s["max"] is not None:
        bits.append(f"{s['min']} à {s['max']} °C" if lang == "fr" else f"{s['min']} to {s['max']} °C")
    if s["rain_mm"] == 0:
        bits.append("pas de pluie prévue" if lang == "fr" else "no rain expected")
    elif s["rain_mm"] is not None:
        bits.append((f"pluie {_num(s['rain_mm'], lang)} mm" if lang == "fr" else f"rain {_num(s['rain_mm'], lang)} mm")
                    + (f" (probabilité {s['rain_prob']} %)" if s.get("rain_prob") is not None and lang == "fr" else
                       f" ({s['rain_prob']}% chance)" if s.get("rain_prob") is not None else ""))  # fmt: skip
    if s["wind_kmh"] is not None:
        bits.append(f"vent {s['wind_kmh']} km/h" if lang == "fr" else f"wind {s['wind_kmh']} km/h")
    nxt = []
    for t in w["days"]:
        if len(nxt) >= 4:
            break
        if t["d"] <= w["day"]:  # the days after the one asked
            continue
        dd = date.fromisoformat(t["d"])
        nxt.append(f"{_DOW[lang][dd.weekday()][:3]}. {t['min']}/{t['max']} °C {t['label'].lower()}"
                   + (f" {_num(t['rain'], lang)} mm" if t["rain"] else ""))  # fmt: skip
    if lang == "fr":
        return (
            f"Prévision MET Norway pour {where}, {_day_name(d, lang)} ({tz}) : " + ", ".join(bits) + ". "
            + ("Jours suivants : " + " ; ".join(nxt) + ". " if nxt else "")
            + "Une carte météo détaillée (heure par heure, 7 jours) est affichée sous ta réponse : écris 1 ou 2 "
            "phrases utiles, sans recopier tous les chiffres ; c'est une prévision, n'invente rien d'autre. "
            f"Source à citer : [{n_src}]."
        )  # fmt: skip
    return (
        f"MET Norway forecast for {where}, {_day_name(d, lang)} ({tz}): " + ", ".join(bits) + ". "
        + ("Next days: " + "; ".join(nxt) + ". " if nxt else "")
        + "A detailed weather card (hourly, 7 days) is shown under your answer: write 1 or 2 useful sentences, "
        "without repeating every figure; it is a forecast, invent nothing else. "
        f"Source to cite: [{n_src}]."
    )  # fmt: skip
