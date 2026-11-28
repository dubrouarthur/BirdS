"""find_places on a category near a town (« supermarchés à Saint-Cloud »): the OSM category around the anchor, never
a shop NAMED « supermarché » 887 km away (production report of 28/11/2026). No network: a fake Nominatim."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from birds.harness import Config, Context, geo, guard
from birds.harness.tools import TOOLS
from birds.harness.tools.places import category

SAINT_CLOUD = {
    "name": "Saint-Cloud",
    "lat": "48.8440",
    "lon": "2.2190",
    "type": "administrative",
    "importance": 0.58,
    "address": {"town": "Saint-Cloud", "postcode": "92210", "country_code": "fr"},
}
BERLIN_SHOP = {"name": "supermarché", "lat": "52.4990", "lon": "13.4250", "type": "clothes", "importance": 0.0001,
               "address": {"road": "Wiener Straße", "house_number": "16", "postcode": "10999", "city": "Berlin",
                           "country_code": "de"}}  # fmt: skip


def _shop(name, lat, lon, kind="supermarket", hours=""):
    return {"name": name, "lat": str(lat), "lon": str(lon), "type": kind, "category": "shop", "importance": 0.01,
            "osm_type": "node", "osm_id": 1, "extratags": {"opening_hours": hours} if hours else {},
            "address": {"road": "Boulevard de la République", "postcode": "92210", "town": "Saint-Cloud"}}  # fmt: skip


IN_TOWN = [
    _shop("Monoprix", 48.8455, 2.2180, hours="Mo-Sa 08:30-21:00"),
    _shop("Lidl", 48.8430, 2.2150),
    _shop("Carrefour City", 48.8470, 2.2230),
    _shop("Banc public", 48.8441, 2.2191, kind="bench"),
]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(guard, "resolve", lambda host: ["93.184.216.34"])
    geo.POLICY.reset()
    geo.POLICY.sleep = lambda s: None
    yield
    geo.POLICY.reset()


def ctx_for(tmp_path, seen):
    def handler(req: httpx.Request) -> httpx.Response:
        q = parse_qs(urlsplit(str(req.url)).query)
        seen.append(q)
        text = q.get("q", [""])[0].lower()
        if "saint-cloud" in text:
            data = [SAINT_CLOUD]
        elif "bounded" in q:
            data = (IN_TOWN if text in ("supermarket", "supermarché")
                    else [_shop("Pharmacie du Parc", 48.8450, 2.2200, kind="pharmacy")] if text == "pharmacy" else [])
        else:
            data = [BERLIN_SHOP] if "supermarch" in text else []
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(data).encode())

    cfg = Config(workspace=tmp_path, audit_file=None, ban_url="https://ban.invalid/search")
    return Context(config=cfg, http=httpx.Client(transport=httpx.MockTransport(handler)), lang="fr")


@pytest.mark.parametrize("q", ["supermarché", "supermarchés", "les supermarchés", "Supermarket", "supermarket"])
def test_category_in_the_users_words_is_the_osm_kind(q):
    assert category(q) == ("supermarket", "")


def test_category_qualifiers_and_names():
    assert category("pharmacie de garde") == ("pharmacy", "de garde")
    assert category("restaurants végétariens") == ("restaurant", "végétariens")
    assert category("distributeur") == ("atm", "")
    assert category("gare") == ("train station", "")
    assert category("station-service") == ("fuel", "")
    assert category("gare de Lyon") is None  # a name that starts with a kind word
    assert category("tour Eiffel") is None and category("Louvre ; Orsay") is None


@pytest.mark.parametrize(
    "q, kind",
    [
        ("pharmacie la plus proche", "pharmacy"),
        ("pharmacies les plus proches", "pharmacy"),
        ("nearest pharmacy", "pharmacy"),
        ("the nearest supermarket", "supermarket"),
        ("supermarchés à proximité", "supermarket"),
        ("supermarkets near me", "supermarket"),
        ("épicerie", "supermarket"),
        ("grocery stores", "supermarket"),
        ("la boulangerie la plus proche", "bakery"),
    ],
)
def test_nearest_and_grocery_wordings_are_the_category(q, kind):
    """The model writes « la plus proche » or « nearest » in the query (the search is already « near »): still the
    category around the anchor, never a name looked up across the world."""
    assert category(q) == (kind, "")


def test_nearest_wording_names_stay_names():
    assert category("gare de Lyon la plus proche") is None and category("Monoprix le plus proche") is None
    assert category("nearest") is None


def test_pharmacie_la_plus_proche_searches_the_category_around_the_town(tmp_path):
    ctx = ctx_for(tmp_path, [])
    TOOLS["find_places"]({"query": "pharmacie la plus proche", "near": "Saint-Cloud"}, ctx)
    w = ctx.step_info["widget"]
    assert w["mode"] == "near" and [p["name"] for p in w["places"]] == ["Pharmacie du Parc"]


def test_supermarches_a_saint_cloud_lists_the_category_around_the_town(tmp_path):
    seen = []
    ctx = ctx_for(tmp_path, seen)
    text = TOOLS["find_places"]({"query": "supermarché", "near": "Saint-Cloud"}, ctx)
    w = ctx.step_info["widget"]
    assert w["mode"] == "near" and w["query"] == "supermarket" and w["center"]["name"] == "Saint-Cloud"
    names = [p["name"] for p in w["places"]]
    assert set(names) == {"Monoprix", "Lidl", "Carrefour City"}  # the bench is dropped
    assert [p["distance_m"] for p in w["places"]] == sorted(p["distance_m"] for p in w["places"])
    assert all(p["distance_m"] <= 6000 for p in w["places"])
    assert "Berlin" not in text and "Mo-Sa 08:30-21:00" in text
    bounded = [q for q in seen if "bounded" in q]
    assert bounded and all(q["q"][0] == "supermarket" for q in bounded)  # never a world-wide name match
    # the box of a town is kilometres wide, not the 500 m of a street corner
    box = [float(x) for x in bounded[0]["viewbox"][0].split(",")]
    assert abs(box[1] - box[3]) * 111 >= 1.9


def test_a_name_far_away_is_not_the_one_near_the_anchor(tmp_path):
    seen = []
    ctx = ctx_for(tmp_path, seen)
    TOOLS["find_places"]({"query": "le supermarché bio", "near": "Saint-Cloud"}, ctx)  # a name: route mode
    w = (ctx.step_info or {}).get("widget") or {}
    assert not any("Berlin" in str(p.get("address")) for p in w.get("places") or [])


def test_anchor_prefers_france_in_a_french_conversation():
    from birds.harness.tools.places import _anchor

    gb = geo.Place("Ministère de la Défense", 51.50, -0.12, kind="government", importance=0.6, country_code="GB")
    fr = geo.Place("La Défense", 48.89, 2.24, kind="suburb", importance=0.56, country_code="FR")
    assert _anchor([gb, fr], "fr").name == "La Défense"
    assert _anchor([gb, fr], "en").name == "Ministère de la Défense"


def test_pharmacie_de_garde_tells_the_model_what_osm_cannot_say(tmp_path):
    ctx = ctx_for(tmp_path, [])
    out = TOOLS["find_places"]({"query": "pharmacie de garde", "near": "Saint-Cloud"}, ctx)
    assert "de garde" in out and "3237" in out


def test_the_same_places_found_twice_make_one_card(tmp_path):
    """Production: « Saint-Cloud » then « Saint-Cloud, France »: two find_places steps, the same card twice."""
    from datetime import datetime
    from types import SimpleNamespace

    from birds.web.widgets import build_widgets

    infos = []
    for near in ("Saint-Cloud", "Saint-Cloud, France"):
        ctx = ctx_for(tmp_path, [])
        TOOLS["find_places"]({"query": "supermarché", "near": near}, ctx)
        infos.append(ctx.step_info)
    steps = [SimpleNamespace(tool="find_places", info=i, error=None) for i in infos]
    ws = build_widgets(steps, "", "fr", datetime(2026, 11, 28, 10, 0), b"k")
    assert [w["type"] for w in ws] == ["places"]


def _near_card(tmp_path, query="supermarché"):
    from datetime import datetime
    from types import SimpleNamespace

    from birds.web.widgets import build_widgets

    ctx = ctx_for(tmp_path, [])
    TOOLS["find_places"]({"query": query, "near": "Saint-Cloud"}, ctx)
    steps = [SimpleNamespace(tool="find_places", info=ctx.step_info, error=None)]
    return build_widgets(steps, "", "fr", datetime(2026, 11, 28, 10, 0), b"k"), steps


def test_an_answer_that_gives_up_beside_the_card_is_written_from_the_results(tmp_path):
    from birds.web.rescue import check_places_answer

    widgets, steps = _near_card(tmp_path)
    bad = ("Je n'ai pas trouvé d'informations fiables sur les supermarchés à Saint-Cloud. Vérifiez sur une carte "
           "locale ou demandez à un voisin.")  # fmt: skip
    fixed = check_places_answer(bad, widgets, steps, "fr")
    assert fixed and "Monoprix" in fixed and "Lidl" in fixed and "voisin" not in fixed
    assert fixed.startswith("Voici 3 supermarchés autour de Saint-Cloud") and "Mo-Sa 08:30-21:00" in fixed
    good = "Le plus proche est Monoprix, boulevard de la République ; Lidl et Carrefour City sont à quelques minutes."
    assert check_places_answer(good, widgets, steps, "fr") is None


def test_pharmacie_de_garde_rewrite_keeps_the_duty_number(tmp_path):
    from birds.web.rescue import check_places_answer

    widgets, steps = _near_card(tmp_path, "pharmacie de garde")
    fixed = check_places_answer("Aucune pharmacie de garde n'est indiquée pour Saint-Cloud.", widgets, steps, "fr")
    assert "Pharmacie du Parc" in fixed and "3237" in fixed


def test_nothing_found_says_what_bird_searched_never_ask_a_neighbour(tmp_path):
    from types import SimpleNamespace

    from birds.web.rescue import check_places_answer

    ctx = ctx_for(tmp_path, [])
    TOOLS["find_places"]({"query": "boulangerie", "near": "Saint-Cloud"}, ctx)  # the fake has no bakery
    steps = [SimpleNamespace(tool="find_places", info=ctx.step_info, error=None)]
    fixed = check_places_answer("Rien sur la carte. Demandez à un voisin.", [], steps, "fr")
    assert fixed.startswith("J'ai cherché les boulangeries sur OpenStreetMap dans un rayon de 5,0 km autour de Saint")
    assert "élargir" in fixed
    assert check_places_answer("Aucune boulangerie n'est répertoriée ; je peux élargir la zone.", [], steps, "fr") is None


NEAR_CARD = [{"type": "places", "mode": "near", "query": "pharmacy", "center": {"name": "Saint-Cloud"},
              "places": [{"name": "Pharmacie du Parc", "address": "1 rue X", "distance_m": 200},
                         {"name": "Monoprix Saint-Cloud", "address": "2 bd", "distance_m": 300}]}]  # fmt: skip


@pytest.mark.parametrize(
    "answer, lang",
    [
        ("Voici les pharmacies : **Pharmacie du Parc** à 200 m. Je ne peux pas savoir laquelle est de garde ce soir : "
         "appelez le 3237.", "fr"),
        ("Le plus proche est le Monoprix, à 300 m, ouvert jusqu'à 21 h.", "fr"),
        ("The nearest is Pharmacie du Parc (200 m). I cannot find its Sunday hours.", "en"),
    ],
)  # fmt: skip
def test_a_good_answer_that_names_the_places_is_never_rewritten(answer, lang):
    """A caveat (« je ne peux pas savoir laquelle est de garde ») or a short name (« le Monoprix ») is not giving up:
    the model's answer stands, its 3237 included."""
    from birds.web.rescue import check_places_answer

    assert check_places_answer(answer, NEAR_CARD, [], lang) is None


