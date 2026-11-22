"""Result widgets: routed tools + prefill, geocoding policy, tools on recorded provider answers, /api/map and
/api/icon, event card, source previews. No network: httpx.MockTransport serves the recorded fixtures."""

import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from birds.harness import Agent, Config, Context, FakeClient, geo, guard
from birds.harness.tools import TOOLS
from birds.harness.tools.fx import parse_ecb
from birds.tools import BIRD_TOOL_NAMES, EXTRA_TOOL_NAMES
from birds.web import demo_widgets, mapimg, tokens
from birds.web.server import create_app
from birds.web.settings import Settings
from birds.web.widgets import build_widgets, enrich_sources, event_widget

DATA = Path(__file__).resolve().parents[1] / "birds" / "web" / "demo_data"
FIX = Path(__file__).parent / "fixtures" / "widgets"
PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 11, 22, 10, 0, tzinfo=PARIS)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(guard, "resolve", lambda host: ["93.184.216.34"])
    geo.POLICY.reset()
    geo.POLICY.sleep = lambda s: None
    yield
    geo.POLICY.reset()
    geo.POLICY.sleep = __import__("time").sleep


def provider_transport(seen):
    """Serves the recorded provider answers (same routing as the demo) and records every request."""

    def handler(req: httpx.Request) -> httpx.Response:
        host = req.headers.get("host", req.url.host)
        seen.append(req)
        url = f"https://{host}{req.url.raw_path.decode()}"
        data = demo_widgets.recorded(url)
        if isinstance(data, str):
            return httpx.Response(200, headers={"content-type": "text/xml"}, content=data.encode())
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(data).encode())

    return httpx.MockTransport(handler)


def ctx_for(seen, tmp_path, lang="fr", **cfg):
    config = Config(workspace=tmp_path, audit_file=None, **cfg)
    return Context(config=config, http=httpx.Client(transport=provider_transport(seen)), lang=lang)


# ---------------------------------------------------------------- tools on recorded data


def test_find_places_near_sorts_by_distance_and_cites(tmp_path):
    seen = []
    ctx = ctx_for(seen, tmp_path)
    text = TOOLS["find_places"]({"query": "restaurant", "near": "gare de Lyon"}, ctx)
    w = ctx.step_info["widget"]
    d = [p["distance_m"] for p in w["places"]]
    assert w["mode"] == "near" and len(d) == 8 and d == sorted(d)
    assert w["places"][0]["name"] == "Gare aux vins" and "26 Boulevard Diderot, 75012 Paris" in text
    assert "ne donne ni note, ni prix" in text and "[1]" in text
    hosts = {r.url.host for r in seen}
    assert hosts == {"93.184.216.34"} or hosts <= {"nominatim.openstreetmap.org"}
    box = [r for r in seen if "viewbox" in r.url.params]
    assert box and box[0].url.params["bounded"] == "1"
    for r in seen:  # only our generic headers upstream
        assert r.headers["user-agent"] == "BirdHarness/0.1 (+geo)"
        assert "cookie" not in r.headers and "referer" not in r.headers and "authorization" not in r.headers


def test_find_places_address_goes_to_ban(tmp_path):
    seen = []
    ctx = ctx_for(seen, tmp_path)
    TOOLS["find_places"]({"query": "20 avenue de Ségur 75007 Paris"}, ctx)
    w = ctx.step_info["widget"]
    assert w["provider"] == "ban" and w["places"][0]["address"].startswith("20 Avenue de Ségur")
    assert any(r.headers["host"] == "data.geopf.fr" for r in seen)


def test_find_places_falls_back_to_photon_and_list_mode(tmp_path):
    seen = []
    ctx = ctx_for(seen, tmp_path, nominatim_url="https://nominatim.openstreetmap.org/search?x=")
    ctx.recorded = lambda url: [] if "nominatim" in url else demo_widgets.recorded(url)
    TOOLS["find_places"]({"query": "tour Eiffel"}, ctx)
    assert ctx.step_info["widget"]["provider"] == "photon"
    ctx2 = ctx_for([], tmp_path)
    TOOLS["find_places"]({"query": "Lyon Part-Dieu ; Lille Europe ; Nantes"}, ctx2)
    names = [p["name"] for p in ctx2.step_info["widget"]["places"]]
    assert ctx2.step_info["widget"]["mode"] == "list" and names[0] == "Lyon Part-Dieu" and names[2] == "Nantes"


