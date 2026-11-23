"""The plan the model wrote, expanded by the harness before it is drawn.

The model gives a title and slides (title + bullets) or sections (heading + Markdown). From that alone the harness
reads what each slide really is: a series of figures (a chart), comparable items (a table), dated steps (a
timeline), a quotation, two sides compared; it adds an agenda, a sources slide and a closing slide, and it places
the pictures it has (the user's, free-licence web pictures, a map) where their words match. Nothing here invents a
fact: every word and figure drawn comes from the plan, the request, the sources read or the pictures' own credits.
"""

from __future__ import annotations

import re

from birds.harness.office_media import Media, words

SOURCES_TITLE = re.compile(r"^\s*(?:sources?|r[ée]f[ée]rences?|bibliograph\w*|cr[ée]dits?(?: photos?)?)\s*:?\s*$", re.I)
AGENDA_TITLE = re.compile(
    r"^\s*(?:sommaire|agenda|plan|ordre du jour|au programme|programme|table des mati[eè]res|contents|outline|"
    r"overview)\s*:?\s*$",
    re.I,
)
CLOSING_TITLE = re.compile(r"^\s*(?:merci|thanks?\b|thank you|questions?\b|des questions|q ?& ?a|contact)", re.I)
TEXT = {
    "agenda": {"fr": "Sommaire", "en": "Agenda"},
    "closing": {"fr": "Merci", "en": "Thank you"},
    "closing_sub": {"fr": "Questions et échanges", "en": "Questions and discussion"},
    "sources": {"fr": "Sources", "en": "Sources"},
    "credits": {"fr": "Crédits des images", "en": "Image credits"},
    "map": {"fr": "Localisation", "en": "Location"},
    "photos": {"fr": "En images", "en": "In pictures"},
    "photo": {"fr": "Photo", "en": "Photo"},
    "chart_src": {"fr": "Source des données", "en": "Data source"},
}


def tr(key: str, lang: str) -> str:
    return TEXT[key]["en" if lang == "en" else "fr"]


# ------------------------------------------------------------------ figures as numbers

_NUM = re.compile(r"([+\-−]?\d{1,3}(?:[\s  ]\d{3})+(?:[.,]\d+)?|[+\-−]?\d+(?:[.,]\d+)?)")
_UNIT = re.compile(
    r"\s?(%|M€|K€|k€|Md€|Mds€|€|M\$|\$|£|millions?|milliards?|k\b|M\b|Md\b|pts?\b|points?\b|h\b|heures?\b|jours?\b|"
    r"clients?\b|salari[ée]s?\b|employ[ée]s?\b|personnes?\b|visiteurs?\b|ventes?\b|unit[ée]s?\b|tonnes?\b|t\b|kg\b|"
    r"km\b|m²|m2\b|MW\b|GW\b|kWh\b|MWh\b|GWh\b|TWh\b|users?\b|utilisateurs?\b)",
    re.I,
)
_TIME = re.compile(
    r"^(?:(?:19|20)\d{2}|[TQS][1-4](?:\s?(?:19|20)\d{2})?|(?:janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|"
    r"d[ée]c|jan|feb|mar|apr|may|jun|jul|aug|sep)\w*\.?(?:\s(?:19|20)?\d{2})?|(?:semaine|week|mois|month|ann[ée]e|year)"
    r"\s?\d{1,2}|[ée]t[ée]|hiver|printemps|automne|summer|winter|spring|autumn)(?:\s(?:19|20)\d{2})?$",
    re.I,
)


def number(text: str) -> float | None:
    t = re.sub(r"[\s  ]", "", text).replace("−", "-")
    if re.fullmatch(r"[+-]?\d+,\d+", t):
        t = t.replace(",", ".")
    elif re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _plain(text: str) -> str:
    from birds.harness.office import plain

    return re.sub(r"\s*\[\d{1,2}\]\s*", " ", plain(str(text))).strip()


_PAIR = re.compile(r"^\s*(?P<label>[^:–—=]{1,40}?)\s*(?::|–|—|=|\s-\s)\s*(?P<rest>.+)$")


