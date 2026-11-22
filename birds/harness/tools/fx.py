"""convert_currency: the European Central Bank daily reference rates (eurofxref-daily.xml, free, official).

A reference rate is not a market quote: the result text and the card both say so. Cross rates go through EUR.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from birds.harness import geo, intents
from birds.harness.guard import Blocked, ToolError

ECB_PAGE = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
TTL = 6 * 3600


def parse_ecb(xml_text: str) -> tuple[str, dict[str, float]]:
    """(date, {code: units per 1 EUR}) from eurofxref-daily.xml. A DOCTYPE (entity tricks) is refused."""
    if re.search(r"<!DOCTYPE|<!ENTITY", xml_text or "", re.I):
        raise Blocked("XML with a DOCTYPE refused")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ToolError("the ECB file could not be read") from e
    date, rates = "", {"EUR": 1.0}
    for el in root.iter():
        if el.tag.endswith("Cube") and el.get("time"):
            date = el.get("time") or ""
        if el.tag.endswith("Cube") and el.get("currency"):
            try:
                rates[el.get("currency").upper()] = float(el.get("rate"))
            except (TypeError, ValueError):
                continue
    if len(rates) < 2 or not date:
        raise ToolError("the ECB file holds no rate")
    return date, rates


def _fmt(x: float, lang: str, digits: int = 2) -> str:
    s = f"{x:,.{digits}f}"
    return s.replace(",", " ").replace(".", ",") if lang == "fr" else s


def convert_currency(args: dict, ctx) -> str:
    lang = ctx.lang if ctx.lang in ("fr", "en") else "fr"
    a = intents.currency_code(str(args.get("from") or "")) or str(args.get("from") or "").upper()[:3]
    b = intents.currency_code(str(args.get("to") or "")) or str(args.get("to") or "").upper()[:3]
    amount = args.get("amount")
    amount = 1.0 if amount in (None, "") else float(amount)
    if not (0 < amount < 1e13):
        raise ToolError("amount must be a positive number")
    xml_text = geo.get_json(ctx, ctx.config.fx_url, xml=True, cache_ttl=TTL, count=False)
    date, rates = parse_ecb(xml_text)
    for code in (a, b):
        if code not in rates:
            raise ToolError(f"no ECB reference rate for {code or '?'}; say so")
    if a == b:
        raise ToolError("the two currencies are the same")
    rate = rates[b] / rates[a]  # units of b for 1 a
    result = round(amount * rate, 2)
    if ECB_PAGE not in ctx.sources:
        ctx.sources.append(ECB_PAGE)
    n_src = ctx.sources.index(ECB_PAGE) + 1
    eur_line = f"1 EUR = {rates[b]:.4f} {b}" if a == "EUR" else f"1 EUR = {rates[a]:.4f} {a}"
    ctx.step_info = {
        "widget": {
            "type": "fx",
            "v": 1,
            "amount": amount,
            "from": a,
            "to": b,
            "result": result,
            "rate": round(rate, 6),
            "date": date,
            "source": {"label": "BCE — taux de référence" if lang == "fr" else "ECB — reference rate", "url": ECB_PAGE},
        },
        "label": "BCE" if lang == "fr" else "ECB",
    }
    digits_amt = 0 if float(amount).is_integer() else 2
    if lang == "fr":
        return (
            f"{_fmt(amount, lang, digits_amt)} {a} = {_fmt(result, lang)} {b} (taux de référence BCE du {date} : "
            f"{eur_line} ; 1 {a} = {rate:.4f} {b}). C'est un taux de référence indicatif, pas un cours de marché. "
            f"Une carte de conversion est affichée à l'utilisateur. Donne ce chiffre exact. Source à citer : [{n_src}]."
        )
    return (
        f"{_fmt(amount, lang, digits_amt)} {a} = {_fmt(result, lang)} {b} (ECB reference rate of {date}: {eur_line}; "
        f"1 {a} = {rate:.4f} {b}). A reference rate, not a market quote. A conversion card is shown to the user. "
        f"Give this exact figure. Source to cite: [{n_src}]."
    )
