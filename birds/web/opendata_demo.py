"""The scripted demo's answer under an open-data card (birds/web/backends.py, scenario_opendata).

Written from the card's own fields (tool results recorded by scripts/opendata_live.py --demo), never invented: the
live model writes its own sentence from the same tool result. A card the recording does not hold gets a calm
« not in the demo data » answer, never a made-up figure.
"""

from __future__ import annotations

MONTHS_FR = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()
MONTHS_EN = "January February March April May June July August September October November December".split()


def _t(lang: str, fr: str, en: str) -> str:
    return en if lang == "en" else fr


def _num(x, lang: str, digits: int = 1) -> str:
    if x is None:
        return "—"
    s = f"{x:,.{digits}f}" if isinstance(x, float) and not float(x).is_integer() else f"{int(x):,}"
    return s.replace(",", " ").replace(".", ",") if lang == "fr" else s


def _day(iso: str, lang: str) -> str:
    y, m, d = (int(x) for x in str(iso)[:10].split("-"))
    return f"{d} {MONTHS_FR[m - 1]} {y}" if lang == "fr" else f"{MONTHS_EN[m - 1]} {d}, {y}"


def answer(tool: str, widgets: list[dict], charts: list[dict], info: dict, lang: str) -> tuple[str, dict]:
    """(answer text with its [1] citation, {source url: title})."""
    q = next((x for x in widgets if x.get("type") == "quote"), None)
    if tool == "get_quote" and q is not None:  # markets (tools/opendata/finance.py)
        return _quote(q, lang), {s["url"]: s["label"] for s in q.get("sources") or [] if s.get("url")}
    w = next((x for x in widgets if x.get("type") in ("calendar", "entity", "tenders", "papers", "commune")), None)
    if tool == "get_statistics" and charts:
        return _stats(charts[0], lang)
    if w is None:
        return (_t(lang, "Ces données ne font pas partie de l'enregistrement de démonstration. Avec le vrai modèle, "
                   "Bird interroge la source officielle en direct et affiche sa fiche, source et licence comprises.",
                   "This data is not part of the demo recording. With the real model, Bird queries the official "
                   "source live and shows its card, with source and licence."), {})  # fmt: skip
    src = w.get("source") or {}
    titles = {src.get("url", ""): src.get("label", "")} if src.get("url") else {}
    return {"calendar": _calendar, "entity": _entity, "tenders": _tenders, "papers": _papers,
            "commune": _commune}[w["type"]](w, lang), titles  # fmt: skip


def _calendar(w: dict, lang: str) -> str:
    zone = (w.get("zone") or {}).get("label", "")
    hol = w.get("holidays") or []
    c = w.get("counts") or {}
    if w.get("mode") == "month":
        m = int(w["month"])
        month = f"{MONTHS_FR[m - 1]} {w['year']}" if lang == "fr" else f"{MONTHS_EN[m - 1]} {w['year']}"
        names = ", ".join(f"**{h['name']}** ({_day(h['d'], lang)})" for h in hol)
        return _t(
            lang,
            f"En {month} ({zone}), on compte **{c.get('workdays')} jours ouvrés** et {c.get('workable')} jours "
            f"ouvrables [1]. Jours fériés du mois : {names or 'aucun'}.",
            f"{month} ({zone}) has **{c.get('workdays')} working days** [1]. Public holidays this month: "
            f"{names or 'none'}.",
        )
    if w.get("mode") == "year":
        firsts = ", ".join(f"{h['name']} ({_day(h['d'], lang)})" for h in hol[:3])
        return _t(
            lang,
            f"**{len(hol)} jours fériés** en {w['year']} ({zone}), pour {c.get('workdays')} jours ouvrés dans l'année "
            f"[1]. Les premiers : {firsts}. La liste complète est dans la fiche.",
            f"**{len(hol)} public holidays** in {w['year']} ({zone}), for {c.get('workdays')} working days in the "
            f"year [1]. The first ones: {firsts}. The full list is in the card.",
        )
    if w.get("mode") == "deadline" and w.get("deadline"):
        d = w["deadline"]
        return _t(lang, f"{d['days']} jours ouvrés après le {_day(d['start'], lang)} : **{_day(d['end'], lang)}** [1].",
                  f"{d['days']} working days after {_day(d['start'], lang)}: **{_day(d['end'], lang)}** [1].")  # fmt: skip
    d = w.get("day") or {}
    return _t(lang, f"Le {_day(d.get('d', ''), lang)} : {('férié, ' + d['holiday']) if d.get('holiday') else 'pas un jour férié'} [1].",
              f"{_day(d.get('d', ''), lang)}: {('a public holiday, ' + d['holiday']) if d.get('holiday') else 'not a public holiday'} [1].")  # fmt: skip


def _entity(w: dict, lang: str) -> str:
    lead = f"**{w.get('title')}**" + (f", {w['description']}" if w.get("description") else "")
    return _t(lang, f"{lead} [1]. La fiche reprend l'extrait de Wikipédia et les données clés de Wikidata.",
              f"{lead} [1]. The card shows the Wikipedia extract and the key facts from Wikidata.")  # fmt: skip


def _tenders(w: dict, lang: str) -> str:
    items = w.get("items") or []
    if not items:
        return _t(lang, f"Aucun avis « {w.get('query')} » publié sur le BOAMP sur la période [1].",
                  f"No notice for “{w.get('query')}” published on the BOAMP in this period [1].")  # fmt: skip
    first = items[0]
    dl = f", réponse avant le {_day(first['deadline'], lang)}" if first.get("deadline") and lang == "fr" else (
        f", answers due {_day(first['deadline'], lang)}" if first.get("deadline") else "")  # fmt: skip
    return _t(
        lang,
        f"**{w.get('total')} avis** « {w.get('query')} » publiés sur le BOAMP depuis le {_day(w['since'], lang)} [1]. "
        f"Le plus récent : {first['title']} ({first.get('buyer') or 'acheteur non précisé'}{dl}).",
        f"**{w.get('total')} notices** for “{w.get('query')}” on the BOAMP since {_day(w['since'], lang)} [1]. "
        f"The latest: {first['title']} ({first.get('buyer') or 'buyer not given'}{dl}).",
    )


