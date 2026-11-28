"""find_tenders: French public tenders from the BOAMP (DILA open data, Opendatasoft API v2.1, Licence Ouverte 2.0).

« Appels d'offres en nettoyage de locaux publiés cette semaine », « marchés publics informatique dans le 59 »:
open calls for tenders (avis de marché) whose subject matches the keywords, newest first, with the buyer, the
département, the publication date, the reply deadline and a link to the official notice on boamp.fr.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from birds.harness.guard import ToolError

from . import http
from .places_fr import DEPARTMENTS, where

RECORDS = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
PAGE = "https://www.boamp.fr/"
LICENSE = {"label": "Licence Ouverte 2.0", "url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"}
SELECT = ("idweb,objet,nomacheteur,code_departement,dateparution,datelimitereponse,nature_libelle,type_marche,"
          "procedure_libelle,url_avis")  # fmt: skip
LIMIT = 8


# words buyers do not write in a notice's subject: the word they write instead
SYNONYMS = {"btp": "travaux", "it": "informatique", "ménage": "nettoyage", "menage": "nettoyage"}


def _keywords(q: str) -> str:
    """Plain search words only: quotes, backslashes and query operators are removed (no ODSQL injection)."""
    q = re.sub(r"[\"\\()=<>]", " ", str(q or ""))
    words = [SYNONYMS.get(w.lower(), w) for w in q.split() if not re.fullmatch(r"(?i:and|or|not|in|like|et|ou)", w)]
    return " ".join(words)[:80]


def find_tenders(args: dict, ctx) -> str:
    lang = http.lang_of(ctx)
    today = getattr(ctx, "today", None) or date.today()
    kw = _keywords(args.get("query"))
    if len(kw) < 3:
        raise ToolError("query is empty: ask the user what kind of contract to look for")
    label, deps = where(str(args.get("where") or ""))
    if args.get("where") and not deps:
        code = str(args["where"]).strip().upper().zfill(2)
        if code in DEPARTMENTS:
            label, deps = f"{DEPARTMENTS[code]} ({code})", [code]
    days = args.get("days")
    days = 30 if days in (None, "") else max(1, min(365, int(float(days))))
    since = today - timedelta(days=days)
    clauses = [f'search(objet,"{kw}")', 'nature="APPEL_OFFRE"', f"dateparution>=date'{since.isoformat()}'"]
    if deps:
        clauses.append("(" + " or ".join(f'code_departement="{d}"' for d in deps) + ")")
    u = http.url(RECORDS, {"select": SELECT, "where": " and ".join(clauses), "order_by": "dateparution desc",
                           "limit": LIMIT})  # fmt: skip
    data = http.get(ctx, u)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ToolError("the BOAMP returned no list")
    items = []
    for r in data["results"]:
        if not isinstance(r, dict) or not r.get("objet"):
            continue
        link = str(r.get("url_avis") or "")
        if not link.startswith("https://www.boamp.fr/"):
            link = (
                f"https://www.boamp.fr/pages/avis/?q=idweb:{http.clean(r.get('idweb'), 20)}" if r.get("idweb") else ""
            )
        deadline = str(r.get("datelimitereponse") or "")[:16]
        items.append({
            "id": http.clean(r.get("idweb"), 20), "title": http.clean(r.get("objet"), 220),
            "buyer": http.clean(r.get("nomacheteur"), 120),
            "deps": [str(d)[:3] for d in (r.get("code_departement") or []) if d][:4],
            "published": str(r.get("dateparution") or "")[:10], "deadline": deadline,
            "kind": ", ".join(http.clean(t, 20) for t in (r.get("type_marche") or [])[:2]),
            "procedure": http.clean(r.get("procedure_libelle"), 60), "url": http.link(link),
        })  # fmt: skip
    total = int(data.get("total_count") or len(items))
    w = {"type": "tenders", "v": 1, "query": kw, "where": label, "days": days, "since": since.isoformat(),
         "total": total, "items": items, "source": {"label": "BOAMP / DILA", "url": PAGE}, "license": LICENSE}  # fmt: skip
    ctx.step_info = {"widget": w, "label": "BOAMP", "found": len(items)}
    n = http.cite(ctx, PAGE)
    scope_fr = f" ({label})" if label else ""
    if not items:
        return (f"Aucun appel d'offres BOAMP publié depuis le {since.isoformat()} pour « {kw} »{scope_fr}. Dis-le et "
                "propose d'élargir la période ou les mots-clés ; n'en invente aucun." if lang == "fr" else
                f"No BOAMP call for tenders published since {since.isoformat()} for '{kw}'{scope_fr}. Say so and offer "
                "to widen the period or the keywords; invent none.")  # fmt: skip
    lines = "; ".join(f"{i['title']} — {i['buyer']} ({', '.join(i['deps'])}), publié le {i['published']}"
                      + (f", réponse avant le {i['deadline'][:10]}" if i["deadline"] else "") for i in items[:5])  # fmt: skip
    if lang == "fr":
        return (f"{total} appel(s) d'offres BOAMP pour « {kw} »{scope_fr} publiés depuis le {since.isoformat()} ; les "
                f"plus récents : {lines}. La liste avec les liens officiels est affichée sous ta réponse : résume en 1 "
                f"ou 2 phrases, sans recopier la liste. Source à citer : [{n}].")  # fmt: skip
    return (f"{total} BOAMP call(s) for tenders for '{kw}'{scope_fr} published since {since.isoformat()}; newest: "
            f"{lines}. The list with official links is shown under your answer: sum up in 1 or 2 sentences, without "
            f"copying the list. Source to cite: [{n}].")  # fmt: skip
