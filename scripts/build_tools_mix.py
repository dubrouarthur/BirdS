"""Supervised data to teach Bird S 4B its modules natively: router decisions and calls of the EXTRA tools.

  .venv/bin/python -I scripts/build_tools_mix.py --out out/tools_mix [--n 6000 --seed 0]

Writes, in the record format of the training mix (``birds/schema.py``, the same as ``scripts/build_mix.py``):

- ``train.jsonl``: templated requests (FR/EN, lowercase and accentless typing, typos, polite padding, follow-ups
  after a rich result) with two kinds of records:
  * ``task: "router"``: the exact router prompt (``router.messages``: catalogue, fixed examples, previous turn,
    hints, words) and the decision as the assistant turn, positives and NEGATIVES (``{"modules":[]}``: false
    triggers such as « météo des marchés », « charte graphique », « image de marque », office prompts, chat);
    the hints are the parsers' own (sometimes wrong, sometimes withheld), so the model learns to overrule them;
  * ``task: "tool_call_extra"``: Bird's system prompt, the product tools (trained block then EXTRA_TOOLS, as served
    when they are routed in), the request, and the assistant's call of get_weather / find_places / find_company /
    convert_currency / web_search (pictures) / make_chart (the user's figures). Ends on the call (the label).
- ``eval.jsonl``: the same, from templates held out whole (a phrasing family never seen in training);
- ``bench_heldout.jsonl``: every trigger-bench phrasing as router records, never in train (``router_eval.py``
  measures on them);
- ``stats.json``: counts per task, family, language, positive/negative.

No external model: phrasings come from templates and slot lists below, labels from the template (checked against
``catalog.check_args``, the router's grounding and the clock/event parsers); duplicates (accents and case folded)
are removed and any request equal to a bench phrasing is dropped from train. The native records carry no
negatives: a "no call" record needs a written answer, which only a teacher model can produce; the negatives live in
the router records, and the existing mix already holds tens of thousands of conversations without a call.

Fine-tune: docs/HARNESS.md, « Apprentissage natif des modules ».
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from birds.harness import catalog, clock, followup, when  # noqa: E402
from birds.harness import router as R  # noqa: E402
from birds.harness.agent import chart_call, detect_lang, figures_in  # noqa: E402
from birds.schema import errors  # noqa: E402
from birds.sources.identity import DEFAULT_SYSTEM  # noqa: E402
from birds.tools import BIRD_TOOLS, EXTRA_TOOLS  # noqa: E402

SOURCE, LICENSE = "bird_tools", "apache-2.0"
NOW = datetime(2026, 11, 23, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))
NATIVE = {"get_weather", "find_places", "find_company", "convert_currency", "work_calendar", "lookup_entity",
          "get_statistics", "find_tenders", "find_papers", "find_commune"}

# ---------------------------------------------------------------- slot lists
TOWNS_FR = [
    "Lyon",
    "Marseille",
    "Lille",
    "Nantes",
    "Bordeaux",
    "Toulouse",
    "Strasbourg",
    "Nice",
    "Rennes",
    "Montpellier",
    "Brest",
    "Grenoble",
    "Dijon",
    "Annecy",
    "Chamonix",
    "Rouen",
    "Reims",
    "Tours",
    "Angers",
    "Metz",
    "Biarritz",
    "Ajaccio",
    "Paris",
    "Clermont-Ferrand",
    "Perpignan",
    "Caen",
    "Limoges",
    "Avignon",
]
TOWNS_EN = [
    "London",
    "Berlin",
    "Madrid",
    "Rome",
    "New York",
    "Amsterdam",
    "Brussels",
    "Geneva",
    "Lisbon",
    "Dublin",
    "Barcelona",
    "Edinburgh",
    "Vienna",
    "Prague",
    "Munich",
    "Boston",
]
DAYS_FR = [
    "demain",
    "jeudi",
    "samedi",
    "ce week-end",
    "lundi prochain",
    "après-demain",
    "ce soir",
    "cette semaine",
    "vendredi",
    "dimanche",
]
DAYS_EN = [
    ("tomorrow", "tomorrow"),
    ("on Friday", "Friday"),
    ("this weekend", "this weekend"),
    ("on Monday", "Monday"),
    ("tonight", "tonight"),
    ("on Saturday", "Saturday"),
]
# (singular, plural, article, keyword, English plural)
KINDS = [
    ("restaurant", "restaurants", "un", "restaurant", "restaurants"),
    ("pharmacie", "pharmacies", "une", "pharmacy", "pharmacies"),
    ("hôtel", "hôtels", "un", "hotel", "hotels"),
    ("parking", "parkings", "un", "parking", "car parks"),
    ("boulangerie", "boulangeries", "une", "bakery", "bakeries"),
    ("café", "cafés", "un", "cafe", "coffee shops"),
    ("distributeur de billets", "distributeurs de billets", "un", "atm", "ATMs"),
    ("supermarché", "supermarchés", "un", "supermarket", "supermarkets"),
    ("coworking", "coworkings", "un", "coworking", "coworking spaces"),
    ("borne de recharge", "bornes de recharge", "une", "charging station", "charging stations"),
    ("librairie", "librairies", "une", "bookshop", "bookshops"),
    ("musée", "musées", "un", "museum", "museums"),
]
LANDMARKS = [
    ("la", "gare de Lyon"),
    ("la", "tour Eiffel"),
    ("la", "place Bellecour"),
    ("le", "Vieux-Port"),
    ("la", "gare Saint-Lazare"),
    ("l'", "aéroport de Nice"),
    ("le", "Louvre"),
    ("la", "gare Montparnasse"),
    ("le", "palais des congrès"),
    ("la", "cathédrale de Strasbourg"),
    ("le", "Capitole"),
    ("le", "Zénith de Nantes"),
    ("l'", "hôtel de ville de Lyon"),
    ("le", "musée d'Orsay"),
    ("la", "Cité des sciences"),
    ("le", "stade de France"),
]
LANDMARKS_EN = [
    "Times Square",
    "the Colosseum",
    "Gare du Nord",
    "the British Museum",
    "Central Park",
    "the Brandenburg Gate",
    "Big Ben",
    "the Sagrada Familia",
]
COMPANIES = [
    "Michelin",
    "Doctolib",
    "Decathlon",
    "Back Market",
    "Alan",
    "Qonto",
    "BlaBlaCar",
    "Leroy Merlin",
    "Danone",
    "Ornikar",
    "Manutan",
    "Free",
    "Carrefour",
    "Malt",
    "Mistral AI",
    "Contentsquare",
    "Ledger",
    "Veepee",
    "Lydia",
    "Swile",
    "Pennylane",
    "Withings",
    "Sézane",
    "Payfit",
]
SIRENS = ["552 100 554", "732 829 320", "552100554", "732829320"]
# (French word(s), English word, code)
CURRENCIES = [
    ("dollars", "dollars", "USD"),
    ("euros", "euros", "EUR"),
    ("livres", "pounds", "GBP"),
    ("yens", "yen", "JPY"),
    ("francs suisses", "Swiss francs", "CHF"),
    ("dollars canadiens", "Canadian dollars", "CAD"),
]
AMOUNTS = [
    ("50", 50),
    ("100", 100),
    ("250", 250),
    ("1 200", 1200),
    ("3 400", 3400),
    ("10 000", 10000),
    ("80", 80),
    ("2 500", 2500),
    ("75", 75),
    ("19,90", 19.9),
]
CITIES_FR = [
    "Tokyo",
    "New York",
    "Sydney",
    "Montréal",
    "Singapour",
    "Londres",
    "Dubaï",
    "Los Angeles",
    "São Paulo",
    "Bombay",
    "Pékin",
    "Hong Kong",
    "Moscou",
    "Mexico",
    "Chicago",
    "San Francisco",
    "Séoul",
    "Bangkok",
]
CITIES_EN = [
    "Tokyo",
    "New York",
    "Sydney",
    "Montreal",
    "Singapore",
    "London",
    "Dubai",
    "Los Angeles",
    "Seoul",
    "Chicago",
    "San Francisco",
    "Hong Kong",
]
PEOPLE = ["Paul", "Sophie", "Karim", "Julie", "Marc", "Anna", "le client", "l'équipe", "Mme Durand", "le comptable"]
PEOPLE_EN = ["John", "Anna", "the sales team", "Sarah", "the client", "David"]
HOURS = ["9h", "10h30", "14h", "16h", "11h", "17h", "8h30"]
SUBJECTS = [
    ("la", "tour Eiffel"),
    ("le", "Mont-Saint-Michel"),
    ("un", "koala"),
    ("le", "Taj Mahal"),
    ("la", "Joconde"),
    ("le", "pont du Gard"),
    ("", "Kyoto"),
    ("la", "Grande Muraille de Chine"),
    ("un", "panda roux"),
    ("le", "château de Chambord"),
    ("la", "Sagrada Familia"),
    ("le", "Machu Picchu"),
    ("", "Marrakech"),
    ("la", "cathédrale de Reims"),
    ("un", "lynx"),
    ("les", "calanques de Cassis"),
]
SUBJECTS_EN = [
    "a koala",
    "the Golden Gate Bridge",
    "the Grand Canyon",
    "the Burj Khalifa",
    "a red panda",
    "Mount Fuji",
    "the Eiffel Tower",
    "Stonehenge",
]
METRICS = ["ventes", "inscriptions", "tickets", "visites", "commandes", "candidatures"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin"]
TOPICS = [
    "le télétravail",
    "notre nouvelle offre",
    "la sécurité informatique",
    "le budget 2027",
    "la RSE",
    "l'onboarding des nouveaux",
    "la qualité de service",
    "le plan de formation",
]
STUDY = ["CRM", "logiciels de paie", "outils de visioconférence", "solutions de signature électronique",
         "ERP pour PME", "outils de gestion de projet"]  # fmt: skip


def _no_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def _art(article: str, name: str) -> str:
    return f"{article}{name}" if article.endswith("'") else (f"{article} {name}" if article else name)


def _de(article: str, name: str) -> str:
    """« de la gare de Lyon », « du Louvre », « de l'aéroport », « des calanques »."""
    return {"le": f"du {name}", "les": f"des {name}", "la": f"de la {name}", "l'": f"de l'{name}"}.get(
        article, f"de {name}"
    )


def _a(article: str, name: str) -> str:
    """« à la gare », « au Louvre », « à l'aéroport »."""
    return {"le": f"au {name}", "les": f"aux {name}", "la": f"à la {name}", "l'": f"à l'{name}"}.get(
        article, f"à {name}"
    )


# ---------------------------------------------------------------- items: (template id, lang, text, history, label)
# label = {"modules": [...], "agent": ..., "needs_web": ...} (router), plus "native": a call or None


def _lab(mods=(), agent="off", web=False, native=None) -> dict:
    return {"modules": [dict(m) for m in mods], "agent": agent, "needs_web": web, "native": native}


def _m(tool, **args) -> dict:
    return {"tool": tool, "args": args}


