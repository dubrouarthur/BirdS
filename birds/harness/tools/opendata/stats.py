"""get_statistics: official series drawn as a line chart, through the make_chart path (chart.normalize_chart).

« Évolution du chômage en France depuis 2015 », « PIB Allemagne vs France », « population de Lille sur 10 ans »:
the harness picks the provider (Eurostat for EU comparisons, the World Bank elsewhere, INSEE Melodi for French
communes and business start-ups), fetches the real series and draws them. The chart carries its source, dataset
code, licence and any transformation made here (a unit conversion, monthly figures summed into years), as the
providers' terms ask. The model never writes a figure of its own: it comments on the drawn series.
"""

from __future__ import annotations

import re
from datetime import date

from birds.harness.guard import ToolError
from birds.harness.tools.chart import MAX_CHARTS, normalize_chart

from . import countries, http, sources
from .commune import best_commune

# indicator key -> definition. eu_a / eu_m / eu_s: Eurostat (dataset, fixed filters) annual / monthly / half-yearly
PRESETS: dict[str, dict] = {
    "unemployment": {
        "fr": "Taux de chômage", "en": "Unemployment rate", "unit": "%",
        "sub_fr": "15-74 ans, en % de la population active", "sub_en": "aged 15-74, % of the labour force",
        "eu_a": ("une_rt_a", {"sex": "T", "age": "Y15-74", "unit": "PC_ACT"}),
        "eu_m": ("une_rt_m", {"sex": "T", "age": "TOTAL", "unit": "PC_ACT", "s_adj": "SA"}),
        "wb": "SL.UEM.TOTL.ZS", "wb_sub_fr": "en % de la population active (estimation OIT)",
        "wb_sub_en": "% of the labour force (ILO estimate)",
    },
    "inflation": {
        "fr": "Inflation", "en": "Inflation", "unit": "%",
        "sub_fr": "IPCH, variation annuelle en %", "sub_en": "HICP, annual rate of change in %",
        "eu_a": ("prc_hicp_ainr", {"coicop18": "TOTAL", "unit": "RCH_A_AVG"}),
        "eu_m": ("prc_hicp_minr", {"coicop18": "TOTAL", "unit": "RCH_A"}),
        "wb": "FP.CPI.TOTL.ZG", "wb_sub_fr": "prix à la consommation, variation annuelle en %",
        "wb_sub_en": "consumer prices, annual %",
    },
    "gdp": {
        "fr": "PIB", "en": "GDP", "unit": "Md$", "wb": "NY.GDP.MKTP.CD", "scale": 1e9,
        "wb_sub_fr": "en milliards de dollars US courants", "wb_sub_en": "current US$, billions",
        "note_fr": "converti en milliards par Bird", "note_en": "converted to billions by Bird",
    },
    "gdp_growth": {
        "fr": "Croissance du PIB", "en": "GDP growth", "unit": "%", "wb": "NY.GDP.MKTP.KD.ZG",
        "wb_sub_fr": "en volume, % par an", "wb_sub_en": "real, annual %",
    },
    "population": {
        "fr": "Population", "en": "Population", "unit": "M", "wb": "SP.POP.TOTL", "scale": 1e6,
        "wb_sub_fr": "en millions d'habitants", "wb_sub_en": "millions",
        "note_fr": "converti en millions par Bird", "note_en": "converted to millions by Bird", "since": 20,
    },
    "electricity": {
        "fr": "Prix de l'électricité pour les entreprises", "en": "Electricity prices for businesses",
        "unit": "€/kWh", "sub_fr": "consommation 500-2 000 MWh (bande IC), hors TVA et taxes récupérables",
        "sub_en": "500-2,000 MWh a year (band IC), excluding VAT and recoverable taxes",
        "eu_s": ("nrg_pc_205", {"siec": "E7000", "nrg_cons": "MWH500-1999", "tax": "I_TAX", "currency": "EUR",
                                "unit": "KWH"}),
    },
    "exports": {
        "fr": "Exportations", "en": "Exports", "unit": "% PIB", "wb": "NE.EXP.GNFS.ZS",
        "wb_sub_fr": "biens et services, en % du PIB", "wb_sub_en": "goods and services, % of GDP",
    },
    "creations": {
        "fr": "Créations d'entreprises en France", "en": "Business start-ups in France", "unit": "",
        "sub_fr": "toutes formes, données brutes, sommes annuelles", "sub_en": "all legal forms, raw data, yearly sums",
        "note_fr": "sommes annuelles des données mensuelles, calculées par Bird ; année en cours exclue",
        "note_en": "yearly sums of the monthly data, computed by Bird; current year left out",
    },
}  # fmt: skip

