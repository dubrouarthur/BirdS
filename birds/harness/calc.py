"""Exact calculator card, from the user's own words. No tool, no network, no model for the numbers.

« 15 % de 240 », « TVA sur 1 200 € HT », « 1 440 € TTC en HT », « acheté 80 € vendu 120 €, quelle marge ? »,
« mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 % », « convertis 5 miles en km », « 30 °C en °F » ->
``detect`` reads the ask and its figures, ``card`` computes in ``Decimal`` (exact, rounded only for display), the
harness hands the model ``summary`` (the results, written out) and the UI the card (its inputs stay editable: the
browser recomputes with the same formulas, ``static/modules.js``). A small model gets arithmetic wrong; the harness
does not. Nothing fires without figures AND a computing cue: « une hausse de 5 % des prix » in a mail is not a sum.
Currencies are left to ``convert_currency`` (« 100 dollars en euros » is a rate, not a unit).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, getcontext

getcontext().prec = 40

# ------------------------------------------------------------------ numbers

_NUM = r"(?:\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,]\d+)?"
_MULT = {"k": Decimal(1000), "m": Decimal(1_000_000), "md": Decimal(1_000_000_000), "mds": Decimal(1_000_000_000)}
_EUR = r"(?:\s?(?:€|euros?|eur)\b|\s?€)"


def number(raw: str) -> Decimal | None:
    """« 1 200,50 » -> 1200.50 ; « 3,5 » -> 3.5 ; « 1.234,5 » (thousands dot) -> 1234.5."""
    s = re.sub(r"[   ]", "", str(raw or "").strip())
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _amount(m: re.Match | None, group: str = "a") -> Decimal | None:
    if not m:
        return None
    v = number(m[group])
    mult = (m.groupdict().get(group + "m") or "").lower()
    return None if v is None else v * _MULT.get(mult, Decimal(1))


def fmt(v: Decimal | float | int, lang: str = "fr", places: int = 2, unit: str = "") -> str:
    """French or English display: 1 234,56 / 1,234.56; trailing zeros of a whole number dropped."""
    d = Decimal(str(v)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP) if places >= 0 else Decimal(v)
    if d == d.to_integral_value():
        d = d.quantize(Decimal(1))
    sign = "-" if d < 0 else ""
    whole, _, frac = f"{abs(d):f}".partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    sep, dot = (" ", ",") if lang != "en" else (",", ".")
    if unit != "€":
        frac = frac.rstrip("0")
    out = sign + sep.join(groups) + (dot + frac if frac else "")
    if unit:
        sep_u = ("" if unit == "%" else " ") if lang == "en" else ("\u202f" if unit in ("%", "€") else " ")
        out += sep_u + unit
    return out


# ------------------------------------------------------------------ cues

# a computing cue: without one, figures in a request are content (« annonce une hausse de 5 % »), not a sum
_CUE = re.compile(
    r"\b(?:combien|calcul\w*|quel(?:le)?s?\s+(?:est|sera|serait|seront|fait|font|donne|montant|prix|marge|"
    r"mensualit[ée]|taux|co[ûu]t|r[ée]sultat|pourcentage|valeur)|[çc]a fait|[çc]a donne|fait combien|"
    r"donne combien|convert\w*|en\s+(?:ht|ttc|pourcentage|percent(?:age)?)\b|how much|what(?:'s| is)|compute|calculate|work out)\b|=\s*\??\s*$|\?\s*$",
    re.I,
)
_NOT = re.compile(
    r"\b(?:r[ée]dige|[ée]cri[st]|mail|courriel|e-mail|lettre|pr[ée]sentation|diapo|slides?|rapport|tableur|excel|"
    r"graphique|courbe|histogramme|camembert|chart|graph|plot|draft|write|explique|explain|pourquoi|why|"
    r"recherche|search|tendance|[ée]volution d[ue]s?|depuis)\b",
    re.I,
)

# ------------------------------------------------------------------ units

_UNITS: dict[str, tuple[str, Decimal, str]] = {}  # spelling -> (dimension, factor to base, canonical symbol)


def _u(dim: str, factor: str, symbol: str, *names: str) -> None:
    for n in (symbol, *names):
        _UNITS[n.lower()] = (dim, Decimal(factor), symbol)


_u("len", "1000", "km", "kilomètre", "kilomètres", "kilometre", "kilometres", "kilometer", "kilometers")
_u("len", "1", "m", "mètre", "mètres", "metre", "metres", "meter", "meters")
_u("len", "0.01", "cm", "centimètre", "centimètres", "centimetre", "centimetres", "centimeter", "centimeters")
_u("len", "0.001", "mm", "millimètre", "millimètres", "millimetre", "millimetres", "millimeter", "millimeters")
_u("len", "1609.344", "mi", "mile", "miles")
_u("len", "0.3048", "ft", "pied", "pieds", "foot", "feet")
_u("len", "0.0254", "in", "pouce", "pouces", "inch", "inches")
_u("len", "0.9144", "yd", "yard", "yards")
_u("len", "1852", "NM", "mille marin", "milles marins", "nautical mile", "nautical miles")
_u("mass", "1000", "kg", "kilo", "kilos", "kilogramme", "kilogrammes", "kilogram", "kilograms")
_u("mass", "1", "g", "gramme", "grammes", "gram", "grams")
_u("mass", "1000000", "t", "tonne", "tonnes", "ton", "tons")
_u("mass", "453.59237", "lb", "lbs", "pound", "pounds")
_u("mass", "28.349523125", "oz", "once", "onces", "ounce", "ounces")
_u("vol", "1", "L", "l", "litre", "litres", "liter", "liters")
_u("vol", "0.01", "cL", "cl", "centilitre", "centilitres")
_u("vol", "0.001", "mL", "ml", "millilitre", "millilitres", "milliliter", "milliliters")
_u("vol", "1000", "m³", "m3", "mètre cube", "mètres cubes", "cubic meter", "cubic meters")
_u("vol", "3.785411784", "gal", "gallon", "gallons", "gallon us", "gallons us")
_u("area", "1", "m²", "m2", "mètre carré", "mètres carrés", "square meter", "square meters")
_u("area", "10000", "ha", "hectare", "hectares")
_u("area", "1000000", "km²", "km2", "kilomètre carré", "kilomètres carrés")
_u("area", "4046.8564224", "acre", "acres")
_u("area", "0.09290304", "ft²", "ft2", "pied carré", "pieds carrés", "square foot", "square feet")
_u("speed", "1", "km/h", "kmh", "kilomètre par heure", "kilomètres par heure", "kilomètres-heure")
_u("speed", "1.609344", "mph", "mile par heure", "miles par heure", "miles per hour")
_u("speed", "3.6", "m/s", "mètre par seconde", "mètres par seconde")
_u("speed", "1.852", "nœud", "noeud", "nœuds", "noeuds", "knot", "knots", "kn")
_u("data", "1", "o", "octet", "octets", "byte", "bytes")
_u("data", "1000", "Ko", "ko", "kb", "kilooctet", "kilooctets", "kilobyte", "kilobytes")
_u("data", "1000000", "Mo", "mo", "mb", "mégaoctet", "mégaoctets", "megabyte", "megabytes")
_u("data", "1000000000", "Go", "go", "gb", "gigaoctet", "gigaoctets", "gigabyte", "gigabytes")
_u("data", "1000000000000", "To", "to", "tb", "téraoctet", "téraoctets", "terabyte", "terabytes")
_u("energy", "1", "Wh", "wh", "wattheure", "wattheures")
_u("energy", "1000", "kWh", "kwh", "kilowattheure", "kilowattheures", "kilowatt-heure", "kilowatt-heures")
_u("energy", "1000000", "MWh", "mwh", "mégawattheure", "mégawattheures")
_u("time", "1", "s", "seconde", "secondes", "second", "seconds")
_u("time", "60", "min", "minute", "minutes")
_u("time", "3600", "h", "heure", "heures", "hour", "hours")
_u("time", "86400", "j", "jour", "jours", "day", "days")
_u("time", "604800", "sem.", "semaine", "semaines", "week", "weeks")
_TEMPS = {"°c": "°C", "°f": "°F", "c": "°C", "f": "°F", "k": "K", "kelvin": "K", "kelvins": "K", "celsius": "°C",
          "degrés celsius": "°C", "degrés c": "°C", "fahrenheit": "°F", "degrés fahrenheit": "°F", "degrés f": "°F",
          "degres celsius": "°C", "degres fahrenheit": "°F"}  # fmt: skip

_UNIT_ALT = "|".join(
    sorted(
        (re.escape(k) for k in list(_UNITS) + list(_TEMPS) if len(k) > 1 or k in ("m", "g", "t", "l", "h", "j", "o")),
        key=len,
        reverse=True,
    )  # fmt: skip
)
_CONVERT = re.compile(
    rf"(?:^|[\s(:])(?P<a>{_NUM})\s*(?P<from>{_UNIT_ALT})\.?\s+(?:en|in|to|into|vers|=|->|→)\s+"
    rf"(?:(?:des?|les?|d')\s*)?(?P<to>{_UNIT_ALT})(?=\s*(?:[?.!,;]|$|\s+(?:s'il|stp|svp|please|\?)))",
    re.I,
)
_HOW_MANY = re.compile(
    rf"\bcombien\s+(?:de\s+|d')?(?P<to>{_UNIT_ALT})\s+(?:dans|font|fait|pour|en|y a-t-il dans)\s+(?P<a>{_NUM})\s*"
    rf"(?P<from>{_UNIT_ALT})\b|\bhow many\s+(?P<to2>{_UNIT_ALT})\s+(?:in|are in|is)\s+(?P<a2>{_NUM})\s*(?P<from2>{_UNIT_ALT})\b",
    re.I,
)


def _unit(word: str) -> tuple[str, Decimal | None, str] | None:
    w = " ".join(word.lower().split())
    if w in _TEMPS:
        return ("temp", None, _TEMPS[w])
    return _UNITS.get(w)


def _temp(v: Decimal, a: str, b: str) -> Decimal:
    c = v if a == "°C" else (v - 32) * 5 / 9 if a == "°F" else v - Decimal("273.15")
    return c if b == "°C" else c * 9 / 5 + 32 if b == "°F" else c + Decimal("273.15")


def _convert(text: str) -> dict | None:
    m = _CONVERT.search(text)
    if m:
        a, fr, to = m["a"], m["from"], m["to"]
    else:
        m = _HOW_MANY.search(text)
        if not m:
            return None
        a, fr, to = (m["a"], m["from"], m["to"]) if m["a"] else (m["a2"], m["from2"], m["to2"])
    ua, ub = _unit(fr), _unit(to)
    v = number(a)
    if not ua or not ub or ua[0] != ub[0] or v is None or ua[2] == ub[2]:
        return None
    return {"kind": "unit", "dim": ua[0], "value": v, "from": ua[2], "to": ub[2]}


# ------------------------------------------------------------------ the asks

_PCT = r"(?P<p>\d+(?:[.,]\d+)?)\s?(?:%|pour ?cent|percent)"
_PCT_OF = re.compile(rf"{_PCT}\s+(?:de|d'|du|des|of)\s*(?P<a>{_NUM})\s?(?P<am>k|m|md|mds)?\b", re.I)
_CHANGE = re.compile(
    rf"(?P<verb>augment\w*|hausse|major\w*|ajout\w*|plus|\+|increase\w*|rais\w*|baiss\w*|diminu\w*|r[ée]duction|"
    rf"remise|rabais|ristourne|minor\w*|moins|-|discount\w*|decrease\w*|reduc\w*)\s+(?:de\s+|of\s+)?{_PCT}\s+"
    rf"(?:sur|de|à|a|on|to|off)\s+(?:un |une |le |la |les |a |an |the )?(?:[\wéèàû'-]+\s+){{0,3}}?(?:de\s+)?"
    rf"(?P<a>{_NUM})\s?(?P<am>k|m)?\b"
    rf"|(?P<a2>{_NUM})\s?(?:€|euros?)?\s*(?P<sign>[+-])\s*(?P<p2>\d+(?:[.,]\d+)?)\s?%",
    re.I,
)
_CHANGE_AFTER = re.compile(
    rf"(?P<a>{_NUM})\s?(?P<am>k|m)?\s?(?:€|euros?)?\s+(?:augment[ée]e?s?|major[ée]e?s?|baiss[ée]e?s?|diminu[ée]e?s?|"
    rf"remis[ée]e?s?|r[ée]duite?s?|increased|reduced|discounted)\s+(?:de|by)\s+{_PCT}",
    re.I,
)
_RATIO = re.compile(
    rf"(?:pourcentage|part|proportion|percentage|ratio|%)\D{{0,40}}?(?P<a>{_NUM})\s?(?:€|euros?)?\s+(?:sur|par rapport [àa]|"
    rf"out of|of|sur un total de)\s+(?P<b>{_NUM})|(?P<a2>{_NUM})\s+(?:sur|out of)\s+(?P<b2>{_NUM})\s*,?\s*"
    rf"(?:en|[çc]a fait combien en|as a|in)\s+(?:pourcentage|%|percent(?:age)?)",
    re.I,
)
_VARIATION = re.compile(
    rf"(?:variation|[ée]volution|hausse|baisse|progression|augmentation|diminution|change|increase|decrease|growth)"
    rf"[^\d]{{0,40}}?(?:entre|de|from|between)\s+(?P<a>{_NUM})\s?(?P<am>k|m)?\s?(?:€|euros?)?\s+(?:et|à|a|and|to)\s+"
    rf"(?P<b>{_NUM})\s?(?P<bm>k|m)?",
    re.I,
)
_VAT_WORD = re.compile(r"\b(?:tva|vat|ttc|ht)\b", re.I)
_VAT_RATE = re.compile(r"(?P<r>\d+(?:[.,]\d+)?)\s?%", re.I)
_HT = re.compile(rf"(?P<a>{_NUM})\s?(?P<am>k)?\s?(?:€|euros?)?\s*(?:hors taxes?|ht|h\.t\.)\b", re.I)
_TTC = re.compile(rf"(?P<a>{_NUM})\s?(?P<am>k)?\s?(?:€|euros?)?\s*(?:ttc|t\.t\.c\.|toutes taxes comprises)\b", re.I)
_TO_HT = re.compile(r"\b(?:en|au|le|prix|montant)\s+(?:hors taxes?|ht)\b|\bhors taxes?\s*\?|\bht\s*\?", re.I)
_VAT_ANY = re.compile(rf"\b(?:tva|vat)\b[^\d]{{0,30}}(?P<a>{_NUM})\s?(?P<am>k)?\s?(?:€|euros?)", re.I)
_MARGIN = re.compile(r"\b(?:marge|margin|taux de marque|coefficient|markup)\b", re.I)
_BUY = re.compile(
    rf"(?:achet[ée]e?s?|co[ûu]t(?:ant)?|prix d'achat|co[ûu]t de revient|bought|cost(?:s|ing)?|purchase price)"
    rf"\s+(?:à\s+|a\s+|de\s+|:\s*|for\s+|at\s+)?(?P<a>{_NUM})\s?(?P<am>k)?",
    re.I,
)
_SELL = re.compile(
    rf"(?:vendue?s?|revendue?s?|prix de vente|vente|sold|selling price|sell(?:s|ing)?(?: it)?)\s+(?:à\s+|a\s+|de\s+|:\s*|"
    rf"for\s+|at\s+)?(?P<a>{_NUM})\s?(?P<am>k)?",
    re.I,
)
_LOAN = re.compile(r"\b(?:pr[êe]t|emprunt|cr[ée]dit|loan|mortgage|mensualit[ée]s?|monthly payment)\b", re.I)
_PRINCIPAL = re.compile(
    rf"(?:pr[êe]t|emprunt|cr[ée]dit|loan|mortgage|emprunter|borrow)\D{{0,25}}?(?P<a>{_NUM})\s?(?P<am>k|m)?\s?(?:€|euros?)?",
    re.I,
)
_YEARS = re.compile(r"(?:sur|pendant|en|over|for)\s+(?P<y>\d{1,2})\s?(?:ans|années|years?)\b", re.I)
_MONTHS = re.compile(r"(?:sur|pendant|en|over|for)\s+(?P<n>\d{1,3})\s?(?:mois|months?)\b", re.I)
_RATE = re.compile(r"(?:à|a|au taux de|taux de|at|rate of)\s+(?P<r>\d+(?:[.,]\d+)?)\s?%", re.I)


def _pct(m: re.Match, key: str = "p") -> Decimal | None:
    return number(m[key]) if m and m[key] else None


def detect(text: str) -> dict | None:
    """The calculation asked in the user's own words, with its exact inputs, or None."""
    t = " ".join(str(text or "").split())
    if not t or len(t) > 400 or not re.search(r"\d", t):
        return None
    got = _detect(t)
    if got and got["kind"] in ("change", "variation", "percent_of", "ratio"):
        got["unit"] = "€" if re.search(r"€|\beuros?\b", t, re.I) else ""
    return got


