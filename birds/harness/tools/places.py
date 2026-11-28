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
# a list card's JSON budget: birds/web/widgets.py MAX_LIST_BYTES (16 KB) less room for the map image it adds
LIST_BYTES = 15_000
MAX_LIST_SLOW = 6  # of which looked up on Nominatim / Photon (1 request a second, OSMF policy); BAN has no such limit
LIST_WORKERS = 4  # parallel BAN requests (its limit is 50 requests a second per address)
_KIND_KEYS = {k for _, k in KINDS}
# « supermarchés », « une pharmacie de garde », « restaurant végétarien »: a category of OpenStreetMap, never a name
# matched across the world (a clothes shop called « supermarché » in Berlin). The model writes the category in the
# user's words or as the key; the code maps it (intents.KINDS) and keeps the rest as a qualifier OSM cannot check.
_CATEGORY = re.compile(
    r"^(?:(?:les|des|un|une|la|le|l'|the|a|some|quelques)\s+)?(?P<kind>" + "|".join(f"(?:{k})" for k, _ in KINDS)
    + r")(?P<rest>(?:\s+[\w'’-]+){0,3})$",
    re.I,
)
# what OpenStreetMap cannot say about a place of the category: the model is told, so it never claims it
_QUALIFIERS = (
    (re.compile(r"\bde garde\b|\bon duty\b|\bopen now\b|\bouverte?s? maintenant\b", re.I), "garde"),
    (re.compile(r"v[ée]g[ée]tarien|vegan|v[ée]g[ée]talien|vegetarian", re.I), "veg"),
)
# a town, a district or a station: places of a kind are looked for within this many metres of it, then twice as far
TOWN_KINDS = {"city", "town", "village", "municipality", "administrative", "suburb", "borough", "quarter",
              "neighbourhood", "hamlet", "city_district", "district", "census"}  # fmt: skip
TOWN_RADII = (2500, 5000)
SPOT_RADII = (500, 1500)
# the words Nominatim reads as the category (its « special phrases »: « train station » finds nothing, « bank » finds
# benches), and the OSM types kept for it (a fuzzy match is dropped). Measured on Nominatim, 28/11/2026.
PHRASES = {"bank": "banks", "atm": "cash machine", "train station": "railway station", "fitness centre": "gym",
           "pizza": "pizzeria", "bookshop": "book shop"}  # fmt: skip
TYPES = {
    "supermarket": {"supermarket", "convenience", "department_store", "greengrocer"},
    "bakery": {"bakery", "pastry"},
    "pharmacy": {"pharmacy", "chemist"},
    "restaurant": {"restaurant", "fast_food", "food_court", "pizza", "cafe"},
    "hospital": {"hospital", "clinic"},
    "train station": {"station", "train_station", "halt", "stop"},
    "subway station": {"subway", "station", "subway_entrance"},
    "parking": {"parking", "parking_entrance", "parking_space"},
    "fuel": {"fuel"},
    "bank": {"bank"},
    "atm": {"atm", "bank"},
    "post office": {"post_office"},
    "school": {"school"},
    "kindergarten": {"kindergarten", "childcare"},
}
FAR_M = 50_000  # a shop or a building farther than this from the anchor is another place with the same name


def category(query: str) -> tuple[str, str] | None:
    """(OSM kind key, qualifier) when ``query`` names a category of place (« supermarchés », « pharmacy »,
    « restaurant végétarien »), else None (a name: « tour Eiffel », « Carrefour Market »)."""
    q = " ".join(str(query or "").replace("’", "'").split())
    if not q or ";" in q:
        return None
    if q.lower() in _KIND_KEYS:
        return q.lower(), ""
    m = _CATEGORY.match(q)
    if not m:
        return None
    kind = next(k for rx, k in KINDS if re.fullmatch(rx, m.group("kind"), re.I))
    rest = m.group("rest").strip()
    if rest and not any(rx.search(rest) for rx, _ in _QUALIFIERS) and not re.match(
        r"^(?:de\s+(?:quartier|proximit[ée])|proches?|ouverte?s?|bio|pas chers?|cheap|nearby|local)\b", rest, re.I
    ):
        return None  # « gare de Lyon », « école des Mines »: a name that starts with a kind word
    return kind, rest


