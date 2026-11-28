"""lookup_entity: an entity card from Wikipedia (REST page summary, CC BY-SA 4.0) and Wikidata (facts, CC0).

« C'est quoi Airbus ? », « fiche sur le Portugal (capitale, population, monnaie) »: the article's opening lines,
its picture and a few facts read from Wikidata claims (inception, headquarters, chief executive, employees,
revenue for a company; capital, population, currency, languages, head of state for a country). Every value comes
from Wikidata with its date when it has one; the model only frames them. The picture is shown only when Wikimedia
Commons gives its licence and author (credited on the card); it is served through the same-origin image proxy.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from birds.harness.guard import ToolError

from . import http

SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WD_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WP_LICENSE = {"label": "CC BY-SA 4.0", "url": "https://creativecommons.org/licenses/by-sa/4.0/deed.fr"}
WD_LICENSE = {"label": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0/deed.fr"}
_IMAGE_HOSTS = ("upload.wikimedia.org",)

http.HOSTS.setdefault("commons.wikimedia.org", (0.2, 7 * http.DAY))

KIND_COUNTRY = {"Q6256", "Q3624078", "Q7275", "Q3024240", "Q1763527", "Q51576574"}
KIND_COMPANY = {"Q4830453", "Q783794", "Q891723", "Q6881511", "Q167037", "Q658255", "Q2085381", "Q1058914",
                "Q210167", "Q18388277", "Q1589009", "Q15711870", "Q1616075", "Q219577"}  # fmt: skip
KIND_HUMAN = {"Q5"}
KIND_CITY = {"Q515", "Q1549591", "Q484170", "Q1637706", "Q200250", "Q5119", "Q22865", "Q15284", "Q3957", "Q532"}
# (property, fr label, en label, value kind) per entity kind
FACTS = {
    "country": [("P36", "Capitale", "Capital", "item"), ("P1082", "Population", "Population", "qty"),
                ("P38", "Monnaie", "Currency", "item"), ("P37", "Langue officielle", "Official language", "items"),
                ("P2046", "Superficie", "Area", "qty"), ("P35", "Chef de l'État", "Head of state", "item"),
                ("P6", "Chef du gouvernement", "Head of government", "item")],
    "company": [("P571", "Création", "Founded", "time"), ("P159", "Siège", "Headquarters", "item"),
                ("P169", "Directeur général", "Chief executive", "item"),
                ("P488", "Président", "Chairperson", "item"), ("P1128", "Effectif", "Employees", "qty"),
                ("P2139", "Chiffre d'affaires", "Revenue", "qty"), ("P452", "Secteur", "Industry", "items"),
                ("P17", "Pays", "Country", "item"), ("P856", "Site officiel", "Website", "url")],
    "human": [("P569", "Naissance", "Born", "time"), ("P570", "Décès", "Died", "time"),
              ("P106", "Activité", "Occupation", "items"), ("P27", "Nationalité", "Citizenship", "items")],
    "city": [("P1082", "Population", "Population", "qty"), ("P17", "Pays", "Country", "item"),
             ("P131", "Division", "Located in", "item"), ("P2046", "Superficie", "Area", "qty")],
    "other": [("P571", "Création", "Inception", "time"), ("P17", "Pays", "Country", "item"),
              ("P159", "Siège", "Headquarters", "item"), ("P856", "Site officiel", "Website", "url")],
}  # fmt: skip
UNITS = {"Q4916": "€", "Q4917": "$", "Q25224": "£", "Q712226": "km²", "Q11573": "m", "Q828224": "km", "Q25344": "CHF",
         "Q8146": "¥", "Q11570": "kg"}  # fmt: skip
MONTHS_FR = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()
MONTHS_EN = "January February March April May June July August September October November December".split()


def _summary(ctx, title: str, lang: str) -> dict | None:
    t = quote(title.strip().replace(" ", "_"), safe="")
    try:
        data = http.get(ctx, SUMMARY.format(lang=lang, title=t) + "?redirect=true")
    except ToolError as e:
        if str(e) == "HTTP 404":
            return None
        raise
    return data if isinstance(data, dict) else None


def _search(ctx, name: str, lang: str) -> list[dict]:
    data = http.get(ctx, http.url(WD_API, {"action": "wbsearchentities", "search": name, "language": lang,
                                           "uselang": lang, "type": "item", "limit": 5, "format": "json"}))  # fmt: skip
    return [x for x in (data.get("search") or []) if isinstance(x, dict)] if isinstance(data, dict) else []


def _entities(ctx, ids: list[str], props: str, lang: str) -> dict:
    if not ids:
        return {}
    data = http.get(ctx, http.url(WD_API, {"action": "wbgetentities", "ids": "|".join(ids[:50]), "props": props,
                                           "languages": f"{lang}|en", "sitefilter": f"{lang}wiki|enwiki",
                                           "format": "json"}))  # fmt: skip
    return (data.get("entities") or {}) if isinstance(data, dict) else {}


def _label(ent: dict, lang: str) -> str:
    labels = ent.get("labels") or {}
    return http.clean((labels.get(lang) or labels.get("en") or {}).get("value", ""), 80)


def _best(claims: list) -> list[dict]:
    """Preferred statements, else normal ones (deprecated never); a dated quantity: the most recent first."""
    ok = [c for c in claims or [] if c.get("rank") != "deprecated" and (c.get("mainsnak") or {}).get("datavalue")]
    pref = [c for c in ok if c.get("rank") == "preferred"] or ok

    def when(c):
        q = ((c.get("qualifiers") or {}).get("P585") or [{}])[0]
        return str(((q.get("datavalue") or {}).get("value") or {}).get("time", ""))

    return sorted(pref, key=when, reverse=True)


def _time(v: dict, lang: str) -> str:
    m = re.match(r"^\+?(-?\d{1,6})-(\d{2})-(\d{2})", str(v.get("time", "")))
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    p = int(v.get("precision") or 9)
    if p >= 11 and mo and d:
        return f"{d}{'er' if d == 1 and lang == 'fr' else ''} {(MONTHS_FR if lang == 'fr' else MONTHS_EN)[mo - 1]} {y}"
    if p == 10 and mo:
        return f"{(MONTHS_FR if lang == 'fr' else MONTHS_EN)[mo - 1]} {y}"
    return str(y)


def _num(x: float, lang: str) -> str:
    if abs(x) >= 1e9:
        s, suf = x / 1e9, (" Md" if lang == "fr" else " bn")
    elif abs(x) >= 1e6:
        s, suf = x / 1e6, (" M" if lang == "fr" else " M")
    else:
        s, suf = x, ""
    txt = f"{s:,.1f}" if suf and s < 100 else f"{s:,.0f}"
    txt = txt.removesuffix(".0")
    return (txt.replace(",", " ").replace(".", ",") if lang == "fr" else txt) + suf


def facts_of(ent: dict, kind: str, lang: str, labels: dict) -> list[dict]:
    out = []
    claims = ent.get("claims") or {}
    for prop, fr, en, vk in FACTS[kind]:
        best = _best(claims.get(prop) or [])
        if not best:
            continue
        values, date = [], ""
        for c in best[: 3 if vk == "items" else 1]:
            dv = (c.get("mainsnak") or {}).get("datavalue") or {}
            v = dv.get("value")
            if vk in ("item", "items") and isinstance(v, dict) and v.get("id"):
                lab = labels.get(v["id"], "")
                if lab:
                    values.append(lab)
            elif vk == "time" and isinstance(v, dict):
                t = _time(v, lang)
                if t:
                    values.append(t)
            elif vk == "qty" and isinstance(v, dict):
                try:
                    amount = float(str(v.get("amount", "")).lstrip("+"))
                except ValueError:
                    continue
                unit = UNITS.get(str(v.get("unit", "")).rsplit("/", 1)[-1], "")
                values.append(_num(amount, lang) + (f" {unit}" if unit else ""))
            elif vk == "url" and isinstance(v, str) and re.match(r"https?://", v):
                values.append(v[:200])
            q = ((c.get("qualifiers") or {}).get("P585") or [{}])[0]
            qv = (q.get("datavalue") or {}).get("value")
            if isinstance(qv, dict) and not date:
                date = _time({**qv, "precision": min(9, int(qv.get("precision") or 9))}, lang)
        if values:
            out.append({"p": prop, "label": fr if lang == "fr" else en, "value": ", ".join(values)[:160],
                        "date": date, "url": values[0] if vk == "url" else ""})  # fmt: skip
    return out[:8]


def _kind(ent: dict) -> str:
    p31 = {((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id")
           for c in (ent.get("claims") or {}).get("P31") or []}  # fmt: skip
    if p31 & KIND_COUNTRY:
        return "country"
    if p31 & KIND_HUMAN:
        return "human"
    if p31 & KIND_COMPANY or "P1128" in (ent.get("claims") or {}) or "P169" in (ent.get("claims") or {}):
        return "company"
    if p31 & KIND_CITY:
        return "city"
    return "other"


def _image(ctx, summary: dict) -> dict | None:
    """The article's thumbnail with its Commons author and licence, or None (no licence known: no picture)."""
    th = summary.get("thumbnail") or {}
    src = str(th.get("source") or "")
    orig = str((summary.get("originalimage") or {}).get("source") or src)
    if http.host_of(src) not in _IMAGE_HOSTS + ("thumb.wikimedia.org",):
        return None
    m = re.search(r"/(?:commons|[a-z]{2})/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/?]+)", orig) or re.search(
        r"/(?:commons|[a-z]{2})/thumb/[0-9a-f]/[0-9a-f]{2}/([^/?]+)/", src)  # fmt: skip
    if not m:
        return None
    from urllib.parse import unquote

    fname = unquote(m.group(1))
    try:
        data = http.get(ctx, http.url(COMMONS_API, {"action": "query", "titles": f"File:{fname}", "prop": "imageinfo",
                                                    "iiprop": "extmetadata", "format": "json"}))  # fmt: skip
    except ToolError:
        return None
    pages = ((data or {}).get("query") or {}).get("pages") or {}
    meta = {}
    for p in pages.values() if isinstance(pages, dict) else []:
        meta = ((p.get("imageinfo") or [{}])[0] or {}).get("extmetadata") or {}
    lic = http.clean((meta.get("LicenseShortName") or {}).get("value"), 40)
    if not lic:
        return None
    artist = http.clean((meta.get("Artist") or {}).get("value"), 80)
    # a Wikimedia thumbnail URL: the proxy fetches it from upload.wikimedia.org (thumb.wikimedia.org redirects there)
    src = src.replace("://thumb.wikimedia.org/", "://upload.wikimedia.org/").split("?", 1)[0]
    return {"src": src, "w": int(th.get("width") or 0), "h": int(th.get("height") or 0), "license": lic,
            "artist": artist, "page": "https://commons.wikimedia.org/wiki/File:" + quote(fname.replace(" ", "_"))}  # fmt: skip


