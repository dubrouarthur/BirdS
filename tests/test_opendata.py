"""Open-data tools (birds/harness/tools/opendata), their routing (catalogue, grounding, veto, parsers) and cards.

The tools run on provider answers recorded live by ``scripts/opendata_live.py --demo`` (birds/web/demo_data/
opendata.json): no network here. The HTTP path is checked with a fake ``guard.fetch_bytes``.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

from birds.harness import Config, Context, catalog, guard, opendata_intents, opendata_route
from birds.harness import router as R
from birds.harness.guard import Blocked, ToolError
from birds.harness.tools.opendata import OPENDATA_TOOLS
from birds.harness.tools.opendata import http as odhttp
from birds.web import demo_widgets, opendata_demo, opendata_widgets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bench_opendata as OD  # noqa: E402


def _ctx(lang="fr", today=None):
    ctx = Context(config=Config(workspace=Path(tempfile.gettempdir()), audit_file=None), http=None, lang=lang)
    ctx.recorded = demo_widgets.recorded
    if today:
        ctx.today = today
    return ctx


def _run(tool, args, lang="fr", today=None):
    ctx = _ctx(lang, today)
    text = OPENDATA_TOOLS[tool](dict(args), ctx)
    return text, ctx


def _ask(q, lang="fr"):
    got = next(i for i in opendata_intents.detect(q, False, lang) if i.args)
    return got.tool, got.args


# ---------------------------------------------------------------- tools on recorded answers


def test_month_of_holidays_and_working_days_from_calendrier_api_gouv():
    text, ctx = _run(*_ask("jours fériés de mai 2027"))
    w = ctx.step_info["widget"]
    assert w["type"] == "calendar" and w["mode"] == "month" and w["year"] == 2027 and w["month"] == 5
    assert [h["name"] for h in w["holidays"]] == ["1er mai", "Ascension", "8 mai", "Lundi de Pentecôte"]
    assert w["counts"]["workdays"] == 19 and w["counts"]["workable"] == 22
    assert "calendrier.api.gouv.fr" in w["source"]["url"] and w["license"]["label"]
    assert "19 jours ouvrés" in text


def test_a_country_s_holidays_come_from_nager_date():
    _, ctx = _run(*_ask("public holidays in Germany in 2027", "en"), lang="en")
    w = ctx.step_info["widget"]
    assert w["zone"]["code"] == "DE" and w["mode"] == "year" and len(w["holidays"]) >= 9
    assert "nager" in w["source"]["url"].lower()


@pytest.mark.parametrize(
    "ask,label,series",
    [
        ("le chômage en France et en Allemagne depuis 2015", "Eurostat", ["France", "Allemagne"]),
        ("PIB de la France et du Japon depuis 2010", "Banque mondiale", ["France", "Japon"]),
        ("population de Roubaix depuis 1968", "Insee", ["Roubaix"]),
    ],
)
def test_official_series_are_drawn_with_their_source_dataset_and_licence(ask, label, series):
    text, ctx = _run(*_ask(ask))
    (spec,) = ctx.charts
    assert spec["source"] == "data" and spec["type"] == "line" and spec["columns"][1:] == series
    src = spec["data_source"]
    assert label.lower() in src["label"].lower() and src["url"].startswith("https://") and src["license"]
    assert len(spec["rows"]) >= 8 and all(isinstance(v, (int, float)) or v is None for r in spec["rows"] for v in r[1:])
    assert "Ne redessine pas le graphique" in text  # the model comments the trend, the chart is already drawn


def test_tenders_scholarly_works_and_a_doi():
    _, ctx = _run(*_ask("appels d'offres maintenance informatique"))
    w = ctx.step_info["widget"]
    assert w["type"] == "tenders" and w["items"] and all(i["url"].startswith("https://") for i in w["items"])
    assert "BOAMP" in w["source"]["label"] and w["license"]["url"].startswith("https://")
    _, ctx = _run(*_ask("articles scientifiques sur les batteries sodium-ion"))
    w = ctx.step_info["widget"]
    assert w["type"] == "papers" and w["source"]["label"] == "OpenAlex" and len(w["items"]) == 6
    assert all(i["title"] and i["year"] for i in w["items"])
    _, ctx = _run(*_ask("vérifie ce DOI 10.1038/nature14539"))
    w = ctx.step_info["widget"]
    assert w["mode"] == "doi" and w["found"] and w["items"][0]["title"] == "Deep learning"


def test_a_commune_and_a_normalised_address():
    _, ctx = _run(*_ask("code postal de Roubaix"))
    c = ctx.step_info["widget"]["communes"][0]
    assert c["name"] == "Roubaix" and c["code"] == "59512" and "59100" in c["postcodes"]
    _, ctx = _run(*_ask("normalise cette adresse : 20 av de segur paris"))
    w = ctx.step_info["widget"]
    assert w["mode"] == "address" and "Ségur" in w["address"]["line1"] and "75007" in w["address"]["line2"]


def test_an_entity_not_recorded_is_a_missing_page_never_invented():
    text, ctx = _run("lookup_entity", {"name": "Zorglub Industries"})
    assert ctx.step_info == {"found": 0} and "n'invente rien" in text


# ---------------------------------------------------------------- the HTTP path: hosts, cap, cache, retries


class _Fetch:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, http, cfg, url, **kw):
        self.calls.append(url)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        body, hdrs = a
        return 200, "application/json", json.dumps(body).encode(), hdrs


@pytest.fixture
def live_ctx(monkeypatch):
    from birds.harness import geo

    monkeypatch.setattr(geo.POLICY, "wait_turn", lambda host: None)
    monkeypatch.setattr(geo.POLICY, "sleep", lambda s: None)
    geo.POLICY.clear() if hasattr(geo.POLICY, "clear") else None
    return Context(config=Config(workspace=Path(tempfile.gettempdir()), audit_file=None, geo_cache_dir=None),
                   http=object(), lang="fr")  # fmt: skip


def test_only_the_listed_hosts_are_reachable(live_ctx):
    with pytest.raises(Blocked):
        odhttp.get(live_ctx, "https://evil.example.org/x.json")


def test_a_429_is_retried_once_then_a_calm_error(monkeypatch, live_ctx):
    f = _Fetch([ToolError("HTTP 429"), ToolError("HTTP 429")])
    monkeypatch.setattr(guard, "fetch_bytes", f)
    with pytest.raises(ToolError, match="busy"):
        odhttp.get(live_ctx, "https://api.openalex.org/works?search=retry-test-1")
    assert len(f.calls) == 2


def test_answers_are_cached_except_no_store_and_calls_are_capped(monkeypatch, live_ctx):
    f = _Fetch([({"a": 1}, {}), ({"b": 2}, {"Cache-Control": "no-store"}), ({"b": 3}, {})] + [({"c": i}, {})
                                                                                         for i in range(10)])  # fmt: skip
    monkeypatch.setattr(guard, "fetch_bytes", f)
    u1, u2 = "https://api.openalex.org/works?search=cache-test-a", "https://api.openalex.org/works?search=cache-test-b"
    assert odhttp.get(live_ctx, u1) == {"a": 1} and odhttp.get(live_ctx, u1) == {"a": 1}
    assert odhttp.get(live_ctx, u2) == {"b": 2} and odhttp.get(live_ctx, u2) == {"b": 3}  # no-store: asked again
    assert len(f.calls) == 3
    with pytest.raises(ToolError, match="limit"):
        for i in range(odhttp.MAX_CALLS + 1):
            odhttp.get(live_ctx, f"https://api.openalex.org/works?search=cap-test-{i}")
    assert len(f.calls) == odhttp.MAX_CALLS


# ---------------------------------------------------------------- routing: catalogue, grounding, veto, parsers


def test_the_catalogue_offers_the_six_open_data_modules_with_valid_grounded_examples():
    names = {m.name for m in catalog.MODULES if m.family == "opendata"}
    assert names == set(OPENDATA_TOOLS)
    for n in names:
        assert f"- {n}(" in catalog.text("fr") and f"- {n}(" in catalog.text("en")
    assert names <= R.available_names(Config(workspace=Path(".")))
    assert not names & R.available_names(Config(workspace=Path("."), allowed_tools=("web_search",)))


@pytest.mark.parametrize(
    "tool,args,text,why",
    [
        ("work_calendar", {"period": "2031"}, "jours fériés en 2027", "year"),
        ("work_calendar", {"period": "2027", "zone": "IT"}, "jours fériés en 2027", "zone"),
        ("lookup_entity", {"name": "Zorglub"}, "c'est quoi Airbus ?", "name"),
        ("get_statistics", {"indicator": "gdp", "places": "Japon"}, "PIB de la France depuis 2010", "place"),
        ("find_tenders", {"query": "voirie"}, "appels d'offres nettoyage de locaux", "query"),
        ("find_papers", {"query": "10.1000/xyz"}, "vérifie ce DOI 10.1038/nature14539", "DOI"),
    ],
)
def test_arguments_the_user_did_not_write_are_refused(tool, args, text, why):
    assert why in opendata_route.ground(R.Call(tool, args), text, "")


def test_country_names_ground_across_languages():
    assert opendata_route.ground(R.Call("get_statistics", {"indicator": "gdp", "places": "Allemagne"}),
                                 "GDP of Germany since 2000", "") == ""  # fmt: skip


@pytest.mark.parametrize(
    "tool,args,text",
    [
        ("lookup_entity", {"name": "KPI"}, "c'est quoi un KPI ?"),
        ("get_statistics", {"indicator": "inflation"}, "rédige un article de blog sur l'inflation"),
        ("work_calendar", {"period": "2027"}, "summarize this paper for me"),
        ("find_tenders", {"query": "nettoyage"}, "comment répondre à un appel d'offres de nettoyage ?"),
        ("get_statistics", {"indicator": "population"}, "la population cible de notre campagne marketing"),
    ],
)
def test_the_veto_blocks_known_false_triggers(tool, args, text):
    assert opendata_route.veto_reason(R.Call(tool, args), text)


@pytest.mark.parametrize("ask", ["inflation de mes loyers depuis 2020", "le chômage dans mon équipe depuis 2015",
                                 "exportations de notre PME depuis 2010", "Inflation des salaires dans l'équipe depuis 2020",
                                 "the unemployment rate in my team since 2015"])  # fmt: skip
def test_the_user_s_own_figures_are_never_an_official_series(ask):
    """No France chart in place of the user's rent, team or company numbers, even merged back in hybrid mode."""
    assert not any(i.args for i in opendata_intents.detect(ask))
    model = R.Decision([], None, False, "model", {})
    assert R.merge(model, R.regex_decision(ask), R.own_decision(ask)).get("get_statistics") is None
    call = R.Call("get_statistics", {"indicator": "inflation", "places": "France"})
    assert opendata_route.veto_reason(call, ask)