def test_a_named_answer_loses_only_its_send_away_sentence():
    from birds.web.rescue import check_places_answer

    out = check_places_answer("Pharmacie du Parc, à 200 m. Demandez à un voisin pour les horaires.", NEAR_CARD, [], "fr")
    assert out == "Pharmacie du Parc, à 200 m."


def test_the_anchor_name_alone_is_not_naming_a_place():
    from birds.web.rescue import check_places_answer

    out = check_places_answer("Il y a une pharmacie à Saint-Cloud.", NEAR_CARD, [], "fr")
    assert out and "Pharmacie du Parc" in out and "Monoprix" in out


@pytest.mark.parametrize(
    "query, kind",
    [("3 meilleures pizzerias", "pizza"), ("les meilleures boulangeries", "bakery"), ("the best bakeries", "bakery"),
     ("top 5 restaurants", "restaurant")],
)  # fmt: skip
def test_a_ranked_category_is_the_category_with_a_rank_osm_cannot_check(query, kind):
    """« De Paris à pizzeria » (production, Chouette): « meilleures pizzerias » was read as a name."""
    assert category(query) == (kind, "les meilleures")
    assert category("Meilleurtaux") is None and category("Best Western") is None and category("Top Gun") is None


def test_ranked_kind_de_town_is_split_into_query_and_near():
    from birds.harness.coerce import _flat
    from birds.harness.intents import split_near

    assert split_near("3 meilleures pizzerias de Paris") == ("pizza", "Paris")
    assert split_near("best bakeries of Lyon") == ("bakery", "Lyon")
    assert split_near("gare de Lyon") is None and split_near("école des Mines") is None
    args, notes = {"query": "3 meilleures pizzerias de Paris"}, []
    _flat(args, "find_places", notes)
    assert args == {"query": "pizza les meilleures", "near": "Paris"} and category(args["query"])[1]


