"""find_places: places, addresses and "X near Y" on OpenStreetMap (geocoders in birds.harness.geo).

The tool returns facts as text for the model and leaves the card/map payload in ``ctx.step_info["widget"]`` for the
UI. Coordinates only ever come from a geocoder response: the model cannot put a pin on the map.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

from birds.harness import geo
from birds.harness.guard import ToolError
from birds.harness.intents import KINDS

MAX_PER_RUN = 2
MAX_CARDS = 8
_KIND_KEYS = {k for _, k in KINDS}


def _osm(lat: float, lon: float, z: int = 18) -> str:
    return f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map={z}/{lat:.6f}/{lon:.6f}"


def _directions(b: geo.Place, a: geo.Place | None = None) -> str:
    start = f"{a.lat:.6f},{a.lon:.6f}" if a else ""
    return "https://www.openstreetmap.org/directions?route=" + quote(f"{start};{b.lat:.6f},{b.lon:.6f}", safe="")


def _card(n, p: geo.Place, origin: geo.Place | None = None) -> dict:
    return {
        "n": n,
        "name": p.name,
        "kind": p.kind,
        "detail": p.detail,
        "address": p.address,
        "lat": round(p.lat, 6),
        "lon": round(p.lon, 6),
        "distance_m": p.distance_m,
        "hours": p.hours,
        "website": p.website,
        "phone": p.phone,
        "wiki": p.wiki,
        "source": {
            "label": "OpenStreetMap" if p.provider != "ban" else "Base Adresse Nationale",
            "url": p.source_url or _osm(p.lat, p.lon),
        },
        "osm": _osm(p.lat, p.lon),
        "directions": _directions(p, origin),
    }


def _fmt_dist(m: int | None, lang: str) -> str:
    if m is None:
        return ""
    if m < 1000:
        return f"{m} m"
    km = f"{m / 1000:.1f}"
    return (km.replace(".", ",") if lang == "fr" else km) + " km"


def _line(n, p: geo.Place, lang: str) -> str:
    parts = [p.name, p.kind or ""]
    if p.detail:
        parts[-1] = (parts[-1] + ", " if parts[-1] else "") + p.detail
    parts += [p.address, _fmt_dist(p.distance_m, lang)]
    if p.hours:
        parts.append(("horaires : " if lang == "fr" else "hours: ") + p.hours)
    parts.append(p.source_url or _osm(p.lat, p.lon))
    return f"{n}. " + " — ".join(x for x in parts if x)


def _tail(lang: str) -> str:
    if lang == "fr":
        return (
            "Ces lieux viennent d'OpenStreetMap et peuvent être incomplets. Une carte et des fiches sont affichées "
            "à l'utilisateur sous ta réponse : ne recopie pas toutes les adresses ; résume, ne cite que ces lieux, "
            "ne donne ni note, ni prix, ni temps de trajet. Tu ne connais ni les lignes de métro ou de bus, ni les "
            "parkings, ni les entrées : ne les invente pas ; dis que le lien « Itinéraire » de la carte donne l'accès."
        )
    return (
        "These come from OpenStreetMap and may be incomplete. A map and cards are shown to the user under your "
        "answer: do not repeat every address; summarise, mention only these places, give no ratings, prices or "
        "travel times. You know no metro or bus lines, car parks or entrances: do not invent them; say that the "
        "map's 'Directions' link shows how to get there."
    )


def _none(q: str, lang: str) -> str:
    if lang == "fr":
        return (
            f"Aucun lieu trouvé pour « {q} » sur OpenStreetMap. Si une page lue donne son adresse ou le lieu qui "
            "l'abrite (un aéroport, un centre commercial…), appelle find_places avec cette adresse ; sinon dis-le, "
            "et n'invente pas d'adresse."
        )
    return (
        f"No place found for '{q}' on OpenStreetMap. If a page you read gives its address or the place that hosts it "
        "(an airport, a mall…), call find_places with that address; otherwise say so, and do not guess an address."
    )


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").replace("’", "'").casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w']+", " ", t).split())


def own_words(value: str, request: str) -> bool:
    """``value`` (a query, a 'near' or a list item) is written in the user's own words, or is a kind keyword."""
    v = _fold(value)
    if not v or value.strip().lower() in _KIND_KEYS:
        return True
    return f" {v} " in f" {_fold(request)} "