def test_no_country_is_filled_in_when_the_user_named_none():
    assert not any(i.args for i in opendata_intents.detect("le chômage depuis 2015"))
    assert _ask("évolution du chômage en France depuis 2015")[1]["places"] == "France"


def test_a_bare_j_plus_n_is_never_counted_in_working_days():
    """« J+30 sur la facture du 3 décembre » is 2 January 2027 in calendar days, not 18 January in working days."""
    ask = "Calcule J+30 sur la facture du 3 décembre"
    assert not any(i.args for i in opendata_intents.detect(ask, today=OD.TODAY))
    call = R.Call("work_calendar", {"period": "2026-12-03", "add_days": 30})
    assert "working days" in opendata_route.ground(call, ask, "")
    assert _ask("J+30 ouvrés à partir du 3 décembre")[1]["add_days"] == 30
    assert opendata_route.ground(call, "J+30 ouvrés à partir du 3 décembre", "") == ""


@pytest.mark.parametrize("ask", ["combien de jours ouvrés de congés me reste-t-il ?",
                                 "how many working days of leave do I have left?",
                                 "combien de jours ouvrés dans mon contrat ?",
                                 "Combien de jours ouvrés reste-t-il avant la fin du projet ?"])  # fmt: skip
def test_the_user_s_leave_contract_or_project_is_not_a_holiday_calendar(ask):
    assert not any(i.args for i in opendata_intents.detect(ask, today=OD.TODAY))
    model = R.Decision([], None, False, "model", {})
    assert R.merge(model, R.regex_decision(ask), R.own_decision(ask)).get("work_calendar") is None
    assert opendata_route.veto_reason(R.Call("work_calendar", {"period": "2026"}), ask)


