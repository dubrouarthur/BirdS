"""Reading one cell: French and English numbers, currencies, percentages, dates, yes/no. Deterministic, stdlib only.

A column is read in two passes: ``number_style`` looks at all its cells to decide whether ``,`` is the decimal mark
(« 1 234,56 », « 12,5 % ») or a thousands separator (« 1,234.56 »), and ``date_order`` whether « 03/04/2024 » is the
3rd of April (French, the default) or March 4th (only when some cell proves it, « 04/13/2024 »).
"""

from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata

GAPS = {"", "-", "–", "—", "n/a", "na", "nd", "n.d.", "n.c.", "nc", "?", "null", "none", "nan", "#n/a", "#na",
        "#value!", "#valeur!", "#div/0!", "#ref!", "/", "x"}  # fmt: skip
TRUE = {"oui", "yes", "vrai", "true", "o", "y", "1", "x", "✓", "ok"}
FALSE = {"non", "no", "faux", "false", "n", "0", ""}
_BOOL_WORDS = {"oui", "non", "yes", "no", "vrai", "faux", "true", "false"}
_SPACES = re.compile(r"[\s    ']+")
_CURRENCY = {"€": "€", "eur": "€", "euro": "€", "euros": "€", "$": "$", "usd": "$", "us$": "$", "£": "£",
             "gbp": "£", "chf": "CHF", "fr": "CHF", "¥": "¥", "jpy": "¥", "cad": "CAD", "c$": "CAD"}  # fmt: skip
_SCALE = {"k": 1e3, "m": 1e6, "md": 1e9, "mds": 1e9, "mrd": 1e9, "mrds": 1e9, "bn": 1e9, "b": 1e9}
_NUM = re.compile(
    r"^(?P<sign>[-+−]?)\s*(?P<pre>[€$£¥]|us\$|c\$)?\s*(?P<sign2>[-+−]?)(?P<num>\d[\d\s.,]*|[.,]\d+)\s*"
    r"(?P<scale>k|m|md|mds|mrds?|bn|b)?\s*(?P<suf>%|‰|[€$£¥]|eur|euros?|usd|gbp|chf|jpy|cad|pts?|h|j|km|kg|t|l)?\.?$"
)
MONTHS = {
    "janvier": 1, "janv": 1, "jan": 1, "january": 1, "fevrier": 2, "fevr": 2, "fev": 2, "february": 2, "feb": 2,
    "mars": 3, "mar": 3, "march": 3, "avril": 4, "avr": 4, "april": 4, "apr": 4, "mai": 5, "may": 5, "juin": 6,
    "june": 6, "jun": 6, "juillet": 7, "juil": 7, "july": 7, "jul": 7, "aout": 8, "august": 8, "aug": 8,
    "septembre": 9, "sept": 9, "sep": 9, "september": 9, "octobre": 10, "oct": 10, "october": 10, "novembre": 11,
    "nov": 11, "november": 11, "decembre": 12, "dec": 12, "december": 12,
}  # fmt: skip
MONTH_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MONTH_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_D_NUM = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})(?:[ t]+(\d{1,2})[:h](\d{2})(?::(\d{2}))?)?(?:\.\d+)?z?$")
_D_MONTH = re.compile(r"^(?:(\d{1,2})(?:er)?\s+)?([a-z]{3,9})\.?[\s\-]+(\d{2}|\d{4})$")
_D_YM = re.compile(r"^(\d{4})[/\-](\d{1,2})$|^(\d{1,2})[/\-](\d{4})$")
_D_QUARTER = re.compile(r"^(?:t|q)([1-4])[\s\-/]*(\d{4})$|^(\d{4})[\s\-/]*(?:t|q)([1-4])$")


