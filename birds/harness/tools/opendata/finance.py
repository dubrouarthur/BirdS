"""get_quote: the last price, the change and the history of a share, an index, a crypto-asset or a currency pair.

« cours de LVMH », « le CAC 40 sur 5 ans », « compare LVMH et Hermès », « bitcoin sur 1 an », « euro dollar sur
6 mois ». The harness resolves each name against a short validated list (``markets.py``: never a ticker guessed by
the model), fetches the real series from the provider whose terms allow this use, and shows:

- a quote card (type ``quote``): last price, change since the previous close as a sign, an arrow and a coloured
  figure, a sparkline, and the date of the figure with its delay (« clôture du 27 novembre 2026 »: never « en
  temps réel » when it is not);
- the history in the chart engine (``ctx.charts``, a line through ``chart.normalize_chart``): the price, or every
  line rebased to 100 on the first common day when up to three instruments are compared; table, PNG and CSV come
  with the chart.

Providers (docs/FINANCE.md says why each one, and why the others were rejected):

- shares and indices: Twelve Data (``/time_series``), a licensed market data feed. It needs a key with display
  rights, ``BIRD_TWELVEDATA_API_KEY`` (sent in a header, never in the URL). Without it, shares and indices are
  said to be unavailable here; nothing is scraped elsewhere;
- crypto-assets: CoinGecko public API, keyless (attribution required, history limited to 365 days);
  ``BIRD_COINGECKO_API_KEY`` (a free Demo key) only raises the quota;
- currency pairs: ECB Data Portal, daily reference rates (EXR), free reuse with the source quoted.

The model never writes a figure of its own: the result text gives it the exact numbers to quote. No advice: when
the user asks whether to buy or sell, the card carries one neutral line and the model is told to give none.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from birds.harness.guard import ToolError
from birds.harness.tools.chart import MAX_CHARTS, MAX_ROWS, normalize_chart

from . import http
from .markets import MAX_SYMBOLS, Instrument, find_all, fx_pair, resolve

RANGES = {"1m": 31, "6m": 183, "1y": 366, "5y": 5 * 366}
RANGE_WORDS = {
    "fr": {"1m": "1 mois", "6m": "6 mois", "1y": "1 an", "5y": "5 ans"},
    "en": {"1m": "1 month", "6m": "6 months", "1y": "1 year", "5y": "5 years"},
}
DEFAULT_RANGE = "6m"
CRYPTO_MAX_DAYS = 365  # CoinGecko public and Demo plans: the past 365 days only

TWELVE = "https://api.twelvedata.com/time_series"
TWELVE_SRC = {"label": "Twelve Data", "url": "https://twelvedata.com/",
              "license": "Données de marché sous licence Twelve Data", "license_en": "Market data licensed by Twelve Data",
              "license_url": "https://twelvedata.com/terms"}  # fmt: skip
GECKO = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
GECKO_PRICE = "https://api.coingecko.com/api/v3/simple/price"
GECKO_SRC = {"label": "CoinGecko", "url": "https://www.coingecko.com/",
             "license": "Données fournies par CoinGecko, attribution requise",
             "license_en": "Data provided by CoinGecko, attribution required",
             "license_url": "https://brand.coingecko.com/resources/attribution-guide"}  # fmt: skip
ECB_DATA = "https://data-api.ecb.europa.eu/service/data/EXR/D.{cur}.EUR.SP00.A"
ECB_SRC = {"label": "BCE — taux de référence", "label_en": "ECB — reference rates",
           "url": "https://data.ecb.europa.eu/data/datasets/EXR",
           "license": "Réutilisation libre, source citée (« Source : BCE »)",
           "license_en": "Free reuse with the source quoted (“Source: ECB”)",
           "license_url": "https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/"
                          "usage_policy.en.html"}  # fmt: skip

# when the day's session is over (local time of the home market, with a few minutes for the closing auction)
_CLOSE = {"XPAR": ("Europe/Paris", 17, 40), "XETR": ("Europe/Berlin", 17, 40), "XLON": ("Europe/London", 16, 40),
          "XNGS": ("America/New_York", 16, 5), "XNYS": ("America/New_York", 16, 5), "XJPX": ("Asia/Tokyo", 15, 35)}  # fmt: skip

# « dois-je acheter », « faut-il vendre », « should I buy »: the card says it gives no advice, the model gives none
ADVICE = re.compile(
    r"\b(?:dois[- ]je|devrais[- ]je|faut[- ]il|vaut[- ]il\s+(?:mieux|le\s+coup)|est[- ]ce\s+(?:le\s+moment|"
    r"une\s+bonne\s+id[ée]e)|conseill?\w*|recommand\w*|bon\s+placement|investir|placer|should\s+i|"
    r"is\s+it\s+(?:a\s+good|time)|worth\s+buying|advice|advise|recommend\w*)\b", re.I)  # fmt: skip


def range_of(text: str) -> str | None:
    """« sur 5 ans », « depuis un an », « 6 derniers mois », « 1M », « over a year »: a range key, or None."""
    t = http.clean(text, 300).lower().replace("’", "'")
    if re.search(r"\b(?:5|cinq|five)\s*(?:(?:derni[èe]res|last|past)\s+)?(?:ans?|ann[ée]es|years?|y)\b|\b5a\b", t):
        return "5y"
    if re.search(
        r"\b(?:1|un|une|one|a)\s*(?:ans?|ann[ée]e|year|y)\b|\b(?:12|douze|twelve)\s*mois\b|\b1a\b|"
        r"\b(?:past|last)\s+(?:year|12\s+months)\b|\bann[ée]e\s+[ée]coul[ée]e\b|"
        r"\bsur\s+l'ann[ée]e\b|\bannuel|\bthis\s+year\b|\bcette\s+ann[ée]e\b|\bdepuis\s+janvier\b",
        t,
    ):
        return "1y"
    if re.search(r"\b(?:6|six)\s*(?:(?:derniers|last|past)\s+)?(?:mois|months?|m)\b|\bsemestre\b|\b6m\b", t):
        return "6m"
    if re.search(
        r"\b(?:1|un|one|a)\s*(?:mois|month)\b|\b(?:30|trente)\s*(?:jours|days)\b|\b1m\b|\bce\s+mois\b|"
        r"\bthis\s+month\b|\b(?:4|quatre)\s+semaines\b",
        t,
    ):
        return "1m"
    return None


def advice_asked(text: str) -> bool:
    return bool(ADVICE.search(str(text or "")))


# ---------------------------------------------------------------- providers: [(day ISO, close)] ascending


def _twelve(ctx, inst: Instrument, days: int) -> tuple[list[tuple[str, float]], dict]:
    key = getattr(ctx.config, "twelvedata_api_key", None)
    if not key:
        raise NeedsKey(inst)
    size = min(5000, int(days * 252 / 365) + 10)
    u = http.url(TWELVE, {"symbol": inst.symbol, "mic_code": inst.mic, "interval": "1day", "outputsize": size,
                          "order": "asc", "timezone": "Exchange"})  # fmt: skip
    try:
        data = http.get(ctx, u, headers={"Authorization": f"apikey {key}"})
    except ToolError as e:
        if re.match(r"HTTP 40[13]", str(e)):
            data = {"status": "error", "code": 401}
        else:
            raise
    if not isinstance(data, dict) or data.get("status") == "error" or not isinstance(data.get("values"), list):
        code = data.get("code") if isinstance(data, dict) else None
        if code in (401, 403):
            raise ToolError("the market data key was refused (plan or symbol not covered); say shares are not "
                            "available here, invent no figure")  # fmt: skip
        if code == 429:
            raise ToolError("the market data service is busy (HTTP 429): try again in a minute")
        raise ToolError(f"no prices for {inst.name}; say so, invent none")
    meta = data.get("meta") or {}
    rows = []
    for v in data["values"]:
        d, c = str(v.get("datetime") or "")[:10], v.get("close")
        try:
            rows.append((d, float(c)))
        except (TypeError, ValueError):
            continue
    rows.sort()
    rows = _closed_only(rows, inst.mic, getattr(ctx, "now", None))
    cur = str(meta.get("currency") or inst.currency).upper()[:3]
    return rows, {"currency": cur, "asof_kind": "close"}


def _closed_only(rows: list[tuple[str, float]], mic: str, now: datetime | None) -> list[tuple[str, float]]:
    """Drop today's bar while the session is still open: the card only ever shows a CLOSE."""
    if not rows or mic not in _CLOSE:
        return rows
    tz, hh, mm = _CLOSE[mic]
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo(tz))
    if rows[-1][0] == local.date().isoformat() and (local.hour, local.minute) < (hh, mm):
        return rows[:-1]
    return rows


