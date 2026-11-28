"""find_commune: French communes (geo.api.gouv.fr, DINUM) and address normalisation (Base Adresse Nationale on the
IGN Géoplateforme geocoder), both Licence Ouverte 2.0.

« Code postal et population de Roubaix »: a commune card (INSEE code, postal codes, population, département,
région). « Quelles communes s'appellent Saint-Martin ? »: every commune of that exact name. « Normalise cette
adresse : 8 bd du port amiens »: the address as the BAN writes it, with its match score; a low score is said.
"""

from __future__ import annotations

import re

from birds.harness.guard import ToolError

from . import http
from .countries import fold

COMMUNES = "https://geo.api.gouv.fr/communes"
BAN = "https://data.geopf.fr/geocodage/search"
GEO_PAGE = "https://geo.api.gouv.fr/decoupage-administratif/communes"
BAN_PAGE = "https://adresse.data.gouv.fr/"
LICENSE = {"label": "Licence Ouverte 2.0", "url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"}
FIELDS = "nom,code,codesPostaux,population,surface,centre,departement,region"
MIN_SCORE = 0.5  # below: the BAN guessed; the card says so and the model must not present it as the address
_ADDRESS = re.compile(r"^\s*\d{1,4}\s*(?:bis|ter|[a-d])?\b|\b(?:rue|avenue|av\.?|bd|boulevard|place|chemin|impasse|all[ée]e|"
                      r"quai|route|cours|square|voie|lieu-dit|faubourg)\b", re.I)  # fmt: skip


def looks_like_address(q: str) -> bool:
    return bool(_ADDRESS.search(q or "")) and bool(re.search(r"[a-zA-Zà-ÿ]{3,}", q or ""))


def _commune(c: dict) -> dict | None:
    if not isinstance(c, dict) or not re.fullmatch(r"[0-9AB]{5}", str(c.get("code", ""))):
        return None
    centre = (c.get("centre") or {}).get("coordinates") or [None, None]
    dep, reg = c.get("departement") or {}, c.get("region") or {}
    pop = c.get("population")
    return {
        "name": http.clean(c.get("nom"), 80), "code": str(c["code"]),
        "postcodes": [str(p) for p in (c.get("codesPostaux") or []) if re.fullmatch(r"\d{5}", str(p))][:12],
        "population": int(pop) if isinstance(pop, (int, float)) else None,
        "surface_km2": round(float(c["surface"]) / 100, 1) if isinstance(c.get("surface"), (int, float)) else None,
        "dept": {"code": str(dep.get("code", ""))[:3], "name": http.clean(dep.get("nom"), 60)},
        "region": {"code": str(reg.get("code", ""))[:3], "name": http.clean(reg.get("nom"), 60)},
        "lat": round(float(centre[1]), 5) if isinstance(centre[1], (int, float)) else None,
        "lon": round(float(centre[0]), 5) if isinstance(centre[0], (int, float)) else None,
    }  # fmt: skip


def search_communes(ctx, name: str, limit: int = 12) -> list[dict]:
    data = http.get(ctx, http.url(COMMUNES, {"nom": name, "fields": FIELDS, "boost": "population", "limit": limit}))
    return [c for c in (_commune(x) for x in (data if isinstance(data, list) else [])) if c]


def commune_by_code(ctx, code: str) -> dict | None:
    if not re.fullmatch(r"[0-9AB]{5}", code or ""):
        return None
    try:
        data = http.get(ctx, http.url(f"{COMMUNES}/{code}", {"fields": FIELDS}))
    except ToolError as e:
        if str(e) == "HTTP 404":
            return None
        raise
    return _commune(data)


def best_commune(ctx, name: str) -> dict | None:
    """The commune a name most likely means: an exact name first (the most populated), else the first answer."""
    found = search_communes(ctx, name, 8)
    exact = [c for c in found if fold(c["name"]) == fold(name)]
    pool = exact or found
    return max(pool, key=lambda c: c["population"] or 0) if pool else None