def series_of(title: str, bullets: list[str]) -> dict | None:
    """A chart spec when the bullets are one series of figures in one unit ('2023 : 1,1 M€', '2024 : 1,4 M€'...),
    with what is left (one or two sentences) as the key takeaway; else None."""
    pts, rest, units = [], [], []
    for raw in bullets:
        text = _plain(raw)
        m = _PAIR.match(text)
        if not m:
            rest.append(raw)
            continue
        label, value = m.group("label").strip(), m.group("rest").strip()
        nm = _NUM.match(value)
        if not nm or re.match(r"(?:19|20)\d{2}\b", value) and not _UNIT.match(value[nm.end() :]):
            rest.append(raw)
            continue
        unit = _UNIT.match(value[nm.end() :])
        tail = value[nm.end() + (len(unit.group(0)) if unit else 0) :].strip(" .;,")
        if len(tail) > 40 or re.match(r"^(?:à|a|to|-|–)\s*\d", tail):  # a sentence or a range, not a data point
            rest.append(raw)
            continue
        v = number(nm.group(1))
        if v is None:
            rest.append(raw)
            continue
        pts.append((label[:30], v, tail))
        units.append((unit.group(1) if unit else "").lower())
    if len(pts) < 3 or len(rest) > 2 or len(set(units)) != 1 or len({p[0].lower() for p in pts}) != len(pts):
        return None
    unit = next((u for u in (_UNIT.match(" " + x) for x in units) if u), None)
    unit_txt = ""
    if units[0]:
        # the unit as the user wrote it (case kept)
        for raw in bullets:
            um = re.search(r"\d\s?(" + re.escape(units[0]) + r")", _plain(raw), re.I)
            if um:
                unit_txt = um.group(1)
                break
    del unit
    timeish = all(_TIME.match(p[0].strip()) for p in pts)
    share = unit_txt == "%" and 95 <= sum(p[1] for p in pts) <= 105 and not timeish
    kind = "line" if timeish and len(pts) >= 4 else "pie" if share and len(pts) <= 6 else "bar"
    head = re.sub(r"\s*\(\d+/\d+\)$", "", _plain(title))[:80]
    return {
        "title": head,
        "type": kind,
        "columns": ["", unit_txt or head[:30]],
        "rows": [[p[0], p[1]] for p in pts],
        "unit": unit_txt,
        "takeaway": [str(r) for r in rest],
    }


def table_of(bullets: list[str]) -> list[list[str]] | None:
    """Rows (header first) when the bullets are comparable items: a Markdown table written in the bullets, or
    'Item : label value, label value' with the same labels in the same order for every item."""
    texts = [str(b).strip() for b in bullets if str(b).strip()]
    if len(texts) >= 2 and all(t.count("|") >= 1 for t in texts):
        rows = [[c.strip() for c in t.strip().strip("|").split("|")] for t in texts]
        rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c) for c in r if c)]
        if len({len(r) for r in rows}) == 1 and len(rows[0]) >= 2 and len(rows) >= 2:
            return rows
    if not 2 <= len(texts) <= 10:
        return None
    items = []
    for t in texts:
        m = _PAIR.match(_plain(t))
        if not m:
            return None
        parts = [p.strip(" .") for p in re.split(r";|,(?!\d)|\s·\s|\s/\s", m.group("rest")) if p.strip(" .")]
        if len(parts) < 2:
            return None
        cells = []
        for p in parts:
            pm = (re.match(r"^(?P<k>[^\d:]{2,30}?)\s*:\s*(?P<v>.{1,40})$", p)
                  or re.match(r"^(?P<k>[^\d:]{2,30}?)\s+(?P<v>[+\-−<>≤≥~]?\s?\d.{0,30})$", p)
                  or re.match(r"^(?P<k>[^\d\s:]{2,20})\s+(?P<v>[^\d:]{1,30})$", p))  # fmt: skip
            if not pm:
                return None
            cells.append((pm.group("k").strip().lower(), pm.group("v").strip(), pm.group("k").strip()))
        items.append((m.group("label").strip(), cells))
    keys = [[c[0] for c in cells] for _, cells in items]
    if any(k != keys[0] for k in keys) or len(set(keys[0])) != len(keys[0]):
        return None
    if not any(re.search(r"\d", c[1]) for _, cells in items for c in cells):
        return None  # 'Avantage : rapide, simple' is prose, not a table of figures
    header = [""] + [c[2][:1].upper() + c[2][1:] for c in items[0][1]]
    return [header] + [[label] + [c[1] for c in cells] for label, cells in items]