def _gecko_headers(ctx) -> dict | None:
    key = getattr(ctx.config, "coingecko_api_key", None)
    return {"x-cg-demo-api-key": key} if key else None


def _gecko(ctx, inst: Instrument, days: int, vs: str) -> tuple[list[tuple[str, float]], dict]:
    days = min(days, CRYPTO_MAX_DAYS) if days <= RANGES["1y"] else days
    if days > CRYPTO_MAX_DAYS:
        raise ToolError("CoinGecko's free history covers the past 365 days only: say so and offer 1 year")
    n = 30 if days <= 31 else 180 if days <= 183 else 365
    u = http.url(GECKO.format(id=inst.symbol), {"vs_currency": vs.lower(), "days": n, "interval": "daily"})
    data = http.get(ctx, u, headers=_gecko_headers(ctx))
    prices = data.get("prices") if isinstance(data, dict) else None
    if not isinstance(prices, list) or not prices:
        raise ToolError(f"no prices for {inst.name}; say so, invent none")
    by_day: dict[str, float] = {}
    last_ts = 0
    for p in prices:
        if not (isinstance(p, list) and len(p) == 2 and isinstance(p[1], (int, float))):
            continue
        ts = int(p[0]) // 1000
        d = datetime.fromtimestamp(ts, UTC).date().isoformat()
        by_day[d] = float(p[1])  # the latest point of a day wins: the last one is « now »
        last_ts = max(last_ts, ts)
    rows = sorted(by_day.items())
    at = datetime.fromtimestamp(last_ts, UTC).strftime("%Y-%m-%dT%H:%MZ") if last_ts else ""
    return rows, {"currency": vs.upper(), "asof_kind": "live", "asof": at}