@pytest.mark.parametrize("ask,tool", [
    ("Translate into French: public holidays in Germany in 2027", "work_calendar"),
    ("Translate this: unemployment in Spain since 2010", "get_statistics"),
    ("Summarize: inflation in the euro area since 2020", "get_statistics"),
    ("Corrige l'orthographe : l'inflation en France depuis 2020 a ete forte", "get_statistics"),
    ("Mets en forme : PIB de la France et du Japon depuis 2000", "get_statistics"),
])  # fmt: skip
def test_a_task_on_the_user_s_text_never_starts_a_card_even_in_fallback(ask, tool):
    """The parser fallback (demo, router off, router timeout) and the veto both leave a text task alone."""
    assert not any(i.args for i in opendata_intents.detect(ask, today=OD.TODAY))
    assert R.regex_decision(ask).get(tool) is None
    assert opendata_route.veto_reason(R.Call(tool, {"indicator": "gdp", "period": "2027"}), ask)


def test_correcting_an_address_is_still_a_lookup():
    ask = "vérifie l'adresse 8 bd du port 95000 cergy"
    call = R.Call("find_commune", dict(_ask(ask)[1]))
    assert opendata_route.veto_reason(call, ask) == ""
    ask = "corrige cette adresse : 8 bd du port 95000 cergy"
    assert opendata_route.veto_reason(R.Call("find_commune", dict(_ask(ask)[1])), ask) == ""