_DATE_HEAD = re.compile(
    r"^\s*(?P<d>(?:(?:janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[ée]c|jan|feb|mar|apr|may|jun|jul|aug|"
    r"sep)\w*\.?\s(?:19|20)\d{2}|(?:[TQS][1-4]|H[12])\s?(?:19|20)\d{2}|(?:19|20)\d{2}(?:\s?[-–]\s?(?:19|20)?\d{2})?|"
    r"(?:janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[ée]c)\w*\.?|\d{1,2}/\d{1,2}(?:/\d{2,4})?|"
    r"(?:semaine|week|mois|month|jour|day|J|M)\s?[+-]?\d{1,3}))\s*(?::|–|—|-)\s*(?P<t>.+)$",
    re.I,
)


def timeline_of(bullets: list[str]) -> list[tuple[str, str]] | None:
    """[(date, text)] when 3 to 6 bullets each start with a date, a quarter or a year ('T1 2026 : pilote')."""
    if not 3 <= len(bullets) <= 6:
        return None
    out = []
    for b in bullets:
        m = _DATE_HEAD.match(_plain(b))
        if not m or len(m.group("t")) > 150:
            return None
        out.append((m.group("d").strip(), m.group("t").strip()))
    return out


_QUOTE = re.compile(r"^\s*[«“\"]\s*(?P<q>.{15,320}?)\s*[»”\"]\s*(?:[—–-]\s*(?P<a>.{2,80}))?\s*$", re.S)


def quote_of(bullets: list[str]) -> tuple[str, str] | None:
    """(quotation, author) for a slide that is one quotation, its author optional on a second line."""
    if not 1 <= len(bullets) <= 2:
        return None
    m = _QUOTE.match(_plain(bullets[0]))
    if not m:
        return None
    author = (m.group("a") or "").strip()
    if len(bullets) == 2:
        second = _plain(bullets[1]).strip()
        if author or not re.match(r"^[—–-]\s*\S", second) or len(second) > 80:
            return None
        author = second.lstrip("—–- ").strip()
    return m.group("q").strip(), author


_VS = re.compile(r"\bvs\.?\b|\bversus\b|\bcompar\w*|\bavant\b.*\bapr[eè]s\b|\bbefore\b.*\bafter\b|\bpour\b.*\bcontre\b|"
                 r"\bpros?\b.*\bcons?\b|\bavantages\b.*\binconv[ée]nients\b", re.I)  # fmt: skip


def compare_of(title: str, bullets: list[str]) -> tuple[str, list[str], str, list[str]] | None:
    """Two sides: every bullet is 'Side : point' with exactly two sides, each with 1 to 5 points."""
    if not 2 <= len(bullets) <= 10:
        return None
    sides: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for b in bullets:
        m = _PAIR.match(_plain(b))
        if not m or len(m.group("label")) > 30:
            return None
        key = m.group("label").strip().lower()
        names.setdefault(key, m.group("label").strip())
        sides.setdefault(key, []).append(m.group("rest").strip())
    if len(sides) != 2 or not all(1 <= len(v) <= 5 for v in sides.values()):
        return None
    if not _VS.search(title) and min(len(v) for v in sides.values()) < 2:
        return None
    (a, pa), (b, pb) = list(sides.items())
    return names[a], pa, names[b], pb


# ------------------------------------------------------------------ deck expansion


def _match(m: Media, text: str) -> int:
    return len(words(" ".join([m.alt, m.title])) & words(text))


def _named(m: Media, text: str) -> bool:
    """The slide names the picture by its file name ('photo-chantier.jpg', 'logo')."""
    name = (m.title or "").lower()
    return bool(name) and name in str(text).lower()