def _papers(w: dict, lang: str) -> str:
    items = w.get("items") or []
    if w.get("mode") == "doi":
        if not items:
            return _t(lang, f"Crossref ne connaît pas le DOI {w.get('query')} [1].",
                      f"Crossref does not know the DOI {w.get('query')} [1].")  # fmt: skip
        i = items[0]
        return _t(lang, f"DOI vérifié : **{i['title']}** ({', '.join(i.get('authors') or [])}, {i.get('venue')}, "
                        f"{i.get('year')}) [1].",
                  f"DOI checked: **{i['title']}** ({', '.join(i.get('authors') or [])}, {i.get('venue')}, "
                  f"{i.get('year')}) [1].")  # fmt: skip
    if not items:
        return _t(lang, "Aucune publication trouvée [1].", "No work found [1].")
    top = items[0]
    return _t(
        lang,
        f"{len(items)} publications sur « {w.get('query')} » [1]. En tête : **{top['title']}** ({top.get('year')}, "
        f"{_num(top.get('cites', 0), lang)} citations).",
        f"{len(items)} works on “{w.get('query')}” [1]. First: **{top['title']}** ({top.get('year')}, "
        f"{_num(top.get('cites', 0), lang)} citations).",
    )


def _commune(w: dict, lang: str) -> str:
    if w.get("mode") == "address" and w.get("address"):
        a = w["address"]
        return _t(lang, f"Adresse normalisée : **{a['line1']}, {a['line2']}** [1].",
                  f"Normalised address: **{a['line1']}, {a['line2']}** [1].")  # fmt: skip
    rows = w.get("communes") or []
    if not rows:
        return _t(lang, "Aucune commune de ce nom [1].", "No commune by that name [1].")
    c = rows[0]
    pc = ", ".join(c.get("postcodes") or [])
    return _t(
        lang,
        f"**{c['name']}** ({(c.get('dept') or {}).get('name', '')}) : code postal {pc}, code Insee {c['code']}, "
        f"{_num(c.get('population'), lang)} habitants [1].",
        f"**{c['name']}** ({(c.get('dept') or {}).get('name', '')}): postcode {pc}, INSEE code {c['code']}, "
        f"population {_num(c.get('population'), lang)} [1].",
    )


def _stats(spec: dict, lang: str) -> tuple[str, dict]:
    src = spec.get("data_source") or {}
    rows, cols = spec.get("rows") or [], spec.get("columns") or []
    parts = []
    for j, name in enumerate(cols[1:], 1):
        vals = [(r[0], r[j]) for r in rows if j < len(r) and r[j] is not None]
        if vals:
            parts.append(_t(lang, f"{name} : {_num(vals[0][1], lang)} en {vals[0][0]}, {_num(vals[-1][1], lang)} en {vals[-1][0]}",
                            f"{name}: {_num(vals[0][1], lang)} in {vals[0][0]}, {_num(vals[-1][1], lang)} in {vals[-1][0]}"))  # fmt: skip
    unit = f" ({spec['unit']})" if spec.get("unit") else ""
    text = _t(lang, f"**{spec.get('title')}**{unit}, d'après {src.get('label', 'la source officielle')} [1]. "
                    + " ; ".join(parts) + ".",
              f"**{spec.get('title')}**{unit}, from {src.get('label', 'the official source')} [1]. "
              + "; ".join(parts) + ".")  # fmt: skip
    return text, ({src["url"]: src.get("label", "")} if src.get("url") else {})


def _quote(w: dict, lang: str) -> str:
    """One sentence per line of the quote card, its figures and its date (the live model writes its own)."""
    from birds.harness.tools.opendata.finance import RANGE_WORDS, asof_text, fmt

    parts = []
    for i in w.get("items") or []:
        cur = f" {i['currency']}" if i.get("kind") != "fx" else ""
        pct = i.get("change_pct") or 0
        sign = "+" if pct > 0 else ""
        pp = i.get("period_pct") or 0
        rw = RANGE_WORDS["en" if lang == "en" else "fr"].get(w.get("range"), "")
        parts.append(_t(
            lang,
            f"**{i['name']}** : {fmt(i['last'], lang)}{cur} ({asof_text(i, lang)}), {sign}{fmt(pct, lang, 2)} % "
            f"{_base(i, 'fr')}, "
            f"{'+' if pp > 0 else ''}{fmt(pp, lang, 2)} % sur {rw} [1].",
            f"**{i['name']}**: {fmt(i['last'], lang)}{cur} ({asof_text(i, lang)}), {sign}{fmt(pct, lang, 2)} % "
            f"{_base(i, 'en')}, "
            f"{'+' if pp > 0 else ''}{fmt(pp, lang, 2)} % over {rw} [1].",
        ))  # fmt: skip
    if w.get("compare"):
        parts.append(_t(lang, "Le graphique compare les lignes en base 100.", "The chart compares the lines rebased "
                        "to 100."))  # fmt: skip
    return " ".join(parts)


def _base(i: dict, lang: str) -> str:
    fr, en = {"24h": ("sur 24 h", "over 24 h"), "prev_ref": ("depuis le taux précédent", "from the previous rate")}.get(
        i.get("change_base"), ("depuis la clôture précédente", "from the previous close"))
    return en if lang == "en" else fr
