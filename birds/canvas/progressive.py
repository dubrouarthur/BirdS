"""Progressive decks and documents: the model plans, the harness gathers, the model writes slide by slide, the
harness checks (docs/CANVAS.md § 11).

    plan    ONE generation, structured output validated here: audience, key message, 6-12 slides (4-8 sections),
            for each its intent, layout, the visual it needs (picture query, chart from which data, key figures,
            table, timeline…) and the facts it needs
    gather  Faucon / Chouette only, in parallel, within a budget: web search + one page read per slide that needs
            facts (sources kept), official series for a chart (get_statistics: Eurostat, World Bank, INSEE), and
            for every level the free-licence picture search (Openverse, Commons: licence checked, birds.canvas.images)
    write   one short generation per slide or section, given ITS facts and visual; each one appears in the canvas
            as soon as it is written (the outline first, then the slides filling in, pictures and charts arriving)
    check   in code: every figure written must be in the request, the facts or a chart's data (else the point is
            dropped), no wall of text, a slide left empty is filled from its facts, a picture that was not found
            becomes a DESIGNED placeholder (``missing``: « Image à ajouter » in the canvas, never text), sources
            numbered in reading order

Colibri / Hirondelle: plan + pictures + write (no web, no statistics). Faucon / Chouette (and Albatros outside the
team): the whole pipeline. Progress is sent as calm lines (``canvas_progress``): « Plan : 8 diapositives »,
« 5 images trouvées », « 2 graphiques à partir d'Eurostat ».

The widgets come from tool results only: a chart is the series get_statistics returned, a picture is the file the
search found and re-encoded, a source is a page that was read. The model writes text and chooses; the harness
fetches, places and verifies. When the plan cannot be read, the caller falls back on the single-generation path.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import dsl, images

FLAG = "BIRD_CANVAS_PROGRESSIVE"  # "0": off (the single-generation path, measured as « before »)
FULL_LEVELS = ("faucon", "chouette", "albatros")
VISUALS = ("image", "chart", "kpi", "table", "diagram", "timeline", "steps", "compare", "cards", "quote", "none")
DATA = ("none", "request", "web", "statistics")
INDICATORS = ("unemployment", "inflation", "gdp", "gdp_growth", "population", "birth_rate", "fertility", "electricity",
              "exports", "creations")  # the data engine's series (birds.harness.tools.opendata.stats.PRESETS)
LAYOUTS = tuple(x for x in dsl.LAYOUT_NAMES if x not in ("agenda", "closing", "code"))
BOUNDS = {"deck": (6, 12), "doc": (4, 8)}
PLAN_TOKENS = 1600
WRITE_TOKENS = {"deck": 460, "doc": 900}
WORKERS = 5
GATHER_SECONDS = 38.0  # web + statistics, all slides together (Faucon / Chouette)
MAX_READS = 6  # pages read in one deck (one per slide that needs facts, the first ones)
MAX_FACTS = 4  # facts given to one slide
FACT_CHARS = 240
MAX_POINTS = {"deck": 6, "doc": 8}
POINT_CHARS = 220

_CITE = re.compile(r"\[\^?(\d{1,2})\]")


def enabled() -> bool:
    return os.environ.get(FLAG, "1") != "0"


def depth_of(level: str | None) -> str:
    return "full" if level in FULL_LEVELS else "fast"


# ------------------------------------------------------------------ 1. the plan (structured output)


def schema(kind: str) -> dict:
    lo, hi = BOUNDS[kind]
    item = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 90},
            "intent": {"type": "string", "maxLength": 200},
            "layout": {"type": "string", "enum": list(LAYOUTS)},
            "visual": {"type": "string", "enum": list(VISUALS)},
            "image_query": {"type": "string", "maxLength": 60},
            "data": {"type": "string", "enum": list(DATA)},
            "indicator": {"type": "string", "enum": ["", *INDICATORS]},
            "places": {"type": "string", "maxLength": 80},
            "since": {"type": "string", "maxLength": 10},
            "search": {"type": "string", "maxLength": 120},
            "facts": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 4},
        },
        "required": ["title", "intent", "layout", "visual", "data"],
    }
    key = "slides" if kind == "deck" else "sections"
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 110},
            "subtitle": {"type": "string", "maxLength": 140},
            "audience": {"type": "string", "maxLength": 120},
            "message": {"type": "string", "maxLength": 240},
            "cover_image": {"type": "string", "maxLength": 60},
            key: {"type": "array", "items": item, "minItems": lo, "maxItems": hi},
        },
        "required": ["title", "audience", "message", key],
    }


PLAN = {
    "deck": {
        "fr": (
            "[Plan] Avant d'écrire la présentation demandée, écris son plan, en JSON uniquement :\n"
            '{{"title": "<titre>", "subtitle": "<sous-titre court>", "audience": "<le public>", '
            '"message": "<le message clé, une phrase>", "cover_image": "<2 à 4 mots en anglais>", '
            '"slides": [{{"title": "<titre de la diapositive>", "intent": "<ce qu\'elle doit faire comprendre>", '
            '"layout": "<{layouts}>", "visual": "<image|chart|kpi|table|diagram|timeline|steps|compare|cards|quote|none>", '
            '"image_query": "<ce qu\'on voit sur la photo, 2 à 5 mots en anglais, si visual=image>", "data": "<none|request|web|statistics>", '
            '"indicator": "<{indicators}, si data=statistics>", "places": "<pays ou villes, si data=statistics>", '
            '"since": "<année de début>", "search": "<requête web, si data=web>", '
            '"facts": ["<un fait de la demande à reprendre>"]}}]}}\n'
            "Règles : {lo} à {hi} diapositives, une idée chacune, dans un ordre qui raconte une histoire ; un "
            "visuel sur la plupart des diapositives, varié (image sur 2 à 4 diapositives, chiffres clés, frise, "
            "étapes, comparaison…) ; un graphique seulement à partir de vraies données : data=statistics pour une "
            "série officielle (chômage, inflation, PIB, croissance, population, prix de l'électricité, exportations, "
            "créations d'entreprises), data=request pour les chiffres donnés dans la demande ; data=web quand la "
            "diapositive a besoin de faits ou de chiffres précis ; aucun chiffre dans facts qui ne soit dans la "
            "demande. Une photo montre une chose réelle (un lieu, un objet, des gens) : jamais une statistique, une "
            "évolution ou un chiffre, qui sont un graphique (chart) ou des chiffres clés (kpi)."
        ),
        "en": (
            "[Plan] Before writing the requested deck, write its plan, in JSON only:\n"
            '{{"title": "<title>", "subtitle": "<short subtitle>", "audience": "<the audience>", '
            '"message": "<the key message, one sentence>", "cover_image": "<2 to 4 words>", '
            '"slides": [{{"title": "<slide title>", "intent": "<what it must get across>", '
            '"layout": "<{layouts}>", "visual": "<image|chart|kpi|table|diagram|timeline|steps|compare|cards|quote|none>", '
            '"image_query": "<what the photo shows, 2 to 5 words, if visual=image>", "data": "<none|request|web|statistics>", '
            '"indicator": "<{indicators}, if data=statistics>", "places": "<countries or towns, if '
            'data=statistics>", "since": "<start year>", "search": "<web query, if data=web>", '
            '"facts": ["<a fact of the request to use>"]}}]}}\n'
            "Rules: {lo} to {hi} slides, one idea each, in an order that tells a story; a visual on most slides, "
            "varied (a picture on 2 to 4 slides, key figures, timeline, steps, comparison…); a chart only from real "
            "data: data=statistics for an official series (unemployment, inflation, GDP, growth, population, "
            "electricity prices, exports, business start-ups), data=request for figures given in the request; "
            "data=web when the slide needs precise facts or figures; no figure in facts that is not in the request. A photo "
            "shows a real thing (a place, an object, people): never a statistic, a trend or a figure, which are a chart "
            "or key figures (kpi)."
        ),
    },
    "doc": {
        "fr": (
            "[Plan] Avant d'écrire le document demandé, écris son plan, en JSON uniquement :\n"
            '{{"title": "<titre>", "subtitle": "<sous-titre court>", "audience": "<le lecteur>", '
            '"message": "<ce que le lecteur doit retenir, une phrase>", '
            '"sections": [{{"title": "<titre de section>", "intent": "<ce qu\'elle doit établir>", '
            '"layout": "bullets", "visual": "<image|chart|kpi|table|diagram|timeline|steps|compare|none>", '
            '"image_query": "<ce qu\'on voit sur la photo, 2 à 5 mots en anglais, si visual=image>", "data": "<none|request|web|statistics>", '
            '"indicator": "<{indicators}, si data=statistics>", "places": "<pays ou villes>", '
            '"since": "<année de début>", "search": "<requête web, si data=web>", '
            '"facts": ["<un fait de la demande à reprendre>"]}}]}}\n'
            "Règles : {lo} à {hi} sections, d'abord celles que la demande nomme ; un tableau, un graphique ou une "
            "figure là où ils aident ; un graphique seulement à partir de vraies données (data=statistics : "
            "chômage, inflation, PIB, croissance, population, prix de l'électricité, exportations, créations "
            "d'entreprises ; data=request : les chiffres de la demande) ; data=web quand la section a besoin de "
            "faits précis ; aucun chiffre dans facts qui ne soit dans la demande ; une photo sur 1 ou 2 sections quand le "
            "sujet se montre (un lieu, un objet, une scène), jamais pour une statistique."
        ),
        "en": (
            "[Plan] Before writing the requested document, write its plan, in JSON only:\n"
            '{{"title": "<title>", "subtitle": "<short subtitle>", "audience": "<the reader>", '
            '"message": "<what the reader must remember, one sentence>", '
            '"sections": [{{"title": "<section title>", "intent": "<what it must establish>", '
            '"layout": "bullets", "visual": "<image|chart|kpi|table|diagram|timeline|steps|compare|none>", '
            '"image_query": "<what the photo shows, 2 to 5 words, if visual=image>", "data": "<none|request|web|statistics>", '
            '"indicator": "<{indicators}, if data=statistics>", "places": "<countries or towns>", '
            '"since": "<start year>", "search": "<web query, if data=web>", '
            '"facts": ["<a fact of the request to use>"]}}]}}\n'
            "Rules: {lo} to {hi} sections, the ones the request names first; a table, a chart or a figure where it "
            "helps; a chart only from real data (data=statistics: unemployment, inflation, GDP, growth, population, "
            "electricity prices, exports, business start-ups; data=request: the figures of the request); data=web "
            "when the section needs precise facts; no figure in facts that is not in the request; a photo on 1 or 2 "
            "sections when the subject can be shown (a place, an object, a scene), never for a statistic."
        ),
    },
}


def plan_message(words: str, kind: str, lang: str, depth: str = "full") -> str:
    lo, hi = BOUNDS[kind]
    if depth == "fast":
        hi = min(hi, lo + 2)
    lg = "en" if lang == "en" else "fr"
    return words + "\n\n" + PLAN[kind][lg].format(lo=lo, hi=hi, layouts="|".join(LAYOUTS),
                                                    indicators="|".join(INDICATORS))  # fmt: skip


@dataclass
class Item:
    title: str
    intent: str = ""
    layout: str = ""
    visual: str = "none"
    query: str = ""
    data: str = "none"
    indicator: str = ""
    places: str = ""
    since: str = ""
    search: str = ""
    facts: list[str] = field(default_factory=list)  # from the request only (checked)


@dataclass
class Outline:
    kind: str
    title: str
    subtitle: str = ""
    audience: str = ""
    message: str = ""
    cover: str = ""
    items: list[Item] = field(default_factory=list)


def _s(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n].strip()


def _json(raw: str):
    s = re.sub(r"^\s*<think>.*?</think>\s*", "", str(raw or ""), flags=re.S)
    s = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", s.strip())
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(s[a : b + 1])
    except ValueError:
        from birds.harness import crew_checks as cc

        try:
            return cc.json_repair(s[a : b + 1])
        except Exception:  # noqa: BLE001 - unreadable: None, the caller falls back
            return None


_ECHO = set("""uniquement seulement only if si none aucun aucune image images photo photos picture visual visuel anglais
english mots words requete query slide diapositive section une des les the and for with pour avec dans sur""".split())


def _picture_words(query: str) -> list[str]:
    """The words of a picture query that describe something (not an echo of the plan's instructions)."""
    from birds.harness import crew_checks as cc

    return [w for w in cc.fold(query).split() if len(w) >= 3 and w not in _ECHO and w not in images.FLUFF]


def _names_series(indicator: str, text: str) -> bool:
    from birds.harness.tools.opendata import stats

    return stats.indicator_of(text, loose=True) == indicator


def parse_outline(
    raw: str, kind: str, words: str, lang: str = "fr", repairs: list[str] | None = None
) -> Outline | None:
    """The plan the model wrote, validated: every field typed and capped, enums enforced, the counts bounded, the
    facts kept only when their figures are in the request. None when it is not a usable plan (fewer than 3 items)."""
    from birds.harness import crew_checks as cc

    repairs = repairs if repairs is not None else []
    obj = _json(raw)
    if not isinstance(obj, dict):
        return None
    rows = obj.get("slides") if isinstance(obj.get("slides"), list) else obj.get("sections")
    if not isinstance(rows, list):
        rows = next((v for v in obj.values() if isinstance(v, list) and v and isinstance(v[0], dict)), None)
    if not isinstance(rows, list):
        return None
    allowed = cc.allowed_figures(words)
    lo, hi = BOUNDS[kind]
    items: list[Item] = []
    seen: set[str] = set()
    used_queries: set[str] = set()
    used_series: set[tuple[str, str]] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        title = _s(r.get("title"), 90)
        key = cc.fold(title)
        if not title or key in seen:
            continue
        seen.add(key)
        visual = str(r.get("visual") or "none").lower()
        visual = visual if visual in VISUALS else "none"
        data = str(r.get("data") or "none").lower()
        data = data if data in DATA else "none"
        layout = dsl.layout_of(r.get("layout")) or ""
        layout = layout if layout in LAYOUTS else ""
        indicator = str(r.get("indicator") or "").lower()
        if indicator not in INDICATORS:
            from birds.harness.tools.opendata import stats

            indicator = stats.indicator_of(indicator, loose=True) if indicator else ""
            indicator = indicator if indicator in INDICATORS else ""
        series = (indicator, cc.fold(_s(r.get("places"), 80)))
        if data == "statistics" and indicator and series in used_series:
            data, indicator = "web", ""  # the same series twice: one chart, the other slide gets facts
            repairs.append(f"series repeated: {title[:30]}")
        if data == "statistics" and indicator:
            used_series.add(series)
        if data == "statistics" and not indicator:
            data = "web" if r.get("search") else "none"
            repairs.append(f"statistics without an indicator: {title[:30]}")
        elif data == "statistics" and not _names_series(indicator, f"{words} {title}"):
            # veto of a known false trigger: the only series at hand drawn off-subject (a population chart in a
            # deck on soft mobility); the slide gets facts from the web instead
            data, indicator = "web", ""
            repairs.append(f"series off-subject dropped: {title[:30]}")
        facts = []
        for f in r.get("facts") or []:
            f = _s(f, 200)
            if f and not cc.unsupported(f, allowed):
                facts.append(f)
            elif f:
                repairs.append("a planned fact with a figure not in the request dropped")
        if visual == "diagram":
            visual = "steps"  # a flow drawn by the canvas (steps); a timeline when the plan says so
        query = images.clean_query(_s(r.get("image_query"), 80))[:60]
        if (visual == "image" or layout.startswith("image")) and (
                not _picture_words(query) or cc.fold(query) in used_queries):  # fmt: skip
            # no concrete thing to show (« uniquement une photo », an echo of the instructions) or the picture of
            # another slide: no photo slot (a search on « Impact de la crise » only finds noise or nothing)
            repairs.append(f"photo slot dropped, no concrete query: {query[:30]!r}")
            query = ""
            visual = "none" if visual == "image" else visual
            layout = "" if layout.startswith("image") else layout
        if query:
            used_queries.add(cc.fold(query))
        if query and not images.variants(query):
            # « Paris bike cargo statistics »: a statistic is a chart (from real data) or key figures, never a photo
            visual = ("chart" if data in ("statistics", "request") else "kpi") if visual == "image" else visual
            layout = "" if layout.startswith("image") else layout
            repairs.append(f"photo of a statistic turned into a {visual}: {title[:30]}")
            query = ""
        if visual != "image" and not layout.startswith("image"):
            query = ""
        items.append(Item(title, _s(r.get("intent"), 200), layout, visual, query, data, indicator,
                          _s(r.get("places"), 80), _s(r.get("since"), 10), _s(r.get("search"), 120),
                          facts[:4]))  # fmt: skip
    if len(items) < 3:
        return None
    if len(items) > hi:
        repairs.append(f"plan cut from {len(items)} to {hi} items")
        items = items[:hi]
    if len(items) < lo:
        repairs.append(f"plan of {len(items)} items (fewer than {lo})")
    title = _s(obj.get("title"), 110)
    cover = images.clean_query(_s(obj.get("cover_image"), 80))[:60]
    if cover and not images.variants(cover):
        cover = ""
    return Outline(kind, title, _s(obj.get("subtitle"), 140), _s(obj.get("audience"), 120),
                   _s(obj.get("message"), 240), cover, items)  # fmt: skip


# ------------------------------------------------------------------ 3. writing one slide or section

WRITE = {
    "deck": {
        "fr": (
            "[Canevas] Présentation « {title} »{audience}. Message clé : {message}\n"
            "Écris uniquement la diapositive {i} sur {n} : « {stitle} ». Objectif : {intent}\n{facts}"
            "Format :\n# {stitle}\n- 4 à 6 points précis, 25 mots au plus chacun : chacun porte un fait, un nom, un lieu, une "
            "date, un chiffre des faits ou un exemple concret, jamais une généralité ni une formule creuse\n{visual}"
            "Règles : rien d'autre que cette diapositive (pas d'introduction, pas de titre de présentation) ; "
            "n'invente aucun chiffre : seulement ceux des faits ci-dessus ou de la demande{cite}."
        ),
        "en": (
            '[Canvas] Deck "{title}"{audience}. Key message: {message}\n'
            'Write only slide {i} of {n}: "{stitle}". Goal: {intent}\n{facts}'
            "Format:\n# {stitle}\n- 4 to 6 precise points, 25 words at most each: each one carries a fact, a name, a place, a "
            "date, a figure of the facts or a concrete example, never a generality or an empty phrase\n{visual}"
            "Rules: nothing but this slide (no introduction, no deck title); invent no figure: only those of the "
            "facts above or of the request{cite}."
        ),
    },
    "doc": {
        "fr": (
            "[Canevas] Document « {title} »{audience}. À retenir : {message}\n"
            "Écris uniquement la section {i} sur {n} : « {stitle} ». Objectif : {intent}\n{facts}"
            "Format :\n# {stitle}\n2 à 4 paragraphes de 3 à 5 phrases : des faits précis (noms, lieux, dates, chiffres des "
            "faits), des exemples, leurs conséquences ; une liste (- point) si elle aide ; ni généralités ni "
            "conclusion creuse.\n{visual}"
            "Règles : rien d'autre que cette section ; n'invente aucun chiffre ni aucun nom : seulement ceux des "
            "faits ci-dessus ou de la demande{cite}."
        ),
        "en": (
            '[Canvas] Document "{title}"{audience}. To remember: {message}\n'
            'Write only section {i} of {n}: "{stitle}". Goal: {intent}\n{facts}'
            "Format:\n# {stitle}\n2 to 4 paragraphs of 3 to 5 sentences: precise facts (names, places, dates, figures of "
            "the facts), examples, their consequences; a list (- point) if it helps; no generalities, no empty "
            "conclusion.\n{visual}"
            "Rules: nothing but this section; invent no figure and no name: only those of the facts above or of "
            "the request{cite}."
        ),
    },
}
VISUAL_HINT = {
    "fr": {
        "kpi": "Puis les chiffres clés, pris dans les faits ou la demande :\n::: kpi\n<chiffre> | <ce qu'il mesure>\n:::\n",
        "chart_request": 'Puis le graphique des chiffres de la demande :\n::: chart type=bar unit="<unité>"\n<libellé>: <nombre>\n:::\n',
        "chart_data": "Bird place la courbe officielle sous ces points : ne la décris pas, donne les valeurs exactes des faits et ce qu'elles signifient.\n",
        "timeline": "Puis une frise :\n::: timeline\n<date> : <étape>\n:::\n",
        "steps": "Puis les étapes :\n::: steps\n<étape> : <ce qu'on y fait>\n:::\n",
        "compare": "Puis la comparaison :\n::: compare\n<option A> | <option B>\n<point A> | <point B>\n:::\n",
        "cards": "Puis des cartes :\n::: cards\n<nom> : <description courte>\n:::\n",
        "quote": "Puis une citation tirée des faits, avec son auteur :\n> « citation » — auteur\n",
        "table": "Puis un tableau :\n| <colonne> | <colonne> |\n| <valeur> | <valeur> |\n",
        "image": "Une photo est placée à côté du texte par Bird : 3 ou 4 points précis.\n",
    },
    "en": {
        "kpi": "Then the key figures, taken from the facts or the request:\n::: kpi\n<figure> | <what it measures>\n:::\n",
        "chart_request": 'Then the chart of the request\'s figures:\n::: chart type=bar unit="<unit>"\n<label>: <number>\n:::\n',
        "chart_data": "Bird places the official curve under these points: do not describe it, give the exact values of the facts and what they mean.\n",
        "timeline": "Then a timeline:\n::: timeline\n<date>: <step>\n:::\n",
        "steps": "Then the steps:\n::: steps\n<step>: <what happens>\n:::\n",
        "compare": "Then the comparison:\n::: compare\n<option A> | <option B>\n<point A> | <point B>\n:::\n",
        "cards": "Then cards:\n::: cards\n<name>: <short description>\n:::\n",
        "quote": 'Then a quotation from the facts, with its author:\n> "quotation" — author\n',
        "table": "Then a table:\n| <column> | <column> |\n| <value> | <value> |\n",
        "image": "A photo is placed beside the text by Bird: 3 or 4 precise points.\n",
    },
}  # fmt: skip


@dataclass
class Fact:
    text: str
    n: int = 0  # the source number (0: the request itself)


@dataclass
class Gathered:
    facts: list[Fact] = field(default_factory=list)
    chart: dict | None = None  # a chart part built from get_statistics' series
    media: dict | None = None  # the browser entry of the picture found (images.to_entry)
    image_tried: bool = False
    error: str = ""


def write_message(o: Outline, i: int, words: str, lang: str, got: Gathered) -> str:
    lg = "en" if lang == "en" else "fr"
    it = o.items[i]
    fr = lg == "fr"
    facts = [(f.n, f.text) for f in got.facts] + [(0, f) for f in it.facts]
    lines = ""
    if facts:
        head = "Faits à utiliser :\n" if fr else "Facts to use:\n"
        lines = head + "".join(f"{'[' + str(n) + '] ' if n else '- '}{t}\n" for n, t in facts[: MAX_FACTS + 2])
    visual = it.visual
    if visual == "chart":
        visual = "chart_data" if got.chart else ("chart_request" if it.data == "request" else "kpi" if facts else "")
    if visual == "kpi" and not any(re.search(r"\d", t) for _, t in facts) and not re.search(r"\d", words):
        visual = ""  # key figures with no figure to show: points only, never invented numbers
    if visual == "image" and not got.media:
        visual = ""
    hint = (
        VISUAL_HINT[lg].get(visual, "")
        if o.kind == "deck" or visual in ("table", "chart_request", "chart_data", "timeline", "steps", "compare")
        else ""
    )
    cite = (
        (
            "; cite la source d'un fait par son numéro entre crochets, par exemple [2]"
            if fr
            else "; cite a fact's source by its number in brackets, for example [2]"
        )
        if any(n for n, _ in facts)
        else ""
    )
    aud = (f" pour {o.audience}" if fr else f" for {o.audience}") if o.audience else ""
    body = WRITE[o.kind][lg].format(title=o.title, audience=aud, message=o.message or o.title, i=i + 1,
                                    n=len(o.items), stitle=it.title, intent=it.intent or it.title, facts=lines,
                                    visual=hint, cite=cite)  # fmt: skip
    return (("Demande de l'utilisateur : « " if fr else "The user's request: \"") + words.strip()[:1200]
            + (" »\n\n" if fr else "\"\n\n") + body)  # fmt: skip


def read_block(text: str, o: Outline, i: int, lang: str, repairs: list[str]) -> dict:
    """The slide or section the model wrote, as one block with the planned title (never fails: possibly empty)."""
    it = o.items[i]
    _, content, _ = dsl.split_answer(text)
    content = re.sub(r"(?m)^\s*---\s*$", "", content)  # a front matter or a slide separator: not ours here
    if not re.search(r"(?m)^\s{0,3}#{1,3}\s", content):
        content = f"# {it.title}\n" + content
    doc = dsl.parse(content, o.kind, lang, repairs)
    blocks = doc.get("blocks") or []
    parts: list[dict] = []
    for b in blocks[:2] if o.kind == "doc" else blocks[:1]:
        parts += b.get("parts") or []
    if len(blocks) > 1 and o.kind == "deck":
        repairs.append(f"slide {i + 1}: {len(blocks) - 1} extra block(s) dropped")
    block = {"id": f"b{i + 1}", "title": it.title, "parts": parts[: dsl.MAX_PARTS], "notes": ""}
    if it.layout:
        block["layout"] = it.layout
    if doc.get("footnotes"):
        block["_notes"] = doc["footnotes"]
    return block


# ------------------------------------------------------------------ 4. the checks (code, no model)


def _part_texts(p: dict) -> list[str]:
    out = [str(p.get(k) or "") for k in ("text", "by")]
    for it in p.get("items") or []:
        out += [str(v) for v in (it.values() if isinstance(it, dict) else [it])]
    return out


def check_figures(block: dict, allowed: set[float], kind: str) -> int:
    """Drop every point, sentence, key figure or row whose figure is not in ``allowed``; returns how many."""
    from birds.harness import crew_checks as cc

    dropped = 0
    keep_parts = []
    for p in block.get("parts") or []:
        t = p.get("t")
        if t == "list":
            items = [x for x in p.get("items") or [] if not cc.unsupported(_CITE.sub(" ", x), allowed)]
            dropped += len(p.get("items") or []) - len(items)
            if not items:
                continue
            p["items"] = items
        elif t in ("text", "callout", "quote"):
            sents = re.split(r"(?<=[.!?])\s+", p.get("text") or "")
            kept = [s for s in sents if not cc.unsupported(_CITE.sub(" ", s), allowed)]
            dropped += len(sents) - len(kept)
            if not kept:
                continue
            p["text"] = " ".join(kept)
        elif t in ("kpi", "timeline", "steps", "cards"):
            items = [
                x for x in p.get("items") or [] if not cc.unsupported(" ".join(str(v) for v in x.values()), allowed)
            ]
            dropped += len(p.get("items") or []) - len(items)
            if not items:
                continue
            p["items"] = items
        elif t == "compare":
            for col in p.get("columns") or []:
                before = len(col.get("items") or [])
                col["items"] = [x for x in col.get("items") or [] if not cc.unsupported(x, allowed)]
                dropped += before - len(col["items"])
        elif t == "table":
            rows = p.get("rows") or []
            kept = rows[:1] + [r for r in rows[1:] if not cc.unsupported(" ".join(r), allowed)]
            dropped += len(rows) - len(kept)
            if len(kept) < 2:
                continue
            p["rows"] = kept
        elif t == "chart" and not p.get("source"):  # a chart the model wrote: every value must be given
            vals = [v for r in p.get("rows") or [] for v in r[1:] if isinstance(v, int | float)]
            if any(not cc.supported(float(v), allowed) for v in vals if abs(v) >= 13 or not float(v).is_integer()):
                dropped += 1
                continue
        keep_parts.append(p)
    block["parts"] = keep_parts
    return dropped


_ANNOUNCE = re.compile(r"^\s*(?:graphiques?|courbes?|charts?|graphs?|figures?)\b[^.]{0,90}$", re.I)
_NOTE = re.compile(r"\[(?!\^?\d{1,2}\])[^\[\]\n]{3,}\]|<[^<>\n]{2,40}>")


def _clean(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _NOTE.sub(" ", text)).strip(" :–—-")


def scrub(block: dict) -> int:
    """The model's notation never reaches the page: « [Graphique des données officielles : …] », « <étape> »,
    « <date> » (template words copied) are removed; a point or a step left empty goes. Returns how many."""
    n = 0
    keep = []
    for p in block.get("parts") or []:
        if p.get("t") in ("text", "callout", "quote") and _NOTE.search(p.get("text") or ""):
            p["text"] = _clean(p["text"])
            n += 1
            if not p["text"]:
                continue
        items = p.get("items")
        if isinstance(items, list):
            out = []
            for x in items:
                if isinstance(x, str):
                    y = _clean(x) if _NOTE.search(x) else x
                    if p.get("t") == "list" and _ANNOUNCE.match(y) and any(q.get("t") == "chart" for q in
                                                                           block.get("parts") or []):  # fmt: skip
                        y = ""  # « Graphique montrant la tendance » beside the chart itself: says nothing
                    n += y != x
                    if y:
                        out.append(y)
                elif isinstance(x, dict):
                    y = {k: (_clean(v) if isinstance(v, str) and _NOTE.search(v) else v) for k, v in x.items()}
                    n += y != x
                    if any(isinstance(v, str) and v for v in y.values()):
                        out.append(y)
            p["items"] = out
            if not out and p.get("t") in ("list", "kpi", "timeline", "steps", "cards"):
                continue
        keep.append(p)
    block["parts"] = keep
    return n


def balance(block: dict, kind: str) -> int:
    """No wall of text: at most MAX_POINTS points of POINT_CHARS characters on a slide. Returns how many cuts."""
    cuts = 0
    for p in block.get("parts") or []:
        if p.get("t") == "list":
            items = p.get("items") or []
            if len(items) > MAX_POINTS[kind]:
                p["items"] = items[: MAX_POINTS[kind]]
                cuts += 1
            if kind == "deck":
                for k, x in enumerate(p["items"]):
                    if len(x) > POINT_CHARS:
                        cut = x[:POINT_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
                        p["items"][k] = cut
                        cuts += 1
        elif p.get("t") == "text" and kind == "deck" and len(p.get("text") or "") > 320:
            sents = re.split(r"(?<=[.!?])\s+", p["text"])
            p["text"] = " ".join(sents[:2])
            cuts += 1
    return cuts


def has_visual(block: dict) -> bool:
    return any(p.get("t") in ("image", "chart", "kpi", "table", "timeline", "steps", "compare", "cards", "quote")
               for p in block.get("parts") or [])  # fmt: skip


# ------------------------------------------------------------------ the pipeline


@dataclass
class Env:
    """What the pipeline needs from the turn (injected: tests and the demo give their own)."""

    llm: object
    tok: object
    lang: str
    words: str
    kind: str
    aid: str
    emit: object  # emit(event dict)
    finder: object  # find(query, exclude, mid) -> Media | None
    tool: object | None = None  # tool(name, args) -> (step, result_text, ctx) ; None: no web, no statistics
    system: str = ""
    cache_salt: str | None = None
    deadline: float = 0.0
    level: str = "hirondelle"
    structured: str | None = None  # the endpoint's structured-output form (None: detect)
    pause: float = 0.0  # demo: a pause between two snapshots


@dataclass
class Result:
    doc: dict | None
    outline: Outline | None = None
    raw_plan: str = ""
    usage: list[dict] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    lines: list[dict] = field(default_factory=list)


class Progress:
    """The calm lines of the turn (« Plan : 8 diapositives »), sent whole on every change."""

    def __init__(self, env: Env):
        self.env, self.lines, self.lock = env, [], threading.Lock()

    def set(self, key: str, text: str, state: str = "done") -> None:
        with self.lock:
            for ln in self.lines:
                if ln["k"] == key:
                    if ln["text"] == text and ln["state"] == state:
                        return
                    ln.update(text=text, state=state)
                    break
            else:
                self.lines.append({"k": key, "text": text, "state": state})
            lines = [dict(x) for x in self.lines]
        self.env.emit({"type": "canvas_progress", "aid": self.env.aid, "lines": lines})


def _pl(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _domain(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


class Pipeline:
    def __init__(self, env: Env):
        self.env = env
        self.fr = env.lang != "en"
        self.res = Result(None)
        self.progress = Progress(env)
        self.lock = threading.Lock()
        self.sources: list[dict] = []  # {"n", "url", "title", "domain"}
        self.reads = 0
        self.fetched: list[str] = []  # texts read (the figure check's allowed set)
        self.used_pictures: set[str] = set()  # the sources of the pictures placed (never the same one twice)

    # ---- generations
    def generate(self, message: str, max_tokens: int, schema_: dict | None = None, temperature: float = 0.4) -> str:
        from birds.harness import router
        from birds.harness.llm import STOP
        from birds.render import prompt as render_prompt

        msgs = ([{"role": "system", "content": self.env.system}] if self.env.system else []) + [
            {"role": "user", "content": message}]  # fmt: skip
        p = render_prompt(self.env.tok, msgs, [], False)
        extra: dict = {"temperature": temperature}
        if schema_ is not None:
            kind = self.env.structured
            if kind is None:
                kind = router.structured_kind(self.env.llm, deadline=time.monotonic() + 6) if router.probeable(
                    self.env.llm) else ""  # fmt: skip
                self.env.structured = kind
            extra.update(router.structured_extra(kind, schema_))
        if self.env.cache_salt:
            extra["cache_salt"] = self.env.cache_salt
        left = self.env.deadline - time.monotonic() if self.env.deadline else 120
        out = self.env.llm.generate(p, max_tokens, STOP, deadline=time.monotonic() + max(5.0, min(left, 90.0)),
                                    extra=extra)  # fmt: skip
        with self.lock:
            self.res.usage.append({k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds",
                                                            "busy_seconds", "cached_tokens", "finish_reason")
                                   if k in out})  # fmt: skip
        return str(out.get("text") or "")

    # ---- 1. plan
    def plan(self) -> Outline | None:
        e = self.env
        depth = depth_of(e.level)
        self.progress.set("plan", "Plan en cours…" if self.fr else "Planning…", "running")
        raw = self.generate(plan_message(e.words, e.kind, e.lang, depth), PLAN_TOKENS, schema(e.kind), 0.3)
        self.res.raw_plan = raw
        o = parse_outline(raw, e.kind, e.words, e.lang, self.res.repairs)
        if o is None:
            return None
        if not o.title:
            from . import convert

            o.title = convert.subject(e.words) or ("Présentation" if self.fr else "Presentation")
        n = len(o.items)
        unit = (_pl(n, "diapositive", "diapositives") if e.kind == "deck" else _pl(n, "section", "sections")) if \
            self.fr else (_pl(n, "slide", "slides") if e.kind == "deck" else _pl(n, "section", "sections"))  # fmt: skip
        self.progress.set("plan", (f"Plan : {unit}" if self.fr else f"Plan: {unit}"))
        return o

    def facts_fallback(self, o: Outline) -> None:
        """Safety net (the model plans, this only fills a gap): a plan that asks no fact at all (seen live on « une
        note de synthèse sur le vélo en ville »: seven sections of generalities) gets web facts for its first
        sections that carry content, each searched on its own title and the subject."""
        from . import convert

        if sum(1 for it in o.items if it.data in ("web", "statistics")) >= 2:
            return
        subject = convert.subject(self.env.words) or o.title
        n = 0
        for it in o.items:
            if n >= MAX_READS - 2:
                break
            if it.data == "none" and it.visual not in ("quote",):
                it.data, it.search = "web", f"{it.title} {subject}"[:120]
                n += 1
        if n:
            self.res.repairs.append(f"no fact planned: web facts for {n} item(s)")

    # ---- the document as it stands
    def skeleton(self, o: Outline) -> dict:
        doc = dsl.empty(o.kind, self.env.lang)
        doc["title"], doc["subtitle"] = o.title, o.subtitle
        if o.kind == "deck" and o.cover:
            doc["cover"] = {"query": o.cover}
        doc["blocks"] = [{"id": f"b{i + 1}", "title": it.title, "parts": [], "notes": "", "pending": True,
                          **({"layout": it.layout} if it.layout else {})} for i, it in enumerate(o.items)]  # fmt: skip
        doc["media"] = {}
        return doc

    def snapshot(self, doc: dict) -> None:
        from birds.web.canvas_web import public

        self.env.emit({"type": "canvas", "phase": "stream", "aid": self.env.aid, "base": None,
                       "kind": self.env.kind, "label": "", "open": True, "doc": public(doc)})  # fmt: skip
        if self.env.pause:
            time.sleep(self.env.pause)

    def media(self, doc: dict, entry: dict) -> None:
        doc.setdefault("media", {})[entry["id"]] = {k: entry[k] for k in ("kind", "alt", "credit", "licence", "source",
                                                                           "w", "h", "query", "title")}  # fmt: skip
        self.env.emit({"type": "canvas_media", "aid": self.env.aid, "media": [entry]})

    # ---- 2. gather
    def source(self, url: str, title: str) -> int:
        with self.lock:
            for s in self.sources:
                if s["url"] == url:
                    return s["n"]
            n = len(self.sources) + 1
            self.sources.append({"n": n, "url": url, "title": _s(title, 120) or _domain(url), "domain": _domain(url)})
            return n

    def find_image(self, query: str, mid: str, retry: bool = False) -> dict | None:
        """A free-licence picture for ``query``, never one already placed in this deck (the same file twice was
        seen live: three slides of « uniquement » got one studio photo)."""
        if not query:
            return None
        try:
            for _ in range(2):
                with self.lock:
                    used = sorted(self.used_pictures)
                m = self.env.finder(query, used, mid)
                if m is None and retry:
                    short = images.short_query(query)
                    if short and short != query:
                        m = self.env.finder(short, used, mid)
                if m is None:
                    return None
                key = m.source or m.title or m.id
                with self.lock:
                    if key not in self.used_pictures:
                        self.used_pictures.add(key)
                        return images.to_entry(m, query)
            return None
        except Exception:  # noqa: BLE001 - a picture search that fails is a placeholder, never a broken turn
            return None

    def statistics(self, it: Item) -> tuple[dict | None, list[Fact]]:
        step, text, ctx = self.env.tool("get_statistics", {"indicator": it.indicator, "places": it.places or "",
                                                            "since": it.since or ""})  # fmt: skip
        if step.error or not getattr(ctx, "charts", None):
            return None, []
        spec = ctx.charts[-1]
        src = spec.get("data_source") or {}
        url = str(src.get("url") or "")
        n = (
            self.source(url, f"{src.get('label', '')} {src.get('dataset', '')}".strip())
            if url.startswith("https://")
            else 0
        )
        label = " ".join(x for x in [str(src.get("label") or ""), str(src.get("dataset") or "")] if x)
        part = {"t": "chart", "type": spec.get("type") if spec.get("type") in dsl.CHART_TYPES else "line",
                "unit": str(spec.get("unit") or "")[:8], "title": str(spec.get("title") or "")[:120],
                "columns": [str(c)[:80] for c in spec.get("columns") or []][:7],
                "rows": [[str(r[0])[:80]] + list(r[1:7]) for r in spec.get("rows") or []][: dsl.MAX_ROWS],
                "source": (label + (f" [{n}]" if n else ""))[:200]}  # fmt: skip
        try:
            part = dsl._part_ok(part)
        except Exception:  # noqa: BLE001 - a series that does not fit the chart shape is not drawn
            return None, []
        facts_txt = re.search(r"données réelles[^.]*\.\s*(.+?)\. Ne redessine|real data[^.]*\.\s*(.+?)\. Do not", text)
        facts = []
        if facts_txt:
            for f in re.split(r"\s;\s|;\s", (facts_txt.group(1) or facts_txt.group(2) or "")):
                if f.strip():
                    facts.append(Fact(_s(f, FACT_CHARS), n))
        with self.lock:
            self.fetched.append(text)
        return part, facts

    def web(self, it: Item) -> list[Fact]:
        from birds.harness import crew_checks as cc

        query = it.search or f"{it.title} {self.env.words[:80]}"
        step, text, ctx = self.env.tool("web_search", {"query": query[:200], "max_results": 4})
        if step.error:
            return []
        results = list((step.info or {}).get("results") or [])
        facts: list[Fact] = []
        head = [w for w in re.findall(r"[\wÀ-ÿ'-]{4,}", f"{it.title} {it.search}")][:8]
        with self.lock:
            go = self.reads < MAX_READS and time.monotonic() < self.gather_until
            if go:
                self.reads += 1
        for r in results[:3]:
            url = str(r.get("url") or "")
            if not go or not url.startswith("https://"):
                continue
            step2, page, _ = self.env.tool("read_page", {"url": url}, ctx=ctx)
            if step2.error or step2.flags:
                continue  # a page that talks to the assistant is never given to a model
            body = page.split("\n\n", 1)[-1]
            ext = cc.evidence(body, head, None, 1400, need_figure=False)
            sents = [s for s in re.split(r"(?<=[.!?])\s+|\n+", ext) if 40 <= len(s) <= 400]
            title = (re.search(r"^Title: ([^\n]+)", page, re.M) or [None, r.get("title") or ""])[1]
            if sents:
                n = self.source(url, title)
                facts += [Fact(_s(s, FACT_CHARS), n) for s in sents[:MAX_FACTS]]
                with self.lock:
                    self.fetched.append(body[:20000])
                break
        if not facts:  # no page kept: the search snippets, each with its own source
            for r in results[:3]:
                url, snip = str(r.get("url") or ""), _s(r.get("snippet"), FACT_CHARS)
                if url.startswith("https://") and len(snip) >= 40:
                    facts.append(Fact(snip, self.source(url, str(r.get("title") or ""))))
                    with self.lock:
                        self.fetched.append(snip)
        return facts[:MAX_FACTS]

    def gather(self, o: Outline, i: int, full: bool) -> Gathered:
        it = o.items[i]
        got = Gathered()
        if not full or self.env.tool is None or time.monotonic() > self.gather_until:
            return got
        try:
            if it.data == "statistics" and it.indicator:
                got.chart, got.facts = self.statistics(it)
                if got.chart:
                    with self.lock:
                        self.res.counts["charts_data"] = self.res.counts.get("charts_data", 0) + 1
                        self.res.counts.setdefault("chart_from", []).append(got.chart["source"].split(" [")[0])
            if it.data == "web" or (it.data == "statistics" and not got.chart):
                got.facts += self.web(it)
        except Exception as e:  # noqa: BLE001 - a tool that fails leaves the slide to its plan, never the turn
            got.error = type(e).__name__
        return got

    def write(self, o: Outline, i: int, got: Gathered) -> dict:
        repairs: list[str] = []
        try:
            text = self.generate(write_message(o, i, self.env.words, self.env.lang, got), WRITE_TOKENS[o.kind])
        except Exception as e:  # noqa: BLE001 - a slide the endpoint failed to write is filled by the check
            repairs.append(f"slide {i + 1} not written ({type(e).__name__})")
            text = ""
        block = read_block(text, o, i, self.env.lang, repairs)
        with self.lock:
            self.res.repairs += repairs
        return block

    # ---- the whole turn
    def run(self) -> Result:
        e = self.env
        t0 = time.monotonic()
        o = self.plan()
        self.res.outline = o
        if o is None:
            self.progress.set("plan", "Plan illisible : rédaction directe" if self.fr else "Plan unreadable: writing "
                              "directly", "done")  # fmt: skip
            return self.res
        full = depth_of(e.level) == "full" and e.tool is not None
        if full:
            self.facts_fallback(o)
        doc = self.skeleton(o)
        self.snapshot(doc)
        self.gather_until = time.monotonic() + GATHER_SECONDS
        n = len(o.items)
        wants_image = [i for i, it in enumerate(o.items) if it.query and (it.visual == "image"
                                                                           or it.layout.startswith("image"))]
        for i in wants_image:
            if not o.items[i].query:
                o.items[i].query = o.items[i].title
        if full:
            self.progress.set("gather", "Recherche des faits et des données…" if self.fr else "Gathering facts and "
                              "data…", "running")  # fmt: skip
        if wants_image or doc.get("cover"):
            self.progress.set("images", "Recherche d'images libres…" if self.fr else "Searching free pictures…",
                              "running")  # fmt: skip
        self.progress.set("write", (f"Rédaction : 0/{n}" if self.fr else f"Writing: 0/{n}"), "running")
        written: dict[int, dict] = {}
        gathered: dict[int, Gathered] = {}
        found: dict[int, dict | None] = {}
        pool = ThreadPoolExecutor(max_workers=WORKERS)
        try:
            jobs = {}
            cover_q = (doc.get("cover") or {}).get("query")
            if cover_q:
                jobs[pool.submit(self.find_image, cover_q, "w0", full)] = ("cover", -1)
            for i in wants_image:
                jobs[pool.submit(self.find_image, o.items[i].query, f"w{i + 1}", full)] = ("image", i)

            def chain(i: int):
                got = self.gather(o, i, full)
                gathered[i] = got
                return got

            for i in range(n):
                jobs[pool.submit(chain, i)] = ("gather", i)
            waiting_write: dict[int, Gathered] = {}
            while jobs:
                left = (e.deadline - time.monotonic()) if e.deadline else 60
                done, _ = wait(list(jobs), timeout=max(0.2, min(1.0, left)), return_when=FIRST_COMPLETED)
                if not done and e.deadline and time.monotonic() > e.deadline - 8:
                    self.res.repairs.append(f"budget reached: {len(jobs)} job(s) left")
                    break
                changed = False
                for f in done:
                    what, i = jobs.pop(f)
                    try:
                        value = f.result()
                    except Exception as ex:  # noqa: BLE001
                        self.res.repairs.append(f"{what} {i} failed ({type(ex).__name__})")
                        value = None
                    if what == "cover":
                        if value:
                            self.media(doc, value)
                            doc["cover"]["media"] = value["id"]
                            changed = True
                    elif what == "image":
                        found[i] = value
                        if value:
                            self.media(doc, value)
                        if i in written:
                            self._place_image(o, doc, i, written[i])
                            changed = True
                        elif i in waiting_write:  # its picture was awaited to write the slide
                            g = waiting_write.pop(i)
                            g.media = value
                            jobs[pool.submit(self.write, o, i, g)] = ("write", i)
                    elif what == "gather":
                        g = value or Gathered()
                        if g.chart:
                            self.progress.set("charts", self._charts_line())
                        if i in wants_image and i not in found:
                            waiting_write[i] = g  # the slide is written knowing whether a photo sits beside it
                        else:
                            g.media = found.get(i)
                            jobs[pool.submit(self.write, o, i, g)] = ("write", i)
                    elif what == "write":
                        block = value or {"id": f"b{i + 1}", "title": o.items[i].title, "parts": [], "notes": ""}
                        g = gathered.get(i) or Gathered()
                        if g.chart:
                            block["parts"] = [p for p in block["parts"] if p.get("t") != "chart"] + [g.chart]
                        written[i] = block
                        self._place_image(o, doc, i, block)
                        doc["blocks"][i] = block
                        changed = True
                        self.progress.set("write", (f"Rédaction : {len(written)}/{n}" if self.fr else
                                                    f"Writing: {len(written)}/{n}"),
                                          "done" if len(written) == n else "running")  # fmt: skip
                if changed:
                    self.snapshot(doc)
                if full and not any(w == "gather" for w, _ in jobs.values()):
                    self.progress.set("gather", self._gather_line(), "done")
                if not any(w in ("image", "cover") for w, _ in jobs.values()) and (wants_image or cover_q):
                    self.progress.set("images", self._images_line(found, cover_q, doc), "done")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        for i in range(n):  # a slide never written (budget): its planned facts, else its intent
            if i not in written:
                doc["blocks"][i] = {"id": f"b{i + 1}", "title": o.items[i].title, "parts": [], "notes": ""}
        self.check(o, doc, gathered, full)
        self.res.doc = doc
        self.res.counts["seconds"] = round(time.monotonic() - t0, 1)
        self.res.lines = self.progress.lines
        return self.res

    def _place_image(self, o: Outline, doc: dict, i: int, block: dict) -> None:
        it = o.items[i]
        if not it.query or not (it.visual == "image" or it.layout.startswith("image")) or \
                i not in self._found_keys(doc, i):  # fmt: skip
            return
        entry = self._entry(doc, i)
        have = next((p for p in block["parts"] if p.get("t") == "image"), None)
        if have is not None:
            if entry and not have.get("media"):  # the picture arrived after the slide was written
                have["media"] = entry
                have.pop("missing", None)
            return
        q = images.clean_query(it.query)
        part = {"t": "image", "query": q, "alt": q, "caption": ""}
        if entry:
            part["media"] = entry
        else:
            part["missing"] = True
        block["parts"].append(part)

    def _found_keys(self, doc: dict, i: int) -> set[int]:
        return {i} if f"w{i + 1}" in (doc.get("media") or {}) or self._searched(i) else set()

    def _searched(self, i: int) -> bool:
        return True  # called once the search ended (found or not): see run()

    def _entry(self, doc: dict, i: int) -> str | None:
        mid = f"w{i + 1}"
        return mid if mid in (doc.get("media") or {}) else None

    def _charts_line(self) -> str:
        n = self.res.counts.get("charts_data", 0)
        frm = ", ".join(dict.fromkeys(self.res.counts.get("chart_from") or []))
        return (f"{_pl(n, 'graphique', 'graphiques')} à partir de {frm}" if self.fr
                else f"{_pl(n, 'chart', 'charts')} from {frm}")  # fmt: skip

    def _gather_line(self) -> str:
        n = len(self.sources)
        if not n:
            return "Aucune source web retenue" if self.fr else "No web source kept"
        return (f"Recherche : {_pl(n, 'source retenue', 'sources retenues')}" if self.fr
                else f"Research: {_pl(n, 'source kept', 'sources kept')}")  # fmt: skip

    def _images_line(self, found: dict, cover_q, doc: dict) -> str:
        got = sum(1 for v in found.values() if v) + (1 if (doc.get("cover") or {}).get("media") else 0)
        miss = sum(1 for v in found.values() if not v)
        line = _pl(got, "image trouvée", "images trouvées") if self.fr else _pl(got, "picture found", "pictures found")
        if miss:
            line += f", {_pl(miss, 'à ajouter', 'à ajouter')}" if self.fr else f", {miss} to add"
        return line

    # ---- 4. check
    def check(self, o: Outline, doc: dict, gathered: dict, full: bool) -> None:
        from birds.harness import crew_checks as cc

        if full:
            self.progress.set("check", "Vérification…" if self.fr else "Checking…", "running")
        facts_all = [f.text for g in gathered.values() for f in g.facts] + [f for it in o.items for f in it.facts]
        chart_vals = [str(v) for g in gathered.values() if g.chart for r in g.chart["rows"] for v in r[1:]]
        allowed = cc.allowed_figures(self.env.words, *facts_all, *self.fetched, " ".join(chart_vals))
        dropped = cuts = filled = 0
        for i, b in enumerate(doc["blocks"]):
            b.pop("pending", None)
            scrub(b)
            dropped += check_figures(b, allowed, o.kind)
            cuts += balance(b, o.kind)
            body = [p for p in b["parts"] if p.get("t") != "image"]
            if not body:  # a slide left empty: its facts (sourced), else what it was planned to say
                g = gathered.get(i) or Gathered()
                pts = [f"{f.text} [{f.n}]" if f.n else f.text for f in g.facts[:3]] or list(o.items[i].facts[:3])
                if pts and o.kind == "deck":
                    b["parts"].insert(0, {"t": "list", "items": [_s(x, POINT_CHARS) for x in pts], "ordered": False})
                elif pts:
                    b["parts"].insert(0, {"t": "text", "text": " ".join(pts)})
                elif o.items[i].intent:
                    b["parts"].insert(0, {"t": "text", "text": o.items[i].intent})
                filled += 1
        # sources: numbered by first citation, unknown numbers removed
        order: list[int] = []
        known = {s["n"] for s in self.sources}
        for b in doc["blocks"]:
            for p in b["parts"]:
                for t in _part_texts(p) + [str(p.get("source") or "")]:
                    for m in _CITE.finditer(t):
                        k = int(m.group(1))
                        if k in known and k not in order:
                            order.append(k)
        remap = {old: new for new, old in enumerate(order, 1)}

        def renum(text: str) -> str:
            def sub(m):
                k = int(m.group(1))
                if k not in remap:
                    return ""
                return f"[^{remap[k]}]" if o.kind == "doc" else f"[{remap[k]}]"

            return re.sub(r"\s?\[\^?(\d{1,2})\]", lambda m: (" " if o.kind == "deck" else "") + sub(m) if sub(m) else "",
                          text)  # fmt: skip

        for b in doc["blocks"]:
            for p in b["parts"]:
                for key in ("text", "by", "source", "caption"):
                    if isinstance(p.get(key), str):
                        p[key] = renum(p[key]).strip()
                if isinstance(p.get("items"), list):
                    p["items"] = [renum(x).strip() if isinstance(x, str) else
                                  {k: renum(v).strip() if isinstance(v, str) else v for k, v in x.items()}
                                  for x in p["items"]]  # fmt: skip
                for col in p.get("columns") or []:
                    if isinstance(col, dict):
                        col["items"] = [renum(x).strip() for x in col.get("items") or []]
                if p.get("t") == "table":
                    p["rows"] = [[renum(c).strip() for c in r] for r in p.get("rows") or []]
            b.pop("_notes", None)
        by_n = {s["n"]: s for s in self.sources}
        cited = [{**by_n[old], "n": new} for old, new in remap.items()]
        doc["sources"] = cited
        if cited and o.kind == "deck":
            items = [f"[{s['n']}] {s['title']} — {s['url']}" for s in cited]
            doc["blocks"].append({"id": f"b{len(doc['blocks']) + 1}", "title": "Sources", "notes": "",
                                  "parts": [{"t": "list", "items": items[: dsl.MAX_ITEMS], "ordered": False}]})  # fmt: skip
        elif cited:
            doc["footnotes"] = [{"n": str(s["n"]), "text": f"{s['title']}, {s['domain']} — {s['url']}"} for s in cited]
        self.res.sources = self.sources
        missing = sum(1 for b in doc["blocks"] for p in b["parts"] if p.get("t") == "image" and p.get("missing"))
        body = [b for b in doc["blocks"] if b.get("title") != "Sources"]
        self.res.counts.update(figures_dropped=dropped, balanced=cuts, filled=filled, missing_images=missing,
                               with_visual=sum(1 for b in body if has_visual(b)), slides=len(body),
                               cited=len(cited), read=len(self.sources))  # fmt: skip
        if full:
            bits = []
            if dropped:
                bits.append(
                    _pl(dropped, "chiffre non sourcé retiré", "chiffres non sourcés retirés")
                    if self.fr
                    else _pl(dropped, "unsourced figure removed", "unsourced figures removed")
                )
            if missing:
                bits.append(
                    _pl(missing, "image à ajouter", "images à ajouter")
                    if self.fr
                    else _pl(missing, "picture to add", "pictures to add")
                )
            if cited:
                bits.append(
                    _pl(len(cited), "source citée", "sources citées")
                    if self.fr
                    else _pl(len(cited), "source cited", "sources cited")
                )
            head = "Vérifié" if self.fr else "Checked"
            self.progress.set("check", head + (" : " if self.fr else ": ") + ", ".join(bits) if bits else
                              ("Vérifié : chiffres et visuels" if self.fr else "Checked: figures and visuals"))  # fmt: skip


def summary(o: Outline | None, lang: str) -> list[str]:
    """Three or four readable lines of the plan for the reasoning panel (the model's own plan, nothing added)."""
    if o is None:
        return []
    fr = lang != "en"
    out = []
    if o.audience:
        out.append(("Public : " if fr else "Audience: ") + o.audience)
    if o.message:
        out.append(("Message : " if fr else "Message: ") + o.message)
    heads = " · ".join(it.title for it in o.items[:8])
    out.append((f"{len(o.items)} parties : " if fr else f"{len(o.items)} parts: ") + heads)
    return out[:4]