def find_places(args: dict, ctx) -> str:
    if ctx.place_calls >= MAX_PER_RUN:
        raise ToolError("places already shown; answer with them")
    lang = ctx.lang if ctx.lang in ("fr", "en") else "fr"
    query = " ".join(str(args.get("query") or "").split())[:200]
    near = " ".join(str(args.get("near") or "").split())[:120]
    if not query:
        raise ToolError("query is empty")
    if getattr(ctx, "attached", False):
        # with a document attached, an address read in the file is never sent to a geocoder: only what the
        # user typed (docs/WEB.md, « Vie privée »)
        parts = [x.strip() for x in query.split(";")] + ([near] if near else [])
        if not all(own_words(x, ctx.request) for x in parts if x):
            raise ToolError(
                "a place read in an attached file is never looked up; ask the user to type the place or address"
            )
    g = geo.Geocoder(ctx)
    center = None
    if ";" in query:
        mode, names = "list", [x.strip() for x in query.split(";") if x.strip()][:5]
        found, missing = [], []
        for name in names:
            try:
                res = g.search(name, limit=1, lang=lang)
            except ToolError:
                res = []
            (found.append(res[0]) if res else missing.append(name))
        places = found
        title = query
    else:
        if near:
            # « aix »: several towns match; the most important one (a city before villages) is the likely meaning
            hits = sorted(g.search(near, limit=5, lang=lang), key=lambda h: -(h.importance or 0.0))[:1]
            if not hits:
                ctx.step_info = {"found": 0}
                return _none(near, lang)
            center = hits[0]
        if center is not None and query.lower() in _KIND_KEYS:
            mode = "near"
            places = g.search(query, near=center, limit=MAX_CARDS, lang=lang)
        elif center is not None:
            mode = "route"
            hits = g.search(query, limit=1, lang=lang)
            places = hits[:1]
            if places:
                places[0].distance_m = geo.distance_m(center.lat, center.lon, places[0].lat, places[0].lon)
        else:
            mode = "where"
            hits = g.search(query, limit=3, lang=lang)
            if hits:
                top = hits[0].importance or 0.0
                hits = [hits[0]] + [h for h in hits[1:] if top and h.importance >= 0.5 * top]
            places = hits
        missing = []
        title = query
    if not places:
        ctx.step_info = {"found": 0}
        return _none(near if near and center is None else query, lang)
    ctx.place_calls += 1
    if mode == "route":
        cards = [_card("A", center), _card("B", places[0], center)]
    else:
        cards = [_card(i, p, None) for i, p in enumerate(places[:MAX_CARDS], 1)]
    widget = {
        "type": "places",
        "v": 1,
        "mode": mode,
        "query": query,
        "near": near,
        "title": title,
        "center": None
        if center is None
        else {"name": center.name, "lat": round(center.lat, 6), "lon": round(center.lon, 6)},
        "single_kind": places[0].kind if len(places) == 1 else "",
        "places": cards,
        "attribution": "© OpenStreetMap contributors",
        "provider": places[0].provider,
        "complete": False,
    }
    if mode == "route":
        widget["distance_m"] = places[0].distance_m
        widget["directions"] = _directions(places[0], center)
    if isinstance(getattr(ctx, "places", None), list):  # a deck or document of the same run can show them on a map
        ctx.places.extend({**c, "near": title} for c in cards if c.get("lat") is not None)
    ctx.step_info = {
        "widget": widget,
        "found": len(places),
        "label": "OpenStreetMap" if places[0].provider != "ban" else "Base Adresse Nationale",
    }
    focus = center or places[0]
    src = f"https://www.openstreetmap.org/#map=16/{focus.lat:.5f}/{focus.lon:.5f}"
    if src not in ctx.sources:
        ctx.sources.append(src)
    n_src = ctx.sources.index(src) + 1
    if lang == "fr":
        if mode == "near":
            head = (
                f"{len(places)} lieu(x) trouvé(s) sur OpenStreetMap autour de {center.name}"
                f"{' (' + center.address + ')' if center.address else ''}, du plus proche au plus loin :"
            )
        elif mode == "route":
            head = (
                f"Départ : {center.name} ({center.address or 'adresse non précisée'}). Arrivée : {places[0].name} "
                f"({places[0].address or 'adresse non précisée'}). Distance à vol d'oiseau : "
                f"{_fmt_dist(places[0].distance_m, lang)}. Aucun temps de trajet n'est connu ; un lien d'itinéraire "
                "OpenStreetMap est affiché."
            )
        elif mode == "list":
            head = "Lieux trouvés sur OpenStreetMap, dans l'ordre demandé :"
        else:
            head = "Résultat OpenStreetMap :"
    else:
        if mode == "near":
            head = (
                f"{len(places)} places found on OpenStreetMap around {center.name}"
                f"{' (' + center.address + ')' if center.address else ''}, nearest first:"
            )
        elif mode == "route":
            head = (
                f"Start: {center.name} ({center.address or 'no address'}). Destination: {places[0].name} "
                f"({places[0].address or 'no address'}). Straight-line distance: "
                f"{_fmt_dist(places[0].distance_m, lang)}. No travel time is known; an OpenStreetMap directions "
                "link is shown."
            )
        elif mode == "list":
            head = "Places found on OpenStreetMap, in the order asked:"
        else:
            head = "OpenStreetMap result:"
    lines = [head] + ([] if mode == "route" else [_line(i, p, lang) for i, p in enumerate(places[:MAX_CARDS], 1)])
    if missing:
        lines.append(("Non trouvés : " if lang == "fr" else "Not found: ") + ", ".join(missing))
    lines.append(_tail(lang) + (f" Source à citer : [{n_src}]." if lang == "fr" else f" Source to cite: [{n_src}]."))
    return "\n".join(lines)
