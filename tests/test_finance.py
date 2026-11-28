"""Markets (get_quote, birds/harness/tools/opendata/finance.py): instrument list, parser, routing checks, the tool on
answers recorded live (CoinGecko, ECB: birds/web/demo_data/finance.json), the licensed feed on a fake HTTP path
(synthetic Twelve Data bodies: its answers are never stored), the card's widget and the scripted demo."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from birds.harness import Agent, Config, Context, catalog, guard, opendata_intents
from birds.harness import router as R
from birds.harness.finance_intents import quote
from birds.harness.guard import ToolError
from birds.harness.tools.opendata import finance, markets
from birds.web import backends, demo_widgets, opendata_demo
from birds.web.widgets import build_widgets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bench_finance as FI  # noqa: E402

RECORDED = datetime.fromisoformat(demo_widgets.FINANCE_RECORDED)


def _ctx(lang="fr", request="", key=None, now=RECORDED):
    cfg = Config(workspace=Path(tempfile.gettempdir()), audit_file=None, twelvedata_api_key=key)
    ctx = Context(config=cfg, http=None, lang=lang, request=request)
    ctx.recorded = demo_widgets.recorded
    ctx.now = now
    return ctx


def _run(args, lang="fr", request=""):
    ctx = _ctx(lang, request)
    return finance.get_quote(dict(args), ctx), ctx


# ---------------------------------------------------------------- the validated list


@pytest.mark.parametrize(
    "name,key",
    [("LVMH", "lvmh"), ("l'action Hermès", "hermes"), ("CAC 40", "cac40"), ("MC.PA", "lvmh"), ("AAPL", "apple"),
     ("bitcoin", "bitcoin"), ("BTC", "bitcoin"), ("L'Oréal", "loreal"), ("Nikkei", "nikkei")],
)  # fmt: skip
def test_names_and_tickers_resolve_to_the_checked_list(name, key):
    assert markets.resolve(name).key == key


def test_unknown_names_are_never_guessed_and_capital_words_are_not_tickers():
    assert markets.resolve("Zorglub SA") is None
    with pytest.raises(ToolError, match="not in Bird's list"):
        finance.instruments_of({"symbols": "Zorglub SA"})
    assert markets.find_all("Fais un graphique du CA : T1 120, T2 135,5") == []  # CA = chiffre d'affaires
    assert markets.find_all("le CAP en alternance") == []
    assert [i.key for i in markets.find_all("cours de CA.PA et BNP")] == ["carrefour", "bnp"]


def test_every_listed_share_has_a_market_code_and_a_currency():
    for i in markets.INSTRUMENTS.values():
        if i.kind in ("equity", "index"):
            assert len(i.mic) == 4 and len(i.currency) == 3 and i.symbol


def test_currency_pairs_come_from_the_words():
    assert markets.fx_pair("EUR/USD").symbol == "EUR/USD"
    assert markets.fx_pair("euro dollar").symbol == "EUR/USD"
    assert markets.fx_pair("le yen").symbol == "EUR/JPY"  # one currency: against the euro
    assert markets.fx_pair("livre sterling euro").symbol == "GBP/EUR"
    assert markets.fx_pair("euro") is None


@pytest.mark.parametrize(
    "words,rng",
    [("sur 5 ans", "5y"), ("depuis un an", "1y"), ("over the past year", "1y"), ("6 derniers mois", "6m"),
     ("ce mois-ci", "1m"), ("cette année", "1y"), ("1M", "1m"), ("bonjour", None)],
)  # fmt: skip
def test_ranges_are_read_from_the_words(words, rng):
    assert finance.range_of(words) == rng


# ---------------------------------------------------------------- the parser (hint and fallback): the bench lists


@pytest.mark.parametrize("item", FI.FINANCE_YES, ids=lambda it: it[0][:40])
def test_the_parser_starts_every_market_ask(item):
    assert FI.started(item), opendata_intents.detect(item[0])


@pytest.mark.parametrize("q", FI.FINANCE_NO)
def test_the_parser_stays_silent_on_lessons_tasks_products_accounts_and_writing(q):
    assert not FI.touched(q), opendata_intents.detect(q)


def test_a_rate_s_history_is_the_market_chart_but_the_day_s_rate_stays_a_conversion():
    from birds.harness import intents

    def first(q):
        return next(i for i in opendata_intents.merge(intents.detect(q), q) if i.args)

    assert first("historique EUR/USD sur 1 an").tool == "get_quote"
    assert first("cours du dollar").tool == "convert_currency"
    assert first("100 dollars en euros").tool == "convert_currency"


# ---------------------------------------------------------------- the model decides: catalogue, grounding, veto


def test_the_catalogue_offers_get_quote_with_grounded_examples():
    m = catalog.BY_NAME["get_quote"]
    assert m.family == "finance" and m.kind == catalog.PREFILL
    assert "- get_quote(" in catalog.text("fr") and "- get_quote(" in catalog.text("en")
    for words, args in m.examples:
        clean, why = catalog.check_args("get_quote", args)
        assert clean is not None, why
        assert not R.ground(R.Call("get_quote", clean), words, ""), words
        assert not R.veto_reason(R.Call("get_quote", clean), words), words
    assert "get_quote" in R.available_names(Config(workspace=Path(".")))


@pytest.mark.parametrize(
    "args,text",
    [({"symbols": "Kering"}, "cours de LVMH"), ({"symbols": "EUR/JPY"}, "évolution de l'euro dollar sur 6 mois"),
     ({"symbols": "bitcoin"}, "quel temps fait-il à Lyon ?")],
)  # fmt: skip
def test_an_instrument_the_user_did_not_name_is_refused(args, text):
    assert R.ground(R.Call("get_quote", args), text, "")


@pytest.mark.parametrize(
    "text",
    ["cours de piano avec Paul", "prix d'un MacBook Air chez Apple", "chiffre d'affaires de LVMH en 2024",
     "mes actions LVMH ont baissé", "c'est quoi le bitcoin ?", "rédige un mail sur la chute du CAC 40"],
)  # fmt: skip
def test_the_veto_blocks_the_known_look_alikes_even_from_the_model(text):
    from birds.harness.tools.opendata.markets import find_all

    sym = ", ".join(i.name for i in find_all(text)) or "LVMH"
    assert R.veto_reason(R.Call("get_quote", {"symbols": sym}), text)


def test_a_router_only_ask_names_its_instrument_and_is_not_vetoed():
    for q, want in FI.FINANCE_ROUTER_YES:
        assert not quote(q)  # the parser leaves it to the model
        assert not R.veto_reason(R.Call("get_quote", want), q), q
        assert not R.ground(R.Call("get_quote", want), q, ""), q


# ---------------------------------------------------------------- the tool on recorded answers


def test_a_crypto_quote_is_dated_with_its_delay_and_drawn_by_the_chart_engine():
    text, ctx = _run({"symbols": "bitcoin", "range": "6m"})
    w = ctx.step_info["widget"]
    (item,) = w["items"]
    assert w["type"] == "quote" and w["range"] == "6m" and item["kind"] == "crypto" and item["currency"] == "EUR"
    assert item["asof_kind"] == "live" and item["asof"].startswith("2026-11-28T") and item["change_base"] == "24h"
    assert "différé de quelques minutes" in text and "temps réel" in text  # « ne dis jamais « en temps réel » »
    assert item["prev"] and round(item["last"] / item["prev"] - 1, 3) == round(item["change_pct"] / 100, 3)
    (spec,) = ctx.charts
    assert spec["type"] == "line" and spec["source"] == "data" and 20 <= len(spec["rows"]) <= 50
    assert spec["data_source"]["label"] == "CoinGecko" and "attribution" in spec["data_source"]["license"]
    assert w["sources"][0]["license_url"].startswith("https://") and ctx.sources == ["https://www.coingecko.com/"]
    assert "5y" not in w["ranges"]  # CoinGecko's free history: one year
    assert len(item["spark"]) <= 40 and item["low"] <= item["last"] * 1.2


def test_five_years_of_a_crypto_asset_are_capped_to_one_and_said():
    text, ctx = _run({"symbols": "bitcoin", "range": "5y"})
    w = ctx.step_info["widget"]
    assert w["range"] == "1y" and w["range_note"] == "crypto" and "1 an" in text


def test_a_comparison_is_rebased_to_100_on_the_first_common_day():
    text, ctx = _run({"symbols": "Bitcoin, Ethereum", "range": "6m"})
    (spec,) = ctx.charts
    assert spec["columns"] == ["Date", "Bitcoin", "Ethereum"] and spec["unit"] == "base 100"
    assert spec["rows"][0][1:] == [100.0, 100.0] and "base 100" in spec["title"]
    assert ctx.step_info["widget"]["compare"] and "base 100" in text


def test_an_ecb_pair_and_a_cross_rate_through_the_euro():
    _, ctx = _run({"symbols": "EUR/USD", "range": "6m"})
    (item,) = ctx.step_info["widget"]["items"]
    assert item["kind"] == "fx" and item["asof_kind"] == "reference" and 1 < item["last"] < 1.3
    assert ctx.charts[0]["data_source"]["label"].startswith("BCE")
    rows = finance.parse_ecb_csv("TIME_PERIOD,OBS_VALUE\n2026-11-26,1.10\n2026-11-27,1.20\n")
    assert rows == [("2026-11-26", 1.1), ("2026-11-27", 1.2)]


def test_cross_rate_math(monkeypatch):
    series = {"USD": [("2026-11-27", 1.10)], "JPY": [("2026-11-27", 176.0)]}
    monkeypatch.setattr(finance, "_ecb_series", lambda ctx, cur, start: series[cur])
    inst = markets.fx_pair("USD/JPY")
    rows, meta = finance._ecb(None, inst, 31, RECORDED.date())
    assert rows == [("2026-11-27", 160.0)] and meta["currency"] == "JPY"
    rows, _ = finance._ecb(None, markets.fx_pair("USD/EUR"), 31, RECORDED.date())
    assert rows == [("2026-11-27", round(1 / 1.10, 6))]


def test_the_card_s_own_asks_start_the_updated_chart_again():
    """Continuity: « Sur 5 ans », « Comparer avec … » are typed asks the parser reads as get_quote."""
    for args in ({"symbols": "bitcoin"}, {"symbols": "EUR/USD", "range": "1y"}):
        _, ctx = _run(args)
        asks = ctx.step_info["widget"]["asks"]
        assert 2 <= len(asks) <= 3
        from birds.harness import intents

        for q in asks:
            got = next(i for i in opendata_intents.merge(intents.detect(q), q) if i.args)
            assert got.tool in ("get_quote", "convert_currency"), q
    w = {"items": [{"key": "lvmh", "name": "LVMH", "kind": "equity", "mic": "XPAR", "symbol": "MC"}]}
    for q in finance._asks(w["items"], "6m", "fr") + finance._asks(w["items"], "6m", "en"):
        got = quote(q, "en" if "stock" in q or "compare" in q and "with" in q else "fr")
        assert got and got.args, q


def test_advice_gets_one_neutral_line_and_no_recommendation():
    text, ctx = _run({"symbols": "bitcoin"}, request="dois-je acheter du bitcoin maintenant ?")
    assert ctx.step_info["widget"]["advice"] is True and "n'en donne aucun" in text
    _, ctx = _run({"symbols": "bitcoin"}, request="cours du bitcoin")
    assert ctx.step_info["widget"]["advice"] is False


def test_crypto_prices_in_dollars_when_the_words_say_so():
    _, ctx = _run({"symbols": "bitcoin", "range": "6m"}, lang="en", request="bitcoin price in dollars")
    assert ctx.step_info["widget"]["items"][0]["currency"] == "USD"


# ---------------------------------------------------------------- the licensed feed (shares, indices)


def _twelve_body(days):
    return {"meta": {"symbol": "MC", "currency": "EUR", "exchange_timezone": "Europe/Paris", "mic_code": "XPAR"},
            "values": [{"datetime": d, "close": str(c)} for d, c in days], "status": "ok"}  # fmt: skip


@pytest.fixture
def fake_fetch(monkeypatch):
    from birds.harness import geo

    monkeypatch.setattr(geo.POLICY, "wait_turn", lambda host: None)
    monkeypatch.setattr(geo.POLICY, "get", lambda key, disk=None: None)  # every test asks the fake afresh
    monkeypatch.setattr(geo.POLICY, "put", lambda *a, **k: None)
    calls = []

    def install(body):
        def f(http, cfg, url, **kw):
            calls.append((url, kw.get("headers") or {}))
            if isinstance(body, Exception):
                raise body
            return 200, "application/json", json.dumps(body).encode(), {}

        monkeypatch.setattr(guard, "fetch_bytes", f)
        return calls

    return install


def _live(key="k-123", now=None):
    cfg = Config(workspace=Path(tempfile.gettempdir()), audit_file=None, geo_cache_dir=None, twelvedata_api_key=key)
    ctx = Context(config=cfg, http=object(), lang="fr", request="cours de LVMH")
    ctx.now = now or datetime(2026, 11, 28, 9, 0, tzinfo=UTC)
    return ctx


def test_shares_need_the_licensed_feed_and_its_key_travels_in_a_header(fake_fetch):
    days = [(f"2026-11-{d:02d}", 600 + d) for d in range(2, 28) if d not in (8, 9, 15, 16, 22, 23)]  # synthetic
    calls = fake_fetch(_twelve_body(days))
    text = finance.get_quote({"symbols": "LVMH", "range": "1m"}, _live())
    ((url, headers),) = calls
    assert "k-123" not in url and headers == {"Authorization": "apikey k-123"}
    assert "symbol=MC" in url and "mic_code=XPAR" in url
    assert "clôture du 27 novembre 2026, pas en temps réel" in text


def test_today_s_bar_is_dropped_while_the_session_is_open(fake_fetch):
    days = [("2026-11-26", 600.0), ("2026-11-27", 610.0), ("2026-11-30", 590.0)]  # synthetic
    fake_fetch(_twelve_body(days))
    ctx = _live(now=datetime(2026, 11, 30, 13, 0, tzinfo=UTC))  # 14:00 in Paris: the session is open
    finance.get_quote({"symbols": "LVMH", "range": "1m"}, ctx)
    (item,) = ctx.step_info["widget"]["items"]
    assert item["asof"] == "2026-11-27" and item["last"] == 610.0 and item["asof_kind"] == "close"


def test_a_refused_key_is_a_calm_error(fake_fetch):
    fake_fetch(ToolError("HTTP 401"))
    with pytest.raises(ToolError, match="refused|not connected"):
        finance.get_quote({"symbols": "LVMH"}, _live())


def test_without_a_key_shares_are_not_prefilled_and_crypto_still_is():
    cfg = Config(workspace=Path("."))
    assert not finance.usable({"symbols": "LVMH, Hermès"}, cfg)
    assert finance.usable({"symbols": "LVMH, bitcoin"}, cfg) and finance.usable({"symbols": "EUR/USD"}, cfg)
    assert finance.usable({"symbols": "LVMH"}, Config(workspace=Path("."), twelvedata_api_key="k"))
    with pytest.raises(ToolError, match="not connected on this server"):
        finance.get_quote({"symbols": "LVMH"}, _ctx())


def test_the_agent_leaves_a_shares_ask_to_the_web_without_the_key(tmp_path):
    from birds.harness.llm import FakeClient
    from birds.harness.template import TemplateTokenizer
    from birds.harness.tools import StaticBackend

    llm = FakeClient(["Je cherche."])
    agent = Agent(llm, TemplateTokenizer(), Config(workspace=tmp_path, audit_file=None),
                  search=StaticBackend([]), http=httpx.Client())  # fmt: skip
    run = agent.run("Cherche le cours de l'action Airbus aujourd'hui.", lang="fr")
    assert not any(s.tool == "get_quote" for s in run.steps)
    assert "get_quote" not in llm.prompts[0]


# ---------------------------------------------------------------- the card reaches the browser, the demo


def test_the_quote_card_goes_through_build_widgets_unchanged():
    from types import SimpleNamespace

    _, ctx = _run({"symbols": "bitcoin"})
    step = SimpleNamespace(tool="get_quote", info=ctx.step_info, error=None)
    (w,) = build_widgets([step], "cours du bitcoin", "fr", RECORDED, b"k")
    assert w["type"] == "quote" and w["items"][0]["name"] == "Bitcoin" and len(json.dumps(w)) < 8000


def test_the_scripted_demo_quotes_crypto_and_rates_from_its_recording_never_shares():
    assert backends.widget_scenario("cours du bitcoin") == "opendata"
    assert backends.widget_scenario("évolution de l'euro dollar sur 6 mois") == "opendata"
    assert backends.widget_scenario("cours de l'action LVMH") != "opendata"
    charts: list = []
    _, info, _ = demo_widgets.run_tool("get_quote", {"symbols": "Bitcoin, Ethereum", "range": "6m"}, "fr", charts)
    text, titles = opendata_demo.answer("get_quote", [info["widget"]], charts, info, "fr")
    assert "**Bitcoin**" in text and "**Ethereum**" in text and "[1]" in text and "base 100" in text
    assert "https://www.coingecko.com/" in titles