def _detect(t: str) -> dict | None:
    if _NOT.search(t):
        return None
    cue = bool(_CUE.search(t))
    # units: the « X unit en unit » shape is itself the ask (« 5 miles en km »), no cue needed
    got = _convert(t)
    if got:
        return got
    if _LOAN.search(t):
        a = _amount(_PRINCIPAL.search(t))
        ym, mm, rm = _YEARS.search(t), _MONTHS.search(t), _RATE.search(t)
        n = int(ym["y"]) * 12 if ym else int(mm["n"]) if mm else None
        r = number(rm["r"]) if rm else None
        if a and n and r is not None and 0 < n <= 600 and Decimal(0) <= r < Decimal(30):
            return {"kind": "loan", "principal": a, "months": n, "rate": r}
        return None
    if _MARGIN.search(t):
        buy, sell = _amount(_BUY.search(t)), _amount(_SELL.search(t))
        if buy and sell and buy > 0 and sell > 0:
            return {"kind": "margin", "cost": buy, "price": sell}
        return None
    if _VAT_WORD.search(t):
        rate_m = _VAT_RATE.search(t)
        rate = number(rate_m["r"]) if rate_m else None
        if rate is not None and rate not in (Decimal("20"), Decimal("10"), Decimal("5.5"), Decimal("2.1"),
                                             Decimal("8.5"), Decimal("13"), Decimal("0")):  # fmt: skip
            rate = None if rate > 30 else rate
        ttc, ht = _amount(_TTC.search(t)), _amount(_HT.search(t))
        if ttc and (_TO_HT.search(t) or not ht):
            return {"kind": "vat", "amount": ttc, "base": "ttc", "rate": rate if rate is not None else Decimal(20),
                    "assumed": rate is None}  # fmt: skip
        if ht:
            return {"kind": "vat", "amount": ht, "base": "ht", "rate": rate if rate is not None else Decimal(20),
                    "assumed": rate is None}  # fmt: skip
        anyv = _amount(_VAT_ANY.search(t))
        if anyv and cue:
            return {"kind": "vat", "amount": anyv, "base": "ht", "rate": rate if rate is not None else Decimal(20),
                    "assumed": rate is None}  # fmt: skip
        return None
    if not cue:
        return None
    m = _CHANGE.search(t)
    if m:
        if m["a2"]:
            base, p, down = number(m["a2"]), number(m["p2"]), m["sign"] == "-"
        else:
            base, p = _amount(m), _pct(m)
            down = bool(re.match(r"baiss|diminu|r[ée]duc|remise|rabais|ristourne|minor|moins|-|discount|decrease|reduc",
                                 m["verb"], re.I))  # fmt: skip
        if base is not None and p is not None:
            return {"kind": "change", "base": base, "pct": p, "down": down}
    m = _CHANGE_AFTER.search(t)
    if m:
        down = bool(re.search(r"baiss|diminu|remis|r[ée]duit|reduced|discounted", m.group(0), re.I))
        return {"kind": "change", "base": _amount(m), "pct": _pct(m), "down": down}
    m = _VARIATION.search(t)
    if m:
        a, b = _amount(m, "a"), _amount(m, "b")
        if a and b is not None and a != 0:
            return {"kind": "variation", "a": a, "b": b}
    m = _PCT_OF.search(t)
    if m:
        return {"kind": "percent_of", "pct": _pct(m), "base": _amount(m)}
    m = _RATIO.search(t)
    if m:
        a, b = (number(m["a"]), number(m["b"])) if m["a"] else (number(m["a2"]), number(m["b2"]))
        if a is not None and b:
            return {"kind": "ratio", "a": a, "b": b}
    return None


