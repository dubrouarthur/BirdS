"""Statistics providers: Eurostat (JSON-stat 2.0), World Bank Indicators v2, INSEE Melodi. Each returns
``{series name: {period: value}}`` plus metadata; nothing here draws or interprets.
"""

from __future__ import annotations

import re

from birds.harness.guard import ToolError

from . import http

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{ds}"
EUROSTAT_PAGE = "https://ec.europa.eu/eurostat/databrowser/view/{ds}/default/table"
EUROSTAT_LICENSE = {"label": "Eurostat, réutilisation autorisée avec mention de la source",
                    "label_en": "Eurostat, reuse authorised with acknowledgement",
                    "url": "https://ec.europa.eu/eurostat/about-us/policies/copyright"}  # fmt: skip
WORLDBANK = "https://api.worldbank.org/v2/country/{codes}/indicator/{ind}"
WORLDBANK_PAGE = "https://data.worldbank.org/indicator/{ind}"
WORLDBANK_LICENSE = {"label": "CC BY 4.0", "url": "https://datacatalog.worldbank.org/public-licenses"}
MELODI = "https://api.insee.fr/melodi/data/{ds}"
MELODI_PAGE = "https://catalogue-donnees.insee.fr/fr/catalogue/recherche/{ds}"
ETALAB = {"label": "Licence Ouverte 2.0", "url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"}


def eurostat(ctx, ds: str, filters: dict, geos: list[str], since: str | None = None,
             last: int | None = None) -> tuple[dict[str, dict[str, float]], dict]:  # fmt: skip
    """{geo code: {period: value}} and {label, updated, flags} from a Eurostat dataset."""
    params: list[tuple[str, str]] = [(k, v) for k, v in filters.items()] + [("geo", g) for g in geos]
    if since:
        params.append(("sinceTimePeriod", since))
    if last:
        params.append(("lastTimePeriod", str(last)))
    params.append(("lang", "FR" if http.lang_of(ctx) == "fr" else "EN"))
    data = http.get(ctx, http.url(EUROSTAT.format(ds=ds), params))
    if not isinstance(data, dict) or "value" not in data:
        raise ToolError("Eurostat returned no data for this request")
    ids, sizes = data.get("id") or [], data.get("size") or []
    dims = data.get("dimension") or {}
    if len(ids) != len(sizes) or "geo" not in ids or "time" not in ids:
        raise ToolError("Eurostat answered in an unexpected shape")
    strides, acc = [0] * len(ids), 1
    for i in range(len(ids) - 1, -1, -1):
        strides[i] = acc
        acc *= int(sizes[i])
    gi, ti = ids.index("geo"), ids.index("time")
    for i, (d, n) in enumerate(zip(ids, sizes, strict=True)):
        if i not in (gi, ti) and int(n) != 1:
            raise ToolError(f"Eurostat dimension {d} is not fixed by the request")
    geo_idx = (dims["geo"].get("category") or {}).get("index") or {}
    time_idx = (dims["time"].get("category") or {}).get("index") or {}
    labels = (dims["geo"].get("category") or {}).get("label") or {}
    values, status = data.get("value") or {}, data.get("status") or {}
    out: dict[str, dict[str, float]] = {}
    flags: set[str] = set()
    for g, gpos in geo_idx.items():
        series = {}
        for t, tpos in time_idx.items():
            k = str(int(gpos) * strides[gi] + int(tpos) * strides[ti])
            v = values.get(k) if isinstance(values, dict) else None
            if isinstance(v, (int, float)):
                series[str(t)] = float(v)
                if status.get(k):
                    flags.add(str(status[k]))
        if series:
            out[g] = series
    meta = {"label": http.clean(data.get("label"), 160), "updated": str(data.get("updated") or "")[:10],
            "flags": sorted(flags), "names": {k: http.clean(v, 60) for k, v in labels.items()}}  # fmt: skip
    return out, meta


def worldbank(ctx, indicator: str, codes: list[str], first: int, last: int) -> tuple[dict, dict]:
    """{iso3: {year: value}} and {label, names, updated} from a World Bank indicator (annual)."""
    if not re.fullmatch(r"[A-Z0-9.]{3,40}", indicator) or not all(re.fullmatch(r"[A-Z]{3}", c) for c in codes):
        raise ToolError("invalid World Bank request")
    u = http.url(WORLDBANK.format(codes=";".join(codes), ind=indicator),
                 {"format": "json", "per_page": 1000, "date": f"{first}:{last}"})  # fmt: skip
    data = http.get(ctx, u)
    if not isinstance(data, list) or len(data) < 2 or not isinstance(data[1], list):
        msg = data[0].get("message") if isinstance(data, list) and data and isinstance(data[0], dict) else None
        raise ToolError("the World Bank returned no data" + (f" ({http.clean(msg, 80)})" if msg else ""))
    out: dict[str, dict[str, float]] = {}
    names, label, updated = {}, "", str(data[0].get("lastupdated") or "") if isinstance(data[0], dict) else ""
    for row in data[1]:
        if not isinstance(row, dict) or not isinstance(row.get("value"), (int, float)):
            continue
        code = str(row.get("countryiso3code") or "")
        out.setdefault(code, {})[str(row.get("date"))] = float(row["value"])
        names[code] = http.clean((row.get("country") or {}).get("value"), 60)
        label = label or http.clean((row.get("indicator") or {}).get("value"), 160)
    return out, {"label": label, "names": names, "updated": updated[:10]}


def melodi(ctx, ds: str, filters: dict, max_result: int = 1000) -> list[dict]:
    """The observations of a Melodi dataset: [{'period', 'value', 'dims'}]."""
    params = {**filters, "maxResult": max_result}
    data = http.get(ctx, http.url(MELODI.format(ds=ds), params))
    obs = (data or {}).get("observations") if isinstance(data, dict) else None
    if not isinstance(obs, list):
        raise ToolError("INSEE Melodi returned no data")
    out = []
    for o in obs:
        dims = o.get("dimensions") or {}
        v = ((o.get("measures") or {}).get("OBS_VALUE_NIVEAU") or {}).get("value")
        if isinstance(v, (int, float)) and dims.get("TIME_PERIOD"):
            out.append({"period": str(dims["TIME_PERIOD"]), "value": float(v), "dims": dims})
    return out