def weather(rng):
    for p in TOWNS_FR:
        for d in rng.sample(DAYS_FR, 4):
            for tid, t in (("wx1", f"météo à {p} {d}"), ("wx2", f"quel temps fera-t-il à {p} {d} ?"),
                           ("wx3", f"il va pleuvoir à {p} {d} ?"), ("wx4", f"prévisions météo pour {p} {d}"),
                           ("wx5", f"je dois prendre un parapluie à {p} {d} ?"),
                           ("wx6", f"quelle température à {p} {d} ?"), ("wx7", f"réunion {d} à {p}, il va faire beau ?"),
                           ("wx8", f"va-t-il neiger à {p} {d} ?")):  # fmt: skip
                m = _m("get_weather", place=p, day=d)
                yield tid, "fr", t, None, _lab([m], native=m)
        m = _m("get_weather", place=p)
        yield "wx9", "fr", f"la météo de {p} stp", None, _lab([m], native=m)
        yield "wx10", "fr", f"meteo {p.lower()}", None, _lab([_m("get_weather", place=p.lower())],
                                                             native=_m("get_weather", place=p.lower()))  # fmt: skip
    for p in TOWNS_EN:
        for written, d in rng.sample(DAYS_EN, 3):
            for tid, t in (("wxe1", f"weather in {p} {written}"), ("wxe2", f"will it rain in {p} {written}?"),
                           ("wxe3", f"do I need an umbrella in {p} {written}?"),
                           ("wxe4", f"forecast for {p} {written}")):  # fmt: skip
                m = _m("get_weather", place=p, day=d)
                yield tid, "en", t, None, _lab([m], native=m)


def places(rng):
    for sing, plur, art, key, en in KINDS:
        for a, lm in rng.sample(LANDMARKS, 5):
            for tid, t in (("pl1", f"{plur} près {_de(a, lm)}"), ("pl2", f"y a-t-il {art} {sing} près {_de(a, lm)} ?"),
                           ("pl3", f"des {plur} autour {_de(a, lm)}"), ("pl4", f"trouve {art} {sing} à côté {_de(a, lm)}")):  # fmt: skip
                m = _m("find_places", query=key, near=lm)
                yield tid, "fr", t, None, _lab([m], native=m)
        for town in rng.sample(TOWNS_FR, 4):
            for tid, t in (("pl5", f"trouve-moi {art} {sing} à {town}"), ("pl6", f"je cherche {art} {sing} à {town}")):
                m = _m("find_places", query=key, near=town)
                yield tid, "fr", t, None, _lab([m], native=m)
        for lm in rng.sample(LANDMARKS_EN, 3):
            m = _m("find_places", query=key, near=lm.removeprefix("the "))
            yield "ple1", "en", f"{en} near {lm}", None, _lab([m], native=m)
    for a, lm in LANDMARKS:
        m = _m("find_places", query=lm)
        for tid, t in (("pl7", f"où est {_art(a, lm)} ?"), ("pl8", f"c'est où {_art(a, lm)} ?"),
                       ("pl9", f"adresse {_de(a, lm)}"), ("pl10", f"localise {_art(a, lm)}")):  # fmt: skip
            yield tid, "fr", t, None, _lab([m], native=m)
    for lm in LANDMARKS_EN:
        m = _m("find_places", query=lm.removeprefix("the "))
        yield "ple2", "en", f"where is {lm}?", None, _lab([m], native=m)


def company(rng):
    for n in COMPANIES:
        m = _m("find_company", name=n)
        for tid, t in (("co1", f"fiche entreprise {n}"), ("co2", f"qui dirige {n} ?"), ("co3", f"le siren de {n}"),
                       ("co4", f"infos sur la société {n}"), ("co5", f"chiffre d'affaires de {n}"),
                       ("co6", f"peux-tu me trouver le kbis de la société {n}"),
                       ("coe1", f"who runs {n}?"), ("coe2", f"look up the company {n}")):  # fmt: skip
            yield tid, "en" if tid.startswith("coe") else "fr", t, None, _lab([m], native=m)
    for s in SIRENS:
        m = _m("find_company", name=s.replace(" ", ""))
        yield "co7", "fr", f"siren {s}", None, _lab([m], native=m)
        yield "co8", "fr", f"vérifie le siren {s} stp", None, _lab([m], native=m)


def fx(rng):
    for fr1, _en1, c1 in CURRENCIES:
        for fr2, _en2, c2 in CURRENCIES:
            if c1 == c2:
                continue
            for written, n in rng.sample(AMOUNTS, 3):
                m = _m("convert_currency", amount=n, **{"from": c1, "to": c2})
                for tid, t in (("fx1", f"{written} {fr1} en {fr2}"), ("fx2", f"convertis {written} {fr1} en {fr2}"),
                               ("fx3", f"combien font {written} {fr1} en {fr2} ?"),
                               ("fx4", f"{written} {fr1} ça fait combien en {fr2} ?"),
                               ("fxe1", f"how much is {written.replace(' ', ',')} {c1} in {c2}?"),
                               ("fxe2", f"convert {written.replace(' ', '')} {c1.lower()} to {c2.lower()}")):  # fmt: skip
                    if tid.startswith("fxe") and "," in written:
                        continue
                    yield tid, "en" if tid.startswith("fxe") else "fr", t, None, _lab([m], native=m)
            m = _m("convert_currency", **{"from": c1, "to": c2})
            yield "fx5", "fr", f"le taux {c1}/{c2} du jour", None, _lab([m], native=m)


def clock_items(rng):
    for c in CITIES_FR:
        for tid, t, mode in (("cl1", f"quelle heure est-il à {c} ?", "time"), ("cl2", f"il est quelle heure à {c}", "time"),
                             ("cl3", f"décalage horaire avec {c}", "offset"), ("cl4", f"quel décalage avec {c} ?", "offset"),
                             ("cl5", f"fuseau horaire de {c}", "offset")):  # fmt: skip
            yield tid, "fr", t, None, _lab([_m("clock", cities=[c], mode=mode)])
    for _ in range(40):
        a, b, c = rng.sample(CITIES_FR, 3)
        yield (
            "cl6",
            "fr",
            f"trouve un créneau commun {a} {b} {c} pour une réunion",
            None,
            _lab([_m("clock", cities=[a, b, c], mode="slot")]),
        )
        yield (
            "cl7",
            "fr",
            f"quel est le décalage horaire entre {a} et {b} ?",
            None,
            _lab([_m("clock", cities=[a, b], mode="offset")]),
        )
    for c in CITIES_EN:
        yield "cle1", "en", f"what time is it in {c}?", None, _lab([_m("clock", cities=[c], mode="time")])
        b = rng.choice([x for x in CITIES_EN if x != c])
        yield (
            "cle2",
            "en",
            f"time difference between {c} and {b}",
            None,
            _lab([_m("clock", cities=[c, b], mode="offset")]),
        )
        yield (
            "cle3",
            "en",
            f"best time for a meeting between {c} and {b}",
            None,
            _lab([_m("clock", cities=[c, b], mode="slot")]),
        )


def events(rng):
    days = ["jeudi", "mardi prochain", "demain", "vendredi", "le 3 décembre", "le 12/12", "lundi"]
    for p in PEOPLE:
        for d in rng.sample(days, 3):
            h = rng.choice(HOURS)
            for tid, t in (("ev1", f"cale une réunion avec {p} {d} à {h}"), ("ev2", f"programme un call avec {p} {d} à {h}"),
                           ("ev3", f"ajoute dans mon agenda un déjeuner avec {p} {d} à {h}"),
                           ("ev4", f"bloque un créneau avec {p} {d} à {h}")):  # fmt: skip
                yield tid, "fr", t, None, _lab([_m("event")])
    for p in PEOPLE_EN:
        for d in ("next Tuesday", "tomorrow", "on Friday"):
            yield "eve1", "en", f"schedule a meeting with {p} {d} at 3pm", None, _lab([_m("event")])


def charts(rng):
    for metric in METRICS:
        vals = [rng.randint(80, 200) for _ in range(4)]
        months = ", ".join(f"{m} {v}" for m, v in zip(MONTHS, vals, strict=False))
        for tid, t, kind in (("ch1", f"fais un graphique des {metric} : {months}", ""),
                             ("ch2", f"{metric} par trimestre : T1 {vals[0]}, T2 {vals[1]}, T3 {vals[2]}, T4 {vals[3]} — "
                                     "sous forme de courbe", "line"),
                             ("ch3", f"graphique en barres des {metric} : 2022 {vals[0]}, 2023 {vals[1]}, 2024 {vals[2]}", "bar")):  # fmt: skip
            got = figures_in(t)
            native = {"tool": "make_chart", "args": chart_call(t, got, "fr")} if got else None
            yield tid, "fr", t, None, _lab([_m("make_chart", **({"type": kind} if kind else {}))], native=native)
    for a, b, c in (("marketing", "RH", "IT"), ("CDI", "CDD", "intérim"), ("loyer", "courses", "transport")):
        p = sorted(rng.sample(range(10, 60), 2))
        t = f"un camembert de la répartition : {a} {p[0]} %, {b} {p[1] - p[0]} %, {c} {100 - p[1]} %"
        got = figures_in(t)
        yield "ch4", "fr", t, None, _lab([_m("make_chart", type="pie")],
                                         native={"tool": "make_chart", "args": chart_call(t, got, "fr")} if got else None)  # fmt: skip
    for indic in ("le chômage en France", "la population de Lyon", "le prix du gaz", "le smic", "l'inflation"):
        for y in ("2010", "2015", "2019"):
            yield (
                "ch5",
                "fr",
                f"l'évolution de {indic} depuis {y}",
                None,
                _lab([_m("make_chart", type="line")], web=True),
            )
    for metric in ("revenue by quarter", "website visits", "monthly signups"):
        yield "che1", "en", f"show me a chart of {metric}", None, _lab([_m("make_chart")])


def images(rng):
    for a, s in SUBJECTS:
        m = _m("images", subject=s)
        native = {"tool": "web_search", "args": {"query": s}}
        for tid, t in (("im1", f"montre-moi une photo {_de(a, s) if a else 'de ' + s}"),
                       ("im2", f"à quoi ressemble {_art(a, s)} ?"),
                       ("im3", f"des images {_de(a, s) if a else 'de ' + s}"),
                       ("im4", f"j'aimerais voir des photos {_de(a, s) if a else 'de ' + s}")):  # fmt: skip
            if tid == "im2" and a == "un":
                continue
            yield tid, "fr", t, None, _lab([m], native=native)
    for s in SUBJECTS_EN:
        subject = re.sub(r"^(?:the|a|an)\s+", "", s)
        yield (
            "ime1",
            "en",
            f"show me a picture of {s}",
            None,
            _lab([_m("images", subject=subject)], native={"tool": "web_search", "args": {"query": subject}}),
        )