# ------------------------------------------------------------------ the card

_TITLES = {
    "unit": ("Conversion d'unités", "Unit conversion"),
    "loan": ("Prêt : mensualité", "Loan: monthly payment"),
    "margin": ("Marge commerciale", "Profit margin"),
    "vat": ("TVA", "VAT"),
    "change": ("Pourcentage appliqué", "Percentage applied"),
    "variation": ("Variation en pourcentage", "Percentage change"),
    "percent_of": ("Pourcentage d'un montant", "Percentage of an amount"),
    "ratio": ("Part en pourcentage", "Share as a percentage"),
}


def _row(label: str, value: Decimal, lang: str, unit: str = "", places: int = 2, main: bool = False) -> dict:
    return {"label": label, "value": fmt(value, lang, places, unit), "raw": str(value.normalize()) if value else "0",
            **({"main": True} if main else {})}  # fmt: skip


def compute(got: dict) -> dict:
    """The exact results, as Decimals: {name: value}."""
    k = got["kind"]
    if k == "unit":
        if got["dim"] == "temp":
            return {"result": _temp(got["value"], got["from"], got["to"])}
        fa, fb = _unit(got["from"])[1], _unit(got["to"])[1]
        return {"result": got["value"] * fa / fb}
    if k == "loan":
        p, n, r = got["principal"], got["months"], got["rate"] / 100 / 12
        pay = p / n if r == 0 else p * r / (1 - (1 + r) ** -n)
        total = pay * n
        return {"payment": pay, "total": total, "interest": total - p}
    if k == "margin":
        c, s = got["cost"], got["price"]
        return {"margin": s - c, "markup": (s - c) / c * 100, "rate": (s - c) / s * 100, "coef": s / c}
    if k == "vat":
        a, r = got["amount"], got["rate"] / 100
        ht = a if got["base"] == "ht" else a / (1 + r)
        return {"ht": ht, "vat": ht * r, "ttc": ht * (1 + r)}
    if k == "change":
        delta = got["base"] * got["pct"] / 100
        return {"delta": delta, "result": got["base"] - delta if got["down"] else got["base"] + delta}
    if k == "variation":
        return {"pct": (got["b"] - got["a"]) / abs(got["a"]) * 100, "delta": got["b"] - got["a"]}
    if k == "percent_of":
        return {"result": got["base"] * got["pct"] / 100}
    if k == "ratio":
        return {"pct": got["a"] / got["b"] * 100}
    raise ValueError(k)