def _radii(anchor: geo.Place) -> tuple[int, ...]:
    return TOWN_RADII if (anchor.kind or "").lower() in TOWN_KINDS else SPOT_RADII


def _anchor(hits: list[geo.Place], lang: str) -> geo.Place | None:
    """The place « near » means: the most important hit, but a hit in France for a French conversation when it is
    nearly as important (« Défense » is La Défense, not the Ministry of Defence in London)."""
    if not hits:
        return None
    hits = sorted(hits, key=lambda h: -(h.importance or 0.0))
    top = hits[0]
    if lang == "fr" and top.country_code and top.country_code != "FR":
        home = next((h for h in hits if h.country_code == "FR"), None)
        if home is not None and (home.importance or 0.0) >= 0.6 * (top.importance or 0.0):
            return home
    return top


def _qualifier_note(rest: str, lang: str) -> str:
    kinds = {k for rx, k in _QUALIFIERS if rx.search(rest or "")}
    if "garde" in kinds:
        return ("OpenStreetMap ne dit pas quelle pharmacie est de garde aujourd'hui : présente ces pharmacies du "
                "secteur avec leurs horaires, et pour la garde de nuit ou du dimanche indique le 3237 ou 3237.fr."
                if lang == "fr" else
                "OpenStreetMap does not say which pharmacy is on duty today: list these pharmacies with their hours, "
                "and for the night or Sunday duty pharmacy point to 3237 or 3237.fr (France).")  # fmt: skip
    if "veg" in kinds:
        return (f"OpenStreetMap ne précise pas pour ces lieux le critère « {rest} » : présente-les comme les "
                "restaurants du secteur, et ne dis végétarien que celui dont la fiche le dit."
                if lang == "fr" else
                f"OpenStreetMap does not state '{rest}' for these places: present them as the restaurants of the "
                "area, and call vegetarian only one whose details say so.")  # fmt: skip
    if rest:
        return (f"Le critère « {rest} » n'est pas vérifié par OpenStreetMap : ne l'affirme pas." if lang == "fr"
                else f"'{rest}' is not checked by OpenStreetMap: do not claim it.")  # fmt: skip
    return ""


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
    query = query[:6000] if ";" in query else query[:200]
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
    qualifier = ""
    if ";" in query:
        from birds.harness.mapwords import plan_of

        every = [x.strip() for x in query.split(";") if x.strip()]
        # past MAX_LIST, nothing is looked up: the names are said « not shown », never dropped silently
        mode, names, not_shown = "list", every[:MAX_LIST], every[MAX_LIST:]
        got, failed = _lookup_list(geo.Geocoder(ctx, count=False), names, lang)
        places = [p for p in got if p is not None]
        missing = [n for i, (n, p) in enumerate(zip(names, got, strict=True)) if p is None and i not in failed]
        unchecked = [names[i] for i in sorted(failed)]
        title = ""  # the card says « N lieux »: the raw ask (up to 6000 characters) never fills the widget
        # the model (or the reading of the ask) says what to compute; the user's words are the fallback
        asked = str(args.get("plan") or "").strip().lower()
        said = getattr(ctx, "request", "") or ""
        for n in names:  # the words of the places themselves (« rue du Circuit ») never ask for a plan
            said = said.replace(n, " ")
        plan = asked if asked in ("order", "distances") else plan_of(said)
        plan = plan if len(places) >= 2 else ""
    else:
        cat = category(query)
        if cat is not None:
            query, qualifier = cat[0], cat[1]
        if near:
            # « aix »: several towns match; the most important one (a city before villages) is the likely meaning
            center = _anchor(g.search(near, limit=5, lang=lang), lang)
            if center is None:
                ctx.step_info = {"found": 0}
                return _none(near, lang)
        if center is not None and cat is not None:
            mode = "near"
            radii = _radii(center)
            want = TYPES.get(query)
            places = g.search(PHRASES.get(query, query), near=center, limit=20, lang=lang, radii=radii,
                              keep=(lambda p: (p.kind or "").lower() in want) if want else None)  # fmt: skip
            # the box's corners reach farther than its radius: nothing past the last radius is « near »
            places = [p for p in places if (p.distance_m or 0) <= radii[-1] * 1.2][:MAX_CARDS]
        elif center is not None:
            mode = "route"
            hits = g.search(query, limit=1, lang=lang)
            places = hits[:1]
            if places:
                places[0].distance_m = geo.distance_m(center.lat, center.lon, places[0].lat, places[0].lon)
                far = places[0].distance_m > FAR_M and (places[0].kind or "").lower() not in TOWN_KINDS
                if far and (places[0].importance or 0.0) < 0.4:
                    # a shop of that name 887 km away is not the one meant: the one around the anchor, or none
                    places = g.search(query, near=center, limit=1, lang=lang, radii=(TOWN_RADII[-1],))[:1]
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
        "query": query[:200],
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
        widget.update(missing=missing, unchecked=unchecked, not_shown=not_shown, plan=plan)
        fit_list(widget, LIST_BYTES)
        places = places[: len(widget["places"])]
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
    if mode == "list" and widget.get("not_shown"):
        lines.append(
            (
                "Non affichés (trop de lieux pour une carte ; dis-le et propose une autre carte pour eux) : "
                if lang == "fr"
                else "Not shown (too many places for one map; say so and offer another map for them): "
            )
            + " ; ".join(widget["not_shown"])
        )
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
    if qualifier:
        lines.append(_qualifier_note(qualifier, lang))
    lines.append(_tail(lang) + (f" Source à citer : [{n_src}]." if lang == "fr" else f" Source to cite: [{n_src}]."))
    return "\n".join(lines)