def expand_deck(title: str, slides: list[dict], media: list[Media], lang: str = "fr", sources: list | None = None,
                options: dict | None = None) -> tuple[list[dict], dict]:  # fmt: skip
    """(slides, deck) — slides as dicts with an optional 'layout' and its payload; deck: {'cover': Media|None,
    'logo': Media|None, 'agenda': bool, 'closing': bool, 'added': [names of what the harness added]}.

    ``options`` (the editor's choices) may carry 'cover' (a media id or 'none'), 'agenda' / 'closing' (bool)."""
    from birds.harness.office import render_kind

    options = options or {}
    by_id = {m.id: m for m in media}
    logo = next((m for m in media if m.logo), None)
    pictures = [m for m in media if not m.logo and m.kind in ("user", "web", "map")]
    charts = [m for m in media if m.kind == "chart"]
    used: set[str] = set()
    out: list[dict] = []
    added: list[str] = []
    for raw in slides:
        s = {k: v for k, v in raw.items() if k in ("title", "bullets", "notes", "image", "layout", "side", "chart")}
        s["title"] = str(s.get("title") or "")
        s["bullets"] = [str(b) for b in (s.get("bullets") or []) if str(b).strip()]
        bullets, t = s["bullets"], s["title"]
        img = s.pop("image", None)
        if isinstance(img, str) and img in by_id:
            s["image"] = by_id[img]
            used.add(img)
        elif img == "none":
            s["no_image"] = True
        for m in pictures:  # a bullet that only names an attached picture places it here
            hit = next((b for b in bullets if _named(m, b) and len(_plain(b)) <= len(m.title) + 20), None)
            if hit and "image" not in s:
                s["image"], s["bullets"] = m, [b for b in bullets if b is not hit]
                used.add(m.id)
                bullets = s["bullets"]
        lay = s.get("layout")
        chart = s.pop("chart", None)
        if isinstance(chart, str) and chart in by_id:
            s["layout"], s["chart"] = "chart", by_id[chart].spec
            used.add(chart)
        elif lay in (None, "", "auto"):
            s.pop("layout", None)
            if SOURCES_TITLE.match(t):
                s["layout"] = "sources"
            elif bullets and (q := quote_of(bullets)):
                s["layout"], s["quote"] = "quote", q
            elif bullets and (spec := series_of(t, bullets)):
                s["layout"], s["chart"] = "chart", spec
            elif bullets and (tl := timeline_of(bullets)):
                s["layout"], s["timeline"] = "timeline", tl
            elif bullets and (rows := table_of(bullets)):
                s["layout"], s["table"] = "table", rows
            elif bullets and (cmp := compare_of(t, bullets)):
                s["layout"], s["compare"] = "compare", cmp
            elif not bullets and AGENDA_TITLE.match(t):
                s["layout"] = "agenda_slot"  # the model's empty agenda slide: filled below
        out.append(s)

    # charts the run drew (make_chart): on the slide that speaks of them, else a slide of their own
    for m in charts:
        if m.id in used:
            continue
        best = max(range(len(out)), key=lambda i: _match(m, out[i]["title"] + " " + " ".join(out[i]["bullets"])),
                   default=None)  # fmt: skip
        if best is not None and _match(m, out[best]["title"]) >= 1 and not out[best].get("layout") \
                and len(out[best]["bullets"]) <= 3:  # fmt: skip
            out[best].update(layout="chart", chart={**m.spec, "takeaway": out[best]["bullets"]})
        else:
            at = (best + 1) if best is not None and _match(m, out[best]["title"]) else len(out)
            out.insert(at, {"title": m.title or m.alt, "bullets": [], "layout": "chart",
                            "chart": {**m.spec, "takeaway": []}})  # fmt: skip
            added.append("chart")
        used.add(m.id)

    sections = [s for s in out if not s["bullets"] and not s.get("layout")]
    # where pictures go: the cover first (a user photo, else a web picture that matches the deck's title)
    cover = None
    if options.get("cover") in by_id:
        cover = by_id[options["cover"]]
    elif options.get("cover") != "none":
        unplaced = [m for m in pictures if m.id not in used and m.kind != "map"]
        cover = next((m for m in unplaced if m.kind == "user"), None) or next(
            (m for m in unplaced if m.kind == "web" and _match(m, title) >= 1), None
        )
    if cover is not None:
        used.add(cover.id)
    eligible = [
        i for i, s in enumerate(out)
        if s["bullets"] and not s.get("layout") and not s.get("no_image") and "image" not in s
        and len(s["bullets"]) <= 5 and sum(len(_plain(b)) for b in s["bullets"]) <= 460
        and render_kind(s["bullets"]) in ("list", "rows", "cards", "statement", "columns")
    ]  # fmt: skip
    for m in [m for m in pictures if m.id not in used]:
        if m.kind == "map":
            continue
        if not eligible:
            break
        scored = sorted(eligible, key=lambda i: -_match(m, out[i]["title"] + " " + " ".join(out[i]["bullets"])))
        best = scored[0]
        if m.kind == "web" and _match(m, out[best]["title"] + " " + " ".join(out[best]["bullets"])) < 1:
            continue  # a web picture goes only where its words are
        if m.kind == "user" and not _match(m, out[best]["title"] + " " + " ".join(out[best]["bullets"])):
            # the user's photos carry no words ('IMG_2034'): spread them evenly over the deck
            k = len([x for x in out if isinstance(x.get("image"), Media)])
            best = eligible[min(len(eligible) - 1, (k * 2 + 1) * len(eligible) // max(2, 2 * len(pictures)))]
        out[best]["image"] = m
        used.add(m.id)
        eligible.remove(best)
    # a map: on the slide about the place, else its own slide before the end
    for m in [m for m in pictures if m.kind == "map" and m.id not in used]:
        about = next((i for i, s in enumerate(out) if "image" not in s and not s.get("layout") and s["bullets"]
                      and re.search(r"acc[eè]s|adresse|localisation|implantation|o[uù] nous|plan d'acc|lieu|site|"
                                    r"location|address|venue|map\b|carte", s["title"], re.I)), None)  # fmt: skip
        if about is not None and len(out[about]["bullets"]) <= 5:
            out[about]["image"] = m
        else:
            out.append({"title": m.title or tr("map", lang), "bullets": [], "image": m, "layout": "image"})
            added.append("map")
        used.add(m.id)
    left = [m for m in pictures if m.id not in used and m.kind == "user"]
    if len(left) >= 2:  # more photos than slides for them: a picture grid
        out.append({"title": tr("photos", lang), "bullets": [], "layout": "grid", "grid": left[:4]})
        used.update(m.id for m in left[:4])
        added.append("grid")
    elif len(left) == 1:
        out.append({"title": left[0].alt if len(words(left[0].alt)) >= 2 else tr("photos", lang), "bullets": [],
                    "layout": "image", "image": left[0]})  # fmt: skip
        used.add(left[0].id)
        added.append("image")
    for s in out:
        if isinstance(s.get("image"), Media) and not s.get("layout"):
            s["layout"] = "image" if not s["bullets"] else "image_side"
    flip = 0
    for s in out:  # image right, then left, then right...
        if s.get("layout") == "image_side":
            s.setdefault("side", "right" if flip % 2 == 0 else "left")
            flip += 1

    # sources: the deck's own Sources slide, or one from the sources read; picture credits go on it
    srcs = [s for s in out if s.get("layout") == "sources"]
    lines = []
    for src in sources or []:
        if isinstance(src, dict) and src.get("url"):
            lines.append(f"[{src.get('n') or len(lines) + 1}] {str(src.get('title') or '').strip() or src['url']} — "
                         f"{src['url']}")  # fmt: skip
        elif isinstance(src, str) and src.strip():
            lines.append(src.strip())
    credits = []
    for m in [x for x in media if x.id in used and x.kind in ("web", "map")] + (
        [cover] if cover and cover.kind == "web" and cover.id not in used else []
    ):
        line = f"{m.title or m.alt} : {m.credit}" + (f" — {m.source}" if m.source else "")
        if line not in credits:
            credits.append(line)
    if lines and not srcs:
        out.append({"title": tr("sources", lang), "bullets": lines, "layout": "sources"})
        srcs = [out[-1]]
        added.append("sources")
    if credits:
        if srcs:
            srcs[-1]["credits"] = credits
        else:
            out.append({"title": tr("credits", lang), "bullets": [], "layout": "sources", "credits": credits})
            added.append("credits")
    # agenda (4+ content slides) and closing slide (4+ content slides, the model wrote none)
    n_content = len([s for s in out if s.get("layout") not in ("sources", "agenda_slot")
                     and (s["bullets"] or s.get("layout"))])  # fmt: skip
    want_agenda = options.get("agenda", n_content >= 4)
    slot = next((i for i, s in enumerate(out) if s.get("layout") == "agenda_slot"), None)
    if want_agenda:
        if len(sections) >= 2:
            items = [s["title"] for s in sections]
        else:
            items, seen = [], set()
            for s in out:
                base = re.sub(r"\s*\(\d+/\d+\)$", "", s["title"]).strip()
                if s.get("layout") in ("sources", "agenda_slot") or CLOSING_TITLE.match(base) or not base:
                    continue
                if base.lower() not in seen:
                    seen.add(base.lower())
                    items.append(base)
        if 3 <= len(items) <= 12:
            agenda = {"title": tr("agenda", lang), "bullets": [], "layout": "agenda", "agenda": items}
            if slot is not None:
                out[slot] = {**agenda, "title": out[slot]["title"] or agenda["title"]}
            else:
                out.insert(0, agenda)
                added.append("agenda")
    out = [s for s in out if s.get("layout") != "agenda_slot"]
    last = out[-1] if out else None
    closing = options.get("closing", n_content >= 4)
    if last is not None and not last["bullets"] and not last.get("layout") and CLOSING_TITLE.match(last["title"]):
        last["layout"] = "closing"
    elif closing:
        out.append({"title": tr("closing", lang), "bullets": [], "layout": "closing",
                    "subtitle": tr("closing_sub", lang)})  # fmt: skip
        added.append("closing")
    return out, {"cover": cover, "logo": logo, "added": added}


# ------------------------------------------------------------------ document expansion


def expand_doc(title: str, sections: list[dict], media: list[Media], lang: str = "fr", sources: list | None = None,
               options: dict | None = None) -> tuple[list[dict], dict]:  # fmt: skip
    """(sections, doc): each section may get 'figures' (Media, placed after its text); the doc gets 'cover' and
    'logo', 'toc' (bool) and the sources and picture credits appended as a last section when none exists."""
    options = options or {}
    by_id = {m.id: m for m in media}
    logo = next((m for m in media if m.logo), None)
    pictures = [m for m in media if not m.logo]
    used: set[str] = set()
    out = []
    for raw in sections:
        s = {"heading": str(raw.get("heading") or ""), "content": str(raw.get("content") or "")}
        figs = raw.get("figures")
        if isinstance(figs, list):
            s["figures"] = [by_id[f] for f in figs if isinstance(f, str) and f in by_id]
            used.update(m.id for m in s["figures"])
            s["fixed"] = True
        out.append(s)
    cover = None
    if options.get("cover") in by_id:
        cover = by_id[options["cover"]]
        used.add(cover.id)
    body = [s for s in out if not SOURCES_TITLE.match(s["heading"])]
    for m in [m for m in pictures if m.id not in used]:
        if not body:
            break
        text = [s["heading"] + " " + s["content"] for s in body]
        best = max(range(len(body)), key=lambda i: (_match(m, text[i]) + (3 if _named(m, text[i]) else 0), -i))
        score = _match(m, text[best]) + (3 if _named(m, text[best]) else 0)
        if m.kind == "web" and score < 1:
            continue
        if m.kind in ("user", "map") and score < 1:
            free = [s for s in body if not s.get("figures") and not s.get("fixed")]
            target = free[0] if free else body[-1]
        else:
            target = body[best]
        if target.get("fixed"):
            continue
        target.setdefault("figures", []).append(m)
        used.add(m.id)
    srcs = next((s for s in out if SOURCES_TITLE.match(s["heading"])), None)
    lines = []
    for src in sources or []:
        if isinstance(src, dict) and src.get("url"):
            lines.append(f"[{src.get('n') or len(lines) + 1}] {str(src.get('title') or '').strip() or src['url']} — "
                         f"{src['url']}")  # fmt: skip
    credits = []
    for m in [x for x in media if x.id in used and x.kind in ("web", "map")]:
        line = f"{m.title or m.alt} : {m.credit}" + (f" — {m.source}" if m.source else "")
        if line not in credits:
            credits.append(line)
    added = []
    if lines and srcs is None:
        srcs = {"heading": tr("sources", lang), "content": "\n".join(lines)}
        out.append(srcs)
        added.append("sources")
    if credits:
        text = "\n".join(f"- {c}" for c in credits)
        if srcs is None:
            out.append({"heading": tr("credits", lang), "content": text})
            added.append("credits")
        else:
            srcs["content"] = srcs["content"].rstrip() + f"\n\n### {tr('credits', lang)}\n" + text
    long = sum(len(s["content"]) for s in out) > 5000
    toc = options.get("toc", len([s for s in out if s["heading"]]) >= 4 or long)
    return out, {"cover": cover, "logo": logo, "toc": bool(toc), "added": added}
