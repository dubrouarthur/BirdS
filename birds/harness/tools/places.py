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
MAX_LIST = 25  # places of one list ask (« montre sur une carte : a ; b ; c … »)
MAX_LIST_SLOW = 6  # of which looked up on Nominatim / Photon (1 request a second, OSMF policy); BAN has no such limit
LIST_WORKERS = 4  # parallel BAN requests (its limit is 50 requests a second per address)
_KIND_KEYS = {k for _, k in KINDS}


def _osm(lat: float, lon: float, z: int = 18) -> str:
    return f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map={z}/{lat:.6f}/{lon:.6f}"


def _directions(b: geo.Place, a: geo.Place | None = None) -> str:
    start = f"{a.lat:.6f},{a.lon:.6f}" if a else ""
    return "https://www.openstreetmap.org/directions?route=" + quote(f"{start};{b.lat:.6f},{b.lon:.6f}", safe="")


def _card(n, p: geo.Place, origin: geo.Place | None = None, slim: bool = False) -> dict:
    card = {
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
    if slim:  # a list of up to 25 places: empty fields are left out (the widget size is capped)
        card = {k: v for k, v in card.items() if v not in ("", None)}
    return card


def itinerary_url(points: list[tuple[float, float]]) -> str:
    """A multi-stop route on OSRM's OpenStreetMap router (openstreetmap.org/directions only takes two points)."""
    return "https://map.project-osrm.org/?" + "&".join(f"loc={la:.5f}%2C{lo:.5f}" for la, lo in points)


def visit_order(points: list[tuple[float, float]]) -> list[int]:
    """An open path from the first point through all the others, short at crow-flies distance: nearest neighbour
    then 2-opt. Indices into ``points``; the first stays first."""
    n = len(points)
    if n <= 2:
        return list(range(n))

    def d(i, j):
        return geo.distance_m(points[i][0], points[i][1], points[j][0], points[j][1])

    order, left = [0], set(range(1, n))
    while left:
        nxt = min(left, key=lambda j: (d(order[-1], j), j))
        order.append(nxt)
        left.remove(nxt)
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for k in range(i + 1, n):
                a, b = order[i - 1], order[i]
                c, e = order[k], (order[k + 1] if k + 1 < n else None)
                before = d(a, b) + (d(c, e) if e is not None else 0)
                after = d(a, c) + (d(b, e) if e is not None else 0)
                if after < before - 1:
                    order[i : k + 1] = reversed(order[i : k + 1])
                    improved = True
    return order


def _lookup_list(g: geo.Geocoder, names: list[str], lang: str) -> tuple[list[geo.Place | None], set[int]]:
    """One place (or None) per name, in order, and the indices of the names that could not be checked. Addresses and
    town names go to BAN in parallel; the others (and the addresses BAN does not know) to Nominatim / Photon one at a
    time, at most MAX_LIST_SLOW of them. A name is « not found » only when a provider answered with nothing: a
    lookup that failed (busy queue, 5xx, timeout, blocked) or never ran (over MAX_LIST_SLOW) is « not checked »."""
    from concurrent.futures import ThreadPoolExecutor

    from birds.harness.intents import known_place

    def fast(name: str) -> geo.Place | None:
        try:
            if geo.looks_like_address(name):
                hits = [h for h in g.ban(name) if h.importance >= 0.6]
            elif known_place(name):
                hits = [h for h in g.ban(name, kind="municipality") if h.importance >= 0.5]
                hits = [h for h in hits if _fold(h.name).startswith(_fold(name).split(" ")[0])]
            else:
                return None
        except (ToolError, geo.guard.Blocked):
            return None  # BAN failed: Nominatim / Photon are asked next (geo.Geocoder.search)
        return hits[0] if hits else None

    with ThreadPoolExecutor(max_workers=LIST_WORKERS) as pool:
        found = list(pool.map(fast, names))
    unchecked: set[int] = set()
    slow = 0
    for i, name in enumerate(names):
        if found[i] is not None:
            continue
        if slow >= MAX_LIST_SLOW:
            unchecked.add(i)
            continue
        slow += 1
        try:
            hits = g.search(name, limit=1, lang=lang)
        except (ToolError, geo.guard.Blocked):
            unchecked.add(i)
            hits = []
        found[i] = hits[0] if hits else None
    return found, unchecked


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
    query = " ".join(str(args.get("query") or "").split())
    query = query[:3000] if ";" in query else query[:200]
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
    plan = ""
    if ";" in query:
        from birds.harness.mapwords import plan_of

        mode, names = "list", [x.strip() for x in query.split(";") if x.strip()][:MAX_LIST]
        got, failed = _lookup_list(geo.Geocoder(ctx, count=False), names, lang)
        places = [p for p in got if p is not None]
        missing = [n for i, (n, p) in enumerate(zip(names, got, strict=True)) if p is None and i not in failed]
        unchecked = [names[i] for i in sorted(failed)]
        title = query
        # the model (or the reading of the ask) says what to compute; the user's words are the fallback
        asked = str(args.get("plan") or "").strip().lower()
        said = getattr(ctx, "request", "") or ""
        for n in names:  # the words of the places themselves (« rue du Circuit ») never ask for a plan
            said = said.replace(n, " ")
        plan = asked if asked in ("order", "distances") else plan_of(said)
        plan = plan if len(places) >= 2 else ""
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
        missing, unchecked = [], []
        title = query
    if not places and unchecked:
        # nothing could be checked: the service failed, the places may well exist
        raise ToolError("the map service is unavailable right now; say so, never that these places do not exist")
    if not places:
        ctx.step_info = {"found": 0}
        return _none(near if near and center is None else query, lang)
    ctx.place_calls += 1
    if mode == "route":
        cards = [_card("A", center), _card("B", places[0], center)]
    elif mode == "list":
        cards = [_card(i, p, None, slim=True) for i, p in enumerate(places, 1)]
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
    if mode == "list":
        pts = [(p.lat, p.lon) for p in places]
        order = visit_order(pts) if plan == "order" else list(range(len(places)))
        legs = [
            {"a": order[i] + 1, "b": order[i + 1] + 1, "m": geo.distance_m(*pts[order[i]], *pts[order[i + 1]])}
            for i in range(len(order) - 1)
        ]
        widget.update(
            missing=missing,
            unchecked=unchecked,
            plan=plan,
            order=[i + 1 for i in order],
            legs=legs if plan else [],
            total_m=sum(x["m"] for x in legs) if plan else None,
            itinerary=itinerary_url([pts[i] for i in order]) if len(pts) >= 2 else "",
        )
        if plan == "distances" and len(pts) <= 8:
            widget["matrix"] = [[geo.distance_m(*a, *b) for b in pts] for a in pts]
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
            head = f"{len(places)} lieu(x) placé(s) sur une carte, dans l'ordre donné :"
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
            head = f"{len(places)} place(s) put on a map, in the order given:"
        else:
            head = "OpenStreetMap result:"
    shown = places if mode == "list" else places[:MAX_CARDS]
    lines = [head] + ([] if mode == "route" else [_line(i, p, lang) for i, p in enumerate(shown, 1)])
    if missing:
        lines.append(("Introuvables (dis-le) : " if lang == "fr" else "Not found (say so): ") + " ; ".join(missing))
    if unchecked:
        lines.append(
            (
                "Non vérifiés (service de cartes indisponible ou trop sollicité ; dis-le, ne dis pas qu'ils "
                "n'existent pas) : "
                if lang == "fr"
                else "Not checked (map service unavailable or busy; say so, never that they do not exist): "
            )
            + " ; ".join(unchecked)
        )
    if mode == "list" and plan:
        lines.append(_plan_text(widget, lang))
    lines.append(_tail(lang) + (f" Source à citer : [{n_src}]." if lang == "fr" else f" Source to cite: [{n_src}]."))
    return "\n".join(lines)


def _plan_text(w: dict, lang: str) -> str:
    """The visit order or the distances, for the model (crow-flies: never a driving time)."""
    seq = " → ".join(str(n) for n in w["order"])
    total = _fmt_dist(w.get("total_m"), lang)
    if w["plan"] == "order":
        return (
            f"Ordre de visite proposé (le plus court à vol d'oiseau, en partant de 1) : {seq}, {total} au total. "
            "Ce n'est pas un temps de trajet ; le lien « Itinéraire complet » de la carte calcule la route."
            if lang == "fr"
            else f"Suggested visit order (shortest as the crow flies, starting from 1): {seq}, {total} in all. "
            "This is not a travel time; the map's 'Full route' link computes the road route."
        )
    legs = " ; ".join(f"{x['a']}–{x['b']} : {_fmt_dist(x['m'], lang)}" for x in w["legs"])
    return (
        f"Distances à vol d'oiseau entre les lieux, dans l'ordre donné : {legs}."
        if lang == "fr"
        else f"Straight-line distances between the places, in the order given: {legs}."
    )