def _gecko_now(ctx, insts: list[Instrument], vs: str) -> dict:
    """{coin id: (price, 24 h change %, ISO time)} in ONE request for every crypto-asset of the answer."""
    u = http.url(GECKO_PRICE, {"ids": ",".join(i.symbol for i in insts), "vs_currencies": vs.lower(),
                               "include_24hr_change": "true", "include_last_updated_at": "true"})  # fmt: skip
    data = http.get(ctx, u, headers=_gecko_headers(ctx))
    out = {}
    for i in insts:
        row = (data or {}).get(i.symbol) if isinstance(data, dict) else None
        if isinstance(row, dict) and isinstance(row.get(vs.lower()), (int, float)):
            ts = row.get("last_updated_at")
            at = datetime.fromtimestamp(int(ts), UTC).strftime("%Y-%m-%dT%H:%MZ") if ts else ""
            ch = row.get(f"{vs.lower()}_24h_change")
            out[i.symbol] = (float(row[vs.lower()]), float(ch) if isinstance(ch, (int, float)) else None, at)
    return out


def parse_ecb_csv(text: str) -> list[tuple[str, float]]:
    rows = []
    for r in csv.DictReader(io.StringIO(text or "")):
        try:
            rows.append((str(r["TIME_PERIOD"])[:10], float(r["OBS_VALUE"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(rows)


def _ecb_series(ctx, cur: str, start: date) -> list[tuple[str, float]]:
    if not re.fullmatch(r"[A-Z]{3}", cur):
        raise ToolError("invalid currency")
    u = http.url(ECB_DATA.format(cur=cur), {"startPeriod": start.isoformat(), "format": "csvdata"})
    try:
        text = http.get(ctx, u, text=True, accept="text/csv", types=("text/csv", "application/csv", "text/plain"))
    except ToolError as e:
        if str(e) == "HTTP 404":
            raise ToolError(f"the ECB publishes no reference rate for {cur}; say so") from None
        raise
    rows = parse_ecb_csv(text) if isinstance(text, str) else []
    if not rows:
        raise ToolError(f"the ECB publishes no reference rate for {cur}; say so")
    return rows


def _ecb(ctx, inst: Instrument, days: int, today: date) -> tuple[list[tuple[str, float]], dict]:
    """1 base = x quote, from the ECB's « units of currency per euro » (cross rates through the euro)."""
    start = today - timedelta(days=days)
    base, quote = inst.base, inst.currency
    if base == "EUR":
        rows = _ecb_series(ctx, quote, start)
    elif quote == "EUR":
        rows = [(d, 1 / v) for d, v in _ecb_series(ctx, base, start) if v]
    else:
        b = dict(_ecb_series(ctx, base, start))
        rows = [(d, v / b[d]) for d, v in _ecb_series(ctx, quote, start) if b.get(d)]
    return [(d, round(v, 6)) for d, v in rows], {"currency": quote, "asof_kind": "reference"}


class NeedsKey(ToolError):
    def __init__(self, inst: Instrument):
        super().__init__(f"no licensed market data feed for {inst.name}")
        self.inst = inst


# ---------------------------------------------------------------- shaping


def sample(rows: list, n: int = MAX_ROWS) -> list:
    """At most ``n`` evenly spaced points, the first and the LAST always kept (the chart ends on the card's figure)."""
    if len(rows) <= n:
        return list(rows)
    step = (len(rows) - 1) / (n - 1)
    idx = sorted({round(i * step) for i in range(n)} | {len(rows) - 1})
    return [rows[i] for i in idx]


def _digits(v: float) -> int:
    """The card's own rule (finance.js fmtPrice): none from 10 000, 2 from 10, else 4 (« 1,0957 » for a rate)."""
    return 0 if abs(v) >= 10000 else 2 if abs(v) >= 10 else 4


def fmt(v: float | None, lang: str, digits: int | None = None) -> str:
    if v is None:
        return "?"
    d = _digits(v) if digits is None else digits
    s = f"{v:,.{d}f}"
    return s.replace(",", " ").replace(".", ",") if lang == "fr" else s


MONTHS_FR = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()
MONTHS_EN = "January February March April May June July August September October November December".split()


def day_text(iso: str, lang: str) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return (
        f"{d.day} {MONTHS_FR[d.month - 1]} {d.year}" if lang == "fr" else f"{MONTHS_EN[d.month - 1]} {d.day}, {d.year}"
    )


def asof_text(item: dict, lang: str) -> str:
    """« clôture du 27 novembre 2026 », « cours du 28 novembre 2026 à 09:55 UTC, différé de quelques minutes »,
    « taux de référence BCE du 27 novembre 2026 »."""
    k, at = item.get("asof_kind"), str(item.get("asof") or "")
    if k == "live":
        hm = at[11:16]
        return (f"cours du {day_text(at, lang)} à {hm} UTC, différé de quelques minutes" if lang == "fr" else
                f"price on {day_text(at, lang)} at {hm} UTC, a few minutes delayed")  # fmt: skip
    if k == "reference":
        return (f"taux de référence BCE du {day_text(at, lang)}, publié vers 16 h, heure de Francfort" if lang == "fr"
                else f"ECB reference rate of {day_text(at, lang)}, published around 4 pm CET")  # fmt: skip
    return f"clôture du {day_text(at, lang)}, pas en temps réel" if lang == "fr" else (
        f"close of {day_text(at, lang)}, not real time")  # fmt: skip


def _asks(items: list[dict], rng: str, lang: str) -> list[str]:
    """2 or 3 next asks built from the card (continuity: each one draws the updated chart)."""
    fr = lang == "fr"
    names = " et ".join(i["name"] for i in items) if fr else " and ".join(i["name"] for i in items)
    if any(i["kind"] == "equity" for i in items):  # « Apple » alone is a brand: the ask names the share
        names = f"cours de {names}" if fr else f"{names} stock"
    first = items[0]
    out = []
    crypto = any(i["kind"] == "crypto" for i in items)
    for r in ("5y", "1y", "1m") if not crypto else ("1y", "1m", "6m"):
        if r != rng:
            w = RANGE_WORDS[lang][r]
            out.append(f"{names} sur {w}" if fr else f"{names} over {w}")
            break
    if len(items) < MAX_SYMBOLS:
        keys = {i["key"] for i in items}
        other = None
        if first["kind"] == "equity":
            other = {"XPAR": "cac40", "XETR": "dax", "XLON": "ftse100"}.get(first.get("mic", ""))
            if first.get("mic") in ("XNGS", "XNYS"):
                other = "microsoft" if first["key"] != "microsoft" else "apple"
        elif first["kind"] == "index":
            other = "dax" if first["key"] != "dax" else "cac40"
        elif first["kind"] == "crypto":
            other = "ethereum" if first["key"] != "ethereum" else "bitcoin"
        from .markets import INSTRUMENTS

        if other and other not in keys:
            o = INSTRUMENTS[other].name
            names = f"le {names}" if fr and names.startswith("cours") else names
            out.append(f"compare {names} avec {'le ' if INSTRUMENTS[other].kind == 'index' else ''}{o}" if fr else
                       f"compare {names} with {'the ' if INSTRUMENTS[other].kind == 'index' else ''}{o}")  # fmt: skip
    if first["kind"] == "fx" and len(items) == 1:
        b, q = first["symbol"].split("/")
        out.append(f"convertis 100 {b} en {q}" if fr else f"convert 100 {b} to {q}")
    return out[:3]


# ---------------------------------------------------------------- the tool


def instruments_of(args: dict) -> list[Instrument]:
    raw = str(args.get("symbols") or args.get("symbol") or args.get("query") or "")
    parts = [p.strip() for p in re.split(r"\s*(?:,|;|\bet\b|\band\b|\bvs\.?|\bversus\b|\bcontre\b|/(?=\s))\s*", raw)
             if p.strip()]  # fmt: skip
    out: list[Instrument] = []
    for p in parts:
        inst = resolve(p)
        if inst is None:
            got = find_all(p)
            inst = got[0] if len(got) == 1 else None
        if inst is None:
            raise ToolError(f"'{http.clean(p, 40)}' is not in Bird's list of quoted instruments (CAC 40 and large "
                            "US shares, main indices, bitcoin and main crypto-assets, ECB currencies): say so, "
                            "never guess a ticker or a price")  # fmt: skip
        if inst not in out:
            out.append(inst)
    if not out:
        fx = fx_pair(raw)
        if fx:
            out = [fx]
    if not out:
        raise ToolError("no instrument named: give a share, an index, a crypto-asset or a currency pair")
    if len(out) > MAX_SYMBOLS:
        raise ToolError(f"at most {MAX_SYMBOLS} instruments in one comparison")
    return out


def usable(args: dict, cfg) -> bool:
    """Can this deployment quote these instruments? Shares and indices need the licensed feed's key; crypto-assets
    and currencies never do. Without it, a shares-only ask is not prefilled: the turn goes on as before (the model
    may search the web, with its sources), never a card that can only say « not available »."""
    try:
        insts = instruments_of(args)
    except ToolError:
        return True  # the tool itself explains what it does not know
    return bool(getattr(cfg, "twelvedata_api_key", None)) or any(i.kind in ("crypto", "fx") for i in insts)


def get_quote(args: dict, ctx) -> str:
    lang = http.lang_of(ctx)
    now = getattr(ctx, "now", None) or datetime.now(UTC)
    today = getattr(ctx, "today", None) or now.date()
    if len(getattr(ctx, "charts", [])) >= MAX_CHARTS:
        raise ToolError(f"at most {MAX_CHARTS} charts per request: answer the user now")
    insts = instruments_of(args)
    rng = str(args.get("range") or "").lower()
    rng = rng if rng in RANGES else (range_of(rng) or DEFAULT_RANGE)
    vs = str(args.get("currency") or "").upper()
    if vs not in ("EUR", "USD"):  # crypto prices in: the user's own words (« en dollars »), else the language's
        words = str(getattr(ctx, "request", "") or "")
        vs = ("USD" if re.search(r"\b(?:en|in)\s+(?:dollars?|usd)\b|\$", words, re.I) else
              "EUR" if re.search(r"\b(?:en|in)\s+(?:euros?|eur)\b|€", words, re.I) else
              "USD" if lang == "en" else "EUR")  # fmt: skip
    if rng == "5y" and any(i.kind == "crypto" for i in insts):
        rng_note = "crypto"
        rng = "1y"
    else:
        rng_note = ""
    days = RANGES[rng]
    series: dict[str, list[tuple[str, float]]] = {}
    metas: dict[str, dict] = {}
    missing: list[Instrument] = []
    failed: list[tuple[Instrument, str]] = []
    cryptos = [i for i in insts if i.kind == "crypto"]
    now_prices = _gecko_now(ctx, cryptos, vs) if cryptos else {}
    for inst in insts:
        try:
            if inst.kind in ("equity", "index"):
                rows, meta = _twelve(ctx, inst, days)
            elif inst.kind == "crypto":
                rows, meta = _gecko(ctx, inst, days, vs)
            else:
                rows, meta = _ecb(ctx, inst, days, today)
        except NeedsKey:
            missing.append(inst)
            continue
        except ToolError as e:  # one provider down or one name without data: the others are still shown
            failed.append((inst, str(e)))
            continue
        cut = (today - timedelta(days=min(days, CRYPTO_MAX_DAYS) if inst.kind == "crypto" else days)).isoformat()
        rows = [r for r in rows if r[0] >= cut]
        if len(rows) < 2:
            failed.append((inst, f"not enough prices for {inst.name} over this period; say so, invent none"))
            continue
        series[inst.key], metas[inst.key] = rows, meta
    if failed and not series and not missing:
        raise ToolError(failed[0][1])
    if not series:
        names = ", ".join(i.name for i in missing)
        raise ToolError(
            f"share and index prices ({names}) come from a licensed market data feed that is not connected on this "
            "server yet. Say so in one plain sentence, invent no price and do not send the user to another website; "
            "offer what Bird can chart right now: bitcoin or ether prices, or a currency pair such as euro/dollar "
            "(ECB rates)")  # fmt: skip
    items: list[dict] = []
    for inst in insts:
        if inst.key not in series:
            continue
        rows, meta = series[inst.key], metas[inst.key]
        last_d, last = rows[-1]
        prev = rows[-2][1]
        item = {"key": inst.key, "name": inst.name, "kind": inst.kind, "symbol": inst.symbol, "mic": inst.mic,
                "currency": meta["currency"], "last": round(last, 6), "prev": round(prev, 6),
                "asof_kind": meta["asof_kind"], "asof": meta.get("asof") or last_d,
                "change_base": "prev_close"}  # fmt: skip
        if inst.kind == "crypto" and inst.symbol in now_prices:
            p, ch24, at = now_prices[inst.symbol]
            item.update(last=round(p, 6), asof=at or item["asof"], change_base="24h")
            item["prev"] = round(p / (1 + ch24 / 100), 6) if ch24 is not None else round(prev, 6)
        item["change"] = round(item["last"] - item["prev"], 6)
        item["change_pct"] = round((item["last"] / item["prev"] - 1) * 100, 2) if item["prev"] else None
        first = rows[0][1]
        item["period_pct"] = round((last / first - 1) * 100, 2) if first else None
        item["high"] = round(max(v for _, v in rows), 6)
        item["low"] = round(min(v for _, v in rows), 6)
        item["start"] = rows[0][0]
        item["spark"] = [round(v, 6) for _, v in sample(rows, 40)]
        items.append(item)
    # the chart: the price alone, or every line rebased to 100 on the first common day
    compare = len(items) > 1
    base_rows = sample(series[items[0]["key"]], MAX_ROWS)
    if compare:
        start = max(series[i["key"]][0][0] for i in items)
        base_rows = sample([r for r in series[items[0]["key"]] if r[0] >= start], MAX_ROWS)
    cols = ["Date"] + [i["name"] for i in items]
    table = []
    firsts = {}
    for d, _ in base_rows:
        row: list = [d]
        for i in items:
            s = series[i["key"]]
            v = next((x for dd, x in reversed(s) if dd <= d), None)  # last known close on or before that day
            if compare and v is not None:
                firsts.setdefault(i["key"], v)
                v = round(v / firsts[i["key"]] * 100, 2)
            elif v is not None:
                v = round(v, 4 if v < 10 else 2)
            row.append(v)
        table.append(row)
    rw = RANGE_WORDS[lang][rng]
    if compare:
        title = (f"{' · '.join(i['name'] for i in items)} — base 100 au {day_text(table[0][0], lang)} ({rw})"
                 if lang == "fr" else
                 f"{' · '.join(i['name'] for i in items)} — rebased to 100 on {day_text(table[0][0], lang)} ({rw})")  # fmt: skip
        unit = "base 100"
    else:
        it = items[0]
        title = f"{it['name']} — {rw}" + (f" ({it['currency']})" if it["currency"] else "")
        unit = it["currency"] if it["kind"] != "fx" else ""
    spec, _ = normalize_chart({"title": title, "type": "line", "columns": cols, "rows": table, "unit": unit},
                              lang, getattr(ctx, "request", ""))  # fmt: skip
    srcs = _sources(items, lang)
    step = len(series[items[0]["key"]]) / max(1, len(base_rows))
    notes = []
    if step > 1.5:
        notes.append(f"un point sur {round(step)} jours de cotation, dernière valeur incluse" if lang == "fr" else
                     f"one point every {round(step)} trading days, last value included")  # fmt: skip
    if compare:
        notes.append("base 100 calculée par Bird" if lang == "fr" else "rebased to 100 by Bird")
    main = srcs[0]
    data_source = {"label": " · ".join(s["label"] for s in srcs), "url": main["url"],
                   "license": main["license"], "license_url": main["license_url"],
                   "updated": str(items[0]["asof"])[:10],
                   "subtitle": asof_text(items[0], lang) if not compare else (
                       "clôtures quotidiennes" if lang == "fr" else "daily closes"),
                   "note": " ; ".join(notes) if lang == "fr" else "; ".join(notes)}  # fmt: skip
    spec = {"id": f"c{len(ctx.charts) + 1}", **spec, "source": "data", "data_source": data_source}
    ctx.charts.append(spec)
    n_src = [http.cite(ctx, s["url"]) for s in srcs]
    advice = advice_asked(getattr(ctx, "request", "") or getattr(ctx, "message", ""))
    ranges = ["1m", "6m", "1y"] if any(i["kind"] == "crypto" for i in items) else ["1m", "6m", "1y", "5y"]
    widget = {"type": "quote", "v": 1, "range": rng, "ranges": ranges, "items": items, "compare": compare,
              "chart": spec["id"], "sources": srcs, "advice": advice,
              "missing": [i.name for i in missing], "range_note": rng_note,
              "asks": _asks(items, rng, lang)}  # fmt: skip
    ctx.step_info = {"widget": widget, "chart": spec["id"], "label": main["label"], "values": len(table),
                     "series": len(items), "type": "line"}  # fmt: skip
    out = _result(items, compare, rng, missing, rng_note, advice, n_src, lang)
    if failed:
        out += (" Sans données ici : " if lang == "fr" else " No data here: ") + "; ".join(
            f"{i.name} ({http.clean(why, 90)})" for i, why in failed)
        widget["unavailable"] = [i.name for i, _ in failed]
    return out


def _sources(items: list[dict], lang: str) -> list[dict]:
    out = []
    for i in items:
        s = TWELVE_SRC if i["kind"] in ("equity", "index") else GECKO_SRC if i["kind"] == "crypto" else ECB_SRC
        e = {"label": s.get("label_en", s["label"]) if lang == "en" else s["label"], "url": s["url"],
             "license": s.get("license_en", s["license"]) if lang == "en" else s["license"],
             "license_url": s["license_url"]}  # fmt: skip
        if e not in out:
            out.append(e)
    return out


def _result(items, compare, rng, missing, rng_note, advice, n_src, lang) -> str:
    fr = lang == "fr"
    rw = RANGE_WORDS[lang][rng]
    facts = []
    for i in items:
        cur = f" {i['currency']}" if i["kind"] != "fx" else ""
        sign = "+" if (i["change_pct"] or 0) > 0 else ""
        base = ("sur 24 h" if fr else "over 24 h") if i["change_base"] == "24h" else (
            "par rapport à la clôture précédente" if fr else "from the previous close")  # fmt: skip
        pp = f"{'+' if (i['period_pct'] or 0) > 0 else ''}{fmt(i['period_pct'], lang, 2)} %"
        facts.append(
            f"{i['name']} : {fmt(i['last'], lang)}{cur} ({asof_text(i, lang)}), {sign}{fmt(i['change_pct'], lang, 2)} % "
            f"{base} ; {pp} sur {rw} (plus haut {fmt(i['high'], lang)}, plus bas {fmt(i['low'], lang)})" if fr else
            f"{i['name']}: {fmt(i['last'], lang)}{cur} ({asof_text(i, lang)}), {sign}{fmt(i['change_pct'], lang, 2)} % "
            f"{base}; {pp} over {rw} (high {fmt(i['high'], lang)}, low {fmt(i['low'], lang)})")  # fmt: skip
    cites = "".join(f"[{n}]" for n in n_src)
    if fr:
        out = ("Fiche de cours et graphique affichés à l'utilisateur (ne cite pas cette note). " + " ; ".join(facts)
               + ". Donne ces chiffres exacts avec leur date, en 1 à 3 phrases, sans redessiner le graphique ; ne dis "
               "jamais « en temps réel ».")  # fmt: skip
        if compare:
            out += " Le graphique compare les lignes en base 100."
        if missing:
            out += (f" Pas de cours pour {', '.join(i.name for i in missing)} : le flux de marché sous licence n'est "
                    "pas branché sur ce serveur ; dis-le simplement, n'invente aucun chiffre.")  # fmt: skip
        if rng_note:
            out += " L'historique gratuit des cryptoactifs s'arrête à 1 an : dis-le."
        if advice:
            out += (" L'utilisateur demande un conseil : n'en donne aucun (ni achat, ni vente, ni prévision) ; une "
                    "phrase neutre suffit, la fiche le précise.")  # fmt: skip
        return out + f" Source à citer : {cites}."
    out = ("Quote card and chart displayed to the user (do not quote this note). " + "; ".join(facts)
           + ". Give these exact figures with their date in 1 to 3 sentences, do not draw the chart again; never "
           "say « real time ».")  # fmt: skip
    if compare:
        out += " The chart compares the lines rebased to 100."
    if missing:
        out += (f" No prices for {', '.join(i.name for i in missing)}: the licensed market feed is not connected on "
                "this server; say so plainly, invent no figure.")  # fmt: skip
    if rng_note:
        out += " The free crypto history stops at 1 year: say so."
    if advice:
        out += " The user asks for advice: give none (no buy, sell or forecast); one neutral sentence is enough."
    return out + f" Source to cite: {cites}."