def card(got: dict, lang: str = "fr") -> dict:
    """The calculator card: {type: "calc", kind, title, inputs[{key, label, value, unit}], rows[{label, value}],
    formula, note}. ``inputs`` carry plain numbers (strings) the browser may change and recompute."""
    lang = "en" if lang == "en" else "fr"
    fr = lang == "fr"
    k = got["kind"]
    res = compute(got)
    inputs: list[dict] = []
    rows: list[dict] = []
    formula, note = "", ""

    def inp(key, label, value, unit=""):
        inputs.append({"key": key, "label": label, "value": f"{Decimal(value).normalize():f}",
                       "unit": unit})  # fmt: skip

    if k == "unit":
        places = 2 if got["dim"] in ("temp",) else 4
        inp("value", "Valeur" if fr else "Value", got["value"], got["from"])
        rows.append(_row(f"{fmt(got['value'], lang, 6)} {got['from']} =", res["result"], lang, got["to"], places,
                         main=True))  # fmt: skip
        formula = f"{got['from']} → {got['to']}"
        extra = {"dim": got["dim"], "from": got["from"], "to": got["to"]}
        if got["dim"] != "temp":
            extra["factor"] = str((_unit(got["from"])[1] / _unit(got["to"])[1]).normalize())
    elif k == "loan":
        inp("principal", "Montant emprunté" if fr else "Amount borrowed", got["principal"], "€")
        inp("years", "Durée (années)" if fr else "Term (years)", Decimal(got["months"]) / 12)
        inp("rate", "Taux annuel (hors assurance)" if fr else "Annual rate (no insurance)", got["rate"], "%")
        rows += [_row("Mensualité" if fr else "Monthly payment", res["payment"], lang, "€", main=True),
                 _row("Coût total des intérêts" if fr else "Total interest", res["interest"], lang, "€"),
                 _row("Total remboursé" if fr else "Total repaid", res["total"], lang, "€")]  # fmt: skip
        formula = "M = C × t / (1 − (1 + t)^−n), t = taux / 12" if fr else "M = P × r / (1 − (1 + r)^−n), r = rate / 12"
        note = ("Amortissement constant, taux fixe, sans assurance ni frais de dossier." if fr
                else "Fixed rate, constant payments, no insurance or fees.")  # fmt: skip
        extra = {}
    elif k == "margin":
        inp("cost", "Prix d'achat (coût)" if fr else "Cost price", got["cost"], "€")
        inp("price", "Prix de vente" if fr else "Selling price", got["price"], "€")
        rows += [_row("Marge" if fr else "Margin", res["margin"], lang, "€", main=True),
                 _row("Taux de marge (sur le coût)" if fr else "Markup (on cost)", res["markup"], lang, "%"),
                 _row("Taux de marque (sur la vente)" if fr else "Margin rate (on price)", res["rate"], lang, "%"),
                 _row("Coefficient multiplicateur" if fr else "Multiplier", res["coef"], lang, "", 4)]  # fmt: skip
        formula = ("marge = vente − coût ; taux de marge = marge / coût ; taux de marque = marge / vente" if fr
                   else "margin = price − cost; markup = margin / cost; margin rate = margin / price")  # fmt: skip
        note = "Montants pris tels quels (HT ou TTC, comme donnés)." if fr else "Amounts taken as given."
        extra = {}
    elif k == "vat":
        inp("amount", "Montant " + ("HT" if got["base"] == "ht" else "TTC") if fr else
            "Amount " + ("excl. VAT" if got["base"] == "ht" else "incl. VAT"), got["amount"], "€")  # fmt: skip
        inp("rate", "Taux de TVA" if fr else "VAT rate", got["rate"], "%")
        main = "ttc" if got["base"] == "ht" else "ht"
        rows += [_row("Montant HT" if fr else "Excl. VAT", res["ht"], lang, "€", main=main == "ht"),
                 _row("TVA" if fr else "VAT", res["vat"], lang, "€"),
                 _row("Montant TTC" if fr else "Incl. VAT", res["ttc"], lang, "€", main=main == "ttc")]  # fmt: skip
        formula = "TTC = HT × (1 + taux)" if fr else "gross = net × (1 + rate)"
        if got.get("assumed"):
            note = "Taux normal de 20 % supposé (France) : changez-le si besoin." if fr else (
                "Standard French rate of 20% assumed: change it if needed.")  # fmt: skip
        extra = {"base": got["base"]}
    elif k == "change":
        cur = got.get("unit", "")
        inp("base", "Montant de départ" if fr else "Starting amount", got["base"], cur)
        inp("pct", "Pourcentage" if fr else "Percentage", got["pct"], "%")
        sign = "−" if got["down"] else "+"
        rows += [_row(f"{sign} {fmt(got['pct'], lang, 4, '%')}", res["delta"], lang, cur),
                 _row("Résultat" if fr else "Result", res["result"], lang, cur, main=True)]  # fmt: skip
        formula = f"x × (1 {sign} p / 100)"
        extra = {"down": got["down"]}
    elif k == "variation":
        inp("a", "Valeur de départ" if fr else "From", got["a"])
        inp("b", "Valeur d'arrivée" if fr else "To", got["b"])
        rows += [_row("Variation" if fr else "Change", res["pct"], lang, "%", main=True),
                 _row("Écart" if fr else "Difference", res["delta"], lang, got.get("unit", ""))]  # fmt: skip
        formula = "(arrivée − départ) / départ × 100" if fr else "(to − from) / from × 100"
        extra = {}
    elif k == "percent_of":
        inp("pct", "Pourcentage" if fr else "Percentage", got["pct"], "%")
        inp("base", "Montant" if fr else "Amount", got["base"])
        rows.append(_row(f"{fmt(got['pct'], lang, 4, '%')} " + ("de" if fr else "of") + f" {fmt(got['base'], lang, 4)}",
                         res["result"], lang, got.get("unit", ""), main=True))  # fmt: skip
        formula = "x × p / 100"
        extra = {}
    else:  # ratio
        inp("a", "Partie" if fr else "Part", got["a"])
        inp("b", "Total", got["b"])
        rows.append(_row(f"{fmt(got['a'], lang, 4)} / {fmt(got['b'], lang, 4)}", res["pct"], lang, "%", main=True))
        formula = "partie / total × 100" if fr else "part / total × 100"
        extra = {}
    return {"type": "calc", "v": 1, "kind": k, "title": _TITLES[k][0 if fr else 1], "inputs": inputs, "rows": rows,
            "formula": formula, "note": note, **extra}  # fmt: skip