def test_nothing_found_gives_no_widget(tmp_path):
    ctx = ctx_for([], tmp_path)
    text = TOOLS["find_places"]({"query": "zzz introuvable"}, ctx)
    assert "n'invente pas" in text and "widget" not in (ctx.step_info or {})


def test_places_cap_per_run(tmp_path):
    ctx = ctx_for([], tmp_path)
    for _ in range(2):
        TOOLS["find_places"]({"query": "tour Eiffel"}, ctx)
    with pytest.raises(guard.ToolError):
        TOOLS["find_places"]({"query": "tour Eiffel"}, ctx)


def test_rate_limit_and_cache(tmp_path):
    clock = [100.0]
    waits = []
    geo.POLICY.clock, geo.POLICY.sleep = (lambda: clock[0]), waits.append
    try:
        seen = []
        ctx = ctx_for(seen, tmp_path)
        geo.Geocoder(ctx).nominatim("Nantes")
        geo.Geocoder(ctx).nominatim("Lille Europe")
        assert waits and abs(waits[0] - 1.1) < 1e-6  # second call waited for the 1.1 s spacing
        n = len(seen)
        geo.Geocoder(ctx).nominatim("Nantes")  # cached: no upstream request
        assert len(seen) == n
        geo.POLICY.next_at["nominatim.openstreetmap.org"] = clock[0] + 10
        with pytest.raises(guard.ToolError):
            geo.Geocoder(ctx).nominatim("Brest")  # > 3 s of waiting: refused rather than queued
    finally:
        geo.POLICY.clock = __import__("time").monotonic


def test_per_run_lookup_cap(tmp_path):
    ctx = ctx_for([], tmp_path)
    ctx.geo_calls = geo.MAX_LOOKUPS_PER_RUN
    with pytest.raises(guard.ToolError):
        geo.Geocoder(ctx).nominatim("Quimper")


def test_find_company_payload_and_privacy(tmp_path):
    ctx = ctx_for([], tmp_path)
    text = TOOLS["find_company"]({"name": "383 474 814"}, ctx)
    w = ctx.step_info["widget"]
    assert w["siren"] == "383474814" and w["legal_form"] == "SAS" and w["lat"] and w["address"]
    assert "annuaire-entreprises.data.gouv.fr/entreprise/383474814" in text
    assert "dirigeant" not in json.dumps(w).lower().replace("#dirigeants", "")
    record = json.loads((DATA / "entreprises_siren.json").read_text())["results"][0]
    sole = dict(record, nature_juridique="1000", siren="732829320")
    ctx2 = ctx_for([], tmp_path)
    ctx2.recorded = lambda url: {"results": [sole]}
    TOOLS["find_company"]({"name": "732829320"}, ctx2)
    w2 = ctx2.step_info["widget"]
    assert w2["natural_person"] and not w2["address"] and w2["lat"] is None and w2["finances"] is None
    assert build_widgets([SimpleNamespace(info=ctx2.step_info, error=None)], "", "fr", NOW, b"k")[0]["map"] is None


def test_convert_currency_ecb(tmp_path):
    ctx = ctx_for([], tmp_path)
    text = TOOLS["convert_currency"]({"amount": 1200, "from": "USD", "to": "EUR"}, ctx)
    w = ctx.step_info["widget"]
    assert w["result"] == 1091.9 and w["date"] == "2026-11-20" and "1 091,90 EUR" in text
    ctx2 = ctx_for([], tmp_path, lang="en")
    TOOLS["convert_currency"]({"amount": 100, "from": "GBP", "to": "USD"}, ctx2)
    assert ctx2.step_info["widget"]["result"] == round(100 * 1.0990 / 0.83735, 2)
    with pytest.raises(guard.ToolError):
        TOOLS["convert_currency"]({"from": "EUR", "to": "XAF"}, ctx_for([], tmp_path))
    with pytest.raises(guard.Blocked):
        parse_ecb('<!DOCTYPE x [<!ENTITY a "b">]><x/>')