_IND_WORDS = [
    (
        "creations",
        r"cr[ée]ations?\s+d'entreprises?|entreprises?\s+cr[ée]{2}e?s|business\s+(?:start-?ups|creations?)|"
        r"new\s+businesses",
    ),
    (
        "electricity",
        r"prix\s+(?:de\s+l'|du\s+)?[ée]lectricit[ée]|tarifs?\s+(?:de\s+l'|d')?[ée]lectricit[ée]|"
        r"electricity\s+prices?|price\s+of\s+electricity|co[uû]t\s+de\s+l'[ée]lectricit[ée]",
    ),
    ("gdp_growth", r"croissance\s+(?:du\s+pib|[ée]conomique)|gdp\s+growth|economic\s+growth"),
    ("unemployment", r"ch[oô]mage|unemployment|jobless"),
    (
        "inflation",
        r"inflation|hausse\s+des\s+prix|prix\s+[àa]\s+la\s+consommation|\bipch?\b|\bhicp\b|\bcpi\b|"
        r"consumer\s+prices",
    ),
    ("gdp", r"\bpib\b|\bgdp\b|produit\s+int[ée]rieur\s+brut|gross\s+domestic\s+product"),
    ("population", r"\bpopulation\b|nombre\s+d'habitants|habitants|inhabitants"),
    ("exports", r"exportations?|\bexports?\b"),
]
_IND_RX = [(k, re.compile(rx, re.I)) for k, rx in _IND_WORDS]


_IND_LOOSE = [
    ("electricity", r"[ée]lectricit[ée]|electricity"),
    ("creations", r"cr[ée]ations?|start-?ups?"),
    ("gdp_growth", r"croissance|growth"),
]


def indicator_of(text: str, loose: bool = False) -> str:
    """The indicator key a text names. ``loose``: a model's short argument (« électricité », « créations »)."""
    t = str(text or "").replace("’", "'")
    if t.strip().lower() in PRESETS:
        return t.strip().lower()
    for key, rx in _IND_RX:
        if rx.search(t):
            return key
    if loose:
        for key, rx in _IND_LOOSE:
            if re.search(rx, t, re.I):
                return key
    return ""


def _since(text: str, today: date) -> tuple[str, int]:
    """('year', first year) or ('month', number of months) from '2015', '24m', '10y', '' (default)."""
    t = str(text or "").strip().lower()
    m = re.fullmatch(r"(\d{1,3})\s*(?:m|mois|months?)", t)
    if m:
        return "month", max(2, min(60, int(m.group(1))))
    m = re.fullmatch(r"(\d{1,2})\s*(?:y|a|ans?|years?)", t)
    if m:
        return "year", today.year - max(1, min(60, int(m.group(1))))
    m = re.fullmatch(r"(19[5-9]\d|20\d\d)", t)
    if m:
        return "year", int(m.group(1))
    return "year", 0


def _split_places(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|;|/|\bet\b|\band\b|\bvs\.?|\bversus\b|\bcontre\b|\bcompar[ée]e?s?\s+[àa]\b)\s*",
                     str(text or ""), flags=re.I)  # fmt: skip
    return [p.strip(" .?!'\"") for p in parts if p and p.strip(" .?!'\"")][:6]


def _fmt(v: float | None, lang: str, unit: str) -> str:
    if v is None:
        return "?"
    digits = 0 if abs(v) >= 1000 else (1 if abs(v) >= 10 or unit in ("%", "% PIB") else 2 if abs(v) >= 1 else 4)
    s = f"{v:,.{digits}f}"
    if lang == "fr":
        s = s.replace(",", " ").replace(".", ",")
    return s + (f" {unit}" if unit else "")


