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
    assert abs(box[1] - box[3]) * 111 >= 4.5


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