def test_coercion_of_model_calls():
    args, err = guard.validate_args("find_places", {"q": "restaurants près de la gare de Lyon"}, EXTRA_TOOL_NAMES)
    assert err is None and args == {"query": "restaurant", "near": "gare de Lyon"}
    args, err = guard.validate_args(
        "convert_currency", {"amount": "1 200,50", "from_currency": "dollars", "to": "eur"}, EXTRA_TOOL_NAMES
    )
    assert err is None and args == {"amount": 1200.5, "from": "USD", "to": "EUR"}
    args, err = guard.validate_args("find_company", {"siren": "383474814"}, EXTRA_TOOL_NAMES)
    assert err is None and args == {"name": "383474814"}


# ---------------------------------------------------------------- routing and prefill


class Tok:
    def apply_chat_template(
        self, messages, tools=None, enable_thinking=False, tokenize=False, add_generation_prompt=False
    ):
        return json.dumps(
            {"tools": [t["function"]["name"] for t in tools or []], "messages": messages}, ensure_ascii=False
        )


def agent(tmp_path, outputs, **cfg):
    seen = []
    config = Config(workspace=tmp_path, audit_file=None, **cfg)
    a = Agent(FakeClient(outputs), Tok(), config, search=None, http=httpx.Client(transport=provider_transport(seen)))
    return a, seen


def test_place_ask_is_prefilled_and_web_withdrawn(tmp_path):
    a, _ = agent(tmp_path, ["Voici les restaurants les plus proches [1]."])
    run = a.run("Restaurants près de la gare de Lyon")
    step = run.steps[0]
    assert step.tool == "find_places" and step.info["auto"] and step.arguments["near"] == "gare de Lyon"
    prompt = json.loads(a.llm.prompts[0])
    assert (
        "find_places" in prompt["tools"] and "web_search" not in prompt["tools"] and "read_page" not in prompt["tools"]
    )
    assert prompt["messages"][-2]["tool_calls"][0]["function"]["name"] == "find_places"
    assert run.answer.startswith("Voici")


def test_hint_only_offers_the_tool(tmp_path):
    a, seen = agent(tmp_path, ["Je n'ai pas de lieu précis."])
    run = a.run("Et des hôtels près de là ?")
    assert not run.steps and not seen
    assert "find_places" in json.loads(a.llm.prompts[0])["tools"]


def test_ordinary_turn_keeps_the_trained_tool_block(tmp_path):
    a, _ = agent(tmp_path, ["Bonjour."])
    a.run("Écris un mail de relance à Paul")
    tools = json.loads(a.llm.prompts[0])["tools"]
    assert tools == [n for n in BIRD_TOOL_NAMES if n in tools] and not set(tools) & set(EXTRA_TOOL_NAMES)


def test_geo_off_withdraws_the_tools(tmp_path):
    a, seen = agent(tmp_path, ["ok"], widgets=False)
    run = a.run("Restaurants près de la gare de Lyon")
    assert not run.steps and not seen
    assert not set(json.loads(a.llm.prompts[0])["tools"]) & set(EXTRA_TOOL_NAMES)


@pytest.mark.parametrize(
    "text",
    [
        "Où est le contrat de Paul Martin ?",
        "Donne-moi l'adresse de Jean Dupont, mon collègue",
        "Adresse de facturation du client Dupont ?",
        "Where is the Q3 report?",
        "c'est où la réunion de demain ?",
        "where does John Smith live",
        "Où sont les fichiers de la compta ?",
    ],
)
def test_office_questions_are_never_sent_to_a_geocoder(tmp_path, text):
    a, seen = agent(tmp_path, ["Je ne peux pas chercher dans vos fichiers."])
    run = a.run(text)
    assert not seen and not run.steps
    tools = json.loads(a.llm.prompts[0])["tools"]
    assert "find_places" not in tools


