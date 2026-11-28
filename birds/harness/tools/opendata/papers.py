"""find_papers: scholarly works from OpenAlex (CC0), and DOI checks / searches on Crossref (metadata, free reuse).

« Articles récents sur les batteries sodium-ion », « les publications les plus citées sur l'hydrogène vert »:
OpenAlex works with authors, year, venue, citation count and an open-access link. « Vérifie ce DOI 10.1038/… »:
Crossref says whether the DOI exists and what it points to, so a reference is checked, never made up.
An optional OpenAlex key (``OPENALEX_API_KEY``, server-side only) raises the daily budget.
"""

from __future__ import annotations

import os
import re
from datetime import date
from urllib.parse import quote

from birds.harness.guard import ToolError

from . import http

OPENALEX = "https://api.openalex.org/works"
OPENALEX_PAGE = "https://openalex.org/"
CROSSREF = "https://api.crossref.org/works"
CROSSREF_PAGE = "https://www.crossref.org/"
CC0 = {"label": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0/deed.fr"}
CROSSREF_LICENSE = {"label": "Métadonnées libres (Crossref)", "label_en": "Open metadata (Crossref)",
                    "url": "https://www.crossref.org/documentation/retrieve-metadata/rest-api/"}  # fmt: skip
DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;:)\]])", re.I)
N = 6
POOL = 25


def _openalex_item(r: dict) -> dict | None:
    title = http.clean(r.get("display_name") or r.get("title"), 240)
    if not title:
        return None
    auths = [http.clean((a.get("author") or {}).get("display_name"), 60) for a in (r.get("authorships") or [])]
    auths = [a for a in auths if a]
    loc = r.get("primary_location") or {}
    venue = http.clean((loc.get("source") or {}).get("display_name"), 120)
    oa = r.get("open_access") or {}
    doi = str(r.get("doi") or "").replace("https://doi.org/", "")
    oa_url = str(oa.get("oa_url") or "")
    return {
        "title": title, "authors": auths[:3], "more": max(0, len(auths) - 3), "year": r.get("publication_year"),
        "venue": venue, "cites": int(r.get("cited_by_count") or 0), "doi": doi[:200],
        "url": f"https://doi.org/{quote(doi, safe='/:().;-_')}" if doi else str(r.get("id") or ""),
        "oa": bool(oa.get("is_oa")), "oa_url": oa_url if oa_url.startswith("https://") else "",
        "kind": http.clean(r.get("type"), 30),
    }  # fmt: skip


def _crossref_item(m: dict) -> dict | None:
    title = http.clean(" ".join(m.get("title") or []), 240)
    if not title:
        return None
    auths = [http.clean(" ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name"), 60)
             for a in (m.get("author") or [])]  # fmt: skip
    auths = [a for a in auths if a]
    parts = ((m.get("issued") or m.get("published") or {}).get("date-parts") or [[None]])[0]
    doi = str(m.get("DOI") or "")
    return {
        "title": title, "authors": auths[:3], "more": max(0, len(auths) - 3),
        "year": parts[0] if parts and isinstance(parts[0], int) else None,
        "venue": http.clean(" ".join(m.get("container-title") or []), 120) or http.clean(m.get("publisher"), 120),
        "publisher": http.clean(m.get("publisher"), 120), "cites": int(m.get("is-referenced-by-count") or 0),
        "doi": doi[:200], "url": f"https://doi.org/{quote(doi, safe='/:().;-_')}" if doi else "", "oa": False,
        "oa_url": "", "kind": http.clean(m.get("type"), 30),
    }  # fmt: skip


