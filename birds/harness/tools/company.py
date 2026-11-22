"""find_company: the official French company register (recherche-entreprises.api.gouv.fr, Etalab 2.0).

Privacy rules, enforced here: a sole trader (entrepreneur individuel) is a natural person, so no street address,
no map and no finances are shown; a non-public record ("statut_diffusion" != "O") shows nothing but the official
link; company directors are never listed by name (a link to the official page instead).
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from birds.harness import geo, intents
from birds.harness.guard import ToolError

LEGAL_FORMS = {
    "1000": "Entrepreneur individuel",
    "5202": "Société en nom collectif",
    "5306": "Société en commandite simple",
    "5308": "Société en commandite par actions",
    "5410": "SARL nationale",
    "5485": "Société d'exercice libéral à responsabilité limitée",
    "5498": "EURL",
    "5499": "SARL",
    "5505": "SA à participation ouvrière",
    "5510": "SA à conseil d'administration",
    "5599": "SA à conseil d'administration",
    "5699": "SA à directoire",
    "5710": "SAS",
    "5720": "SASU",
    "5785": "Société d'exercice libéral par actions simplifiée",
    "6220": "GIE",
    "6540": "SCI",
    "6589": "Société civile de moyens",
    "6599": "Société civile",
    "9210": "Association non déclarée",
    "9220": "Association déclarée",
    "9300": "Fondation",
}
STAFF = {
    "NN": "",
    "00": "0 salarié",
    "01": "1 ou 2 salariés",
    "02": "3 à 5 salariés",
    "03": "6 à 9 salariés",
    "11": "10 à 19 salariés",
    "12": "20 à 49 salariés",
    "21": "50 à 99 salariés",
    "22": "100 à 199 salariés",
    "31": "200 à 249 salariés",
    "32": "250 à 499 salariés",
    "41": "500 à 999 salariés",
    "42": "1 000 à 1 999 salariés",
    "51": "2 000 à 4 999 salariés",
    "52": "5 000 à 9 999 salariés",
    "53": "10 000 salariés et plus",
}
STAFF_EN = {
    "00": "0 employees", "01": "1-2 employees", "02": "3-5 employees", "03": "6-9 employees",
    "11": "10-19 employees", "12": "20-49 employees", "21": "50-99 employees", "22": "100-199 employees",
    "31": "200-249 employees", "32": "250-499 employees", "41": "500-999 employees", "42": "1,000-1,999 employees",
    "51": "2,000-4,999 employees", "52": "5,000-9,999 employees", "53": "10,000+ employees",
}  # fmt: skip
OFFICIAL = "https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"


def legal_form(code: str) -> str:
    code = str(code or "")
    if code in LEGAL_FORMS:
        return LEGAL_FORMS[code]
    if code.startswith("7"):
        return "Personne morale de droit public"
    return code


def _fmt_siren(s: str) -> str:
    return " ".join(s[i : i + 3] for i in range(0, 9, 3)) if len(s) == 9 else s


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _payload(r: dict, lang: str) -> dict:
    siren = str(r.get("siren") or "")
    siege = r.get("siege") or {}
    comp = r.get("complements") or {}
    natural = str(r.get("nature_juridique")) == "1000" or bool(comp.get("est_entrepreneur_individuel"))
    public = str(r.get("statut_diffusion") or "O") == "O"
    src = {"label": "Annuaire des entreprises (data.gouv.fr)", "url": OFFICIAL.format(siren=siren)}
    base = {
        "type": "company",
        "v": 1,
        "name": str(r.get("nom_complet") or "")[:160],
        "siren": siren,
        "source": src,
        "natural_person": natural,
        "public": public,
    }
    if not public:
        return {**base, "name": "", "map": None}
    staff_code = str(r.get("tranche_effectif_salarie") or "")
    out = {
        **base,
        "sigle": str(r.get("sigle") or "")[:40],
        "siret": "" if natural else str(siege.get("siret") or ""),
        "legal_form": legal_form(r.get("nature_juridique")),
        "naf": str(r.get("activite_principale") or ""),
        "staff": (STAFF_EN if lang == "en" else STAFF).get(staff_code, ""),
        "created": str(r.get("date_creation") or ""),
        "status": "closed" if str(r.get("etat_administratif")) == "C" else "active",
        "closed_on": str(r.get("date_fermeture") or ""),
        "address": "",
        "commune": str(siege.get("libelle_commune") or "")[:80],
        "lat": None,
        "lon": None,
        "finances": None,
        "directors_url": OFFICIAL.format(siren=siren) + "#dirigeants" if siren else "",
    }
    if not natural:
        out["address"] = " ".join(str(siege.get("adresse") or "").split())[:200]
        lat, lon = _num(siege.get("latitude")), _num(siege.get("longitude"))
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            out["lat"], out["lon"] = round(lat, 6), round(lon, 6)
        fin = r.get("finances") or {}
        if isinstance(fin, dict) and fin:
            year = max(fin)
            row = fin.get(year) or {}
            if row.get("ca") is not None or row.get("resultat_net") is not None:
                out["finances"] = {
                    "year": str(year),
                    "revenue": _num(row.get("ca")),
                    "net_income": _num(row.get("resultat_net")),
                }
    return out


def _eur(v: float, fr: bool) -> str:
    s = f"{v:,.0f} €"
    return s.replace(",", "\u202f") if fr else s


def _text(p: dict, lang: str, n_src: int) -> str:
    fr = lang == "fr"
    if not p.get("public", True):
        return (
            "Fiche non diffusible : l'entreprise a demandé que ses informations ne soient pas publiées. "
            f"Lien officiel : {p['source']['url']} [{n_src}]"
            if fr
            else f"Non-public record: the company asked for its data not to be published. Official page: "
            f"{p['source']['url']} [{n_src}]"
        )
    rows = [
        (("Nom", "Name"), p["name"] + (f" ({p['sigle']})" if p.get("sigle") else "")),
        (("SIREN", "SIREN"), _fmt_siren(p["siren"])),
        (("Forme juridique", "Legal form"), p.get("legal_form")),
        (("Activité (code NAF)", "Activity (NAF code)"), p.get("naf")),
        (("Effectif", "Staff"), p.get("staff")),
        (("Création", "Created"), p.get("created")),
        (
            ("État", "Status"),
            ("active" if p["status"] == "active" else f"cessée le {p.get('closed_on')}")
            if fr
            else ("active" if p["status"] == "active" else f"closed on {p.get('closed_on')}"),
        ),
        (("Siège", "Head office"), p.get("address") or p.get("commune")),
    ]
    if p.get("finances"):
        f = p["finances"]
        if f.get("revenue") is not None:
            rows.append(((f"Chiffre d'affaires {f['year']}", f"Revenue {f['year']}"), _eur(f['revenue'], fr)))
        if f.get("net_income") is not None:
            rows.append(((f"Résultat net {f['year']}", f"Net income {f['year']}"), _eur(f['net_income'], fr)))
    lines = [f"{k[0] if fr else k[1]} : {v}" for k, v in rows if v]
    lines.append(f"Source : {p['source']['url']} [{n_src}]")
    lines.append(
        "Une fiche est affichée à l'utilisateur sous ta réponse ; n'invente aucun autre chiffre ni dirigeant."
        if fr
        else "A card is shown to the user under your answer; do not invent other figures or directors."
    )
    return "\n".join(lines)


def find_company(args: dict, ctx) -> str:
    lang = ctx.lang if ctx.lang in ("fr", "en") else "fr"
    name = " ".join(str(args.get("name") or "").split())[:100]
    if not name:
        raise ToolError("name is empty")
    digits = re.sub(r"[\s. ]", "", name)
    q = digits if re.fullmatch(r"\d{9}|\d{14}", digits) else name
    base = ctx.config.company_url
    url = base + ("&" if "?" in base else "?") + urlencode({"q": q, "per_page": 3, "page": 1})
    try:
        data = geo.get_json(ctx, url, cache_ttl=86400, count=False)
    except ToolError:
        geo.POLICY.cache.pop(geo.Policy.key("get", url), None)
        data = geo.get_json(ctx, url, cache_ttl=86400, count=False)  # one retry: the register's tunnel is flaky
    results = [r for r in (data.get("results") or []) if isinstance(r, dict)] if isinstance(data, dict) else []
    if q.isdigit():
        results = [r for r in results if str(r.get("siren")) == q[:9]] or results[:1]
    if not results:
        ctx.step_info = {"found": 0}
        return (
            f"Aucune entreprise trouvée pour « {name} » dans l'annuaire officiel. Dis-le ; n'invente rien."
            if lang == "fr"
            else f"No company found for '{name}' in the official register. Say so; invent nothing."
        )
    best = _payload(results[0], lang)
    candidates = []
    if not q.isdigit() and len(results) > 1:
        top = intents.normalise(name).lower()
        same = [r for r in results if intents.normalise(str(r.get("nom_complet") or "")).lower() == top]
        if len(same) > 1:
            candidates = [
                {
                    "name": str(r.get("nom_complet") or "")[:120],
                    "siren": str(r.get("siren") or ""),
                    "commune": str((r.get("siege") or {}).get("libelle_commune") or "")[:60],
                    "url": OFFICIAL.format(siren=r.get("siren")),
                }
                for r in same[:3]
            ]
    best["candidates"] = candidates
    src = best["source"]["url"]
    if src not in ctx.sources:
        ctx.sources.append(src)
    n_src = ctx.sources.index(src) + 1
    ctx.step_info = {"widget": best, "found": len(results), "label": "Annuaire des entreprises"}
    text = _text(best, lang, n_src)
    if candidates:
        others = "; ".join(f"{c['name']} (SIREN {_fmt_siren(c['siren'])}, {c['commune']})" for c in candidates)
        text += (
            "\nPlusieurs entreprises portent ce nom : " + others + ". La première est affichée ; demande à "
            "l'utilisateur laquelle il veut."
            if lang == "fr"
            else "\nSeveral companies have this name: "
            + others
            + ". The first is shown; ask the user which one they mean."
        )
    return text