def cards(rng):
    """The small modules (« card »): a positive only when the words hold the data; the same asks without data, and
    questions about the topic, are negatives (nothing to build, the model answers)."""
    def card(kind):
        return _lab([_m("card", kind=kind)])

    events = [("2015", "création à Lyon"), ("2017", "premier salarié"), ("2018", "premier client export"),
              ("2021", "levée de fonds"), ("2023", "ouverture de Lille"), ("2024", "rachat d'un concurrent")]  # fmt: skip
    for _ in range(6):
        ev = sorted(rng.sample(events, rng.choice([3, 4])))
        items = ", ".join(f"{y} {t}" for y, t in ev)
        for tid, t in (("cd1", f"fais une frise chronologique : {items}"), ("cd2", f"frise : {items}"),
                       ("cd3", f"mets ces dates sur une chronologie : {items}")):  # fmt: skip
            yield tid, "fr", t, None, card("timeline")
    for _ in range(3):
        yield "cde1", "en", "make a timeline: 2016 founded, 2019 first export, 2023 Series A", None, card("timeline")
    offers = [("Alpha", 120, 4), ("Beta", 95, 8), ("Gamma", 140, 2), ("Delta", 110, 6)]
    for k in (2, 3, 4):
        rows = "\n".join(f"| {a} | {p} € | {d} h |" for a, p, d in rng.sample(offers, k))
        t = f"compare ces offres :\n| Offre | Prix | Délai |\n|---|---|---|\n{rows}"
        yield "cd4", "fr", t, None, card("matrix")
    tasks = ["appeler le fournisseur", "envoyer le devis", "relancer Paul", "réserver la salle", "commander le traiteur",
             "mettre à jour le planning"]  # fmt: skip
    for _ in range(6):
        pick = rng.sample(tasks, rng.choice([3, 4]))
        yield "cd5", "fr", "transforme en liste de tâches :\n" + "\n".join(f"- {x}" for x in pick), None, card("tasks")
        yield "cd6", "fr", "fais une checklist : " + ", ".join(pick), None, card("tasks")
    for topic, pros, cons in (("télétravail", ["moins de trajets", "plus de calme"], ["isolement", "réunions longues"]),
                              ("la voiture électrique", ["silence", "coût au km"], ["prix d'achat", "autonomie"]),
                              ("un CRM", ["suivi des clients", "relances"], ["coût", "formation"])):  # fmt: skip
        t = f"pour et contre de {topic} : pour : {', '.join(pros)} ; contre : {', '.join(cons)}"
        yield "cd7", "fr", t, None, card("proscons")
        yield "cd8", "fr", f"avantages et inconvénients de {topic} : avantages : {', '.join(pros)} ; inconvénients : " \
            f"{', '.join(cons)}", None, card("proscons")
        yield "ng18", "fr", f"quels sont les avantages et inconvénients de {topic} ?", None, _lab()
    for ca, mg, n in (("1,2 M€", "18 %", "45"), ("3,4 M€", "9 %", "120"), ("850 k€", "22 %", "12")):
        yield "cd9", "fr", f"fais une fiche de chiffres clés : CA 2025 : {ca} ; marge : {mg} ; effectif : {n}", None, \
            card("figures")
        yield "cde2", "en", f"key figures: revenue: {ca}; margin: {mg}; headcount: {n}", None, card("figures")
    yield "ng19", "fr", "quels sont les chiffres clés du marché du vélo en France ?", None, _lab(web=True, agent="auto")
    yield "cd10", "fr", ("fais un glossaire :\nRGPD : règlement général sur la protection des données\nDPO : délégué à "
                         "la protection des données\nCNIL : Commission nationale de l'informatique et des libertés"), \
        None, card("glossary")
    yield "ng20", "fr", "fais un glossaire du RGPD", None, _lab()
    yield "ng20", "fr", "fais une frise de l'histoire de France", None, _lab()
    for amount in ("1 200", "3 450", "980"):
        yield "cd11", "fr", f"combien font 17 % de {amount} € ?", None, card("calc")
        yield "cd12", "fr", f"prix TTC de {amount} € HT avec une TVA à 20 %", None, card("calc")
    for p, y, r in (("200 000", 20, "3,5"), ("150 000", 15, "3,2"), ("300 000", 25, "3,9")):
        yield "cd13", "fr", f"mensualité d'un prêt de {p} € sur {y} ans à {r} %", None, card("calc")
    for t in ("donne-moi les sources de ta réponse", "montre-moi tes sources", "cite tes sources"):
        yield "cd14", "fr", t, None, card("sources")


def office(rng):
    for topic in TOPICS:
        n = rng.choice([3, 4, 5, 6, 8])
        yield "of1", "fr", f"fais une présentation de {n} slides sur {topic}", None, _lab([_m("office", kind="slides")])
        yield "of2", "fr", f"rédige une note sur {topic} pour le comité", None, _lab([_m("office", kind="document")])
        yield (
            "of3",
            "fr",
            f"prépare une présentation sur {topic} avec des chiffres récents",
            None,
            _lab([_m("office", kind="slides")], agent="auto", web=True),
        )
    for p in PEOPLE[:6]:
        for why in ("pour décaler la réunion", "pour relancer la facture 2025-114", "pour le remercier"):
            yield "of4", "fr", f"rédige un mail à {p} {why}", None, _lab([_m("office", kind="email")])
    for cols in ("nom, prénom, email", "date, montant, client", "tâche, responsable, échéance"):
        yield "of5", "fr", f"crée un tableur avec les colonnes {cols}", None, _lab([_m("office", kind="sheet")])
    for p in PEOPLE_EN[:4]:
        yield "ofe1", "en", f"draft an email to {p} to move the meeting", None, _lab([_m("office", kind="email")])
    for s in STUDY:
        yield (
            "ag1",
            "fr",
            f"fais une étude comparative des 3 principaux {s} du marché avec des sources",
            None,
            _lab([_m("office", kind="document")], agent="on", web=True),
        )
        yield (
            "ag2",
            "fr",
            f"j'ai besoin d'un benchmark des {s} du marché pour une PME",
            None,
            _lab([_m("office", kind="document")], agent="on", web=True),
        )
        yield (
            "age1",
            "en",
            f"write a comparative study of the main {s} on the market",
            None,
            _lab([_m("office", kind="document")], agent="on", web=True),
        )


NEG_FR = [  # (template id, text, office kind or "", needs_web, agent)
    ("ng1", "fais-moi la météo des marchés", "", True, "off"), ("ng1", "la météo sociale de l'entreprise", "", False, "off"),
    ("ng1", "la météo du projet est au vert", "", False, "off"), ("ng1", "fais la météo des ventes de la semaine", "", False, "off"),
    ("ng2", "comment réduire le temps de réponse du serveur ?", "", False, "off"),
    ("ng2", "comment réduire le temps de chargement de l'appli ?", "", False, "off"),
    ("ng3", "quel temps de livraison pour un colis vers Nantes ?", "", False, "off"),
    ("ng3", "quel temps de cuisson pour des pâtes ?", "", False, "off"),
    ("ng3", "quel temps faut-il pour valider une note de frais ?", "", False, "off"),
    ("ng4", "il pleut des bugs en production", "", False, "off"), ("ng4", "il neige des tickets au support", "", False, "off"),
    ("ng5", "quelle est la charte graphique de notre marque ?", "", False, "off"),
    ("ng5", "rédige une charte graphique pour notre startup", "document", False, "off"),
    ("ng6", "explique-moi la courbe en J", "", False, "off"), ("ng6", "notre courbe d'apprentissage est lente", "", False, "off"),
    ("ng7", "fais un diagramme de Gantt du projet", "", False, "off"),
    ("ng7", "dessine un diagramme de flux pour le processus de commande", "", False, "off"),
    ("ng8", "où en est le projet Atlas ?", "", False, "off"), ("ng8", "où est passé mon fichier ?", "", False, "off"),
    ("ng8", "où est le contrat de Paul Martin ?", "", False, "off"),
    ("ng9", "fais une carte mentale de mes idées", "", False, "off"), ("ng9", "ma carte graphique chauffe, que faire ?", "", False, "off"),
    ("ng10", "image de marque de notre entreprise", "", False, "off"), ("ng10", "droit à l'image des salariés", "", False, "off"),
    ("ng10", "génère une image de chat", "", False, "off"), ("ng10", "insère une photo de la tour Eiffel dans la présentation", "slides", False, "off"),
    ("ng11", "heure de pointe à Lyon, quel itinéraire ?", "", False, "off"), ("ng11", "combien d'heures sup ce mois-ci ?", "", False, "off"),
    ("ng11", "à quelle heure est la réunion ?", "", False, "off"), ("ng11", "point avec Londres entre 10h et 11h", "", False, "off"),
    ("ng12", "annule la réunion de jeudi à 14h", "", False, "off"), ("ng12", "décale le rdv de demain à 16h", "", False, "off"),
    ("ng12", "rédige le compte rendu de la réunion de lundi", "document", False, "off"),
    ("ng12", "comment organiser une réunion efficace ?", "", False, "off"),
    ("ng13", "convertis ce fichier en PDF", "", False, "off"), ("ng13", "le prix est de 45 dollars, c'est cher ?", "", False, "off"),
    ("ng13", "le taux de TVA en France", "", True, "off"),
    ("ng14", "dirigeants de PME : 5 conseils", "", False, "off"), ("ng14", "explique ce qu'est un numéro SIREN", "", False, "off"),
    ("ng14", "présente notre entreprise en 3 lignes", "", False, "off"),
    ("ng15", "Bonjour", "", False, "off"), ("ng15", "merci, c'est parfait !", "", False, "off"),
    ("ng15", "traduis ce texte en anglais", "", False, "off"), ("ng15", "résume ce document en 5 points", "", False, "off"),
    ("ng15", "écris une fonction Python qui trie une liste", "", False, "off"),
    ("ng15", "Explique la différence entre CDD et CDI", "", False, "off"),
    ("ng16", "c'est quoi un histogramme ?", "", False, "off"), ("ng16", "comment faire un graphique dans Excel ?", "", False, "off"),
    ("ng16", "quel graphique choisir pour montrer une répartition ?", "", False, "off"),
    ("ng17", "quelles sont les tendances du marketing digital en 2026 ?", "", True, "auto"),
    ("ng17", "l'évolution de carrière d'un comptable", "", False, "off"),
]  # fmt: skip
NEG_EN = [
    ("nge1", "sales forecast for Q3", "", False, "off"), ("nge1", "draft an email about the weather station launch", "email", False, "off"),
    ("nge2", "time management tips for managers", "", False, "off"), ("nge2", "show me pictures of our team", "", False, "off"),
    ("nge3", "where is the value in this deal", "", False, "off"), ("nge3", "how do I schedule a meeting in Outlook?", "", False, "off"),
    ("nge3", "convert this docx to pdf", "", False, "off"), ("nge3", "which chart should I use for market share?", "", False, "off"),
    ("nge4", "Hello", "", False, "off"), ("nge4", "thanks, that's perfect", "", False, "off"),
]  # fmt: skip


def negatives(rng):
    for tid, t, kind, web, agent in NEG_FR:
        yield tid, "fr", t, None, _lab([_m("office", kind=kind)] if kind else [], agent=agent, web=web)
    for tid, t, kind, web, agent in NEG_EN:
        yield tid, "en", t, None, _lab([_m("office", kind=kind)] if kind else [], agent=agent, web=web)


