"""A weak top geocoder hit (« place Bellecour à Lyon » -> the France Miniature replica in Élancourt) is checked
again: Nominatim with « à » read as a comma, then Photon, the most important strong hit wins."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from birds.harness import geo
from birds.harness.config import Config, Context
from birds.harness.tools.places import find_places

MINIATURE = {  # what Nominatim really answers for « place Bellecour à Lyon » (2026-11-28)
    "lat": "48.7656",
    "lon": "1.9745",
    "name": "Place Bellecour à Lyon",
    "category": "tourism",
    "type": "attraction",
    "importance": 6.2e-05,
    "osm_type": "N",
    "osm_id": 1,
    "address": {"tourism": "Place Bellecour à Lyon", "village": "Élancourt", "postcode": "78990"},
}
BELLECOUR = {
    "lat": "45.7578",
    "lon": "4.8320",
    "name": "Place Bellecour",
    "category": "place",
    "type": "square",
    "importance": 0.4027,
    "osm_type": "W",
    "osm_id": 2,
    "address": {"square": "Place Bellecour", "city": "Lyon", "postcode": "69002"},
}
PHOTON_BELLECOUR = {
    "geometry": {"coordinates": [4.8321, 45.7579]},
    "properties": {"name": "Place Bellecour", "osm_key": "place", "osm_value": "square", "postcode": "69002",
                   "city": "Lyon", "osm_type": "W", "osm_id": 2},
}  # fmt: skip


@pytest.fixture(autouse=True)
def fresh_cache():
    geo.POLICY.reset()
    yield
    geo.POLICY.reset()


def make_ctx(tmp_path, answers, asked, boxes=None):
    boxes = [] if boxes is None else boxes

    def recorded(url):
        parts = urlsplit(url)
        q = parse_qs(parts.query).get("q", [""])[0]
        host = "photon" if "photon" in parts.netloc else "nominatim"
        asked.append((host, q))
        boxes.extend(parse_qs(parts.query).get("viewbox", []))
        return answers.get((host, q), [] if host == "nominatim" else {"features": []})

    ctx = Context(config=Config(workspace=tmp_path, audit_file=None), http=httpx.Client(), lang="fr")
    ctx.recorded = recorded
    return ctx


def test_bellecour_weak_hit_is_replaced_by_the_real_square(tmp_path):
    asked = []
    ctx = make_ctx(
        tmp_path,
        {("nominatim", "place Bellecour à Lyon"): [MINIATURE], ("nominatim", "place Bellecour, Lyon"): [BELLECOUR]},
        asked,
    )
    hits = geo.Geocoder(ctx).search("place Bellecour à Lyon", limit=5)
    assert hits and "69002" in hits[0].address
    assert all("78990" not in h.address for h in hits)
    assert ("photon", "place Bellecour, Lyon") not in asked  # a strong hit already: no third lookup


def test_photon_rescues_when_nominatim_stays_weak(tmp_path):
    asked = []
    ctx = make_ctx(
        tmp_path,
        {("nominatim", "place Bellecour à Lyon"): [MINIATURE], ("photon", "place Bellecour, Lyon"): {
            "features": [PHOTON_BELLECOUR]}},
        asked,
    )  # fmt: skip
    hits = geo.Geocoder(ctx).search("place Bellecour à Lyon", limit=5)
    assert hits[0].provider == "photon" and "69002" in hits[0].address


def test_weak_hit_kept_when_nothing_better(tmp_path):
    ctx = make_ctx(tmp_path, {("nominatim", "place Bellecour à Lyon"): [MINIATURE]}, [])
    hits = geo.Geocoder(ctx).search("place Bellecour à Lyon", limit=5)
    assert hits and "78990" in hits[0].address  # never an empty answer because the hit looked weak


def test_strong_hit_needs_no_second_opinion(tmp_path):
    asked = []
    ctx = make_ctx(tmp_path, {("nominatim", "place Bellecour, Lyon"): [BELLECOUR]}, asked)
    hits = geo.Geocoder(ctx).search("place Bellecour, Lyon", limit=3)
    assert "69002" in hits[0].address and len(asked) == 1


def test_important_attraction_is_not_replaced_by_photon(tmp_path):
    disney = dict(MINIATURE, name="Disneyland Paris", type="theme_park", importance=0.6,
                  address={"city": "Chessy", "postcode": "77700"})  # fmt: skip
    hotel = {"geometry": {"coordinates": [2.78, 48.87]},
             "properties": {"name": "Disneyland Hotel", "osm_key": "tourism", "osm_value": "hotel"}}  # fmt: skip
    asked = []
    ctx = make_ctx(
        tmp_path, {("nominatim", "Disneyland Paris"): [disney], ("photon", "Disneyland Paris"): {"features": [hotel]}},
        asked,
    )  # fmt: skip
    hits = geo.Geocoder(ctx).search("Disneyland Paris", limit=3)
    assert hits[0].name == "Disneyland Paris" and not any(h == "photon" for h, _ in asked)


def test_find_places_near_bellecour_searches_around_lyon(tmp_path):
    asked, boxes = [], []
    ctx = make_ctx(
        tmp_path,
        {("nominatim", "place Bellecour à Lyon"): [MINIATURE], ("nominatim", "place Bellecour, Lyon"): [BELLECOUR]},
        asked,
        boxes,
    )
    ctx.request = "Des boulangeries près de la place Bellecour à Lyon"
    find_places({"query": "bakery", "near": "place Bellecour à Lyon"}, ctx)
    assert ("nominatim", "bakery") in asked and boxes
    west, north, east, south = (float(v) for v in boxes[0].split(","))
    assert west < 4.832 < east and south < 45.7578 < north  # around the real square, not Élancourt (1.97, 48.77)
