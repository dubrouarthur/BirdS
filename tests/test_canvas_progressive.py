"""The progressive deck / document pipeline (birds/canvas/progressive.py, docs/CANVAS.md § 11): the plan is
validated, a statistic is never a photo, pictures and figures come from tools, a failed picture is a designed
placeholder, the exports carry the pictures and the native charts."""

from __future__ import annotations

import base64
import io
import json
import threading
from types import SimpleNamespace

from birds.canvas import dsl, export, images
from birds.canvas import progressive as pg
from birds.harness import office_media as om


class Tok:
    def apply_chat_template(self, messages, tools=None, tokenize=False, add_generation_prompt=True, **kw):
        return "\n".join(m["content"] for m in messages)


PLAN = {
    "title": "La mobilité douce à Lyon",
    "subtitle": "Conseil municipal",
    "audience": "les élus",
    "message": "Le vélo et la marche gagnent du terrain.",
    "cover_image": "Lyon cyclists street",
    "slides": [
        {"title": "Pourquoi agir", "intent": "le constat", "layout": "image-right", "visual": "image",
         "image_query": "[cyclists Lyon 1]", "data": "none"},
        {"title": "Le vélo cargo en chiffres", "intent": "les chiffres", "layout": "bullets", "visual": "image",
         "image_query": "Paris bike cargo statistics", "data": "web", "search": "vélo cargo chiffres"},
        {"title": "Le chômage recule", "intent": "contexte", "layout": "chart", "visual": "chart",
         "data": "statistics", "indicator": "unemployment", "places": "France", "since": "2015"},
        {"title": "Les étapes", "intent": "le plan", "layout": "steps", "visual": "diagram", "data": "none"},
        {"title": "Un quartier piéton", "intent": "exemple", "layout": "image-left", "visual": "image",
         "image_query": "pedestrian street market", "data": "none"},
        {"title": "Décider", "intent": "la suite", "layout": "bullets", "visual": "none", "data": "none"},
    ],
}  # fmt: skip


class LLM:
    """The plan first (structured output), then one slide per call, named after the slide's title."""

    def __init__(self, plan=PLAN):
        self.plan, self.calls, self.lock = plan, [], threading.Lock()

    def generate(self, prompt, max_tokens, stop, deadline=None, extra=None):
        with self.lock:
            self.calls.append(prompt)
        if "[Plan]" in prompt:
            return {"text": json.dumps(self.plan), "completion_tokens": 300, "prompt_tokens": 500}
        title = prompt.split("« ", 2)[2].split(" »", 1)[0] if "diapositive" in prompt else "Section"
        body = (
            f"# {title}\n- La métropole de Lyon compte 1 400 km d'aménagements cyclables [1]\n"
            "- La Part-Dieu accueille la plus grande vélostation de France\n"
            "- Les Voies lyonnaises relieront 12 lignes d'ici 2026\n- Des rues scolaires devant 40 écoles\n"
        )
        return {"text": body, "completion_tokens": 120, "prompt_tokens": 400}