def plain(text) -> str:
    """Lower case, no accents, single spaces: what the matchers compare."""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def is_gap(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and plain(value) in GAPS


# ---------------------------------------------------------------- numbers


def number_style(texts) -> str:
    """',' when the comma is the decimal mark in these cells (French), '.' otherwise. Votes on unambiguous cells:
    « 12,5 », « 1 234,56 », « 1.234,5 » vote ','; « 12.5 », « 1,234.56 » vote '.'. « 1,234 » alone is ambiguous
    and goes with the majority (French when none)."""
    comma = dot = 0
    for raw in texts:
        if not isinstance(raw, str):
            continue
        s = _SPACES.sub(" ", raw).strip()
        m = re.search(r"\d[\d .,]*", s)
        if not m:
            continue
        num = m.group(0).strip(" .,")
        if "," in num and "." in num:
            comma += num.rfind(",") > num.rfind(".")
            dot += num.rfind(".") > num.rfind(",")
        elif "," in num:
            tail = num.rsplit(",", 1)[1]
            if len(tail) != 3 or num.count(",") == 1 and " " in num:
                comma += 1
            elif num.count(",") > 1:
                dot += 1  # « 1,234,567 »
        elif "." in num:
            tail = num.rsplit(".", 1)[1]
            if len(tail) != 3:
                dot += 1
            elif num.count(".") > 1:
                comma += 1  # « 1.234.567 »
    return "." if dot > comma else ","


def parse_number(value, decimal: str = ",") -> tuple[float | None, str]:
    """(number, unit) — unit is '', '%', '‰' or a currency/unit symbol. ``None`` for a gap. Raises ValueError when
    the cell is not a number. « (1 200) » is -1200 (accounting); « 1,2 M€ » is 1 200 000 €."""
    if value is None:
        return None, ""
    if isinstance(value, bool):
        raise ValueError("bool")
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            return None, ""
        return value, ""
    s = _SPACES.sub(" ", str(value)).strip()
    if plain(s) in GAPS:
        return None, ""
    neg = False
    if len(s) > 2 and s[0] == "(" and s[-1] == ")":
        neg, s = True, s[1:-1].strip()
    low = s.lower()
    m = _NUM.match(low)
    if not m:
        raise ValueError("not a number")
    num = m.group("num").replace(" ", "")
    if decimal == ",":
        if "." in num and "," in num:
            if num.rfind(",") > num.rfind("."):
                num = num.replace(".", "").replace(",", ".")
            else:
                num = num.replace(",", "")
        elif "," in num:
            num = num.replace(",", ".") if num.count(",") == 1 else num.replace(",", "")
        elif num.count(".") > 1 and not re.fullmatch(r"\d{1,3}(?:\.\d{3})+", num):
            raise ValueError("not a number")  # « 1.2.3.4 »: a version or an address, not a number
        elif num.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", num):
            num = num.replace(".", "")  # « 1.234 » in a French column: thousands
    else:
        num = num.replace(",", "")
    if num.count(".") > 1:
        raise ValueError("not a number")
    try:
        n = float(num)
    except ValueError:
        raise ValueError("not a number") from None
    pre, suf, scale = m.group("pre") or "", m.group("suf") or "", m.group("scale") or ""
    currency = _CURRENCY.get(pre) or _CURRENCY.get(suf)
    if scale == "m" and not currency:
        # « 12 m » is metres; « 3 M » or « 3 M€ » is millions
        if re.search(r"\dM\b|\d M\b", s):
            n *= 1e6
        elif suf:
            raise ValueError("not a number")
        else:
            suf = "m"
    elif scale == "b" and not currency:
        raise ValueError("not a number")
    else:
        n *= _SCALE.get(scale, 1)
    signs = m.group("sign") + m.group("sign2")
    if neg or "-" in signs or "−" in signs:
        n = -n
    unit = currency or suf
    if suf in ("pt", "pts"):
        unit = "pts"
    if float(n).is_integer() and abs(n) < 2**53 and ("." not in num or scale):
        n = int(n)
    return n, unit


def as_float(value, decimal: str = ",") -> float | None:
    try:
        n, _ = parse_number(value, decimal)
    except ValueError:
        return None
    return None if n is None else float(n)


# ---------------------------------------------------------------- dates


def date_order(texts) -> str:
    """'dmy' (French, the default) or 'mdy' when a cell like « 04/13/2024 » proves the month comes first."""
    dmy = mdy = 0
    for raw in texts:
        if not isinstance(raw, str):
            continue
        m = _D_NUM.match(raw.strip().lower())
        if not m or len(m.group(1)) == 4:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        dmy += a > 12 >= b
        mdy += b > 12 >= a
    return "mdy" if mdy > dmy else "dmy"


def _year(y: int) -> int:
    return y + (2000 if y < 70 else 1900) if y < 100 else y


def parse_date(value, order: str = "dmy") -> tuple[dt.datetime | None, str]:
    """(datetime, grain) — grain is 'day', 'month', 'quarter' or 'year' (what the cell says). Raises ValueError."""
    if isinstance(value, dt.datetime):
        return value, "day"
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day), "day"
    if value is None or isinstance(value, bool | int | float):
        raise ValueError("not a date")
    s = plain(value).replace(",", " ").strip()
    s = " ".join(s.split())
    if not s:
        raise ValueError("not a date")
    m = _D_NUM.match(s)
    if m:
        a, b, c = m.group(1), m.group(2), m.group(3)
        if len(a) == 4:
            y, mo, d = int(a), int(b), int(c)
        elif len(c) in (2, 4):
            y = _year(int(c))
            d, mo = (int(a), int(b)) if order == "dmy" else (int(b), int(a))
            if mo > 12 and d <= 12:
                d, mo = mo, d
        else:
            raise ValueError("not a date")
        hh, mm, ss = (int(m.group(i) or 0) for i in (4, 5, 6))
        try:
            return dt.datetime(y, mo, d, hh, mm, ss), "day"
        except ValueError:
            raise ValueError("not a date") from None
    m = _D_YM.match(s)
    if m:
        y, mo = (int(m.group(1)), int(m.group(2))) if m.group(1) else (int(m.group(4)), int(m.group(3)))
        if 1 <= mo <= 12 and 1900 <= y <= 2100:
            return dt.datetime(y, mo, 1), "month"
        raise ValueError("not a date")
    m = _D_QUARTER.match(s)
    if m:
        q, y = (int(m.group(1)), int(m.group(2))) if m.group(1) else (int(m.group(4)), int(m.group(3)))
        return dt.datetime(y, 3 * q - 2, 1), "quarter"
    m = _D_MONTH.match(s)
    if m and m.group(2) in MONTHS:
        y = _year(int(m.group(3)))
        d = int(m.group(1) or 1)
        try:
            return dt.datetime(y, MONTHS[m.group(2)], d), "day" if m.group(1) else "month"
        except ValueError:
            raise ValueError("not a date") from None
    raise ValueError("not a date")