def false_triggers(rng):
    """Templated near misses of every family: the words of a module, never its request."""
    towns, people = TOWNS_FR, ["Paul Martin", "Sophie Leroy", "Julien", "Marie Dupont", "Karim"]
    days = ["lundi", "jeudi", "demain", "vendredi", "mardi prochain"]
    gen = []
    for x in ("des marchés", "sociale", "du projet", "des ventes", "de l'équipe", "du moral", "des projets", "interne"):
        for y in ("", " de la semaine", " du mois", " pour le comité"):
            gen.append(("nt1", f"fais-moi la météo {x}{y}", "", False))
            gen.append(("nt1", f"la météo {x}{y} est mauvaise", "", False))
    for x in ("réponse", "chargement", "calcul", "traitement"):
        for y in ("du serveur", "de l'appli", "du site", "de la base", "de l'API"):
            gen.append(("nt2", f"comment réduire le temps de {x} {y} ?", "", False))
    for x in ("livraison", "préparation", "validation", "traitement", "réponse"):
        for y in [f"un colis vers {t}" for t in rng.sample(towns, 3)] + ["le dossier Martin", "une commande"]:
            gen.append(("nt3", f"quel temps de {x} pour {y} ?", "", False))
    for x in ("bugs", "tickets", "réclamations", "mails"):
        gen.append(("nt4", f"il pleut des {x} depuis la mise à jour", "", False))
        gen.append(("nt4", f"une pluie de {x if x != 'bugs' else 'critiques'} sur le projet", "", False))
    for x in ("le projet", "le dossier", "le recrutement", "la migration", "le chantier"):
        for y in ("Atlas", "client", "de Lyon", "ERP", ""):
            gen.append(("nt5", f"où en est {x} {y} ?".replace("  ", " "), "", False))
    for x in ("le contrat", "le fichier", "la facture", "le devis", "le rapport"):
        for p in people:
            gen.append(("nt6", f"où est {x} de {p} ?", "", False))
    for t in TOPICS:
        gen.append(("nt7", f"fais une carte mentale sur {t}", "", False))
        gen.append(("nt7", f"un plan d'action pour {t}", "", False))
        gen.append(("nt8", f"rédige une charte graphique pour {t}", "document", False))
        gen.append(("nt8", f"fais un diagramme de Gantt pour {t}", "", False))
    for x in ("Excel", "Word", "Google Sheets", "PowerPoint"):
        gen.append(("nt9", f"comment faire un graphique dans {x} ?", "", False))
        gen.append(("nt9", f"comment insérer une courbe dans {x} ?", "", False))
    for x in ("notre entreprise", "la boîte", "notre marque", "la société"):
        gen.append(("nt10", f"comment améliorer l'image de marque de {x} ?", "", False))
    for x in ("un chat", "un logo", "une forêt", "un robot"):
        gen.append(("nt10", f"génère une image de {x}", "", False))
    for a, s in SUBJECTS[:6]:
        gen.append(("nt10", f"insère une photo {_de(a, s) if a else 'de ' + s} dans la présentation", "slides", False))
    for t in rng.sample(towns, 8):
        gen.append(("nt11", f"heure de pointe à {t}, quel itinéraire ?", "", False))
        gen.append(("nt11", f"point avec {t} entre 10h et 11h", "", False))
        gen.append(("nt11", f"trouve un créneau pour une réunion à {t}", "", False))
    for c in rng.sample(CITIES_FR, 5):
        gen.append(("nt11", f"combien d'heures de vol entre Paris et {c} ?", "", False))
    for d in days:
        for h in rng.sample(HOURS, 2):
            gen.append(("nt12", f"annule la réunion de {d} à {h}", "", False))
            gen.append(("nt12", f"décale le rdv de {d} à {h}", "", False))
        gen.append(("nt12", f"rédige le compte rendu de la réunion de {d}", "document", False))
        gen.append(("nt12", f"prépare l'ordre du jour de la réunion de {d}", "document", False))
        gen.append(("nt12", f"résume la réunion de {d}", "", False))
    for x in ("fichier", "texte", "document", "tableau"):
        for y in ("PDF", "Word", "majuscules"):
            gen.append(("nt13", f"convertis ce {x} en {y}", "", False))
    for written, _n in AMOUNTS[:6]:
        for fr, _en, _c in CURRENCIES[:3]:
            gen.append(("nt13", f"le prix est de {written} {fr}, c'est cher ?", "", False))
    for n in (3, 5, 7, 10):
        gen.append(("nt14", f"dirigeants de PME : {n} conseils", "", False))
        gen.append(("nt14", f"présente notre entreprise en {n} lignes", "", False))
    for x in ("trie une liste", "lit un CSV", "calcule une moyenne", "envoie une requête HTTP"):
        gen.append(("nt15", f"écris une fonction Python qui {x}", "", False))
    for n in (3, 5, 10):
        gen.append(("nt15", f"résume ce document en {n} points", "", False))
    for x in ("anglais", "espagnol", "allemand"):
        gen.append(("nt15", f"traduis ce paragraphe en {x}", "", False))
    for x in ("CDD et CDI", "SAS et SARL", "brut et net", "HT et TTC"):
        gen.append(("nt15", f"explique la différence entre {x}", "", False))
    for a, s in SUBJECTS[:10]:  # writing about a picture is a text task: no image search
        de = _de(a, s) if a else "de " + s
        for x in ("notre newsletter", "Instagram", "le site", "notre blog"):
            gen.append(("nt16", f"rédige la légende d'une photo {de} pour {x}", "", False))
        gen.append(("nt16", f"écris un texte alternatif pour la photo {de}", "", False))
    figs = ["Paris 12, Lyon 8, Marseille 5", "Q1 40, Q2 55, Q3 61", "Nord 120, Sud 95, Est 80, Ouest 60"]
    for fig in figs + ["janvier 14, février 18, mars 21"]:  # a table asked for: a table, never a chart
        gen.append(("nt17", f"mets en forme ce tableau : {fig}", "", False))
        gen.append(("nt17", f"fais un tableau propre avec ces chiffres : {fig}", "", False))
        gen.append(("nt17", f"présente ces données sous forme de tableau : {fig}", "", False))
    for t in rng.sample(towns, 6):  # a task on pasted text: the module words inside the quote are content
        gen.append(("nt18", f"résume ce mail : « Bonjour, la réunion de jeudi est maintenue. Météo à {t} demain : "
                            "pluie, prenez un parapluie. Cordialement »", "", False))  # fmt: skip
        gen.append(("nt18", f"corrige les fautes : « le rendez-vous au restaurant de {t} est reporter a lundi »", "",
                    False))  # fmt: skip
        gen.append(("nt18", f"reformule ce message : « l'horloge de l'agence de {t} retarde de dix minutes »", "",
                    False))  # fmt: skip
    for tid, text, kind, web in gen:
        yield tid, "fr", text, None, _lab([_m("office", kind=kind)] if kind else [], web=web)
    for x in SUBJECTS_EN[:6]:
        yield "nte2", "en", f"write a caption for a photo of {x}", None, _lab([])
        yield "nte2", "en", f"suggest alt text for our picture of {x}", None, _lab([])
    for fig in ("Berlin 7, Madrid 4, Rome 3", "Q1 40, Q2 55, Q3 61", "north 120, south 95, east 80"):
        yield "nte3", "en", f"format this table: {fig}", None, _lab([])
        yield "nte3", "en", f"put these figures in a table: {fig}", None, _lab([])
    for x in ("sales", "revenue", "demand"):
        for y in ("Q3", "next year", "2027"):
            yield "nte1", "en", f"{x} forecast for {y}", None, _lab([])
    for x in ("our team", "the party", "our office"):
        yield "nte1", "en", f"show me pictures of {x}", None, _lab([])
    for x in ("Outlook", "Teams", "Google Calendar"):
        yield "nte1", "en", f"how do I schedule a meeting in {x}?", None, _lab([])
    for x in ("this docx to pdf", "this text to uppercase", "these notes to a table"):
        yield "nte1", "en", f"convert {x}", None, _lab([])


def _history(tool, args, ask) -> list[dict]:
    memo = followup.memo_part({"tool": tool, "args": args}, "fr")
    return [{"role": "user", "content": ask}, {"role": "assistant", "content": f"Voilà.\n\n[Mémo de ce tour — {memo}]"}]


def followups(rng):
    for p in rng.sample(TOWNS_FR, 12):
        d = rng.choice(DAYS_FR)
        h = _history("get_weather", {"place": p, "day": d}, f"météo à {p} {d}")
        q = rng.choice([x for x in TOWNS_FR if x != p])
        m = _m("get_weather", place=q, day=d)
        yield "fu1", "fr", f"et à {q} ?", h, _lab([m], native=m)
        d2 = rng.choice([x for x in DAYS_FR if x != d])
        m = _m("get_weather", place=p, day=d2)
        yield "fu2", "fr", f"et {d2} ?", h, _lab([m], native=m)
        m = _m("find_places", query="restaurant", near=p)
        yield "fu3", "fr", "et des restaurants autour ?", h, _lab([m], native=m)
        for t in ("rédige un mail de relance pour la facture 2024-118", "ok", "merci", "et le projet ?"):
            yield "fu4", "fr", t, h, _lab([_m("office", kind="email")] if "mail" in t else [])
    for _sing, plur, _art, key, _en in rng.sample(KINDS, 6):
        a, lm = rng.choice(LANDMARKS)
        h = _history("find_places", {"query": key, "near": lm}, f"{plur} près {_de(a, lm)}")
        town = rng.choice(TOWNS_FR)
        m = _m("find_places", query=key, near=town)
        yield "fu5", "fr", f"et à {town} ?", h, _lab([m], native=m)
        m = _m("find_places", query="hotel", near=lm)
        yield "fu6", "fr", "et des hôtels ?", h, _lab([m], native=m)
    for fr1, _e1, c1 in CURRENCIES[:3]:
        h = _history("convert_currency", {"from": c1, "to": "EUR" if c1 != "EUR" else "USD", "amount": 100},
                     f"100 {fr1} en euros")  # fmt: skip
        to = "EUR" if c1 != "EUR" else "USD"
        for fr2, _e2, c2 in CURRENCIES[3:]:
            m = _m("convert_currency", amount=100, **{"from": c1, "to": c2})
            yield "fu7", "fr", f"et en {fr2} ?", h, _lab([m], native=m)
        m = _m("convert_currency", amount=500, **{"from": c1, "to": to})
        yield "fu8", "fr", "et 500 ?", h, _lab([m], native=m)
    for c in rng.sample(CITIES_FR, 8):
        h = _history("clock", {"cities": ["Tokyo"], "mode": "time"}, "quelle heure est-il à Tokyo")
        if c != "Tokyo":
            yield "fu9", "fr", f"et {c} ?", h, _lab([_m("clock", cities=[c], mode="time")])
    for n in rng.sample(COMPANIES, 6):
        h = _history("find_company", {"name": "Michelin"}, "qui dirige Michelin ?")
        if n != "Michelin":
            m = _m("find_company", name=n)
            yield "fu10", "fr", f"et {n} ?", h, _lab([m], native=m)


# ---------------------------------------------------------------- open data (catalogue family "opendata")
OD_YEARS = ["2026", "2027", "2028"]
OD_MONTHS = [("janvier", "01", "January"), ("mai", "05", "May"), ("juin", "06", "June"), ("août", "08", "August"),
             ("novembre", "11", "November"), ("décembre", "12", "December")]  # fmt: skip
OD_ZONES = [("en Alsace-Moselle", "alsace-moselle"), ("en Guadeloupe", "guadeloupe"), ("à La Réunion", "la-reunion"),
            ("en Allemagne", "DE"), ("en Belgique", "BE"), ("en Espagne", "ES"), ("en Italie", "IT")]  # fmt: skip