def test_attachment_with_place_words_is_only_offered_and_file_text_is_refused(tmp_path):
    call = "<tool_call>\n<function=find_places>\n<parameter=query>\n12 rue de la Paix, 75002 Paris\n</parameter>\n</function>\n</tool_call>"
    a, seen = agent(tmp_path, [call, "Je ne peux pas géocoder une adresse lue dans le fichier."])
    text = "Affiche le lieu de la réunion de ce PDF sur une carte"
    run = a.run(text, request_text=text, attached=True)
    assert "find_places" in json.loads(a.llm.prompts[0])["tools"]
    assert not seen and run.steps and run.steps[0].error and "attached" in run.steps[0].error


def test_attachment_typed_place_is_still_looked_up(tmp_path):
    call = (
        "<tool_call>\n<function=find_places>\n<parameter=query>\nrestaurant\n</parameter>\n"
        "<parameter=near>\ngare de Lyon\n</parameter>\n</function>\n</tool_call>"
    )
    a, seen = agent(tmp_path, [call, "Voici [1]."])
    text = "Restaurants près de la gare de Lyon pour les invités de la liste jointe"
    run = a.run(text, request_text=text, attached=True)
    assert seen and run.steps[0].tool == "find_places" and not run.steps[0].error


def test_attachment_address_is_not_geocoded(tmp_path):
    a, seen = agent(tmp_path, ["ok"])
    a.run("Résume ce document", request_text="Résume ce document", attached=True)
    assert not seen


# ---------------------------------------------------------------- widgets and maths


def test_fit_and_mercator():
    assert geo.fit([(48.85, 2.29)])[1] == 16
    assert geo.fit([(48.85, 2.29)], single=13)[1] == 13
    (lat, lon), z = geo.fit([(45.76, 4.86), (50.64, 3.07), (47.22, -1.55)])
    assert 4 <= z <= 6 and 45 < lat < 51
    x, y = geo.world_xy(0, 0, 1)
    assert (x, y) == (256, 256)
    assert geo.unproject(*geo.world_xy(48.8, 2.3, 15), 15) == pytest.approx((48.8, 2.3))


def test_build_widgets_signs_a_map():
    ctx_info = {"widget": {"type": "places", "mode": "where", "places": [{"n": 1, "lat": 48.8, "lon": 2.3}],
                           "single_kind": "tower"}, "auto": True}  # fmt: skip
    w = build_widgets([SimpleNamespace(info=ctx_info, error=None)], "", "fr", NOW, b"secret")[0]
    assert w["auto"] and w["map"]["z"] == 16 and w["map"]["src"].startswith("/api/map?t=")
    p = tokens.verify(w["map"]["src"].split("t=", 1)[1], b"secret")
    assert p["k"] == "map" and p["c"] == [48.8, 2.3]


@pytest.mark.parametrize(
    "text,title,start,warn",
    [
        ("Organise une réunion avec Paul jeudi prochain à 14h", "Réunion avec Paul", "2026-11-26T14:00:00+01:00", None),
        (
            "Cale un déjeuner avec l'équipe le 25 décembre à midi",
            "Déjeuner avec l'équipe",
            "2026-12-25T12:00:00+01:00",
            "holiday",
        ),
        ("rdv chez le client samedi à 10h", "Rendez-vous", "2026-11-28T10:00:00+01:00", "weekend"),
    ],
)
def test_event_widget(text, title, start, warn):
    holidays = lambda y: json.loads((DATA / "feries_metropole_2026.json").read_text())  # noqa: E731
    w = event_widget(text, NOW, "fr", holidays=holidays)
    assert w["title"] == title and w["start"] == start
    assert (warn is None and not w["warnings"]) or w["warnings"][0]["kind"] == warn


@pytest.mark.parametrize(
    "text",
    [
        "fais le point sur le budget",
        "Comment planifier une réunion dans Outlook ?",
        "fais-moi un point sur les ventes d'aujourd'hui",
        "Cherche les actualités de la réunion de l'OPEP demain",
        "Organise une réunion avec Paul",
    ],
)
def test_no_event_card(text):
    assert event_widget(text, NOW, "fr") is None