def test_a_rank_tells_the_model_osm_holds_no_ratings():
    from birds.harness.tools.places import _qualifier_note

    assert "ni notes ni avis" in _qualifier_note("les meilleures", "fr")
    assert "no ratings" in _qualifier_note("les meilleures", "en")


def test_anchor_prefers_the_very_name_asked():
    """« Montreuil » is Montreuil (93), not Montreuil-sur-Mer; « Valence » in English is not Valencia."""
    from birds.harness.tools.places import _anchor

    mer = geo.Place("Montreuil-sur-Mer", 50.46, 1.76, kind="administrative", importance=0.612, country_code="FR")
    m93 = geo.Place("Montreuil", 48.86, 2.44, kind="administrative", importance=0.576, country_code="FR")
    m28 = geo.Place("Montreuil", 48.78, 1.38, kind="administrative", importance=0.546, country_code="FR")
    assert _anchor([mer, m28, m93], "fr", "Montreuil").lat == 48.86
    es = geo.Place("Valencia", 39.47, -0.38, kind="administrative", importance=0.731, country_code="ES")
    fr = geo.Place("Valence", 44.93, 4.89, kind="administrative", importance=0.615, country_code="FR")
    assert _anchor([es, fr], "en", "Valence").name == "Valence"
    assert _anchor([es, fr], "en", "Valencia").name == "Valencia"
    assert _anchor([mer, m93], "fr", "Montreuil-sur-Mer").name == "Montreuil-sur-Mer"


