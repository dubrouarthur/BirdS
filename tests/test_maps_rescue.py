"""Maps (wave 2) end to end: lists of up to 25 places on recorded provider answers, a visit order, the card sent
as soon as the tool returns (``widget`` event), and an answer written from the results when the model fails."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from birds.harness import Config, Context, FakeClient, followup, geo
from birds.harness.guard import ToolError
from birds.harness.llm import EndpointError
from birds.harness.tools.places import find_places, itinerary_url, visit_order
from birds.web import rescue
from birds.web.backends import HarnessBackend
from birds.web.demo_widgets import recorded
from birds.web.server import create_app
from birds.web.settings import Settings

OWNER = "montre sur une carte : 10 rue de Rivoli Paris ; 5 place Bellecour Lyon ; 1 La Canebière Marseille"


class Tok:
    def apply_chat_template(self, messages, tools=None, **_):
        return json.dumps({"tools": [t["function"]["name"] for t in tools or []], "messages": messages})


class Down(FakeClient):
    """The endpoint fails at the first generation (paused, in error, or out of time)."""

    def __init__(self, kind="endpoint_down"):
        super().__init__([])
        self.kind = kind

    def generate(self, prompt, max_tokens, stop, **kw):
        self.prompts.append(prompt)
        raise EndpointError(self.kind, "the endpoint is paused")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every provider answer comes from the recordings of birds/web/demo_data (no network)."""
    monkeypatch.setattr(geo, "get_json", lambda ctx, url, **kw: recorded(url))
    geo.POLICY.reset()


def sse(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [json.loads(f[6:]) for f in response.text.split("\n\n") if f.startswith("data: ")]


def chat(llm, text, history=()):
    app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(llm, Tok()))
    with TestClient(app) as c:
        body = {"messages": [*history, {"role": "user", "content": text}], "lang": "fr"}
        return sse(c.post("/api/chat", json=body))


def ctx(request=""):
    return Context(
        config=Config(workspace=Path(tempfile.gettempdir()), audit_file=None), http=None, lang="fr", request=request
    )


# --------------------------------------------------------------------------- the tool


def test_the_owner_example_puts_every_address_on_one_map():
    c = ctx(OWNER)
    text = find_places({"query": "10 rue de Rivoli Paris ; 5 place Bellecour Lyon ; 1 La Canebière Marseille"}, c)
    w = c.step_info["widget"]
    assert w["mode"] == "list" and [p["n"] for p in w["places"]] == [1, 2, 3] and w["missing"] == []
    assert [p["address"].split()[-1] for p in w["places"]] == ["Paris", "Lyon", "Marseille"]
    assert "3 lieu(x) placé(s) sur une carte" in text and c.geo_calls == 0  # BAN lookups of a list: their own cap
    assert w["itinerary"].startswith("https://map.project-osrm.org/?loc=48.85")


def test_missing_items_are_listed_honestly():
    c = ctx("carte")
    text = find_places({"query": "20 avenue de Ségur Paris ; 99 rue Inexistante Nullepart ; Lyon"}, c)
    w = c.step_info["widget"]
    assert len(w["places"]) == 2 and w["missing"] == ["99 rue Inexistante Nullepart"]
    assert "Introuvables (dis-le) : 99 rue Inexistante Nullepart" in text


def test_ten_towns_are_geocoded_and_ordered_on_request():
    towns = "Paris ; Lyon ; Marseille ; Bordeaux ; Nantes ; Lille ; Strasbourg ; Toulouse ; Nice ; Rennes"
    c = ctx("dans quel ordre visiter ces villes ?")
    text = find_places({"query": towns}, c)
    w = c.step_info["widget"]
    assert len(w["places"]) == 10 and w["plan"] == "order" and sorted(w["order"]) == list(range(1, 11))
    assert w["order"][0] == 1 and len(w["legs"]) == 9 and w["total_m"] == sum(x["m"] for x in w["legs"])
    assert "Ordre de visite proposé" in text and "Ce n'est pas un temps de trajet" in text