def test_enrich_sources():
    steps = [SimpleNamespace(tool="web_search", info={"results": [
        {"url": "https://www.impots.gouv.fr/x", "title": "T", "snippet": "Le calendrier", "date": "2026-09-01"}]})]  # fmt: skip
    sources = [{"n": 1, "title": "T", "url": "https://www.impots.gouv.fr/x"},
               {"n": 2, "title": "W", "url": "https://fr.wikipedia.org/wiki/X"}]  # fmt: skip
    out = enrich_sources(sources, steps, b"k")
    assert out[0]["kind"] == "gov" and out[0]["domain"] == "impots.gouv.fr" and out[0]["snippet"] == "Le calendrier"
    assert out[0]["icon"] == mapimg.icon_src(b"k", "www.impots.gouv.fr") and out[1]["kind"] == "wiki"
    assert "snippet" not in out[1]


# ---------------------------------------------------------------- /api/map and /api/icon


def tile_png():
    return (FIX / "tile_15_16597_11274.png").read_bytes()


@pytest.fixture
def app_client(monkeypatch):
    calls = {"tiles": 0, "max": 0, "now": 0, "fail": set(), "icon": None}

    def fake_fetch(http, cfg, url, **kw):
        if "favicon" in url:
            if calls["icon"] is None:
                raise guard.ToolError("HTTP 404")
            return 200, "image/x-icon", calls["icon"], {}
        guard.check_url(url, cfg)
        calls["tiles"] += 1
        calls["now"] += 1
        calls["max"] = max(calls["max"], calls["now"])
        try:
            if any(f in url for f in calls["fail"]):
                raise guard.ToolError("HTTP 500")
            return 200, "image/png", tile_png(), {"cache-control": "max-age=20000", "etag": '"x"'}
        finally:
            calls["now"] -= 1

    monkeypatch.setattr(guard, "fetch_bytes", fake_fetch)
    s = Settings(demo_delay=0, signing_secret=b"s" * 32)
    app = create_app(s)
    return TestClient(app), s, calls