OD_ZONES_EN = [("in Germany", "DE"), ("in Spain", "ES"), ("in the UK", "GB"), ("in Ireland", "IE")]
OD_ENTITIES = ["Airbus", "l'OCDE", "l'Unesco", "la Banque mondiale", "Bpifrance", "le CNRS", "l'Insee", "Eurostat",
               "le Portugal", "la Slovénie", "Rennes", "Strasbourg", "le Mont-Saint-Michel", "l'ONU"]  # fmt: skip
OD_ENTITIES_EN = ["Airbus", "the OECD", "UNESCO", "the World Bank", "Portugal", "the Louvre"]
OD_INDICATORS = [("le chômage", "unemployment"), ("le taux de chômage", "unemployment"), ("l'inflation", "inflation"),
                 ("le PIB", "gdp"), ("la croissance du PIB", "gdp_growth"), ("la population", "population"),
                 ("les exportations", "exports")]  # fmt: skip
OD_INDICATORS_EN = [("unemployment", "unemployment"), ("inflation", "inflation"), ("GDP", "gdp"),
                    ("GDP growth", "gdp_growth"), ("population", "population")]  # fmt: skip
OD_COUNTRIES = [("en France", "France"), ("en Allemagne", "Allemagne"), ("en Espagne", "Espagne"),
                ("en Italie", "Italie"), ("au Japon", "Japon"), ("en Suède", "Suède"), ("aux Pays-Bas", "Pays-Bas")]  # fmt: skip
OD_COUNTRIES_EN = [("in France", "France"), ("in Germany", "Germany"), ("in Japan", "Japan"), ("in Spain", "Spain")]
OD_TENDERS = ["nettoyage de locaux", "maintenance informatique", "travaux de voirie", "restauration collective",
              "formation bureautique", "audit énergétique", "transport scolaire", "fourniture de mobilier"]  # fmt: skip
OD_WHERE = [("dans le Nord", "Nord"), ("en Bretagne", "Bretagne"), ("en Gironde", "Gironde"),
            ("dans le Rhône", "Rhône"), ("en Occitanie", "Occitanie")]  # fmt: skip
OD_TOPICS = ["batteries sodium-ion", "microbiote intestinal", "apprentissage fédéré", "pompes à chaleur",
             "agrivoltaïsme", "télétravail et productivité", "hydrogène vert"]  # fmt: skip
OD_TOPICS_EN = ["sodium-ion batteries", "federated learning", "heat pumps", "CRISPR gene editing", "green hydrogen"]
OD_DOIS = ["10.1038/nature14539", "10.1126/science.aaa8415", "10.1145/3065386"]
OD_COMMUNES = ["Roubaix", "Vierzon", "Saint-Malo", "Annecy", "Colmar", "Bayonne", "Saint-Denis", "Montauban"]
OD_ADDRESSES = ["20 av de segur paris", "8 bd du port 95000 cergy", "1 place de la mairie 69001 lyon",
                "12 rue nationale lille"]  # fmt: skip
OD_NEG = [  # (template id, text): the words of a card in writing, a how-to or the user's own data
    ("odn1", "rédige un mail pour prévenir que le bureau est fermé le jour férié"),
    ("odn1", "fais une note sur la politique des jours fériés"),
    ("odn2", "comment compter les jours ouvrés dans Excel ?"), ("odn2", "explique les jours ouvrables"),
    ("odn3", "c'est quoi un KPI ?"), ("odn3", "c'est quoi le chômage partiel ?"), ("odn3", "explique-moi le PIB"),
    ("odn4", "comment répondre à un appel d'offres ?"), ("odn4", "rédige notre mémoire technique pour l'appel d'offres"),
    ("odn5", "nos chiffres de ventes depuis 2015"), ("odn5", "la population cible de notre campagne"),
    ("odn6", "résume cet article scientifique"), ("odn6", "traduis le résumé de cette publication"),
    ("odn7", "corrige l'adresse dans la signature de mon mail"), ("odn7", "mets à jour l'adresse du client"),
    ("odne1", "how do I count working days in Google Sheets?"), ("odne1", "what is a call for tenders?"),
    ("odne2", "summarize this paper for me"), ("odne2", "write an email about the bank holiday"),
    # the user's own figures, leave and bids; a bare J+N; a task on the user's text (worded unlike the bench)
    ("odn8", "l'inflation de nos loyers depuis 2019"), ("odn8", "le taux de chômage de mon service depuis 2018"),
    ("odn8", "évolution des salaires de l'équipe depuis 2021"),
    ("odn9", "combien de jours de congés il me reste ?"), ("odn9", "jours ouvrés restants sur mon projet"),
    ("odn10", "calcule J+60 sur le devis du 15 mars"),
    ("odn11", "traduis : le chômage en Italie depuis 2012"), ("odn11", "relis ce texte : PIB de l'Espagne depuis 2005"),
    ("odn12", "les marchés publics que nous avons gagnés l'an dernier"),
    ("odne3", "translate to Spanish: bank holidays in France in 2027"),
    ("odne3", "rewrite this: GDP growth in Italy since 2010"), ("odne3", "how many leave days do I have left?"),
]  # fmt: skip


def opendata(rng):
    for y in OD_YEARS:
        for tid, t in (("od1", f"quels sont les jours fériés en {y} ?"), ("od2", f"liste des jours fériés {y}"),
                       ("od3", f"les fériés de {y} stp")):  # fmt: skip
            m = _m("work_calendar", period=y)
            yield tid, "fr", t, None, _lab([m], native=m)
        for z, code in OD_ZONES:
            m = _m("work_calendar", period=y, zone=code)
            yield "od4", "fr", f"jours fériés {z} en {y}", None, _lab([m], native=m)
        for z, code in OD_ZONES_EN:
            m = _m("work_calendar", period=y, zone=code)
            yield "ode1", "en", f"public holidays {z} in {y}", None, _lab([m], native=m)
        for mo, num, en in OD_MONTHS:
            m = _m("work_calendar", period=f"{y}-{num}")
            yield "od5", "fr", f"combien de jours ouvrés en {mo} {y} ?", None, _lab([m], native=m)
            yield "od6", "fr", f"jours fériés de {mo} {y}", None, _lab([m], native=m)
            yield "ode2", "en", f"how many working days in {en} {y}?", None, _lab([m], native=m)
    for n in (10, 15, 30, 45):
        m = _m("work_calendar", period="2026-12-03", add_days=n)
        yield "od7", "fr", f"J+{n} ouvrés à partir du 2026-12-03", None, _lab([m], native=m)
        yield "od8", "fr", f"quelle date à {n} jours ouvrés du 2026-12-03 ?", None, _lab([m], native=m)
    for e in OD_ENTITIES:
        name = re.sub(r"^(?:l'|le |la |les )", "", e)
        m = _m("lookup_entity", name=name)
        for tid, t in (("od9", f"c'est quoi {e} ?"), ("od10", f"fiche Wikipédia de {name}"),
                       ("od11", f"présente-moi {e} en bref")):  # fmt: skip
            yield tid, "fr", t, None, _lab([m], native=m)
    for e in OD_ENTITIES_EN:
        name = e.removeprefix("the ")
        m = _m("lookup_entity", name=name)
        yield "ode3", "en", f"tell me about {e}", None, _lab([m], native=m)
    for w, key in OD_INDICATORS:
        for place, name in rng.sample(OD_COUNTRIES, 3):
            for y in ("2010", "2015"):
                m = _m("get_statistics", indicator=key, places=name, since=y)
                for tid, t in (("od12", f"évolution de {w} {place} depuis {y}"),
                               ("od13", f"courbe de {w} {place} depuis {y}")):  # fmt: skip
                    yield tid, "fr", t, None, _lab([m], native=m)
        (p1, n1), (p2, n2) = rng.sample(OD_COUNTRIES, 2)
        m = _m("get_statistics", indicator=key, places=f"{n1}, {n2}", since="2012")
        yield "od14", "fr", f"compare {w} {p1} et {p2} depuis 2012", None, _lab([m], native=m)
    for w, key in OD_INDICATORS_EN:
        for place, name in OD_COUNTRIES_EN:
            m = _m("get_statistics", indicator=key, places=name, since="2010")
            yield "ode4", "en", f"{w} {place} since 2010", None, _lab([m], native=m)
    for c in OD_COMMUNES[:4]:
        m = _m("get_statistics", indicator="population", places=c, since="1990")
        yield "od15", "fr", f"évolution de la population de {c} depuis 1990", None, _lab([m], native=m)
    for q in OD_TENDERS:
        m = _m("find_tenders", query=q)
        yield "od16", "fr", f"appels d'offres {q}", None, _lab([m], native=m)
        yield "od17", "fr", f"trouve des marchés publics de {q}", None, _lab([m], native=m)
        for wtxt, w in rng.sample(OD_WHERE, 2):
            m = _m("find_tenders", query=q, where=w)
            yield "od18", "fr", f"appels d'offres {q} {wtxt}", None, _lab([m], native=m)
    for q in OD_TOPICS:
        for tid, t, order in (("od19", f"articles scientifiques sur {q}", None),
                              ("od20", f"publications récentes sur {q}", "recent"),
                              ("od21", f"les études les plus citées sur {q}", "cited")):  # fmt: skip
            m = _m("find_papers", query=q, **({"order": order} if order else {}))
            yield tid, "fr", t, None, _lab([m], native=m)
    for q in OD_TOPICS_EN:
        m = _m("find_papers", query=q)
        yield "ode5", "en", f"find papers on {q}", None, _lab([m], native=m)
    for d in OD_DOIS:
        m = _m("find_papers", query=d)
        yield "od22", "fr", f"vérifie ce DOI {d}", None, _lab([m], native=m)
        yield "ode6", "en", f"check DOI {d}", None, _lab([m], native=m)
    for c in OD_COMMUNES:
        m = _m("find_commune", name=c)
        for tid, t in (("od23", f"code postal de {c}"), ("od24", f"code INSEE de {c}"),
                       ("od25", f"dans quel département est {c} ?")):  # fmt: skip
            yield tid, "fr", t, None, _lab([m], native=m)
        yield "ode7", "en", f"postcode of {c}", None, _lab([m], native=m)
    for a in OD_ADDRESSES:
        m = _m("find_commune", name=a)
        yield "od26", "fr", f"normalise l'adresse {a}", None, _lab([m], native=m)
        yield "od27", "fr", f"vérifie cette adresse : {a}", None, _lab([m], native=m)
    for tid, t in OD_NEG:
        yield tid, "en" if tid.startswith("odne") else "fr", t, None, _lab([], web=False)


FAMILIES = (
    weather,
    places,
    company,
    fx,
    clock_items,
    events,
    charts,
    images,
    office,
    cards,
    negatives,
    false_triggers,
    followups,
    opendata,
)


# ---------------------------------------------------------------- variants (typing styles), checks, records


def _typo(text: str, keep: set[str], rng) -> str | None:
    words = text.split()
    idx = [i for i, w in enumerate(words) if len(w) >= 5 and w.isalpha() and R.fold(w) not in keep]
    if not idx:
        return None
    i = rng.choice(idx)
    w = words[i]
    j = rng.randrange(1, len(w) - 2)
    words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2 :]
    return " ".join(words)