def get_statistics(args: dict, ctx) -> str:
    lang = http.lang_of(ctx)
    today = getattr(ctx, "today", None) or date.today()
    if len(getattr(ctx, "charts", [])) >= MAX_CHARTS:
        raise ToolError(f"at most {MAX_CHARTS} charts per request: answer the user now")
    key = indicator_of(str(args.get("indicator") or ""), loose=True)
    if key not in PRESETS:
        raise ToolError("unknown indicator: use chômage, inflation, PIB, croissance, population, prix de "
                        "l'électricité, exportations or créations d'entreprises")  # fmt: skip
    p = PRESETS[key]
    names = _split_places(str(args.get("places") or "")) or ["France"]
    codes, towns = [], []
    for n in names:
        found = countries.find(n)
        if found:
            codes += [c for c in found if c not in codes]
        else:
            towns.append(n)
    freq, since = _since(str(args.get("since") or ""), today)
    if key == "creations":
        series, meta = _creations(ctx, lang, today)
    elif towns:
        if key != "population" or codes:
            raise ToolError(f"no national series for {', '.join(towns)}: only population is available for a French "
                            "commune, and communes cannot be mixed with countries; say so")  # fmt: skip
        series, meta = _towns(ctx, towns, lang)
    else:
        series, meta = _countries(ctx, key, p, codes, freq, since, lang, today)
    if not series:
        raise ToolError("the provider has no figures for this request; say so, invent none")
    first = since if freq == "year" and since else (today.year - p.get("since", 10) if freq == "year" else 0)
    periods = sorted({t for s in series.values() for t in s})
    if freq == "year" and first:
        periods = [t for t in periods if int(t[:4]) >= first] or periods[-12:]
    periods = periods[-50:]
    names_shown = list(series)
    rows = [[_label(t, lang)] + [series[s].get(t) for s in names_shown] for t in periods]
    rows = [r for r in rows if any(v is not None for v in r[1:])]
    if not rows:
        raise ToolError("the provider has no figures for this period; say so, invent none")
    span = f"{rows[0][0]} – {rows[-1][0]}" if len(rows) > 1 else rows[0][0]
    where = ", ".join(names_shown) if len(names_shown) <= 3 else ", ".join(names_shown[:3]) + "…"
    title = f"{p[lang]} ({span})" if key == "creations" else f"{p[lang]}, {where} ({span})"
    label_col = {"month": "Mois", "half": "Semestre"}.get(meta.get("freq", "year"), "Année") if lang == "fr" else (
        {"month": "Month", "half": "Half-year"}.get(meta.get("freq", "year"), "Year"))  # fmt: skip
    spec, _ = normalize_chart({"title": title, "type": "line", "columns": [label_col, *names_shown],
                               "rows": rows, "unit": meta.get("unit", p["unit"])}, lang, getattr(ctx, "request", ""))  # fmt: skip
    src = meta["source"]
    spec = {"id": f"c{len(ctx.charts) + 1}", **spec, "source": "data", "data_source": src}
    ctx.charts.append(spec)
    n_src = http.cite(ctx, src["url"])
    ctx.step_info = {"chart": spec["id"], "values": len(rows), "series": len(names_shown), "type": spec["type"],
                     "label": src["label"], "dataset": src.get("dataset", "")}  # fmt: skip
    facts = []
    for j, s in enumerate(names_shown, 1):
        vals = [(r[0], r[j]) for r in rows if r[j] is not None]
        if vals:
            facts.append(f"{s} : {_fmt(vals[0][1], lang, spec['unit'])} en {vals[0][0]} → {_fmt(vals[-1][1], lang, spec['unit'])} "
                         f"en {vals[-1][0]}" if lang == "fr" else
                         f"{s}: {_fmt(vals[0][1], lang, spec['unit'])} in {vals[0][0]} → "
                         f"{_fmt(vals[-1][1], lang, spec['unit'])} in {vals[-1][0]}")  # fmt: skip
    sub = src.get("subtitle", "")
    if lang == "fr":
        return (f"Graphique affiché à l'utilisateur (ne cite pas cette note) : « {spec['title']} » ({sub}), données "
                f"réelles {src['label']}{' ' + src['dataset'] if src.get('dataset') else ''}. " + " ; ".join(facts)
                + ". Ne redessine pas le graphique et ne recopie pas tous les chiffres : commente la tendance en 1 à 3 "
                f"phrases avec ces valeurs exactes. Source à citer : [{n_src}].")  # fmt: skip
    return (f"Chart displayed to the user (do not quote this note): '{spec['title']}' ({sub}), real data from "
            f"{src['label']}{' ' + src['dataset'] if src.get('dataset') else ''}. " + "; ".join(facts)
            + ". Do not draw it again or list every figure: comment on the trend in 1 to 3 sentences with these exact "
            f"values. Source to cite: [{n_src}].")  # fmt: skip


def _label(t: str, lang: str) -> str:
    m = re.fullmatch(r"(\d{4})-S([12])", t)
    if m:
        return f"S{m.group(2)} {m.group(1)}"
    m = re.fullmatch(r"(\d{4})M(\d{2})", t)
    return f"{m.group(1)}-{m.group(2)}" if m else t