def parse_bool(value) -> bool | None:
    s = plain(value) if value is not None else ""
    if s in ("oui", "yes", "vrai", "true", "ok", "✓"):
        return True
    if s in ("non", "no", "faux", "false"):
        return False
    raise ValueError("not a yes/no")


def bool_column(texts) -> bool:
    words = {plain(t) for t in texts if isinstance(t, str)}
    return bool(words) and words <= _BOOL_WORDS | {""} and len(words - {""}) >= 1


# ---------------------------------------------------------------- display


def fmt_number(v, lang: str = "fr", digits: int | None = None) -> str:
    """« 1 234,5 » (narrow no-break space, French) or « 1,234.5 »."""
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        v = int(v)
    if digits is None:
        digits = 0 if isinstance(v, int) else (2 if abs(v) < 1000 else 1 if abs(v) < 100000 else 0)
    text = f"{v:,.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".") if digits else text
    if lang == "en":
        return text
    return text.replace(",", " ").replace(".", ",")


def fmt_value(v, unit: str = "", lang: str = "fr") -> str:
    text = fmt_number(v, lang)
    if not unit:
        return text
    if unit == "%":
        return f"{text} %" if lang != "en" else f"{text}%"
    if unit in ("$", "£") and lang == "en":
        return f"{unit}{text}"
    return f"{text} {unit}"


def fmt_period(d: dt.datetime, grain: str, lang: str = "fr") -> str:
    if grain == "year":
        return str(d.year)
    if grain == "quarter":
        return f"{'T' if lang != 'en' else 'Q'}{(d.month - 1) // 3 + 1} {d.year}"
    if grain == "month":
        return f"{(MONTH_FR if lang != 'en' else MONTH_EN)[d.month - 1]} {d.year}"
    if grain == "week":
        y, w, _ = d.isocalendar()
        return f"{'S' if lang != 'en' else 'W'}{w:02d} {y}"
    return d.strftime("%d/%m/%Y") if lang != "en" else d.strftime("%Y-%m-%d")