def variants(text: str, lang: str, label: dict, rng) -> list[str]:
    keep = {R.fold(w) for m in label["modules"] for v in m["args"].values()
            for w in (v if isinstance(v, list) else [str(v)]) for w in R.fold(w).split()}  # fmt: skip
    out = [text]
    r = rng.random()
    if r < 0.35:
        out.append(_no_accents(text).lower().rstrip(" ?"))
    elif r < 0.55:
        out.append(("bonjour, " if lang == "fr" else "hi, ") + text)
    elif r < 0.7:
        out.append(text.rstrip(" ?") + (" stp" if lang == "fr" else " please"))
    elif r < 0.85 and (t := _typo(text, keep, rng)):
        out.append(t)
    return out


def check(text: str, history, label: dict) -> bool:
    """The label is valid (arguments), grounded in these words, and the harness can build its card."""
    ctx = R.previous_summary(history)
    for m in label["modules"]:
        args, why = catalog.check_args(m["tool"], m["args"])
        if args is None or R.ground(R.Call(m["tool"], args), text, ctx, detect_lang(text)):
            return False
        if m["tool"] == "clock" and not clock.detect(R.clock_text(R.Call("clock", args))):
            return False
        if m["tool"] == "event" and when.event_ask(text, NOW, detect_lang(text)) is None:
            return False
        if catalog.BY_NAME[m["tool"]].family == "opendata" and R.veto_reason(R.Call(m["tool"], args), text):
            return False  # a label the harness would refuse is never taught
    return True


def decision_json(label: dict) -> str:
    d = {"modules": label["modules"], "agent": label["agent"], "needs_web": label["needs_web"]}
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def router_record(text, lang, history, label, rng, rid: str, hints_on: bool | None = None) -> dict:
    hints = R.regex_decision(text, history=history, lang=lang, now=NOW)
    if hints_on is False or (hints_on is None and rng.random() < 0.3):
        hints = None  # no hints: the decision must stand on the words alone
    msgs = R.messages(text, history=history, hints=hints, lang=lang)
    msgs.append({"role": "assistant", "content": decision_json(label)})
    return {"id": rid, "source": SOURCE, "license": LICENSE, "lang": lang, "task": "router", "thinking": False,
            "messages": msgs}  # fmt: skip


def native_record(text, lang, history, label, rid: str) -> dict | None:
    call = label.get("native")
    if not call or history:  # a follow-up's earlier turn would be learnt too (birds.render.expand): router only
        return None
    tools = BIRD_TOOLS + [t for t in EXTRA_TOOLS if t["function"]["name"] in NATIVE | {"make_chart"}]
    msgs = [{"role": "system", "content": DEFAULT_SYSTEM[lang]}]
    msgs.append({"role": "user", "content": text})
    msgs.append({"role": "assistant", "content": "",
                 "tool_calls": [{"type": "function", "function": {"name": call["tool"], "arguments": call["args"]}}]})  # fmt: skip
    return {"id": rid, "source": SOURCE, "license": LICENSE, "lang": lang, "task": "tool_call_extra",
            "thinking": False, "tools": tools, "messages": msgs}  # fmt: skip


# share of the positive router records per family (the rest of the budget goes to negatives)
FAMILY_SHARE = {"weather": 0.09, "places": 0.10, "company": 0.05, "fx": 0.08, "clock_items": 0.07, "events": 0.05,
                "charts": 0.04, "images": 0.04, "office": 0.06, "followups": 0.06, "cards": 0.05,
                "opendata": 0.09}  # fmt: skip


def _negative(label: dict) -> bool:
    """No rich module (an office file or nothing): the false triggers, office prompts and chat."""
    return all(catalog.BY_NAME[m["tool"]].kind == catalog.HINT for m in label["modules"])


def _key(text: str, history) -> str:
    prev = R.previous_summary(history) if history else ""
    return R.fold(text) + "|" + R.fold(prev)