def test_two_osm_points_of_one_place_make_one_card():
    from birds.harness.tools.places import _distinct

    a = geo.Place("A Tavola", 48.8400, 2.2400)
    b = geo.Place("A Tavola", 48.8401, 2.2401)
    c = geo.Place("A Tavola", 48.8600, 2.2600)  # another one, 2 km away
    assert [p.lat for p in _distinct([a, b, c])] == [48.84, 48.86]


def test_a_listed_place_the_tool_did_not_return_is_dropped():
    """« pharmacie de garde à Lyon 3e »: the answer listed the pharmacies found, then a hospital in Marseille."""
    from birds.web.rescue import check_places_answer

    answer = ("Voici les pharmacies :\n1. **Pharmacie du Parc** — 1 rue X — 200 m\n2. **Hôpital Nord** — Chemin des "
              "Bourrely, 13015 Marseille\n3. **Monoprix Saint-Cloud** — 300 m\n- Appelez le 3237 pour la garde.")
    out = check_places_answer(answer, NEAR_CARD, [], "fr")
    assert "Hôpital Nord" not in out and "Marseille" not in out
    assert "1. **Pharmacie du Parc**" in out and "2. **Monoprix Saint-Cloud**" in out and "3237" in out


def test_an_answer_listing_only_places_not_found_is_written_from_the_results():
    from birds.web.rescue import check_places_answer

    answer = "Voici :\n- **Pharmacie du Parc**, 200 m\n- **Pharmacie Centrale** — 4 rue Y, 69003 Lyon"
    assert check_places_answer(answer, NEAR_CARD, [], "fr") is not None  # one result named: only the intruder goes
    only_wrong = "Voici :\n- **Hôpital Nord** — 13015 Marseille\n- **Pharmacie Centrale** — 69003 Lyon"
    out = check_places_answer(only_wrong, NEAR_CARD, [], "fr")
    assert out is None or ("Hôpital Nord" not in out and "Pharmacie du Parc" in out)


def test_a_duty_pharmacy_answer_always_carries_the_3237(tmp_path):
    """« pharmacie de garde à Lyon 3e »: the model listed pharmacies and said « le reste est fermé », no 3237."""
    from birds.web.rescue import check_places_answer

    widgets, steps = _near_card(tmp_path, "pharmacie de garde")
    out = check_places_answer("La plus proche : **Pharmacie du Parc**, à 130 m.", widgets, steps, "fr")
    assert out.startswith("La plus proche : **Pharmacie du Parc**") and "3237" in out
    assert check_places_answer("**Pharmacie du Parc**, à 130 m ; la nuit, le 3237.", widgets, steps, "fr") is None


def test_de_garde_in_the_users_words_holds_when_the_model_drops_it(tmp_path):
    ctx = ctx_for(tmp_path, [])
    ctx.request = "pharmacie de garde à Saint-Cloud"
    text = TOOLS["find_places"]({"query": "pharmacy", "near": "Saint-Cloud"}, ctx)
    assert "3237" in text and "3237" in ctx.step_info["caveat"]


def test_a_spot_in_a_town_is_geocoded_as_spot_comma_town(tmp_path):
    """« place Bellecour à Lyon », written whole, was France Miniature's « Place Bellecour à Lyon » in Élancourt."""
    seen = []
    ctx = ctx_for(tmp_path, seen)
    TOOLS["find_places"]({"query": "boulangerie", "near": "Saint-Cloud à Paris"}, ctx)
    assert seen[0]["q"][0] == "Saint-Cloud, Paris"