def plan_list(w: dict) -> None:
    """The visit order, legs, total and full-route link of a list card, from the places it shows (``w["plan"]``)."""
    pts = [(c["lat"], c["lon"]) for c in w["places"]]
    plan = w.get("plan") if len(pts) >= 2 else ""
    order = visit_order(pts) if plan == "order" else list(range(len(pts)))
    legs = [
        {"a": order[i] + 1, "b": order[i + 1] + 1, "m": geo.distance_m(*pts[order[i]], *pts[order[i + 1]])}
        for i in range(len(order) - 1)
    ]
    w.update(
        plan=plan,
        order=[i + 1 for i in order],
        legs=legs if plan else [],
        total_m=sum(x["m"] for x in legs) if plan else None,
        itinerary=itinerary_url([pts[i] for i in order]) if len(pts) >= 2 else "",
    )
    w.pop("matrix", None)
    if plan == "distances" and len(pts) <= 8:
        w["matrix"] = [[geo.distance_m(*a, *b) for b in pts] for a in pts]


def _size(w: dict) -> int:
    import json

    return len(json.dumps(w, ensure_ascii=False, separators=(",", ":")))


def fit_list(w: dict, budget: int) -> list[str]:
    """Plan a list card and keep it within ``budget`` bytes: the last places go first, their names join
    ``not_shown`` (before the names past MAX_LIST), and the order, legs, total and route are computed again on what
    is shown, so they never go through a place the card does not show. Returns the names dropped."""
    plan_list(w)
    dropped: list[str] = []
    while _size(w) > budget and len(w.get("places") or []) > 1:
        dropped.insert(0, str(w["places"].pop().get("name") or ""))
        plan_list(w)
        w["not_shown"] = [x for x in dropped if x] + [x for x in w.get("not_shown") or [] if x not in dropped]
    return dropped


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