def _countries(ctx, key, p, codes, freq, since, lang, today):
    use_eu = all(countries.in_eurostat(c) for c in codes) and ("eu_a" in p or "eu_s" in p)
    if not use_eu and "wb" not in p:
        raise ToolError(f"{p['en']} is published by Eurostat for European countries only; say so")
    if use_eu:
        if "eu_s" in p:
            ds, flt = p["eu_s"]
            kind, kw = "half", {"since": f"{since or today.year - 8}-S1"}
        elif freq == "month" and "eu_m" in p:
            ds, flt = p["eu_m"]
            kind, kw = "month", {"last": since}
        else:
            ds, flt = p["eu_a"]
            kind, kw = "year", {"since": str(since or today.year - p.get("since", 10))}
        geos = [countries.eurostat_code(c) for c in codes]
        data, meta = sources.eurostat(ctx, ds, flt, geos, **kw)
        back = {countries.eurostat_code(c): c for c in codes}
        series = {countries.name(back[g], lang): v for g, v in data.items() if g in back}
        series = {countries.name(c, lang): series[countries.name(c, lang)] for c in codes
                  if countries.name(c, lang) in series}  # fmt: skip
        notes = []
        if "b" in meta["flags"]:
            notes.append("rupture de série signalée par Eurostat" if lang == "fr" else "break in series (Eurostat)")
        if "p" in meta["flags"] or "e" in meta["flags"]:
            notes.append(
                "valeurs provisoires ou estimées incluses" if lang == "fr" else "provisional or estimated values"
            )
        src = {"label": "Eurostat", "dataset": ds, "url": sources.EUROSTAT_PAGE.format(ds=ds),
               "license": sources.EUROSTAT_LICENSE["label" if lang == "fr" else "label_en"],
               "license_url": sources.EUROSTAT_LICENSE["url"], "updated": meta["updated"],
               "subtitle": p.get("sub_" + lang, ""), "note": "; ".join(notes)}  # fmt: skip
        return series, {"source": src, "freq": kind}
    wb_codes = [countries.worldbank_code(c) for c in codes]
    if not all(wb_codes):
        raise ToolError("no World Bank series for one of these places; say so")
    first = since if freq == "year" and since else today.year - (p.get("since", 10) if freq == "year" else 3)
    data, meta = sources.worldbank(ctx, p["wb"], wb_codes, first, today.year)
    scale = p.get("scale", 1)
    series = {}
    for c, wc in zip(codes, wb_codes, strict=True):
        if wc in data:
            series[countries.name(c, lang)] = {y: round(v / scale, 2) for y, v in data[wc].items()}
    src = {"label": "Banque mondiale" if lang == "fr" else "World Bank", "dataset": p["wb"],
           "url": sources.WORLDBANK_PAGE.format(ind=p["wb"]), "license": sources.WORLDBANK_LICENSE["label"],
           "license_url": sources.WORLDBANK_LICENSE["url"], "updated": meta["updated"],
           "subtitle": p.get("wb_sub_" + lang, ""), "note": p.get("note_" + lang, "")}  # fmt: skip
    return series, {"source": src, "freq": "year"}


def _towns(ctx, towns: list[str], lang: str):
    series = {}
    for t in towns[:3]:
        c = best_commune(ctx, t)
        if not c:
            raise ToolError(f"no French commune named '{t}'; say so")
        obs = sources.melodi(ctx, "DS_POPULATIONS_HISTORIQUES", {"GEO": f"COM-{c['code']}"}, 100)
        vals = {o["period"]: o["value"] for o in obs if o["dims"].get("POPREF_MEASURE", "PMUN") == "PMUN"}
        if vals:
            series[c["name"]] = vals
    src = {"label": "Insee", "dataset": "DS_POPULATIONS_HISTORIQUES",
           "url": sources.MELODI_PAGE.format(ds="DS_POPULATIONS_HISTORIQUES"), "license": sources.ETALAB["label"],
           "license_url": sources.ETALAB["url"],
           "subtitle": "population municipale (recensement)" if lang == "fr" else "municipal population (census)",
           "note": ""}  # fmt: skip
    return series, {"source": src, "freq": "year", "unit": "hab." if lang == "fr" else "inhabitants"}


def _creations(ctx, lang: str, today: date):
    obs = sources.melodi(ctx, "DS_SIDE_CREA_ENT_SERIES", {"GEO": "FRANCE-F", "FREQ": "M", "ACTIVITY": "_T",
                                                          "LEGAL_FORM": "_T", "SEASONAL_ADJUST": "N"}, 1000)  # fmt: skip
    months: dict[str, dict[str, float]] = {}
    for o in obs:
        m = re.fullmatch(r"(\d{4})-(\d{2})", o["period"])
        if m:
            months.setdefault(m.group(1), {})[m.group(2)] = o["value"]
    years = {y: round(sum(v.values())) for y, v in months.items() if len(v) == 12 and int(y) < today.year}
    name = "France"
    src = {"label": "Insee", "dataset": "DS_SIDE_CREA_ENT_SERIES",
           "url": sources.MELODI_PAGE.format(ds="DS_SIDE_CREA_ENT_SERIES"), "license": sources.ETALAB["label"],
           "license_url": sources.ETALAB["url"], "subtitle": PRESETS["creations"]["sub_" + lang],
           "note": PRESETS["creations"]["note_" + lang]}  # fmt: skip
    return ({name: years} if years else {}), {"source": src, "freq": "year"}