def lookup_entity(args: dict, ctx) -> str:
    lang = http.lang_of(ctx)
    name = " ".join(str(args.get("name") or "").split())[:80]
    if len(name) < 2:
        raise ToolError("name is empty: ask the user what to look up")
    summary = _summary(ctx, name, lang)
    if summary is None or summary.get("type") == "disambiguation" or not summary.get("wikibase_item"):
        hits = [h for h in _search(ctx, name, lang) if not re.search(r"homonymie|disambiguation|Wikimedia",
                                                                       str(h.get("description", "")), re.I)]  # fmt: skip
        if not hits:
            ctx.step_info = {"found": 0}
            return (f"Aucune fiche Wikipédia ou Wikidata pour « {name} ». Dis-le simplement ; n'invente rien."
                    if lang == "fr" else f"No Wikipedia or Wikidata entry for '{name}'. Say so; invent nothing.")  # fmt: skip
        qid = str(hits[0]["id"])
        ent = _entities(ctx, [qid], "claims|labels|descriptions|sitelinks", lang).get(qid) or {}
        site = (ent.get("sitelinks") or {}).get(f"{lang}wiki") or {}
        summary = _summary(ctx, site["title"], lang) if site.get("title") else None
        summary = summary or {"title": _label(ent, lang) or name,
                              "description": http.clean(((ent.get("descriptions") or {}).get(lang) or {}).get("value"))}  # fmt: skip
    else:
        qid = str(summary["wikibase_item"])
        try:
            ent = _entities(ctx, [qid], "claims|labels|descriptions", lang).get(qid) or {}
        except ToolError:  # Wikidata busy (429) or down: the Wikipedia summary alone still makes a card
            ent = {}
    kind = _kind(ent) if ent else "other"
    ids = []
    for prop, *_rest in FACTS[kind]:
        for c in _best((ent.get("claims") or {}).get(prop) or [])[:3]:
            v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(v, dict) and v.get("id"):
                ids.append(v["id"])
    try:
        labels = {k: _label(v, lang) for k, v in _entities(ctx, list(dict.fromkeys(ids)), "labels", lang).items()}
    except ToolError:
        labels, ent = {}, {}
    facts = facts_of(ent, kind, lang, labels) if ent else []
    page = str(((summary.get("content_urls") or {}).get("desktop") or {}).get("page") or "")
    if not page.startswith(f"https://{lang}.wikipedia.org/"):
        page = ""
    extract = http.clean(summary.get("extract"), 700)
    image = _image(ctx, summary) if summary.get("thumbnail") else None
    wd_url = f"https://www.wikidata.org/wiki/{qid}" if re.fullmatch(r"Q\d{1,12}", qid or "") else ""
    w = {
        "type": "entity", "v": 1, "title": http.clean(summary.get("title") or name, 100),
        "description": http.clean(summary.get("description"), 160), "extract": extract, "kind": kind,
        "facts": facts, "image": image, "url": page, "qid": qid if wd_url else "", "wikidata": wd_url,
        "source": {"label": "Wikipédia" if lang == "fr" else "Wikipedia", "url": page or wd_url},
        "license": WP_LICENSE, "data_license": WD_LICENSE,
    }  # fmt: skip
    if not (extract or facts):
        ctx.step_info = {"found": 0}
        return (f"La fiche de « {name} » est vide. Dis-le ; n'invente rien." if lang == "fr"
                else f"The entry for '{name}' is empty. Say so; invent nothing.")  # fmt: skip
    ctx.step_info = {"widget": w, "label": "Wikipédia / Wikidata", "found": 1}
    n_src = http.cite(ctx, page or wd_url)
    lines = "; ".join(f"{f['label']} : {f['value']}" + (f" ({f['date']})" if f["date"] else "") for f in facts)
    if lang == "fr":
        return (f"Fiche « {w['title']} »" + (f" — {w['description']}" if w["description"] else "") + f". Résumé "
                f"Wikipédia : {extract}" + (f"\nFaits Wikidata : {lines}." if lines else "") + "\nUne fiche est "
                "affichée sous ta réponse (résumé, image, faits, sources) : réponds en 2 ou 3 phrases à partir de ces "
                f"éléments seulement, sans tout recopier. Source à citer : [{n_src}].")  # fmt: skip
    return (f"Entry '{w['title']}'" + (f" — {w['description']}" if w["description"] else "") + f". Wikipedia "
            f"summary: {extract}" + (f"\nWikidata facts: {lines}." if lines else "") + "\nA card is shown under your "
            "answer (summary, picture, facts, sources): answer in 2 or 3 sentences from these facts only, without "
            f"copying everything. Source to cite: [{n_src}].")  # fmt: skip