# ---------------------------------------------------------------- the data planner (task "data_plan")
# Synthetic tables of four shapes, each with templated questions and the typed spec Bird must answer
# (birds/harness/analysis/planner.py). Every label is checked by planner.check (the engine's own validation) and run
# once on its table; held-out templates go to eval. Negatives: requests that compute nothing ({"analysis": null}).
DATA_TABLES = {
    "ventes": ("Date;Région;Produit;Commercial;Montant (€);Quantité",
               lambda i, r: f"{1 + i % 28:02d}/{1 + i % 12:02d}/{2024 + i % 2};{r.choice(['Nord', 'Sud', 'Est', 'Ouest'])};"
                            f"{r.choice(['Alpha', 'Beta', 'Gamma', 'Delta'])};{r.choice(['Léa', 'Hugo', 'Nina'])};"
                            f"{r.randint(80, 4000)},{r.randint(0, 99):02d};{r.randint(1, 40)}"),
    "rh": ("Mois;Service;Site;Effectif;Absences (j);Salaire moyen (€)",
           lambda i, r: f"{1 + i % 12:02d}/{2023 + i % 3};{r.choice(['Finance', 'IT', 'Ventes', 'RH'])};"
                        f"{r.choice(['Paris', 'Lyon', 'Lille'])};{r.randint(5, 80)};{r.randint(0, 30)};{r.randint(2200, 5200)}"),
    "web": ("Date;Canal;Pays;Visites;Commandes;Revenu (€)",
            lambda i, r: f"{1 + i % 28:02d}/{1 + i % 12:02d}/2025;{r.choice(['SEO', 'Email', 'Social', 'Pub'])};"
                         f"{r.choice(['France', 'Belgique', 'Suisse'])};{r.randint(100, 9000)};{r.randint(0, 200)};"
                         f"{r.randint(0, 20000)}"),
    "budget": ("Poste;Département;Année;Budget (€);Réalisé (€)",
               lambda i, r: f"{r.choice(['Loyer', 'Salaires', 'Marketing', 'IT', 'Voyages'])};"
                            f"{r.choice(['Siège', 'Usine', 'Agence'])};{2023 + i % 3};{r.randint(1000, 90000)};"
                            f"{r.randint(1000, 90000)}"),
}  # fmt: skip
_AGG = {"total": "sum", "moyen": "mean", "médian": "median", "maximum": "max"}
# (template id, table, FR words, EN words, spec builder) ; {m} measure, {d} dimension, {d2} 2nd dimension, {n} top
DATA_TEMPLATES = [
    ("sum_by", None, "{m} total par {dl}", "total {m} by {dl}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "by": d, "sort": "desc"}, "bar")),
    ("mean_by", None, "{m} moyen par {dl}", "average {m} per {dl}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "mean", "by": d, "sort": "desc"}, "bar")),
    ("top_n", None, "les {n} {dl} avec le plus de {m}", "top {n} {dl} by {m}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "by": d, "sort": "desc", "top": n}, "hbar")),
    ("bottom_n", None, "les {n} {dl} les plus faibles en {m}", "the {n} {dl} with the least {m}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "by": d, "sort": "asc", "top": n}, "hbar")),
    ("share", None, "quelle part de {m} pour chaque {dl} ?", "share of {m} for each {dl}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "by": d, "sort": "desc", "share": True},
                             "donut")),
    ("pivot", None, "{m} par {dl} et par {d2l}", "{m} by {dl} and {d2l}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "by": d, "pivot": d2}, "stacked")),
    ("heat", None, "carte de chaleur de {m} par {dl} et {d2l}", "heat map of {m} by {dl} and {d2l}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "by": d, "pivot": d2}, "heatmap")),
    ("monthly", "time", "évolution mensuelle de {m}", "monthly {m}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "time": t, "period": "month"}, "line")),
    ("moving", "time", "{m} par mois avec une moyenne mobile sur {n} mois", "{m} per month with a {n}-month moving average",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "time": t, "period": "month",
                              "window": max(2, n)}, "combo")),
    ("change", "time", "variation en % de {m} d'un trimestre à l'autre", "quarter-on-quarter % change of {m}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "time": t, "period": "quarter",
                              "change": True}, "combo")),
    ("filtered", None, "{m} total par {d2l}, seulement pour {v}", "total {m} by {d2l}, only for {v}",
     lambda m, d, d2, t, n: ({"op": "aggregate", "measure": m, "agg": "sum", "by": d2, "sort": "desc"}, "bar")),
    ("compare_by", "years", "compare {y1} et {y2} par {dl}", "compare {y1} and {y2} by {dl}",
     lambda m, d, d2, t, n: ({"op": "compare", "measure": m, "agg": "sum", "time": t, "years": n, "by": d}, "bar")),
    ("corr", "two", "y a-t-il un lien entre {m} et {m2} ?", "is {m} related to {m2}?",
     lambda m, d, d2, t, n: ({"op": "corr", "x": m, "y": n}, "scatter")),
    ("describe", None, "distribution de {m}", "distribution of {m}",
     lambda m, d, d2, t, n: ({"op": "describe", "measure": m}, "auto")),
]  # fmt: skip
DATA_NEGATIVES = [
    ("résume ce fichier", "summarise this file"), ("traduis les en-têtes en anglais", "translate the headers into French"),
    ("rédige un mail à l'équipe avec ce tableau", "write an email to the team about this table"),
    ("explique-moi ce que contient ce tableau", "explain what this table contains"),
    ("corrige l'orthographe des noms", "fix the spelling of the names"), ("merci !", "thanks!"),
]  # fmt: skip
# the table is already in the conversation (an analysis was shown) and the message is about something else: null
# (review 28/11/2026: the rules turned each of these into « sum of the main measure »)
DATA_UNRELATED = [
    ("quelle est la population de Canberra ?", "what is the population of Canberra?"),
    ("combien font 17 x 23 ?", "what is 17 times 23?"),
    ("quel temps fera-t-il demain à Lyon ?", "what will the weather be like in Lyon tomorrow?"),
    ("combien coûte un abonnement Bird ?", "how much is a Bird subscription?"),
    ("quelle est la meilleure façon de présenter ce fichier à mon chef ?", "what is the best way to present this file "
     "to my boss?"),
]  # fmt: skip


def _short_col(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip().lower()


DATA_HELDOUT = ("heat", "bottom_n")


def data_plan_records(seed: int = 0, heldout=DATA_HELDOUT) -> dict:
    from birds.harness.analysis import planner as P
    from birds.harness.analysis.profile import frame_of
    from birds.harness.analysis.query import run_query
    from birds.harness.analysis.table import read_text_table

    rng = random.Random(f"{seed}-data")
    out = {"train": [], "eval": []}
    for tname, (head, row) in DATA_TABLES.items():
        text = head + "\n" + "\n".join(row(i, rng) for i in range(120))
        f = frame_of(read_text_table(text, f"{tname}.csv"))
        nums = [c.name for c in f.columns if c.type == "number"]
        cats = [c.name for c in f.columns if c.type in ("category", "bool")]
        dates = [c.name for c in f.columns if c.type == "date"]
        for tid, need, fr, en, build_spec in DATA_TEMPLATES:
            years = sorted({v.year for v in f.col(dates[0]).values if v is not None})[-2:] if dates else []
            if (need in ("time", "years") and not dates) or (need == "years" and len(years) < 2) \
                    or (need == "two" and len(nums) < 2) or len(cats) < 2:  # fmt: skip
                continue
            for lang in ("fr", "en"):
                m, m2 = rng.sample(nums, 2) if len(nums) > 1 else (nums[0], nums[0])
                d, d2 = rng.sample(cats, 2)
                n = rng.choice([3, 5, 10])
                v = next(x for x in f.col(d).values if x is not None)
                arg = m2 if tid == "corr" else years if tid == "compare_by" else n
                spec, chart = build_spec(m, d, d2, dates[0] if dates else None, arg)
                if tid == "filtered":
                    spec["filters"] = [{"col": d, "op": "eq", "value": v}]
                words = (fr if lang == "fr" else en).format(m=_short_col(m), m2=_short_col(m2), dl=_short_col(d),
                                                          d2l=_short_col(d2), n=n, v=v,
                                                          y1=years[0] if years else "", y2=years[-1] if years else "")  # fmt: skip
                plan, why = P.check(f, {"analysis": spec, "chart": chart})
                if why:
                    raise SystemExit(f"data template {tid} on {tname}: {why}")
                run_query(f, plan["query"], lang)
                hints = P.rule_plan(f, words) if rng.random() < 0.7 else None
                msgs = P.messages(f, words, hints=hints, lang=lang)
                msgs.append({"role": "assistant", "content": P._dump({"analysis": spec, "chart": chart})})
                split = "eval" if tid in heldout else "train"
                out[split].append({"id": f"{SOURCE}-data-{split}-{tname}-{tid}-{lang}", "source": SOURCE,
                                   "license": LICENSE, "lang": lang, "task": "data_plan", "thinking": False,
                                   "messages": msgs, "template": f"data_{tid}"})  # fmt: skip
        # follow-ups with the previous turn's spec: « par {d2} » edits the category, keeps measure and aggregation;
        # an unrelated message computes nothing
        m, d, d2 = nums[0], cats[0], cats[1]
        prev = {"analysis": {"op": "aggregate", "measure": m, "agg": "mean", "by": d, "sort": "desc"}, "chart": "bar"}
        follow = [("by", ("par " if lang == "fr" else "by ") + _short_col(d2), lang,
                   {"analysis": {**prev["analysis"], "by": d2}, "chart": "bar"}) for lang in ("fr", "en")]
        follow += [(f"unrelated{j}", words, lang, {"analysis": None, "chart": "auto"})
                   for j, pair in enumerate(DATA_UNRELATED) for lang, words in zip(("fr", "en"), pair, strict=True)]
        for fid, words, lang, answer in follow:
            if answer["analysis"]:
                plan, why = P.check(f, answer)
                if why:
                    raise SystemExit(f"data follow-up {fid} on {tname}: {why}")
                run_query(f, plan["query"], lang)
            msgs = P.messages(f, words, previous=prev, hints=P.rule_plan(f, words, prev), lang=lang)
            msgs.append({"role": "assistant", "content": P._dump(answer)})
            out["train"].append({"id": f"{SOURCE}-data-train-{tname}-follow-{fid}-{lang}", "source": SOURCE,
                                 "license": LICENSE, "lang": lang, "task": "data_plan", "thinking": False,
                                 "messages": msgs, "template": "data_none" if answer["analysis"] is None
                                 else f"data_follow_{fid}"})  # fmt: skip
        for j, (fr, en) in enumerate(DATA_NEGATIVES):
            for lang, words in (("fr", fr), ("en", en)):
                msgs = P.messages(f, words, hints=P.rule_plan(f, words), lang=lang)
                msgs.append({"role": "assistant", "content": P._dump({"analysis": None, "chart": "auto"})})
                out["train"].append({"id": f"{SOURCE}-data-train-{tname}-neg{j}-{lang}", "source": SOURCE,
                                     "license": LICENSE, "lang": lang, "task": "data_plan", "thinking": False,
                                     "messages": msgs, "template": "data_none"})  # fmt: skip
    return out


def build(n: int = 6000, seed: int = 0, heldout_share: float = 0.12) -> dict:
    import router_data as D

    rng = random.Random(seed)
    bench = {R.fold(it["text"]) for it in D.items()}
    raw = []
    for fam in FAMILIES:
        for tid, lang, text, history, label in fam(random.Random(f"{seed}-{fam.__name__}")):
            raw.append((fam.__name__, tid, lang, text, history, label))
    tids = sorted({r[1] for r in raw})
    held = {t for t in tids if int(hashlib.sha1(f"{seed}{t}".encode()).hexdigest(), 16) % 1000 < heldout_share * 1000}
    seen: set[str] = set()
    pool = {"train": [], "eval": []}
    stats = {"rejected_label": 0, "duplicate": 0, "bench_overlap": 0}
    for fam, tid, lang, text, history, label in raw:
        for v in variants(text, lang, label, rng):
            k = _key(v, history)
            if k in seen:
                stats["duplicate"] += 1
                continue
            seen.add(k)
            if R.fold(v) in bench and not history:
                stats["bench_overlap"] += 1
                continue
            if not check(v, history, label):
                stats["rejected_label"] += 1
                continue
            pool["eval" if tid in held else "train"].append((fam, tid, lang, v, history, label))
    out = {"train": [], "eval": [], "bench_heldout": []}
    for split, items in pool.items():
        rng.shuffle(items)
        neg = [x for x in items if _negative(x[5])]
        pos = [x for x in items if not _negative(x[5])]
        # a negative the parsers misread comes twice, with their (wrong) hints and without: the model learns to
        # overrule them
        picked = [(x, True) for x in neg]
        picked += [(x, False) for x in neg if R.regex_decision(x[3], history=x[4], lang=x[2], now=NOW).modules]
        budget = n if split == "train" else max(1, n // 8)
        share = {f: max(1, int(budget * w)) for f, w in FAMILY_SHARE.items()}
        for x in pos:
            if share.get(x[0], 0) > 0 and len(picked) < budget:
                share[x[0]] -= 1
                picked.append((x, None))
        rng.shuffle(picked)
        for i, ((_fam, tid, lang, text, history, label), hints_on) in enumerate(picked[:budget]):
            rec = router_record(text, lang, history, label, rng, f"{SOURCE}-{split}-r{i:06d}", hints_on)
            out[split].append({**rec, "template": tid})
            nat = native_record(text, lang, history, label, f"{SOURCE}-{split}-n{i:06d}") if hints_on is None else None
            if nat:
                out[split].append({**nat, "template": tid})
    for i, it in enumerate(D.items()):  # the bench, for evaluation only
        lab = D.oracle(it)
        out["bench_heldout"].append(
            router_record(
                it["text"],
                detect_lang(it["text"]),
                it["history"],
                {**lab, "native": None},
                rng,
                f"{SOURCE}-bench-{i:06d}",
            )
            | {"family": it["family"], "label": it["label"]}  # fmt: skip
        )
    data = data_plan_records(seed)  # the analysis planner (birds/harness/analysis/planner.py)
    for split in ("train", "eval"):
        out[split] += data[split]
        rng.shuffle(out[split])
    bad = [(r["id"], errors(r)) for s in out.values() for r in s if errors({k: v for k, v in r.items()
                                                                             if k not in ("family", "label")})]  # fmt: skip
    if bad:
        raise SystemExit(f"invalid records: {bad[:3]}")
    st = {"filtered": stats, "templates": len(tids) + len(DATA_TEMPLATES),
          "held_out_templates": sorted(held | {f"data_{t}" for t in DATA_HELDOUT})}  # fmt: skip
    for split, rows in out.items():
        st[split] = {
            "records": len(rows),
            "router": sum(r["task"] == "router" for r in rows),
            "tool_call_extra": sum(r["task"] == "tool_call_extra" for r in rows),
            "data_plan": sum(r["task"] == "data_plan" for r in rows),
            "fr": sum(r["lang"] == "fr" for r in rows),
            "negatives": sum(
                r["task"] == "router" and _negative(json.loads(r["messages"][-1]["content"])) for r in rows
            ),  # fmt: skip
            "follow_ups": sum(
                r["task"] == "router" and "Tour précédent" in r["messages"][-2]["content"] for r in rows
            ),  # fmt: skip
        }
    rx = reflexion_records(seed)  # Mode Réflexion: the level decision (task « reflexion »)
    for split in ("train", "eval"):
        out[split] += rx[split]
        st[split]["reflexion"] = len(rx[split])
        st[split]["records"] += len(rx[split])
        st[split]["fr"] += sum(r["lang"] == "fr" for r in rx[split])
    st["held_out_templates"] = sorted(set(st["held_out_templates"]) | set(rx["held"]))
    ns = nextsteps_records(seed)  # next steps under an answer (task « nextsteps »)
    for split in ("train", "eval"):
        out[split] += ns[split]
        st[split]["nextsteps"] = len(ns[split])
        st[split]["records"] += len(ns[split])
        st[split]["fr"] += sum(r["lang"] == "fr" for r in ns[split])
    st["held_out_templates"] = sorted(set(st["held_out_templates"]) | set(ns["held"]))
    out["stats"] = st
    return out


# ---------------------------------------------------------------- Mode Réflexion: the level decision of « Auto »
# (birds/harness/reflexion.py). The exact prompt (reflexion.messages) and {"level": …} as the one assistant turn.
# The eval phrasings of router_data.REFLEXION_LEVELS never reach train.

RX_TEMPLATES = [  # (template id, lang, level, phrasings with {slots})
    ("rx_hello", "fr", "colibri", ["bonjour", "salut !", "coucou Bird", "merci !", "super, merci", "d'accord, parfait",
                                   "bonne soirée", "qui es-tu ?", "ok merci, ça ira"]),
    ("rx_fact", "fr", "colibri", ["quelle est la capitale du {pays} ?", "traduis « {mot} » en anglais",
                                  "comment dit-on « {mot} » en espagnol ?", "en quelle année a eu lieu la prise de la "
                                  "Bastille ?"]),
    ("rx_hello_en", "en", "colibri", ["hello", "hi Bird", "thank you!", "great, thanks", "good night",
                                      "what is the capital of {country}?", "translate « {mot} » into French"]),
    ("rx_write", "fr", "hirondelle", ["rédige un mail à {qui} pour {objet}", "écris un message à {qui} pour {objet}",
                                      "prépare une réponse polie à {qui} pour {objet}",
                                      "résume ce compte rendu en {n} points", "donne-moi {n} idées pour {sujet}",
                                      "explique simplement ce qu'est {notion}", "propose un plan pour {sujet}"]),
    ("rx_write_en", "en", "hirondelle", ["draft an email to {who} to {task}", "write a short note to {who} to {task}",
                                         "summarize these notes in {n} bullet points",
                                         "give me {n} ideas for {topic_en}", "explain {notion_en} in plain words"]),
    ("rx_calc", "fr", "faucon", ["combien font {a} € HT avec une TVA à 20 % ?", "une remise de {p} % sur {a} €, "
                                 "ça fait combien ?", "{a} € par mois pendant {n} ans, ça fait combien au total ?",
                                 "compare {a} € par mois et {b} € par an : lequel est le moins cher ?",
                                 "quel est le taux de marge si j'achète {b} € et je vends {a} € ?",
                                 "écris une fonction Python qui {code}", "corrige ce code : {snippet}",
                                 "combien de jours ouvrés entre le {d1} et le {d2} ?"]),
    ("rx_calc_en", "en", "faucon", ["what is {p}% of {a} dollars?", "compare {a} a month with {b} a year: which is "
                                    "cheaper?", "write a Python function that {code_en}",
                                    "how many working days are there between {d1_en} and {d2_en}?"]),
    ("rx_deep", "fr", "chouette", ["analyse les risques et les opportunités de {projet}",
                                   "quelle stratégie adopter pour {projet} ? pèse les arguments",
                                   "fais un diagnostic complet de {projet} avec les scénarios possibles",
                                   "évalue les avantages et les inconvénients de {projet} pour une PME de {n} personnes"]),
    ("rx_deep_en", "en", "chouette", ["analyze the risks and opportunities of {projet_en}",
                                      "what strategy should we adopt for {projet_en}? weigh the arguments",
                                      "evaluate the trade-offs of {projet_en} for a company of {n} people"]),
]
RX_SLOTS = {
    "pays": ["Portugal", "Canada", "Japon", "Pérou", "Kenya"], "country": ["Peru", "Norway", "Japan", "Chile"],
    "mot": ["bonjour", "merci", "à bientôt", "réunion", "facture"],
    "qui": ["Paul", "l'équipe", "le client", "Mme Durand", "le comptable"], "who": ["John", "the team", "a client"],
    "objet": ["décaler la réunion à jeudi", "relancer la facture de mars", "remercier pour le rendez-vous",
              "annoncer le nouveau planning"],
    "task": ["move the meeting to Friday", "follow up on the March invoice", "thank them for the visit"],
    "n": ["3", "5", "4", "10"], "sujet": ["le séminaire d'équipe", "la newsletter de juin", "un atelier client"],
    "topic_en": ["a team offsite", "our June newsletter"], "notion": ["l'inflation", "un tableau croisé dynamique",
                                                                     "la TVA intracommunautaire"],
    "notion_en": ["inflation", "a pivot table"], "a": ["1 250", "89", "2 400", "14,90", "560"],
    "b": ["149", "980", "1 800", "1 200"], "p": ["12", "15", "7,5", "30"],
    "code": ["calcule la moyenne pondérée d'une liste", "trie des factures par date", "compte les mots d'un texte"],
    "code_en": ["computes a weighted average", "sorts invoices by date"], "snippet": ["for i in range(10) print(i)",
                                                                                      "SELECT * FROM t WHERE"],
    "d1": ["3 mars", "12 avril"], "d2": ["28 mars", "5 mai"], "d1_en": ["March 3"], "d2_en": ["March 28"],
    "projet": ["passer à la semaine de quatre jours", "ouvrir une deuxième agence à Lyon",
               "remplacer notre ERP", "lancer une offre d'abonnement"],
    "projet_en": ["a four-day week", "opening a second office", "replacing our ERP"],
}  # fmt: skip


def reflexion_records(seed: int = 0, heldout_share: float = 0.12) -> dict:
    """{"train": […], "eval": […], "held": [template ids]}: one record per filled phrasing (and its accentless,
    lowercase variant), templates held out whole like the router's."""
    import router_data as D

    from birds.harness import reflexion as RX

    rng = random.Random(f"{seed}-reflexion")
    banned = {R.fold(t) for t, _ in D.REFLEXION_LEVELS}
    held = {t for t, *_ in RX_TEMPLATES if int(hashlib.sha1(f"{seed}{t}".encode()).hexdigest(), 16) % 1000
            < heldout_share * 1000 * 2}  # fmt: skip
    out, seen = {"train": [], "eval": [], "held": sorted(held)}, set()
    for tid, lang, level, phrasings in RX_TEMPLATES:
        for ph in phrasings:
            for _ in range(3):
                text = re.sub(r"\{(\w+)\}", lambda m: rng.choice(RX_SLOTS[m.group(1)]), ph)
                for v in (text, _no_accents(text).lower()):
                    k = R.fold(v)
                    if k in seen or k in banned:
                        continue
                    seen.add(k)
                    split = "eval" if tid in held else "train"
                    msgs = RX.messages(v, lang) + [{"role": "assistant", "content": RX.decision_json(level)}]
                    out[split].append({"id": f"{SOURCE}-{split}-x{len(out[split]):06d}", "source": SOURCE,
                                       "license": LICENSE, "lang": lang, "task": "reflexion", "thinking": False,
                                       "messages": msgs, "template": tid})  # fmt: skip
    return out


# ---------------------------------------------------------------- next steps (birds/harness/nextsteps.py)
# The exact prompt (nextsteps.messages with the full capabilities line) and the suggestions JSON as the one
# assistant turn: in the user's voice, specific, the options of Bird's question as the user's answers, none after
# small talk. The eval cases of router_data.NEXTSTEPS_CASES never reach train.

NS_TEMPLATES = [  # (template id, lang, request, answer, [(needs, label, prompt)]) with {slots}
    ("ns_ask_format", "fr", "j'ai besoin de présenter {sujet} à {qui}",
     "Je peux préparer ce support sur {sujet}. Préférez-vous une présentation ou une note d'une page ?",
     [("office", "Fais une présentation", "Fais une présentation de {sujet} pour {qui}."),
      ("office", "Rédige une note d'une page", "Rédige une note d'une page sur {sujet} pour {qui}.")]),
    ("ns_ask_detail", "fr", "explique-moi {notion}",
     "{Notion} désigne… Voulez-vous un exemple chiffré ou une version plus courte ?",
     [("write", "Donne un exemple chiffré", "Donne un exemple chiffré de {notion}."),
      ("write", "Fais une version plus courte", "Explique {notion} en trois phrases.")]),
    ("ns_mail", "fr", "rédige un mail à {qui} pour {objet}",
     "Objet : {Objet}\n\nBonjour, je vous écris pour {objet}…",
     [("office", "Rends le ton plus chaleureux", "Rends ce mail à {qui} plus chaleureux."),
      ("office", "Ajoute une date limite", "Ajoute au mail une date limite de réponse."),
      ("office", "Traduis-le en anglais", "Traduis ce mail en anglais.")]),
    ("ns_deck", "fr", "fais une présentation sur {sujet}",
     "La présentation « {Sujet} » est dans le canevas : 5 diapositives.",
     [("office", "Ajoute une diapo de chiffres clés", "Ajoute une diapositive de chiffres clés sur {sujet}."),
      ("office", "Ajoute une conclusion", "Ajoute une diapositive de conclusion avec trois messages clés.")]),
    ("ns_info", "fr", "écris un mail à {qui} pour {objet}",
     "Il me manque l'adresse et la date. Pouvez-vous me les donner ?",
     [("office", "Rédige-le avec des champs à compléter", "Rédige le mail à {qui} avec l'adresse et la date à compléter.")]),
    ("ns_hello", "fr", "{salut}", "Bonjour ! Comment puis-je vous aider ?", []),
    ("ns_thanks", "fr", "{merci}", "Avec plaisir ! Bonne journée.", []),
    ("ns_ask_en", "en", "help me prepare {topic_en}",
     "Here is an outline for {topic_en}. Would you like a checklist or a timeline?",
     [("write", "Make a checklist", "Make a checklist for {topic_en}."),
      ("write", "Draw up a timeline", "Draw up a timeline for {topic_en}.")]),
    ("ns_mail_en", "en", "draft an email to {who} to {task}",
     "Subject: Quick update\n\nHi, I am writing to {task}…",
     [("office", "Make it shorter", "Make this email to {who} shorter."), ("office", "Add a call to action", "Add a clear call to action.")]),
    ("ns_thanks_en", "en", "{thanks_en}", "You're welcome! Have a great day.", []),
]
NS_SLOTS = {
    "sujet": ["le budget 2027", "notre offre de formation", "le plan de recrutement", "la nouvelle politique RSE"],
    "qui": ["le comité de direction", "l'équipe", "nos clients", "le conseil d'administration"],
    "notion": ["la TVA intracommunautaire", "l'amortissement", "le BFR", "la marge brute"],
    "objet": ["décaler la réunion à jeudi", "relancer le devis de mars", "remercier pour le rendez-vous"],
    "salut": ["bonjour", "salut !", "coucou Bird"], "merci": ["merci !", "super, merci", "parfait, merci beaucoup"],
    "topic_en": ["a client workshop", "our quarterly review", "a product launch"],
    "who": ["John", "the team", "a supplier"], "task": ["move the meeting to Friday", "confirm the order"],
    "thanks_en": ["thanks!", "great, thank you", "perfect, thanks"],
}  # fmt: skip


def nextsteps_records(seed: int = 0, heldout_share: float = 0.12) -> dict:
    """{"train": […], "eval": […], "held": [template ids]}, like reflexion_records."""
    import router_data as D

    from birds.harness import nextsteps as N

    rng = random.Random(f"{seed}-nextsteps")
    banned = {R.fold(c[2]) for c in D.NEXTSTEPS_CASES}
    held = {t for t, *_ in NS_TEMPLATES if int(hashlib.sha1(f"{seed}{t}".encode()).hexdigest(), 16) % 1000
            < heldout_share * 1000 * 2}  # fmt: skip
    caps = {lg: N.capabilities(lg, None, None) for lg in ("fr", "en")}
    out, seen = {"train": [], "eval": [], "held": sorted(held)}, set()

    def fill(text: str, pick: dict) -> str:
        def one(m):
            k = m.group(1)
            v = pick.setdefault(k.lower(), rng.choice(NS_SLOTS[k.lower()]))
            return v[:1].upper() + v[1:] if k[:1].isupper() else v

        return re.sub(r"\{(\w+)\}", one, text)

    for tid, lang, req, ans, sugg in NS_TEMPLATES:
        for _ in range(16):
            pick: dict = {}
            r, a = fill(req, pick), fill(ans, pick)
            items = [(n, fill(x, pick), fill(y, pick)) for n, x, y in sugg]
            k = R.fold(r + " " + a)
            if k in seen or R.fold(r) in banned:
                continue
            seen.add(k)
            target = [{"needs": n, "label": x, "prompt": y} for n, x, y in items]
            kept, dropped = N.validate({"suggestions": target}, lang=lang, available=set())
            assert not dropped and len(kept) == len(target), (tid, dropped)  # it passes the live validation
            split = "eval" if tid in held else "train"
            msgs = N.messages(r, a, lang, caps[lang]) + [
                {"role": "assistant", "content": json.dumps({"suggestions": target}, ensure_ascii=False,
                                                            separators=(",", ":"))}]  # fmt: skip
            out[split].append({"id": f"{SOURCE}-{split}-n{len(out[split]):06d}", "source": SOURCE,
                               "license": LICENSE, "lang": lang, "task": "nextsteps", "thinking": False,
                               "messages": msgs, "template": tid})  # fmt: skip
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=6000, help="router records in train (native calls come on top)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    got = build(a.n, a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for split in ("train", "eval", "bench_heldout"):
        with open(out / f"{split}.jsonl", "w", encoding="utf-8") as f:
            for r in got[split]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "stats.json").write_text(json.dumps(got["stats"], indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in got["stats"].items() if k in ("train", "eval", "bench_heldout", "filtered")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
