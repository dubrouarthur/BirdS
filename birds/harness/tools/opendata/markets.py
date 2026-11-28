"""The instruments Bird can quote: a small, validated list (never a symbol guessed by the model).

Each entry was checked against the provider's own reference list on 2026-11-28: Twelve Data ``/symbol_search`` and
``/indices`` for shares and indices (symbol + MIC code of the home market), CoinGecko coin ids for crypto-assets.
Currency pairs come from the ECB reference rates (any code the ECB publishes). A name outside this list is not
looked up elsewhere: the tool says it does not know it, never guesses a ticker.

``resolve(text)`` reads ONE name (« LVMH », « l'action Hermès », « CAC 40 », « bitcoin », « euro dollar », « MC »);
``find_all(text)`` finds every instrument a sentence names, in order (at most ``MAX_SYMBOLS``). Pure, no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_SYMBOLS = 3  # a comparison of more than three lines is unreadable on a phone


@dataclass(frozen=True)
class Instrument:
    key: str  # stable id used in the widget and the asks
    name: str  # display name
    kind: str  # "equity" | "index" | "crypto" | "fx"
    symbol: str  # provider symbol (Twelve Data symbol, CoinGecko id, or « USD/EUR » for a pair)
    mic: str = ""  # market identifier code (ISO 10383) of the home market, shares and indices
    currency: str = ""  # quote currency
    aliases: tuple[str, ...] = ()  # folded words that name it (the display name and the ticker are added)
    base: str = ""  # fx: the currency quoted (1 base = x quote)


def fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("’", "'").replace("&", " et ")
    return " ".join(re.sub(r"[^\w' /.-]", " ", s).split())


_EQ = "equity"
_IX = "index"

# shares (home market) and indices: (key, name, symbol, mic, currency, aliases)
_LISTED: tuple[tuple[str, str, str, str, str, tuple[str, ...], str], ...] = (
    # Euronext Paris (XPAR), CAC 40 members most asked about
    ("lvmh", "LVMH", "MC", "XPAR", "EUR", ("lvmh", "lvmh moet hennessy", "louis vuitton", "moet hennessy"), _EQ),
    ("hermes", "Hermès", "RMS", "XPAR", "EUR", ("hermes", "hermes international"), _EQ),
    ("loreal", "L'Oréal", "OR", "XPAR", "EUR", ("l'oreal", "loreal", "l oreal"), _EQ),
    ("totalenergies", "TotalEnergies", "TTE", "XPAR", "EUR", ("totalenergies", "total energies"), _EQ),
    ("airbus", "Airbus", "AIR", "XPAR", "EUR", ("airbus",), _EQ),
    ("sanofi", "Sanofi", "SAN", "XPAR", "EUR", ("sanofi",), _EQ),
    ("bnp", "BNP Paribas", "BNP", "XPAR", "EUR", ("bnp paribas", "bnp"), _EQ),
    ("schneider", "Schneider Electric", "SU", "XPAR", "EUR", ("schneider electric", "schneider"), _EQ),
    ("air-liquide", "Air Liquide", "AI", "XPAR", "EUR", ("air liquide",), _EQ),
    ("safran", "Safran", "SAF", "XPAR", "EUR", ("safran",), _EQ),
    ("axa", "AXA", "CS", "XPAR", "EUR", ("axa",), _EQ),
    ("kering", "Kering", "KER", "XPAR", "EUR", ("kering",), _EQ),
    ("danone", "Danone", "BN", "XPAR", "EUR", ("danone",), _EQ),
    ("vinci", "Vinci", "DG", "XPAR", "EUR", ("vinci",), _EQ),
    ("societe-generale", "Société Générale", "GLE", "XPAR", "EUR", ("societe generale", "socgen"), _EQ),
    ("credit-agricole", "Crédit Agricole", "ACA", "XPAR", "EUR", ("credit agricole",), _EQ),
    ("orange", "Orange", "ORA", "XPAR", "EUR", ("orange sa", "action orange", "titre orange"), _EQ),
    ("renault", "Renault", "RNO", "XPAR", "EUR", ("renault",), _EQ),
    ("stellantis", "Stellantis", "STLAP", "XPAR", "EUR", ("stellantis",), _EQ),
    ("michelin", "Michelin", "ML", "XPAR", "EUR", ("michelin",), _EQ),
    ("capgemini", "Capgemini", "CAP", "XPAR", "EUR", ("capgemini",), _EQ),
    ("dassault-systemes", "Dassault Systèmes", "DSY", "XPAR", "EUR", ("dassault systemes",), _EQ),
    ("thales", "Thales", "HO", "XPAR", "EUR", ("thales",), _EQ),
    ("carrefour", "Carrefour", "CA", "XPAR", "EUR", ("carrefour",), _EQ),
    ("engie", "Engie", "ENGI", "XPAR", "EUR", ("engie",), _EQ),
    ("saint-gobain", "Saint-Gobain", "SGO", "XPAR", "EUR", ("saint-gobain", "saint gobain"), _EQ),
    ("pernod", "Pernod Ricard", "RI", "XPAR", "EUR", ("pernod ricard", "pernod"), _EQ),
    ("essilorluxottica", "EssilorLuxottica", "EL", "XPAR", "EUR", ("essilorluxottica", "essilor"), _EQ),
    # United States (NASDAQ XNGS, NYSE XNYS)
    ("apple", "Apple", "AAPL", "XNGS", "USD", ("apple",), _EQ),
    ("microsoft", "Microsoft", "MSFT", "XNGS", "USD", ("microsoft",), _EQ),
    ("nvidia", "Nvidia", "NVDA", "XNGS", "USD", ("nvidia",), _EQ),
    ("alphabet", "Alphabet (Google)", "GOOGL", "XNGS", "USD", ("alphabet", "google"), _EQ),
    ("amazon", "Amazon", "AMZN", "XNGS", "USD", ("amazon",), _EQ),
    ("meta", "Meta", "META", "XNGS", "USD", ("meta platforms", "facebook"), _EQ),
    ("tesla", "Tesla", "TSLA", "XNGS", "USD", ("tesla",), _EQ),
    ("netflix", "Netflix", "NFLX", "XNGS", "USD", ("netflix",), _EQ),
    ("ibm", "IBM", "IBM", "XNYS", "USD", ("ibm",), _EQ),
    ("coca-cola", "Coca-Cola", "KO", "XNYS", "USD", ("coca-cola", "coca cola"), _EQ),
    # Germany (Xetra)
    ("sap", "SAP", "SAP", "XETR", "EUR", ("sap",), _EQ),
    ("siemens", "Siemens", "SIE", "XETR", "EUR", ("siemens",), _EQ),
    # indices (Twelve Data /indices, 2026-11-28)
    ("cac40", "CAC 40", "FCHI", "XPAR", "EUR", ("cac 40", "cac40", "cac", "indice parisien", "bourse de paris"), _IX),
    ("sbf120", "SBF 120", "SBF120", "XPAR", "EUR", ("sbf 120", "sbf120"), _IX),
    ("dax", "DAX", "GDAXI", "XETR", "EUR", ("dax", "dax 40", "dax40"), _IX),
    ("ftse100", "FTSE 100", "FTSE", "XLON", "GBP", ("ftse 100", "ftse", "footsie"), _IX),
    ("nikkei", "Nikkei 225", "N225", "XJPX", "JPY", ("nikkei", "nikkei 225"), _IX),
)  # fmt: skip

# crypto-assets: (key, name, CoinGecko id, ticker, aliases)
_CRYPTO: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("bitcoin", "Bitcoin", "bitcoin", "BTC", ("bitcoin", "bitcoins", "btc")),
    ("ethereum", "Ethereum", "ethereum", "ETH", ("ethereum", "ether", "eth")),
    ("solana", "Solana", "solana", "SOL", ("solana",)),
    ("xrp", "XRP", "ripple", "XRP", ("xrp", "ripple")),
    ("bnb", "BNB", "binancecoin", "BNB", ("bnb", "binance coin")),
    ("cardano", "Cardano", "cardano", "ADA", ("cardano",)),
    ("dogecoin", "Dogecoin", "dogecoin", "DOGE", ("dogecoin", "doge")),
)

INSTRUMENTS: dict[str, Instrument] = {}
for _k, _n, _s, _m, _c, _a, _kind in _LISTED:
    INSTRUMENTS[_k] = Instrument(_k, _n, _kind, _s, _m, _c, tuple(fold(x) for x in (_n, *_a)))
for _k, _n, _id, _t, _a in _CRYPTO:
    INSTRUMENTS[_k] = Instrument(_k, _n, "crypto", _id, "", "", tuple(fold(x) for x in (_n, _t, *_a)))

# tickers typed as such (« MC.PA », « AAPL », « RMS ») — only the ones in the list
_TICKERS: dict[str, str] = {}
for _i in INSTRUMENTS.values():
    if _i.kind in ("equity", "index"):
        _TICKERS[_i.symbol.lower()] = _i.key
        suffix = {"XPAR": "pa", "XETR": "de", "XLON": "l", "XJPX": "t"}.get(_i.mic)
        if suffix:
            _TICKERS[f"{_i.symbol.lower()}.{suffix}"] = _i.key
    elif _i.kind == "crypto":
        _TICKERS[_i.aliases[1]] = _i.key

# a few names are also common words (« orange », « total », « meta », « vinci », « apple »): they only count as an
# instrument next to a market word (checked by the caller with ``AMBIGUOUS``)
AMBIGUOUS = {"orange", "total", "meta", "vinci", "apple", "amazon", "cac", "sap", "axa", "ether", "doge", "eth",
             "renault", "michelin", "danone", "carrefour", "thales", "safran"}  # fmt: skip

# capitals that are words or business acronyms before they are tickers
_TICKER_WORDS = {"CAP", "AIR", "SAN", "SAF", "ORA", "SIE", "SAP", "KER", "ACA", "GLE", "CAC", "SBF", "ETH", "SOL",
                 "BNB", "XRP", "ADA", "DOGE", "OR", "AI", "EL", "RI", "HO", "BN", "DG", "CS", "SU", "ML", "CA", "MC",
                 "KO"}  # fmt: skip

_ALIAS: list[tuple[str, str]] = sorted(
    ((a, i.key) for i in INSTRUMENTS.values() for a in i.aliases), key=lambda x: -len(x[0])
)


def fx_pair(text: str) -> Instrument | None:
    """« euro dollar », « EUR/USD », « dollar en euros », « la livre » (against the euro): an ECB pair."""
    from birds.harness import intents

    t = fold(text)
    m = re.fullmatch(r"([a-z]{3})\s*[/-]\s*([a-z]{3})", t)
    words = [m.group(1), m.group(2)] if m else re.findall(r"[a-z]+", t)
    codes: list[str] = []
    i = 0
    while i < len(words):
        two = " ".join(words[i : i + 2])
        c = intents.currency_code(two) if i + 1 < len(words) else ""
        if c and c not in codes:
            codes.append(c)
            i += 2
            continue
        c = intents.currency_code(words[i])
        if c and c not in codes and words[i] not in ("en", "de", "a", "le", "la"):
            codes.append(c)
        i += 1
    if not codes or len(codes) > 2:
        return None
    if len(codes) == 1:
        if codes[0] == "EUR":
            return None
        codes = ["EUR", codes[0]]
    base, quote = codes
    if base == quote:
        return None
    return Instrument(f"fx-{base}-{quote}".lower(), f"{base}/{quote}", "fx", f"{base}/{quote}", "", quote, (), base)


def resolve(text: str) -> Instrument | None:
    """The instrument ONE name designates, or None (never a guess)."""
    t = fold(text)
    exact = dict(_ALIAS).get(t)
    if exact:  # « L'Oréal » before its article is peeled
        return INSTRUMENTS[exact]
    t = re.sub(r"^(?:l'|le |la |les |du |de la |de l'|des |the )", "", t)
    t = re.sub(r"^(?:action|actions|titre|titres|indice|share|shares|stock|cours|cours de|cours du)\s+(?:de\s+|d'|du\s+)?",
               "", t).strip(" .")  # fmt: skip
    if not t:
        return None
    if t in _TICKERS and (t.upper() not in _TICKER_WORDS or t.upper() in str(text)):
        # « or » (gold), « air », « cap »: a word, a ticker only typed in capitals (« OR », « OR.PA »)
        return INSTRUMENTS[_TICKERS[t]]
    for a, k in _ALIAS:
        if t == a:
            return INSTRUMENTS[k]
    return fx_pair(t)


# a listed coin's name inside another asset's name: never that coin (a Bitcoin card for « Bitcoin Cash » is wrong)
_OTHER_COIN_AFTER = re.compile(r"\s+(?:cash|classic|gold|sv|satoshi|diamond|private|etf|etfs|trust|futures?|token|"
                               r"inu|pow|fair|2|ii|nova|vision|plus)\b")  # fmt: skip
_OTHER_COIN_BEFORE = re.compile(r"\b(?:wrapped|staked|lido|synthetic|tokenized|tokenise|tokenis[ée]|w|st)\s+$")


def find_all(text: str) -> list[Instrument]:
    """Every listed instrument a sentence names, in the order of the sentence, at most ``MAX_SYMBOLS`` (whole words;
    tickers only when typed in capitals, « MC » or « RMS », so « or » and « ai » stay words)."""
    raw = str(text or "")
    t = " " + fold(raw) + " "
    hits: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for a, k in _ALIAS:
        for m in re.finditer(rf"(?<![\w]){re.escape(a)}(?![\w])", t):
            span = (m.start(), m.end())
            if INSTRUMENTS[k].kind == "crypto" and (_OTHER_COIN_AFTER.match(t, m.end())
                                                    or _OTHER_COIN_BEFORE.search(t[: m.start()])):
                taken.append(span)  # « Bitcoin Cash », « Ethereum Classic », « wrapped bitcoin »: another asset
                continue
            if any(s < span[1] and span[0] < e for s, e in taken):
                continue
            taken.append(span)
            hits.append((m.start(), k))
    for m in re.finditer(r"(?<![\w.])([A-Z]{2,5}(?:\.(?:PA|DE|L|T))?)(?![\w])", raw):
        tk = m.group(1)
        if "." not in tk and (len(tk) < 3 or tk in _TICKER_WORDS):
            continue  # « CA » (chiffre d'affaires), « AI », « CAP », « AIR »: only as MC.PA, CA.PA…
        k = _TICKERS.get(tk.lower())
        if k and k not in (x[1] for x in hits):
            hits.append((len(fold(raw[: m.start()])) + 1, k))
    out: list[Instrument] = []
    for _, k in sorted(hits):
        i = INSTRUMENTS[k]
        if i not in out:
            out.append(i)
    return out[:MAX_SYMBOLS]
