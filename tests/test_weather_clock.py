"""Weather (MET Norway) and world clock: detection from the user's own words, MET parsing on recorded answers,
symbol mapping, HTTP caching rules, time-zone maths (DST edges), widget payloads, agent wiring. No network."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from birds.harness import Agent, Config, Context, FakeClient, clock, geo, guard, intents
from birds.harness.tools import TOOLS, weather
from birds.tools import BIRD_TOOL_NAMES, EXTRA_TOOL_NAMES
from birds.web import demo_widgets
from birds.web.widgets import build_widgets

DATA = Path(__file__).resolve().parents[1] / "birds" / "web" / "demo_data"
RECORDED = datetime.fromisoformat(demo_widgets.MET_RECORDED)
PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(guard, "resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(weather, "utcnow", lambda: RECORDED)
    geo.POLICY.reset()
    geo.POLICY.sleep = lambda s: None
    yield
    geo.POLICY.reset()
    geo.POLICY.sleep = __import__("time").sleep


def transport(seen, met_headers=None):
    def handler(req: httpx.Request) -> httpx.Response:
        host = req.headers.get("host", req.url.host)
        seen.append(req)
        data = demo_widgets.recorded(f"https://{host}{req.url.raw_path.decode()}")
        headers = {"content-type": "application/json"}
        if host == "api.met.no" and met_headers:
            headers.update(met_headers(req))
            if headers.pop("status", None) == "304":
                return httpx.Response(304, headers=headers)
        return httpx.Response(200, headers=headers, content=json.dumps(data).encode())

    return httpx.MockTransport(handler)


def ctx_for(seen, tmp_path, lang="fr", met_headers=None, **cfg):
    config = Config(workspace=tmp_path, audit_file=None, **cfg)
    return Context(config=config, http=httpx.Client(transport=transport(seen, met_headers)), lang=lang)


# ---------------------------------------------------------------- detection (the bench's lists, and more)

WEATHER_YES = [
    ("météo à Lyon demain", {"place": "Lyon", "day": "demain"}),
    ("il va pleuvoir à Nantes ?", {"place": "Nantes"}),
    ("quel temps pour jeudi à Lille", {"place": "Lille", "day": "jeudi"}),
    ("weather in London tomorrow", {"place": "London", "day": "tomorrow"}),
    ("Quel temps fera-t-il à Paris ce week-end ?", {"place": "Paris", "day": "ce week-end"}),
    ("meteo a lyon demain", {"place": "lyon", "day": "demain"}),
    ("va-t-il neiger à Chamonix samedi ?", {"place": "Chamonix", "day": "samedi"}),
    ("do I need an umbrella in Paris tomorrow?", {"place": "Paris", "day": "tomorrow"}),
    ("météo à la gare de Lyon ce soir", {"place": "gare de Lyon", "day": "ce soir"}),
    ("il fait beau à Nice ?", {"place": "Nice"}),
]
WEATHER_NO = [
    "le climat social est tendu",
    "fais-moi la météo des marchés",
    "comment réduire le temps de réponse ?",
    "il fait beau ce projet",
    "la météo sociale de l'entreprise",
    "quel est le temps de trajet entre Lyon et Paris ?",
    "une pluie de critiques sur le projet",
    "sales forecast for Q3",
    "règle la température du modèle à 0,7",
    "quelle est la température idéale d'un bureau ?",
    "Quel temps de livraison pour un colis vers Lyon ?",
    "Quel temps de préparation pour le dossier Martin ?",
    "Quel temps faut-il pour traiter une commande ?",
    "Quel temps de validation pour les notes de frais ?",
    "Quel temps de cuisson pour un rôti ?",
    "Il pleut des bugs en production depuis la mise à jour",
    "Il neige des tickets au support ce matin",
    "Le parapluie de garantie couvre-t-il notre filiale de Lille ?",
    "Je veux un parapluie publicitaire avec notre logo pour le salon de Lyon",
    "Le projet Météo à Toulouse est en retard",
    "les prévisions météo du chiffre d'affaires",
    "Draft an email about the weather station product launch in Berlin",
]


@pytest.mark.parametrize("text,args", WEATHER_YES)
def test_weather_asks_are_prefilled(text, args):
    found = intents.detect(text)
    assert found and found[0].tool == "get_weather" and found[0].args == args and not found[0].keep_web


@pytest.mark.parametrize("text", WEATHER_NO)
def test_weather_look_alikes_offer_nothing(text):
    assert not any(i.tool == "get_weather" for i in intents.detect(text))


def test_weather_without_a_place_is_only_offered():
    found = intents.detect("quel temps fait-il demain ?")
    assert found == [intents.Intent("get_weather", None, keep_web=True)]


def test_a_lowercase_place_outside_the_city_table_is_only_offered():
    assert intents.weather("météo pour le séminaire demain ?") == intents.Intent("get_weather", None, keep_web=True)
    assert intents.weather("météo à lyon demain").args == {"place": "lyon", "day": "demain"}  # a table city
    assert intents.weather("quel temps de chien à Lille demain ?").args == {"place": "Lille", "day": "demain"}


def test_weather_wins_over_a_map_and_places_still_win_their_own_asks():
    assert intents.detect("météo à la tour Eiffel")[0].tool == "get_weather"
    assert intents.detect("restaurants près de la gare de Lyon")[0].tool == "find_places"


CLOCK_YES = [
    ("quelle heure est-il à New York", "time", ["New York"]),
    ("décalage horaire avec Tokyo", "offset", ["Tokyo"]),
    ("trouve un créneau commun Paris Montréal Singapour pour une réunion", "slot", ["Paris", "Montréal", "Singapour"]),
    ("what time is it in Sydney?", "time", ["Sydney"]),
    ("time difference between Paris and Los Angeles", "offset", ["Paris", "Los Angeles"]),
    ("décalage horaire avec les États-Unis", "offset", ["Washington"]),
]
CLOCK_NO = [
    "à quelle heure est la réunion ?",
    "heure de pointe à Paris",
    "trouve un créneau commun avec Paul et Marie",
    "combien d'heures sup ce mois-ci ?",
    "combien d'heures de vol entre Paris et Tokyo ?",
    "can you help us with this",
]


@pytest.mark.parametrize("text,mode,cities", CLOCK_YES)
def test_clock_asks(text, mode, cities):
    found = clock.detect(text)
    assert found["mode"] == mode and [c["fr"] for c in found["cities"]] == cities


@pytest.mark.parametrize("text", CLOCK_NO)
def test_clock_look_alikes(text):
    found = clock.detect(text)
    assert not found or clock.card(found, datetime(2026, 11, 23, 9, 0, tzinfo=PARIS)) is None


def test_slot_in_one_zone_is_a_calendar_question():
    found = clock.detect("trouve un créneau pour une réunion entre Lyon et Paris")
    assert clock.card(found, datetime(2026, 11, 23, 9, 0, tzinfo=PARIS)) is None


def test_city_table_is_large_and_every_zone_exists():
    assert len(clock.CITIES) >= 150 and len(clock.COUNTRIES) >= 100
    for c in clock.CITIES:
        ZoneInfo(c["zone"])


# ---------------------------------------------------------------- time-zone maths


def test_offsets_follow_daylight_saving_on_both_sides_of_the_atlantic():
    ny = "America/New_York"
    paris = "Europe/Paris"
    winter = datetime(2026, 3, 1, 12, tzinfo=UTC)
    gap = datetime(2026, 3, 15, 12, tzinfo=UTC)  # US on summer time (8 March), Europe not yet (29 March)
    summer = datetime(2026, 4, 15, 12, tzinfo=UTC)
    autumn_gap = datetime(2026, 10, 28, 12, tzinfo=UTC)  # Europe back on winter time (25 Oct), US not (1 Nov)
    diff = [clock.offset_minutes(ny, t) - clock.offset_minutes(paris, t) for t in (winter, gap, summer, autumn_gap)]
    assert diff == [-360, -300, -360, -300]


def test_day_of_a_clock_change_has_24_real_hours_labelled_as_they_are():
    spring = clock.day_columns("Europe/Paris", date(2026, 3, 29))
    hours = [t.astimezone(PARIS).hour for t in spring]
    assert hours[:4] == [0, 1, 3, 4] and hours[-1] == 0  # 02:00 does not exist; the 24th hour is next midnight
    autumn = [t.astimezone(PARIS).hour for t in clock.day_columns("Europe/Paris", date(2026, 10, 25))]
    assert autumn[:4] == [0, 1, 2, 2]  # 02:00 happens twice


def test_half_hour_zone_and_common_slot():
    found = clock.detect("créneau commun Paris Bombay")
    w = clock.card(found, datetime(2026, 11, 23, 9, 25, tzinfo=PARIS))
    rows = {r["name"]: r for r in w["cities"]}
    assert rows["Bombay"]["offset"] == "UTC+5:30" and rows["Bombay"]["diff_min"] == 270
    assert w["common"][0]["local"][0] == ["09:00", "13:30"] and w["common"][0]["local"][1] == ["13:30", "18:00"]


def test_no_office_slot_gives_the_widest_compromise():
    found = clock.detect("trouve un créneau commun Paris Montréal Singapour pour une réunion")
    w = clock.card(found, datetime(2026, 11, 23, 9, 25, tzinfo=PARIS))
    assert w["common"] == [] and w["wide"][0]["local"] == [["13:00", "14:00"], ["07:00", "08:00"], ["20:00", "21:00"]]
    assert len(w["timeline"]["rows"]) == 3 and all(len(r["hours"]) == 24 for r in w["timeline"]["rows"])
    text = clock.summary(w, "fr")
    assert "Aucun créneau commun" in text and "13:00–14:00 heure de Paris" in text


def test_weekend_board_moves_to_monday_and_user_zone_is_added():
    found = clock.detect("quelle heure est-il à Tokyo")
    w = clock.card(found, datetime(2026, 11, 28, 10, 0, tzinfo=PARIS), "en")  # a Saturday
    assert w["timeline"]["date"] == "2026-11-30"
    assert [r["name"] for r in w["cities"]] == ["Paris", "Tokyo"] and w["cities"][0]["user"]
    assert w["cities"][1]["local"] == "2026-11-28T18:00" and "Tokyo 18:00 (UTC+9, 8h ahead)" in clock.summary(w, "en")


def test_unknown_town_takes_its_zone_from_its_country_never_its_coordinates(tmp_path):
    seen = []
    ctx = ctx_for(seen, tmp_path)
    c = clock.lookup("Nantes", ctx)  # recorded Nominatim answer: country_code fr, region Pays de la Loire
    assert c["zone"] == "Europe/Paris" and c["cc"] == "FR"
    assert clock.country_zone("FR", "La Réunion") == "" and clock.country_zone("US") == ""
    assert clock.country_zone("JP") == "Asia/Tokyo" and clock.valid_zone("Mars/Base") == "Europe/Paris"


# ---------------------------------------------------------------- MET Norway


@pytest.mark.parametrize(
    "code,icon,fr",
    [
        ("clearsky_day", "sun", "Ciel dégagé"),
        ("clearsky_night", "moon", "Ciel dégagé"),
        ("fair_polartwilight", "sun", "Beau temps"),
        ("partlycloudy_night", "partly_night", "Partiellement nuageux"),
        ("cloudy", "cloud", "Nuageux"),
        ("fog", "fog", "Brouillard"),
        ("lightrain", "drizzle", "Pluie faible"),
        ("heavyrain", "rain", "Pluie forte"),
        ("rainshowers_day", "showers", "Averses"),
        ("lightrainshowers_night", "drizzle", "Averses faibles"),
        ("lightsleet", "sleet", "Neige fondue faible"),
        ("heavysnowshowers_day", "snow", "Fortes averses de neige"),
        ("rainandthunder", "thunder", "Pluie et orage"),
        ("lightssleetshowersandthunder_day", "cloud", "Nuageux"),  # unknown (typo): a neutral cloud, no guess
    ],
)
def test_symbol_codes_map_to_icons_and_labels(code, icon, fr):
    s = weather.sky(code)
    assert s["icon"] == icon and s["fr"] == fr and s["icon"] in weather.ICONS


def test_every_recorded_symbol_has_an_icon():
    for name in ("lyon", "lille", "london", "nantes"):
        data = json.loads((DATA / f"met_{name}.json").read_text())
        for p in data["properties"]["timeseries"]:
            for k in ("next_1_hours", "next_6_hours", "next_12_hours"):
                if k in p["data"]:
                    code = p["data"][k]["summary"]["symbol_code"]
                    assert weather.sky(code)["icon"] != "cloud" or "cloud" in code or "fog" in code, code


def test_parse_met_and_rain_is_never_counted_twice():
    data = json.loads((DATA / "met_lyon.json").read_text())
    points, updated = weather.parse_met(data)
    assert len(points) == 92 and updated == "2026-11-23T07:16:57Z"
    assert points[0]["temp"] == 5.7 and points[0]["sym1"] == "partlycloudy_day"
    periods = weather.rain_periods(points)
    for (a, ha, _, _), (b, _, _, _) in zip(periods, periods[1:], strict=False):
        assert (b - a).total_seconds() >= ha * 3600  # no overlap between periods
    assert {h for _, h, _, _ in periods} == {1, 6}
    with pytest.raises(guard.ToolError):
        weather.parse_met({"properties": {"timeseries": []}})


def test_weather_tool_on_recorded_answers(tmp_path):
    seen = []
    ctx = ctx_for(seen, tmp_path)
    ctx.now = RECORDED
    text = TOOLS["get_weather"]({"place": "Lyon", "day": "demain"}, ctx)
    w = ctx.step_info["widget"]
    assert w["type"] == "weather" and w["day"] == "2026-11-24" and w["day_kind"] == "tomorrow"
    assert w["tz"] == "Europe/Paris" and w["place"]["name"] == "Lyon" and "Auvergne" in w["place"]["region"]
    assert w["summary"] == {
        "kind": "day", "temp": 8, "icon": "cloud", "symbol": "cloudy", "label": "Nuageux", "wind_kmh": 13,
        "rain_mm": 2.8, "rain_prob": None, "min": 3, "max": 8,
    }  # fmt: skip
    assert len(w["hours"]) == 24 and w["hours"][0]["t"] == "2026-11-24T00:00" and len(w["days"]) == 7
    assert w["source"]["label"] == "MET Norway" and w["license"]["label"] == "CC BY 4.0"
    assert len(json.dumps(w, ensure_ascii=False)) < 8000
    assert "Prévision MET Norway pour Lyon" in text and "mardi 24 novembre" in text and "[1]" in text
    met = [r for r in seen if r.headers.get("host") == "api.met.no"][0]
    assert met.url.params["lat"] == "45.7578" and met.url.params["lon"] == "4.8320"  # 4 decimals at most
    assert met.headers["user-agent"] == "BirdHarness/0.1 (+https://bird-s.vercel.app)"
    assert "cookie" not in met.headers and "referer" not in met.headers


def test_weather_in_london_uses_the_london_zone_and_the_users_language(tmp_path):
    ctx = ctx_for([], tmp_path)
    TOOLS["get_weather"]({"place": "London"}, ctx)
    w = ctx.step_info["widget"]
    assert w["place"]["name"] == "Londres" and w["tz"] == "Europe/London" and w["summary"]["kind"] == "now"


def test_weather_beyond_the_forecast_and_in_the_past_say_so(tmp_path):
    ctx = ctx_for([], tmp_path)
    with pytest.raises(guard.ToolError, match="no forecast yet"):
        TOOLS["get_weather"]({"place": "Lyon", "day": "le 20 décembre"}, ctx)
    with pytest.raises(guard.ToolError, match="past"):
        TOOLS["get_weather"]({"place": "Lyon", "day": "2026-11-01"}, ctx)


def test_met_expires_and_if_modified_since(tmp_path):
    seen = []
    state = {"n": 0}

    def headers(req):
        state["n"] += 1
        if state["n"] == 1:
            return {"expires": "Mon, 23 Nov 2026 07:56:45 GMT", "last-modified": "Mon, 23 Nov 2026 07:25:19 GMT"}
        assert req.headers["if-modified-since"] == "Mon, 23 Nov 2026 07:25:19 GMT"
        return {"status": "304", "expires": "Mon, 23 Nov 2026 08:30:00 GMT"}

    clock_now = [RECORDED.timestamp()]
    geo.POLICY.wall = lambda: clock_now[0]
    try:
        ctx = ctx_for(seen, tmp_path, met_headers=headers)
        a = weather.fetch(ctx, 45.7578, 4.832)
        weather.fetch(ctx_for(seen, tmp_path, met_headers=headers), 45.7578, 4.832)  # fresh: from the cache
        assert state["n"] == 1
        clock_now[0] += 3600  # past Expires: a conditional request, 304 keeps the forecast
        b = weather.fetch(ctx_for(seen, tmp_path, met_headers=headers), 45.7578, 4.832)
        assert state["n"] == 2 and a == b
    finally:
        geo.POLICY.wall = __import__("time").time


def test_a_town_from_an_attached_file_is_never_looked_up(tmp_path):
    seen = []
    ctx = ctx_for(seen, tmp_path)
    ctx.attached, ctx.request = True, "quel temps fera-t-il là-bas ?"
    with pytest.raises(guard.ToolError, match="attached file"):
        TOOLS["get_weather"]({"place": "Lyon"}, ctx)
    assert not seen


# ---------------------------------------------------------------- agent and widgets


class Tok:
    def apply_chat_template(self, messages, tools=None, enable_thinking=False, tokenize=False,
                            add_generation_prompt=False):  # fmt: skip
        return json.dumps({"tools": [t["function"]["name"] for t in tools or []], "messages": messages},
                          ensure_ascii=False)  # fmt: skip


def agent(tmp_path, outputs, **cfg):
    seen = []
    config = Config(workspace=tmp_path, audit_file=None, **cfg)
    a = Agent(FakeClient(outputs), Tok(), config, search=None, http=httpx.Client(transport=transport(seen)))
    return a, seen


def test_weather_is_prefilled_and_the_web_withdrawn_even_for_today(tmp_path):
    a, seen = agent(tmp_path, ["Demain à Lyon : nuageux, 3 à 8 °C [1]."])
    run = a.run("météo à Lyon aujourd'hui")
    step = run.steps[0]
    assert step.tool == "get_weather" and step.info["auto"] and step.arguments == {"place": "Lyon"}
    tools = json.loads(a.llm.prompts[0])["tools"]
    assert "get_weather" in tools and "web_search" not in tools and "read_page" not in tools
    assert {r.headers["host"] for r in seen} == {"nominatim.openstreetmap.org", "api.met.no"}
    widgets = build_widgets(run.steps, "météo à Lyon aujourd'hui", "fr", datetime(2026, 11, 23, 8, tzinfo=PARIS),
                            b"k", extra=run.widgets)  # fmt: skip
    assert [w["type"] for w in widgets] == ["weather"] and widgets[0]["auto"]


def test_clock_is_computed_by_the_harness_without_tool_or_network(tmp_path):
    a, seen = agent(tmp_path, ["Il est 03:25 à New York."])
    run = a.run("quelle heure est-il à New York ?", tz="Europe/Paris")
    assert not run.steps and not seen
    prompt = json.loads(a.llm.prompts[0])
    assert not set(prompt["tools"]) & ({"web_search", "read_page"} | set(EXTRA_TOOL_NAMES))
    assert "Note de Bird" in prompt["messages"][-1]["content"] and "New York" in prompt["messages"][-1]["content"]
    assert run.widgets and run.widgets[0]["type"] == "clock"
    widgets = build_widgets(run.steps, "", "fr", datetime.now(PARIS), b"k", extra=run.widgets)
    assert widgets[0]["type"] == "clock" and widgets[0]["user_tz"] == "Europe/Paris"


def test_ordinary_turn_still_keeps_the_trained_tool_block(tmp_path):
    a, _ = agent(tmp_path, ["Bonjour."])
    a.run("Écris un mail de relance à Paul")
    tools = json.loads(a.llm.prompts[0])["tools"]
    assert tools == [n for n in BIRD_TOOL_NAMES if n in tools] and not set(tools) & set(EXTRA_TOOL_NAMES)
    assert EXTRA_TOOL_NAMES[0] == "make_chart" and "get_weather" in EXTRA_TOOL_NAMES


def test_model_call_with_other_argument_names_is_repaired():
    args, err = guard.validate_args("get_weather", {"city": "Lyon", "date": "demain"}, EXTRA_TOOL_NAMES)
    assert err is None and args == {"place": "Lyon", "day": "demain"}


def test_event_card_gets_a_one_line_weather_hint_for_the_same_day(tmp_path):
    ctx = ctx_for([], tmp_path)
    TOOLS["get_weather"]({"place": "Lille", "day": "jeudi"}, ctx)
    from types import SimpleNamespace

    step = SimpleNamespace(tool="get_weather", info=dict(ctx.step_info), error=None)
    out = build_widgets([step], "réunion jeudi à Lille à 14h", "fr", datetime(2026, 11, 23, 8, tzinfo=PARIS), b"k")
    ev = next(w for w in out if w["type"] == "event")
    assert ev["start"].startswith("2026-11-26") and ev["weather"]["place"] == "Lille"
    assert ev["weather"]["min"] == -3 and ev["weather"]["max"] == 0


def test_demo_scenarios(tmp_path):
    from birds.web.backends import pick_scenario

    assert pick_scenario("météo à Lyon demain") == "weather"
    assert pick_scenario("décalage horaire avec Tokyo") == "clock"
    assert pick_scenario("trouve un créneau commun Paris Montréal Singapour pour une réunion") == "clock"
    text, info, sources = demo_widgets.run_tool("get_weather", {"place": "Nantes"}, "fr")
    assert info["widget"]["day"] == "2026-11-23" and sources == [weather.DOC_URL]