def _qty(amount, unit):
    unit = unit if unit == "1" else "http://www.wikidata.org/entity/" + unit
    return [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"amount": amount, "unit": unit}}}}]


def test_entity_figures_keep_small_values_and_never_lose_their_currency():
    from birds.harness.tools.opendata import entity as E

    city = E.facts_of({"claims": {"P2046": _qty("+0.44", "Q712226")}}, "city", "fr", {})
    assert city[0]["value"] == "0,44 km²"  # Vatican City, never « 0 km² »
    assert E.facts_of({"claims": {"P2046": _qty("+0.44", "Q712226")}}, "city", "en", {})[0]["value"] == "0.44 km²"
    sek = E.facts_of({"claims": {"P2139": _qty("+232600000000", "Q122922")}}, "company", "fr", {})
    assert sek[0]["value"] == "233 Md SEK"
    # a currency (or any unit) Bird does not know: the figure is left out, never shown as if in euros
    assert E.facts_of({"claims": {"P2139": _qty("+1000000000", "Q999999")}}, "company", "fr", {}) == []
    assert E.facts_of({"claims": {"P2046": _qty("+12", "Q999999")}}, "city", "fr", {}) == []
    assert E.facts_of({"claims": {"P1082": _qty("+764", "1")}}, "city", "fr", {})[0]["value"] == "764"


def test_the_veto_never_blocks_what_the_parser_itself_starts():
    for q, _tool, _args in OD.OPENDATA_YES:
        got = [i for i in opendata_intents.detect(q, False, "fr", today=OD.TODAY) if i.args]
        assert opendata_route.veto_reason(R.Call(got[0].tool, dict(got[0].args)), q) == "", q