def _jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (320, 200), (40, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def finder(found: set[str]):
    def find(q, exclude, mid):
        if not any(w in q.lower() for w in found):
            return None
        return om.Media(id=mid, kind="photo", data=_jpeg(), fmt="jpeg", w=320, h=200, alt=q, title=q,
                        credit="Jane Doe — CC BY — Wikimedia Commons", licence="CC BY",
                        source=f"https://commons.wikimedia.org/wiki/File:{q.replace(' ', '_')}.jpg")  # fmt: skip

    return find


def tool(name, args, ctx=None):
    ctx = ctx or SimpleNamespace(charts=[])
    step = SimpleNamespace(error=None, flags=[], info={})
    if name == "get_statistics":
        ctx.charts = [{"type": "line", "unit": "%", "title": "Taux de chômage, France", "columns": ["Année", "France"],
                       "rows": [["2015", 10.4], ["2019", 8.4], ["2024", 7.3]],
                       "data_source": {"label": "Eurostat", "dataset": "une_rt_a",
                                       "url": "https://ec.europa.eu/eurostat/databrowser/view/une_rt_a"}}]  # fmt: skip
        text = (
            "Graphique affiché à l'utilisateur (ne cite pas cette note) : « Taux de chômage » (annuel), données "
            "réelles Eurostat une_rt_a. France : 10,4 % en 2015 → 7,3 % en 2024. Ne redessine pas le graphique"
        )
        return step, text, ctx
    if name == "web_search":
        step.info = {"results": [{"url": "https://www.lyon.fr/velo", "title": "Le vélo à Lyon",
                                  "snippet": "La métropole de Lyon compte 1 400 km d'aménagements cyclables en 2024."}]}  # fmt: skip
        return step, "results", ctx
    step.error = "blocked"
    return step, "", ctx


def env(kind="deck", events=None, plan=PLAN, found=("cyclists", "pedestrian", "lyon")):
    events = [] if events is None else events
    return pg.Env(llm=LLM(plan), tok=Tok(), lang="fr", words="Fais une présentation sur la mobilité douce à Lyon",
                  kind=kind, aid="a0123456789ab", emit=events.append, finder=finder(set(found)), tool=tool,
                  level="faucon", structured="")  # fmt: skip


def test_the_plan_is_validated_and_a_statistic_is_never_a_photo():
    repairs: list[str] = []
    o = pg.parse_outline(json.dumps(PLAN), "deck", "mobilité douce", "fr", repairs)
    by = {it.title: it for it in o.items}
    assert by["Pourquoi agir"].query == "cyclists Lyon"  # the model's notation cleaned
    stat = by["Le vélo cargo en chiffres"]
    assert stat.visual == "kpi" and stat.query == ""  # a statistic: key figures (web data), never a photo
    assert by["Les étapes"].visual == "steps"  # a diagram is drawn by the canvas
    assert any("photo of a statistic" in r for r in repairs)
    assert pg.parse_outline("pas un plan", "deck", "x") is None


def test_the_pipeline_gathers_in_parallel_and_streams_the_deck():
    events: list[dict] = []
    res = pg.Pipeline(env(events=events)).run()
    doc = res.doc
    snaps = [e for e in events if e["type"] == "canvas" and e["phase"] == "stream"]
    assert len(snaps) >= 3  # the outline, then the slides filling in
    assert all(b.get("pending") for b in snaps[0]["doc"]["blocks"])
    media = [m for e in events if e["type"] == "canvas_media" for m in e["media"]]
    assert {m["id"] for m in media} >= {"w0", "w1", "w5"}  # the cover and the two photos, found by the tool
    assert all(m["licence"] and m["credit"] for m in media)
    chart = next(p for b in doc["blocks"] for p in b["parts"] if p["t"] == "chart")
    assert chart["source"].startswith("Eurostat") and chart["rows"][0] == ["2015", 10.4]
    body = [b for b in doc["blocks"] if b["title"] != "Sources"]
    assert len(body) == 6 and all(len(b["parts"]) >= 1 for b in body)
    first = next(b for b in body if b["title"] == "Pourquoi agir")
    assert len([x for p in first["parts"] if p["t"] == "list" for x in p["items"]]) >= 3  # full content
    assert not any(p["t"] == "image" for b in body if b["title"] == "Le vélo cargo en chiffres" for p in b["parts"])
    assert doc["sources"] and doc["sources"][0]["url"].startswith("https://")
    lines = [ln["text"] for ln in res.lines]
    assert any(t.startswith("Plan : 6 diapositives") for t in lines)
    assert dsl.validate(doc)["blocks"]  # a valid canvas document


def test_a_picture_not_found_is_a_designed_placeholder_with_a_clean_label():
    res = pg.Pipeline(env(found=("cyclists",))).run()  # the pedestrian street is not found
    ph = [p for b in res.doc["blocks"] for p in b["parts"] if p["t"] == "image" and not p.get("media")]
    assert len(ph) == 1 and ph[0]["missing"] is True and ph[0]["query"] == "pedestrian street market"
    kept = dsl.validate(res.doc)
    assert any(p.get("missing") for b in kept["blocks"] for p in b["parts"] if p["t"] == "image")
    assert res.counts["missing_images"] == 1
    # the search is not repeated after the turn (images.resolve skips a placeholder already searched)
    assert images.resolve(res.doc, lambda q, e, m: (_ for _ in ()).throw(AssertionError("searched again"))) == []


def test_a_document_has_full_sections_and_a_fast_level_reads_no_web():
    e = env(kind="doc", plan={**PLAN, "sections": PLAN["slides"][:5], "slides": None})
    e.level = "hirondelle"
    calls = []
    e.tool = lambda *a, **k: calls.append(a) or tool(*a, **k)
    res = pg.Pipeline(e).run()
    assert res.doc["kind"] == "doc" and len(res.doc["blocks"]) == 5
    assert calls == []  # Hirondelle: plan, pictures and writing only


def test_the_write_prompt_asks_for_specific_content():
    o = pg.parse_outline(json.dumps(PLAN), "deck", "mobilité douce", "fr")
    msg = pg.write_message(o, 5, "mobilité douce", "fr", pg.Gathered())
    assert "4 à 6 points précis" in msg and "jamais une généralité" in msg
    o2 = pg.parse_outline(json.dumps({**PLAN, "sections": PLAN["slides"][:4]}), "doc", "x", "en")
    assert "2 to 4 paragraphs" in pg.write_message(o2, 0, "x", "en", pg.Gathered())


def test_exports_carry_the_pictures_and_a_native_chart():
    res = pg.Pipeline(env()).run()
    doc = dsl.validate(res.doc)
    jpeg = base64.b64encode(_jpeg()).decode()
    media = {mid: jpeg for mid in (doc.get("media") or {})}
    data, _name, _ = export.export(doc, "pptx", media)
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    shapes = [sh for s in prs.slides for sh in s.shapes]
    assert sum(1 for sh in shapes if sh.shape_type == 13) >= 2  # pictures
    assert any(getattr(sh, "has_chart", False) and sh.has_chart for sh in shapes)  # a native, editable chart
    docx_doc = {**doc, "kind": "doc"}
    blob = export.export(docx_doc, "docx", media)[0]
    from docx import Document

    d = Document(io.BytesIO(blob))
    assert len(d.inline_shapes) >= 2  # the photos and the chart as figures


def test_a_new_deck_request_runs_the_pipeline_in_the_web_turn(tmp_path, monkeypatch):
    """The whole chat turn: plan, slides streamed, the final version and the chat line (no web, no pictures here:
    the transport is the subject)."""
    import pytest

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from birds.web.backends import HarnessBackend
    from birds.web.server import create_app
    from birds.web.settings import Settings

    monkeypatch.setenv("BIRD_CANVAS_PROGRESSIVE", "1")
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    monkeypatch.setattr(images, "search_web", lambda *a, **k: None)  # no picture source reachable in tests
    plan = {**PLAN, "slides": [{**s, "data": "none"} for s in PLAN["slides"]]}

    class Web(LLM):
        def generate(self, prompt, max_tokens, stop, deadline=None, extra=None, **_):
            return super().generate(prompt, max_tokens, stop, deadline, extra)

    backend = HarnessBackend(Web(plan), Tok(), model="bird-test")
    s = Settings(demo_delay=0.0, signing_secret=b"x" * 32, signing="configured", rate_limit=0)
    with TestClient(create_app(s, server_backend=backend)) as client:
        r = client.post("/api/chat", json={"messages": [{"role": "user", "content":
                        "Fais une présentation sur la mobilité douce à Lyon"}], "reflexion": "hirondelle"})  # fmt: skip
    events = [json.loads(f[6:]) for f in r.text.split("\n\n") if f.startswith("data: ")]
    kinds = [e["type"] for e in events]
    assert "canvas_progress" in kinds
    final = next(e for e in events if e["type"] == "canvas" and e["phase"] == "final")
    assert len(final["doc"]["blocks"]) == 6
    ph = [p for b in final["doc"]["blocks"] for p in b["parts"] if p["t"] == "image"]
    assert ph and all(p.get("missing") for p in ph)  # searched, not found: designed placeholders
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["canvas"]["aid"] == final["aid"]


def test_the_single_generation_never_keeps_a_photo_of_a_statistic():
    from birds.canvas import turn

    doc = {"kind": "deck", "title": "Vélo", "blocks": [
        {"id": "b1", "title": "Chiffres", "parts": [{"t": "text", "text": "a"},
                                                    {"t": "image", "query": "[Paris bike cargo statistics]"}]},
        {"id": "b2", "title": "Rue", "parts": [{"t": "image", "query": "Photo : [cargo bike street 2]"}]}]}  # fmt: skip
    repairs: list[str] = []
    turn.photo_queries(doc, repairs)
    assert [p["t"] for p in doc["blocks"][0]["parts"]] == ["text"] and repairs
    assert doc["blocks"][1]["parts"][0]["query"] == "cargo bike street"


def test_echoed_or_repeated_queries_off_subject_series_and_notation_are_caught():
    plan = {**PLAN, "slides": [
        {"title": "Chômage des jeunes", "visual": "image", "image_query": "uniquement", "data": "none", "intent": "x",
         "layout": "image-right"},
        {"title": "Le marché du travail", "visual": "image", "image_query": "job center queue", "data": "none",
         "intent": "x", "layout": "bullets"},
        {"title": "Les seniors", "visual": "image", "image_query": "job center queue", "data": "none", "intent": "x",
         "layout": "bullets"},
        {"title": "Démographie", "visual": "chart", "data": "statistics", "indicator": "population", "intent": "x",
         "layout": "chart"},
    ]}  # fmt: skip
    repairs: list[str] = []
    o = pg.parse_outline(json.dumps(plan), "deck", "Fais une présentation sur la mobilité douce", "fr", repairs)
    # « uniquement » is an echo of the instructions: no concrete thing to show, no photo slot (nor its layout)
    assert (o.items[0].query, o.items[0].visual, o.items[0].layout) == ("", "none", "")
    assert o.items[1].query == "job center queue"
    assert (o.items[2].query, o.items[2].visual) == ("", "none")  # never the picture of another slide
    assert o.items[3].data == "web" and o.items[3].indicator == ""  # a population chart off-subject: vetoed
    block = {"parts": [
        {"t": "text", "text": "[Graphique des données officielles : population de 65 à 68 M] La ville change [1]."},
        {"t": "steps", "items": [{"title": "<étape>", "text": "Concerter"}, {"title": "<date>", "text": ""}]},
        {"t": "list", "items": ["Graphique montrant la tendance descendante", "10,4 % en 2015 [1]"]},
        {"t": "chart", "type": "line", "columns": ["a", "b"], "rows": [["2015", 10.4]], "source": "Eurostat"},
    ]}  # fmt: skip
    assert pg.scrub(block) >= 2
    assert block["parts"][0]["text"] == "La ville change [1]."
    assert block["parts"][1]["items"] == [{"title": "", "text": "Concerter"}]
    assert block["parts"][2]["items"] == ["10,4 % en 2015 [1]"]  # a point announcing the chart beside it goes
    twice = {**PLAN, "slides": [*PLAN["slides"], {**PLAN["slides"][2], "title": "Le chômage en 2024"}]}
    o2 = pg.parse_outline(json.dumps(twice), "deck", "mobilité douce", "fr")
    assert [it.data for it in o2.items].count("statistics") == 1  # one chart per series


def test_the_same_picture_is_never_placed_twice():
    same = lambda q, exclude, mid: None if "https://x/1.jpg" in exclude else om.Media(  # noqa: E731
        id=mid, kind="photo", data=_jpeg(), fmt="jpeg", w=320, h=200, alt=q, title=q, credit="c", licence="CC0",
        source="https://x/1.jpg")  # fmt: skip
    e = env()
    e.finder = same
    res = pg.Pipeline(e).run()
    placed = [p for b in res.doc["blocks"] for p in b["parts"] if p["t"] == "image" and p.get("media")]
    cover = 1 if (res.doc.get("cover") or {}).get("media") else 0
    assert len(placed) + cover == 1


def test_a_plan_without_any_fact_gets_web_facts_at_full_depth():
    plan = {**PLAN, "slides": [{**x, "data": "none", "visual": "none"} for x in PLAN["slides"]]}
    calls: list[str] = []
    e = env(plan=plan)
    e.tool = lambda name, args, ctx=None: calls.append(name) or tool(name, args, ctx)
    res = pg.Pipeline(e).run()
    assert calls.count("web_search") >= 3 and any("no fact planned" in r for r in res.repairs)
    assert res.doc["sources"]


def test_an_unrelated_search_result_is_never_a_source_and_a_slide_never_says_it_twice():
    def junk(name, args, ctx=None):
        step = SimpleNamespace(error=None, flags=[], info={"results": [
            {"url": "https://fr.wikipedia.org/wiki/Jordanie_football", "title": "Équipe de Jordanie de football",
             "snippet": "La sélection nationale de football de Jordanie dispute la coupe d'Asie depuis 1984."}]})  # fmt: skip
        return step, "", ctx

    e = env()
    e.tool = junk
    p = pg.Pipeline(e)
    p.gather_until = 1e18
    assert p.web(pg.Item("Le train de nuit Paris-Vienne", search="train de nuit Europe")) == []
    block = {"parts": [
        {"t": "list", "items": ["1850 : premier train de nuit en France", "1870 : extension du réseau en Allemagne"]},
        {"t": "timeline", "items": [{"when": "1850", "what": "premier train de nuit en France"},
                                    {"when": "1870", "what": "extension du réseau en Allemagne"}]},
    ]}  # fmt: skip
    assert pg.dedupe_visual(block) == 1 and [x["t"] for x in block["parts"]] == ["timeline"]