def find_papers(args: dict, ctx) -> str:
    lang = http.lang_of(ctx)
    today = getattr(ctx, "today", None) or date.today()
    q = " ".join(str(args.get("query") or "").split())[:200]
    order = str(args.get("order") or "relevance").lower()
    order = order if order in ("relevance", "cited", "recent") else "relevance"
    via = str(args.get("source") or "").lower()
    if len(q) < 3:
        raise ToolError("query is empty: ask the user what topic or DOI to look up")
    doi = DOI.search(q)
    if doi:
        return _doi(ctx, doi.group(1), lang)
    if via == "crossref":
        params = {"query": q, "rows": N, "select": "DOI,title,author,container-title,issued,is-referenced-by-count,"
                  "publisher,type"}  # fmt: skip
        if order == "recent":
            params |= {"sort": "published", "order": "desc"}
        elif order == "cited":
            params |= {"sort": "is-referenced-by-count", "order": "desc"}
        data = http.get(ctx, http.url(CROSSREF, params))
        msg = (data or {}).get("message") if isinstance(data, dict) else None
        items, seen = [], set()
        for i in (_crossref_item(x) for x in ((msg or {}).get("items") or [])):
            if i and i["title"].lower() not in seen:  # a book's chapters share its title: once
                seen.add(i["title"].lower())
                items.append(i)
        total = int((msg or {}).get("total-results") or len(items))
        src, lic, page = "Crossref", CROSSREF_LICENSE, CROSSREF_PAGE
    else:
        params = {"search": q, "per_page": N, "select": "id,doi,display_name,publication_year,cited_by_count,"
                  "authorships,primary_location,open_access,type"}  # fmt: skip
        if order == "cited":  # OpenAlex's own citation sort drops relevance: the most cited of the most relevant
            params["per_page"] = POOL
        elif order == "recent":
            params["filter"] = f"from_publication_date:{today.year - 3}-01-01"
        key = os.environ.get("OPENALEX_API_KEY", "").strip()
        if key and re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            params["api_key"] = key
        data = http.get(ctx, http.url(OPENALEX, params))
        items = [i for i in (_openalex_item(x) for x in ((data or {}).get("results") or [])) if i]
        if order == "cited":
            items = sorted(items, key=lambda i: -i["cites"])[:N]
        total = int(((data or {}).get("meta") or {}).get("count") or len(items))
        src, lic, page = "OpenAlex", CC0, OPENALEX_PAGE
    w = {"type": "papers", "v": 1, "mode": "search", "query": q, "order": order, "total": total, "items": items,
         "pool": POOL if order == "cited" and src == "OpenAlex" else 0,
         "source": {"label": src, "url": page},
         "license": {"label": lic.get("label_en" if lang == "en" and "label_en" in lic else "label"),
                     "url": lic["url"]}}  # fmt: skip
    ctx.step_info = {"widget": w, "label": src, "found": len(items)}
    n = http.cite(ctx, page)
    if not items:
        return (f"Aucune publication trouvée sur {src} pour « {q} ». Dis-le ; n'invente aucune référence."
                if lang == "fr" else f"No work found on {src} for '{q}'. Say so; invent no reference.")  # fmt: skip
    lines = "; ".join(f"« {i['title']} » ({', '.join(i['authors'][:2])}{' et al.' if i['more'] or len(i['authors']) > 2 else ''}, "
                      f"{i['year'] or '?'}, {i['cites']} citations)" for i in items[:5])  # fmt: skip
    if lang == "fr":
        return (f"{total} publications sur {src} pour « {q} » ; les premières : {lines}. La liste (avec DOI et liens en "
                "accès ouvert) est affichée sous ta réponse : présente-la en 1 à 3 phrases, cite uniquement ces "
                f"références, n'en invente aucune. Source à citer : [{n}].")  # fmt: skip
    return (f"{total} works on {src} for '{q}'; first ones: {lines}. The list (with DOIs and open-access links) is "
            "shown under your answer: present it in 1 to 3 sentences, cite only these references, invent none. "
            f"Source to cite: [{n}].")  # fmt: skip


def _doi(ctx, doi: str, lang: str) -> str:
    try:
        data = http.get(ctx, f"{CROSSREF}/{quote(doi, safe='/:().;-_')}")
        item = _crossref_item((data or {}).get("message") or {}) if isinstance(data, dict) else None
    except ToolError as e:
        if str(e) != "HTTP 404":
            raise
        item = None
    w = {"type": "papers", "v": 1, "mode": "doi", "query": doi, "found": bool(item), "items": [item] if item else [],
         "total": 1 if item else 0, "source": {"label": "Crossref", "url": CROSSREF_PAGE},
         "license": {"label": CROSSREF_LICENSE["label_en" if lang == "en" else "label"],
                     "url": CROSSREF_LICENSE["url"]}}  # fmt: skip
    ctx.step_info = {"widget": w, "label": "Crossref", "found": 1 if item else 0}
    n = http.cite(ctx, CROSSREF_PAGE)
    if not item:
        return (f"Le DOI {doi} est inconnu de Crossref : il n'existe pas ou est mal recopié. Dis-le clairement ; ne "
                "propose aucune référence de remplacement inventée." if lang == "fr" else
                f"DOI {doi} is unknown to Crossref: it does not exist or is mistyped. Say so; invent no replacement.")  # fmt: skip
    a = ", ".join(item["authors"]) + (" et al." if item["more"] else "")
    if lang == "fr":
        return (f"DOI {doi} vérifié chez Crossref : « {item['title']} », {a}, {item['venue']}, {item['year']} "
                f"({item['kind']}, {item['publisher']}). Une fiche est affichée sous ta réponse : confirme la référence "
                f"en une ou deux phrases. Source à citer : [{n}].")  # fmt: skip
    return (f"DOI {doi} checked on Crossref: '{item['title']}', {a}, {item['venue']}, {item['year']} ({item['kind']}, "
            f"{item['publisher']}). A card is shown under your answer: confirm the reference in one or two sentences. "
            f"Source to cite: [{n}].")  # fmt: skip