def summary(w: dict, lang: str = "fr") -> str:
    """The results for the model, one line: « Mensualité : 1 159,92 € ; … »."""
    parts = [f"{r['label'].rstrip(' =')} : {r['value']}" if lang != "en" else f"{r['label'].rstrip(' =')}: {r['value']}"
             for r in w.get("rows", [])]  # fmt: skip
    return " ; ".join(parts) + "."


NOTE = {
    "fr": "\n\n(Note de Bird : une fiche « Calcul » est affichée sous ta réponse, calculée exactement par le harnais. "
    "Résultats : {facts} Réponds en une ou deux phrases avec ces valeurs exactes ; n'en recalcule aucune et ne "
    "cherche rien sur le web.)",
    "en": "\n\n(Bird's note: a 'Calculation' card is shown under your answer, computed exactly by the harness. "
    "Results: {facts} Answer in one or two sentences with these exact values; recompute none and do not search the "
    "web.)",
}


def facts_for(text: str, lang: str = "fr") -> tuple[dict | None, str]:
    """(card, facts) for the user's words, or (None, "")."""
    try:
        got = detect(text)
        if not got:
            return None, ""
        w = card(got, lang)
    except (InvalidOperation, ZeroDivisionError, OverflowError, ValueError, TypeError):
        return None, ""
    return w, summary(w, lang)