def test_visit_order_is_a_short_open_path():
    # a line of points given out of order: the order walks along it
    pts = [(45.0, 4.0), (45.0, 7.0), (45.0, 5.0), (45.0, 6.0)]
    assert visit_order(pts) == [0, 2, 3, 1]
    assert itinerary_url([(1, 2), (3, 4)]).count("loc=") == 2


def test_distances_plan_gives_a_matrix_for_a_few_places():
    c = ctx("distances entre Lyon, Grenoble et Annecy")
    find_places({"query": "Lyon ; Grenoble ; Annecy"}, c)
    w = c.step_info["widget"]
    assert w["plan"] == "distances" and len(w["matrix"]) == 3 and w["matrix"][0][0] == 0


def test_the_plan_argument_is_read_and_checked():
    # the model (or the reading of the ask) passes the plan: no need for the words to be in the request
    c = ctx("montre-les")
    find_places({"query": "Lyon ; Grenoble ; Annecy", "plan": "order"}, c)
    assert c.step_info["widget"]["plan"] == "order"
    c = ctx("montre-les")
    find_places({"query": "Lyon ; Grenoble ; Annecy", "plan": "itinerary"}, c)  # not in the enum: ignored
    assert c.step_info["widget"]["plan"] == ""


# --------------------------------------------------------------------------- independent of the model


def test_the_card_is_sent_as_soon_as_the_tool_returns():
    events = chat(FakeClient(["Voici les trois adresses sur la carte [1]."]), OWNER)
    kinds = [e["type"] for e in events]
    assert kinds.index("widget") < kinds.index("answer")
    (live,) = [e for e in events if e["type"] == "widget"]
    assert live["widgets"][0]["type"] == "places" and live["widgets"][0]["map"]["src"].startswith("/api/map?t=")
    ans = next(e for e in events if e["type"] == "answer")
    assert len(ans["widgets"]) == 1 and "fallback" not in ans  # the answer lists the card once


@pytest.mark.parametrize("kind", ["endpoint_down", "server", "unreachable"])
def test_a_failed_model_after_a_pre_call_still_answers_from_the_results(kind):
    events = chat(Down(kind), OWNER)
    assert not [e for e in events if e["type"] == "error"]
    ans = next(e for e in events if e["type"] == "answer")
    assert ans["content"] == "Voici les 3 lieux sur la carte, dans l'ordre donné."
    assert ans["fallback"] == rescue.NOTE["fr"] and ans["widgets"][0]["mode"] == "list"
    assert "find_places" in ans["memo"]  # « et à Lyon ? » can still lean on it


def test_out_of_time_after_a_pre_call_answers_from_the_results():
    events = chat(Down("timeout"), "restaurants près de la gare de Lyon")
    ans = next(e for e in events if e["type"] == "answer")
    assert ans["content"].startswith("Voici 8 restaurants autour de Gare de Lyon") and ans["fallback"]


def test_a_failed_model_with_nothing_found_is_still_an_error():
    events = chat(Down(), "où est la boutique imaginaire de Zzyzx ?")
    assert [e for e in events if e["type"] == "error"]


def test_summary_text_covers_each_card():
    assert rescue.summary_text([{"type": "fx", "amount": 100, "from": "USD", "to": "EUR", "result": 92.1,
                                 "date": "2026-11-27"}], "fr") == "100 USD = 92.1 EUR (taux BCE du 2026-11-27)."  # fmt: skip
    route = {"type": "places", "mode": "route", "distance_m": 391500, "places": [{"name": "Lyon"}, {"name": "Paris"}]}
    assert rescue.summary_text([route], "fr").startswith("Lyon et Paris sont à 391,5 km à vol d'oiseau")
    miss = {"type": "places", "mode": "list", "places": [{"name": "A"}, {"name": "B"}], "missing": ["x", "y"]}
    assert rescue.summary_text([miss], "fr").endswith("2 adresses introuvables : x ; y.")