def test_api_map_renders_webp_and_caches(app_client):
    from PIL import Image

    client, s, calls = app_client
    t = mapimg.map_token(s.signing_secret, (48.8447, 2.3740), 15)
    r = client.get(f"/api/map?t={t}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert "no-store" not in r.headers["cache-control"] and "set-cookie" not in r.headers
    assert Image.open(io.BytesIO(r.content)).size == (640, 360)
    n = calls["tiles"]
    assert 4 <= n <= 12 and calls["max"] <= 2
    client.get(f"/api/map?t={t}&dz=1")
    m = calls["tiles"]
    client.get(f"/api/map?t={t}&dz=1")
    assert calls["tiles"] == m  # final-image cache


def test_api_map_errors(app_client):
    client, s, calls = app_client
    t = mapimg.map_token(s.signing_secret, (48.8, 2.3), 15)
    assert client.get(f"/api/map?t={t}x").json()["detail"]["code"] == "bad_signature"
    assert client.get(f"/api/map?t={t}&dz=9").status_code == 400
    old = mapimg.map_token(s.signing_secret, (48.8, 2.3), 15, now=0)
    assert client.get(f"/api/map?t={old}").status_code == 410
    assert client.get(f"/api/map?t={t}", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    calls["fail"].add("/15/")
    t2 = mapimg.map_token(s.signing_secret, (40.0, 3.0), 15)
    r = client.get(f"/api/map?t={t2}")
    assert r.status_code == 502 and "openstreetmap" not in r.text


def test_api_map_partial_and_geo_off(app_client, monkeypatch):
    client, s, calls = app_client
    calls["fail"].add("/15/16598/")
    t = mapimg.map_token(s.signing_secret, (48.8447, 2.3740), 15)
    r = client.get(f"/api/map?t={t}")
    assert r.status_code == 200 and r.headers.get("x-bird-partial") == "1" and r.headers["cache-control"] == "no-store"
    before = calls["tiles"]
    calls["fail"].clear()  # the upstream recovers: the next request retries only the missing tiles
    r = client.get(f"/api/map?t={t}")
    assert r.status_code == 200 and "x-bird-partial" not in r.headers and "max-age" in r.headers["cache-control"]
    assert 1 <= calls["tiles"] - before < 4
    again = calls["tiles"]
    client.get(f"/api/map?t={t}")
    assert calls["tiles"] == again  # the complete image is final
    off = TestClient(create_app(Settings(demo_delay=0, signing_secret=b"s" * 32, geo=False)))
    assert off.get(f"/api/map?t={t}").json()["detail"]["code"] == "geo_disabled"


def test_map_limit_ignores_a_forged_forwarded_for(app_client):
    client, s, calls = app_client
    t = mapimg.map_token(s.signing_secret, (48.8447, 2.3740), 15)
    codes = [client.get(f"/api/map?t={t}&dz=1", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
             for i in range(40)]  # fmt: skip
    assert codes.count(429) == 10


def test_tile_downloads_have_a_global_budget():
    n = {"calls": 0}

    def fetch(url, headers):
        n["calls"] += 1
        return 200, "image/png", tile_png(), {}

    tiles = mapimg.Tiles(fetch, per_minute=3)
    for i in range(3):
        tiles.get(f"https://tile.example/{i}.png")
    with pytest.raises(guard.ToolError):
        tiles.get("https://tile.example/9.png")
    assert n["calls"] == 3 and tiles.get("https://tile.example/0.png")[1]  # cached tiles stay free


def test_api_icon(app_client):
    client, s, calls = app_client
    calls["icon"] = (FIX / "favicon_lemonde.ico").read_bytes()
    r = client.get(mapimg.icon_src(s.signing_secret, "www.lemonde.fr"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    from PIL import Image

    assert Image.open(io.BytesIO(r.content)).size == (32, 32)
    assert client.get("/api/icon?d=www.lemonde.fr&s=" + "0" * 24).status_code == 403
    calls["icon"] = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'
    assert client.get(mapimg.icon_src(s.signing_secret, "svg.example.org")).status_code == 404
    assert mapimg._registrable("a.b.gouv.fr") == "b.gouv.fr"


def test_demo_scenarios_show_widgets():
    client = TestClient(create_app(Settings(demo_delay=0)))
    for text, kind in [
        ("Restaurants près de la gare de Lyon", "places"),
        ("Donne-moi la fiche de la société Airbus", "company"),
        ("Convertis 1 200 dollars en euros", "fx"),
        ("Organise une réunion avec Paul jeudi prochain à 14h", "event"),
    ]:
        r = client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": text}]}, headers={"x-bird-mode": "demo"}
        )
        events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
        answer = next(e for e in events if e["type"] == "answer")
        assert answer["widgets"] and answer["widgets"][0]["type"] == kind
        m = answer["widgets"][0].get("map")
        if m:
            assert m["src"].startswith("/static/demo/") and client.get(m["src"]).status_code == 200


# ---------------------------------------------------------------- .ics built in the browser (static/ics.js, run with Node)


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="node not installed")
def test_ics_golden():
    import subprocess

    ics = (Path(__file__).resolve().parents[1] / "birds" / "web" / "static" / "ics.js").as_uri()
    script = (
        f"import('{ics}').then(m => process.stdout.write(JSON.stringify({{"
        "ics: m.buildIcs({title: 'Réunion très importante avec l’équipe de développement, à Paris; salle B', "
        "date: '2026-03-29', start: '10:00', end: '11:00', tz: 'Europe/Paris', location: 'Paris, 8e', "
        "description: 'ligne 1\\nligne 2'}, {uid: 'u1', now: new Date(Date.UTC(2026, 0, 1))}), "
        "name: m.icsName('Réunion avec Paul', '2026-12-03')})))"
    )
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    text = out["ics"]
    assert out["name"] == "reunion-avec-paul-2026-12-03.ics"
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    lines = text.split("\r\n")
    assert all(len(line.encode()) <= 75 for line in lines)
    assert "DTSTART:20260329T080000Z" in lines and "DTEND:20260329T090000Z" in lines  # CEST after the DST change
    unfolded = text.replace("\r\n ", "")
    assert "SUMMARY:Réunion très importante avec l’équipe de développement\\, à Paris\\; salle B" in unfolded
    assert "LOCATION:Paris\\, 8e" in unfolded and "DESCRIPTION:ligne 1\\nligne 2" in unfolded
    assert "METHOD:PUBLISH" in lines and not any(line.startswith("ATTENDEE") for line in lines)


def test_event_ask_withdraws_the_web_and_tells_the_model(tmp_path):
    a, _ = agent(tmp_path, ["C'est noté."])
    a.run("Cale un déjeuner avec l'équipe le 25 décembre à midi")
    prompt = json.loads(a.llm.prompts[0])
    assert "web_search" not in prompt["tools"] and "Ajouter au calendrier" in prompt["messages"][-1]["content"]
    assert "25 décembre 20" in prompt["messages"][-1]["content"] and "12:00–13:00" in prompt["messages"][-1]["content"]
    b, _ = agent(tmp_path, ["ok"])
    b.run("Cherche les actualités de la réunion de l'OPEP demain")
    assert "Ajouter au calendrier" not in json.loads(b.llm.prompts[0])["messages"][-1]["content"]


@pytest.mark.parametrize(
    "text",
    [
        "Rédige le compte rendu de la réunion de jeudi : présents Paul et Marie ; décisions : budget validé",
        "Écris un mail pour annuler la réunion de demain avec Paul",
        "Prépare l'ordre du jour de la réunion de lundi",
    ],
)
def test_document_about_a_meeting_gets_no_event_note_nor_card(tmp_path, text):
    a, _ = agent(tmp_path, ["ok"])
    a.run(text)
    assert "calendrier" not in json.loads(a.llm.prompts[0])["messages"][-1]["content"]
    assert event_widget(text, NOW, "fr") is None


@pytest.mark.parametrize(
    "text,scenario",
    [
        ("Prépare les slides pour le meeting de lundi", "slides"),
        ("Fais une présentation pour le séminaire de vendredi", "slides"),
        ("Rédige le compte rendu de la réunion de jeudi", "minutes"),
        ("Écris un mail pour annuler la réunion de demain", "email"),
        ("Quels documents apporter à l'entretien annuel de vendredi ?", "document"),
        ("Rédige une invitation au webinaire du 3 décembre", "search"),  # as before the widgets
        ("Organise une réunion avec Paul jeudi prochain à 14h", "event"),
        ("Restaurants près de la gare de Lyon", "places"),
        ("Convertis 1 200 dollars en euros dans un tableur", "sheet"),
    ],
)
def test_demo_routing_keeps_document_scenarios(text, scenario):
    from birds.web.backends import pick_scenario

    assert pick_scenario(text) == scenario


# ---------------------------------------------------------------- widgets.js under Node with a tiny DOM (fakedom.mjs)

STATIC = Path(__file__).resolve().parents[1] / "birds" / "web" / "static"
needs_node = pytest.mark.skipif(not __import__("shutil").which("node"), reason="node not installed")


def demo_widget(tool, args, lang="fr", static=True):
    _, info, _ = demo_widgets.run_tool(tool, args, lang)
    ws = build_widgets([SimpleNamespace(tool=tool, info=info, error=None)], "", lang, NOW, b"k")
    return demo_widgets.localise_maps(ws)[0] if static else ws[0]


def run_js(body: str, lang: str = "fr", **data):
    """Runs ``body`` (an async module body; ``W`` = widgets.js, ``C`` = core.js, ``D`` = the fake document,
    ``data`` = the keyword arguments as JSON) and returns what it passes to ``out(...)``."""
    import subprocess

    script = (
        f"import {{ install }} from '{(FIX.parent / 'fakedom.mjs').as_uri()}';\n"
        "const D = install();\n"
        f"const C = await import('{(STATIC / 'core.js').as_uri()}');\n"
        f"C.state.prefs.lang = {json.dumps(lang)};\n"
        f"const W = await import('{(STATIC / 'widgets.js').as_uri()}');\n"
        f"const data = {json.dumps(data, ensure_ascii=False)};\n"
        "const out = (v) => process.stdout.write(JSON.stringify(v));\n"
        "const render = (w) => { const el = W.renderWidgets({ id: 't1', answer: { widgets: [w] } }); "
        "D.body.append(el); return el; };\n" + body
    )
    res = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@needs_node
def test_static_map_frame_has_no_stray_text_node():
    w = demo_widget("find_places", {"query": "restaurant", "near": "gare de Lyon"})
    assert w["map"]["static"]
    got = run_js(
        "const el = render(data.w); const f = el.querySelector('.map-frame');"
        "out({ kinds: f.childNodes.map((n) => n.nodeType), text: f.childNodes.filter((n) => n.nodeType === 3)"
        ".map((n) => n.data), zoom: !!f.querySelector('.map-zoom') });",
        w=w,
    )
    assert got["kinds"] and set(got["kinds"]) == {1} and not got["text"] and not got["zoom"]


def test_pin_tip_is_on_the_coordinate():
    """The pin's tail is centred under it and the translate puts the tail's tip on (--x, --y) (checked in Chromium
    by the browser recipe: tip within 1.5 px of the coordinate)."""
    import re

    css = (STATIC / "app.css").read_text(encoding="utf-8")
    pin = re.search(r"\n\.map-pin \{(.*?)\n\}", css, re.S).group(1)
    tail = re.search(r"\n\.map-pin::after \{(.*?)\n\}", css, re.S).group(1)
    assert "transform: translate(-50%, calc(-100% - var(--tail)))" in pin and "border-radius: 13px;" in pin
    assert "inset-inline-start: 50%" in tail and "translate: -50% 0" in tail
    assert "border-block-start: var(--tail) solid" in tail


@needs_node
def test_event_chips_follow_the_fields():
    holidays = lambda y: json.loads((DATA / "feries_metropole_2026.json").read_text())  # noqa: E731
    w = event_widget("Cale un déjeuner avec l'équipe le 25 décembre à midi", NOW, "fr", holidays=holidays)
    assert w["holidays"]["2026-12-25"] == "Jour de Noël" and w["warnings"][0]["date"] == "2026-12-25"
    got = run_js(
        "const el = render(data.w); const chips = () => el.querySelector('.ev-chips').textContent;"
        "const [date, start] = el.querySelectorAll('input').filter((i) => ['date', 'time'].includes(i.attributes.type));"
        "const a = chips(); date.value = '2026-12-28'; date.dispatch('input'); const b = chips();"
        "date.value = '2026-12-26'; date.dispatch('input'); const c = chips();"
        "start.value = ''; start.dispatch('input'); const d = chips();"
        "out({ a, b, c, d, pure: W.eventChips({ date: '2026-11-11', start: '10:00', end: '11:00' }, data.w.holidays) });",
        w=w,
    )
    assert "Jour de Noël" in got["a"] and "Durée par défaut" in got["a"]
    assert "Jour de Noël" not in got["b"] and "Week-end" not in got["b"] and "Durée par défaut" in got["b"]
    assert "Week-end (samedi)" in got["c"]
    assert "Journée entière" in got["d"] and "Durée par défaut" not in got["d"]
    assert got["pure"] == [["warn", "Jour férié : 11 novembre"]]


def test_widget_buttons_have_distinct_names():
    """'Copier' is the turn's own action: a card's copy button says what it copies (one accessible name each)."""
    import re

    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    for lang_block in js.split('"act.copy":')[1:]:
        plain = re.search(r'^\s*"([^"]+)"', lang_block).group(1)
        for key in ("event.copy", "company.copySiren"):
            v = re.search(rf'"{re.escape(key)}":\s*"([^"]+)"', lang_block).group(1)
            assert v != plain and len(v) > len(plain)