def find_commune(args: dict, ctx) -> str:
    lang = http.lang_of(ctx)
    q = " ".join(str(args.get("name") or "").split())[:160]
    if len(q) < 2:
        raise ToolError("name is empty: ask the user which commune or address")
    if looks_like_address(q):
        return _address(ctx, q, lang)
    found = search_communes(ctx, q, 20)
    exact = [c for c in found if fold(c["name"]) == fold(q)]
    if not found:
        ctx.step_info = {"found": 0}
        return (f"Aucune commune française nommée « {q} ». Dis-le ; n'invente rien." if lang == "fr"
                else f"No French commune named '{q}'. Say so; invent nothing.")  # fmt: skip
    rows = sorted(exact, key=lambda c: -(c["population"] or 0)) if exact else found[:1]
    mode = "homonyms" if len(exact) > 1 else "commune"
    w = {"type": "commune", "v": 1, "mode": mode, "query": q, "total": len(rows), "communes": rows[:12],
         "source": {"label": "geo.api.gouv.fr", "url": GEO_PAGE}, "license": LICENSE}  # fmt: skip
    n = http.cite(ctx, GEO_PAGE)
    ctx.step_info = {"widget": w, "label": "geo.api.gouv.fr", "found": len(rows)}

    def line(c):
        pop = f"{c['population']:,}".replace(",", " ") if c["population"] is not None else "?"
        return (f"{c['name']} ({c['dept']['name']}, {c['dept']['code']}) : code INSEE {c['code']}, code(s) postal(aux) "
                f"{', '.join(c['postcodes']) or '?'}, {pop} habitants" if lang == "fr" else
                f"{c['name']} ({c['dept']['name']}, {c['dept']['code']}): INSEE code {c['code']}, postcode(s) "
                f"{', '.join(c['postcodes']) or '?'}, population {pop}")  # fmt: skip

    body = "; ".join(line(c) for c in rows[:8])
    if lang == "fr":
        head = f"{len(rows)} communes s'appellent « {q} »" if mode == "homonyms" else "Commune trouvée"
        return (f"{head} (geo.api.gouv.fr) : {body}. Une fiche commune est affichée sous ta réponse : réponds en 1 ou 2 "
                f"phrases avec ces chiffres exacts. Source à citer : [{n}].")  # fmt: skip
    head = f"{len(rows)} communes are named '{q}'" if mode == "homonyms" else "Commune found"
    return (f"{head} (geo.api.gouv.fr): {body}. A commune card is shown under your answer: answer in 1 or 2 sentences "
            f"with these exact figures. Source to cite: [{n}].")  # fmt: skip


def _address(ctx, q: str, lang: str) -> str:
    data = http.get(ctx, http.url(BAN, {"q": q, "limit": 1, "index": "address"}))
    feats = (data or {}).get("features") if isinstance(data, dict) else None
    f = feats[0] if isinstance(feats, list) and feats else None
    props = (f or {}).get("properties") or {}
    if not props.get("label"):
        ctx.step_info = {"found": 0}
        return (f"La Base Adresse Nationale ne reconnaît pas « {q} ». Dis-le et demande l'adresse complète ; n'en "
                "invente aucune." if lang == "fr" else
                f"The national address base does not recognise '{q}'. Say so and ask for the full address.")  # fmt: skip
    score = float(props.get("score") or 0)
    coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
    street = http.clean(props.get("name"), 120)
    addr = {
        "label": http.clean(props.get("label"), 160), "line1": street,
        "line2": f"{props.get('postcode', '')} {http.clean(props.get('city'), 80)}".strip(),
        "postcode": str(props.get("postcode") or "")[:5], "city": http.clean(props.get("city"), 80),
        "citycode": str(props.get("citycode") or "")[:5], "score": round(score, 2), "sure": score >= MIN_SCORE,
        "kind": str(props.get("type") or "")[:20], "context": http.clean(props.get("context"), 120),
        "lat": round(float(coords[1]), 6) if isinstance(coords[1], (int, float)) else None,
        "lon": round(float(coords[0]), 6) if isinstance(coords[0], (int, float)) else None,
    }  # fmt: skip
    try:
        com = commune_by_code(ctx, addr["citycode"])
    except ToolError:
        com = None
    w = {"type": "commune", "v": 1, "mode": "address", "query": q, "address": addr, "communes": [com] if com else [],
         "total": 1, "source": {"label": "Base Adresse Nationale (IGN Géoplateforme)", "url": BAN_PAGE},
         "license": LICENSE}  # fmt: skip
    n = http.cite(ctx, BAN_PAGE)
    ctx.step_info = {"widget": w, "label": "BAN", "found": 1}
    unsure_fr = "" if addr["sure"] else " Correspondance faible : présente-la comme une suggestion à vérifier."
    unsure_en = "" if addr["sure"] else " Weak match: present it as a suggestion to check."
    if lang == "fr":
        return (f"Adresse normalisée (Base Adresse Nationale, score {addr['score']:.2f}) : {addr['line1']}, "
                f"{addr['line2']} ; code INSEE {addr['citycode']} ; {addr['context']}.{unsure_fr} Une fiche est "
                f"affichée sous ta réponse : donne l'adresse telle quelle en une phrase. Source à citer : [{n}].")  # fmt: skip
    return (f"Normalised address (national address base, score {addr['score']:.2f}): {addr['line1']}, {addr['line2']}; "
            f"INSEE code {addr['citycode']}; {addr['context']}.{unsure_en} A card is shown under your answer: give the "
            f"address as is in one sentence. Source to cite: [{n}].")  # fmt: skip