# --------------------------------------------------------------------------- « autour de moi »


def test_near_me_asks_for_a_place_then_the_reply_searches_around_it():
    llm = FakeClient(["Près de quelle adresse ou de quelle gare voulez-vous chercher une pharmacie ?"])
    events = chat(llm, "une pharmacie autour de moi")
    prompt = json.loads(llm.prompts[0])
    assert (
        "find_places" not in prompt["tools"]
        and "position de l'utilisateur est inconnue" in prompt["messages"][-1]["content"]
    )
    assert not [e for e in events if e["type"] == "step"]  # nothing geocoded
    ans = next(e for e in events if e["type"] == "answer")
    prev = followup.previous([{"role": "assistant", "content": ans["content"], "memo": ans["memo"]}])
    assert prev == {"tool": "find_places", "args": {"query": "pharmacy"}}
    got = followup.resolve("à la gare de Lyon", prev, "fr")
    assert (got.mode, got.args) == ("near", {"query": "pharmacy", "near": "gare de Lyon"})


# --------------------------------------------------------------------------- a failed lookup is not « not found »


def _failing(monkeypatch, fail):
    """Provider answers from the recordings, except the URLs for which ``fail(url)`` raises."""

    def get_json(ctx, url, **kw):
        fail(url)
        return recorded(url)

    monkeypatch.setattr(geo, "get_json", get_json)


def _http_503(url):
    if "Inexistante" in url:
        raise ToolError("HTTP 503")


def test_a_503_is_reported_as_not_checked_never_as_not_found(monkeypatch):
    _failing(monkeypatch, _http_503)
    c = ctx("carte")
    text = find_places({"query": "20 avenue de Ségur Paris ; 99 rue Inexistante Nullepart ; Lyon"}, c)
    w = c.step_info["widget"]
    assert len(w["places"]) == 2 and w["missing"] == [] and w["unchecked"] == ["99 rue Inexistante Nullepart"]
    assert "Introuvables" not in text and "Non vérifiés (service de cartes indisponible" in text
    lines = " ".join(rescue.places_lines(w, "fr"))
    assert "1 lieu non vérifié (service de cartes indisponible) : 99 rue Inexistante Nullepart" in lines
    assert "introuvable" not in lines


def test_a_busy_queue_is_reported_as_not_checked(monkeypatch):
    def busy(url):
        if "nominatim" in url or "photon" in url:  # the 1.1 s queue of the OSMF services is past MAX_WAIT
            geo.POLICY.next_at[geo.httpx_host(url)] = geo.POLICY.clock() + 60
            geo.POLICY.wait_turn(geo.httpx_host(url))

    _failing(monkeypatch, busy)
    c = ctx("carte")
    text = find_places({"query": "Lyon ; Musée Imaginaire du Quai"}, c)
    w = c.step_info["widget"]
    assert w["unchecked"] == ["Musée Imaginaire du Quai"] and w["missing"] == []
    assert "Non vérifiés" in text and "Introuvables" not in text


def test_when_nothing_could_be_checked_the_tool_says_the_service_failed(monkeypatch):
    def down(url):
        raise ToolError("HTTP 503")

    _failing(monkeypatch, down)
    with pytest.raises(ToolError, match="unavailable"):
        find_places({"query": "Lyon ; Marseille"}, ctx("carte"))
    with pytest.raises(ToolError, match="unavailable"):
        find_places({"query": "tour Eiffel"}, ctx("où est la tour Eiffel"))


def test_an_empty_answer_is_still_not_found(monkeypatch):
    c = ctx("carte")
    find_places({"query": "Lyon ; 99 rue Inexistante Nullepart"}, c)
    assert c.step_info["widget"]["missing"] == ["99 rue Inexistante Nullepart"]
    assert c.step_info["widget"]["unchecked"] == []