def test_router_only_asks_pass_grounding_and_veto_with_their_labels():
    for q, tool, args in OD.OPENDATA_ROUTER_YES:
        clean, why = catalog.check_args(tool, args)
        assert clean is not None, (q, why)
        call = R.Call(tool, clean)
        assert R.ground(call, q, "") == "" and R.veto_reason(call, q) == "", q


def test_the_bench_families_pass():
    assert all(OD.started(it) for it in OD.OPENDATA_YES)
    assert not any(OD.touched(q) for q in OD.OPENDATA_NO)


def test_hints_and_fallback_include_the_open_data_parsers():
    d = R.regex_decision("jours fériés de mai 2027")
    assert d.get("work_calendar") is not None and d.get("work_calendar").args["period"] == "2027-05"
    # « bank holidays in the UK »: the holiday words win over the map's « bank »
    d = R.regex_decision("bank holidays in the UK in 2027", lang="en")
    assert d.tools()[:1] == ["work_calendar"]


def test_the_agent_withdraws_make_chart_when_statistics_are_drawn():
    pre = opendata_intents.Intent("get_statistics", {"indicator": "gdp"})
    assert opendata_intents.withdraw(pre) == {"make_chart"} and opendata_intents.own(pre)


# ---------------------------------------------------------------- cards: server-side finishing, demo text


def test_entity_pictures_are_signed_same_origin_only_with_a_licence():
    w = {"type": "entity", "image": {"src": "https://upload.wikimedia.org/a.jpg", "license": "CC BY-SA 4.0"}}
    out = opendata_widgets.prepare(dict(w), b"k" * 32)
    assert out["image"]["src"].startswith("/api/img?")
    for bad in ({"src": "https://evil.org/a.jpg", "license": "CC0"}, {"src": "https://upload.wikimedia.org/a.jpg"}):
        assert opendata_widgets.prepare({"type": "entity", "image": bad}, b"k" * 32)["image"] is None


def test_the_demo_routes_open_data_asks_and_writes_from_the_card():
    from birds.web.backends import widget_scenario

    for q in ("jours fériés de mai 2027", "code postal de Roubaix", "appels d'offres maintenance informatique"):
        assert widget_scenario(q) == "opendata", q
    assert widget_scenario("météo à Lyon demain") == "weather"
    _, ctx = _run(*_ask("jours fériés de mai 2027"))
    text, titles = opendata_demo.answer("work_calendar", [ctx.step_info["widget"]], [], {}, "fr")
    assert "19 jours ouvrés" in text and "[1]" in text and titles
    _, ctx = _run(*_ask("population de Roubaix depuis 1968"))
    text, titles = opendata_demo.answer("get_statistics", [], ctx.charts, {}, "fr")
    assert "Roubaix" in text and "[1]" in text
    text, _ = opendata_demo.answer("lookup_entity", [], [], {}, "en")
    assert "not part of the demo recording" in text


def test_recorded_dates_are_normalised_so_replays_match_any_day():
    assert demo_widgets.opendata_key("https://x/y?d=2026-10-29&e=2027-01-01") == "https://x/y?d=DATE&e=DATE"
    _, ctx = _run(*_ask("appels d'offres maintenance informatique"), today=date(2027, 3, 1))
    assert ctx.step_info["widget"]["items"]


def test_links_reach_the_browser_as_https_it_accepts():
    u = "https://fr.wikipedia.org/wiki/Organisation_des_Nations_unies_pour_l'%C3%A9ducation"
    assert odhttp.link(u).endswith("pour_l%27%C3%A9ducation") and "'" not in odhttp.link(u)
    assert odhttp.link("javascript:alert(1)") == "" and odhttp.link("http://x.fr") == ""
    _, ctx = _run("lookup_entity", {"name": "Unesco"})
    w = ctx.step_info["widget"]
    assert w["url"].startswith("https://fr.wikipedia.org/") and "'" not in w["url"] and w["name"] == "Unesco"
