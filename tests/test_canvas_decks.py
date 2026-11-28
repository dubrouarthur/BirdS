"""Canvas decks: typed slides, the layout catalogue, the four themes, Openverse pictures and the .pptx that looks
like the preview (birds/canvas/layouts.py, deck_pptx.py, images.py)."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from birds.canvas import deck_pptx, dsl, export, images, layouts, patch, turn
from birds.web import canvas_demo

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "canvas_layouts.json").read_text("utf-8"))


def gallery(theme: str = "corporate") -> tuple[dict, dict]:
    d = dsl.parse(canvas_demo.GALLERY, "deck")
    turn.finish_doc(d, "deck", "galerie", "fr")
    d["theme"] = theme
    found = images.resolve(d, images.finder("demo", theme=theme), limit=12)
    return dsl.validate(d), {m["id"]: m["data"] for m in found}


# ------------------------------------------------------------------ the format


def test_typed_blocks_and_layout_hints_are_read():
    text = """---
title: T
image: forêt tropicale
---
# Avant / après {versus}
::: compare
Avant | Après
Papier | Numérique
:::
# Méthode
layout: étapes
::: steps
Cadrer : objectifs
Tester : pilote
:::
# Équipe
::: équipe
Alice — cheffe de projet
Bruno | données
:::
"""
    repairs: list[str] = []
    d = dsl.parse(text, "deck", "fr", repairs)
    assert d["cover"] == {"query": "forêt tropicale"}
    b1, b2, b3 = d["blocks"]
    assert b1["title"] == "Avant / après" and b1["layout"] == "versus"
    assert b1["parts"][0] == {"t": "compare", "columns": [{"title": "Avant", "items": ["Papier"]},
                                                          {"title": "Après", "items": ["Numérique"]}]}  # fmt: skip
    assert b2["layout"] == "steps" and b2["parts"][0]["items"][1] == {"title": "Tester", "text": "pilote"}
    assert b3["parts"][0]["t"] == "cards" and b3["parts"][0]["items"][0]["text"] == "cheffe de projet"
    # the text format round-trips (a patch turn gives the model the deck in this format)
    again = dsl.parse(dsl.to_dsl(d, ids=True), "deck")
    assert [b.get("layout") for b in again["blocks"]] == ["versus", "steps", None]
    assert again["cover"]["query"] == "forêt tropicale"
    assert again["blocks"][0]["parts"] == b1["parts"]


def test_dated_steps_become_a_timeline_and_groups_a_comparison():
    d = dsl.parse("# Plan\n::: étapes\n2024 : cadrage\n2025 : pilote\n:::\n", "deck")
    assert d["blocks"][0]["parts"][0]["t"] == "timeline"
    d = dsl.parse("# Choix\n::: compare\nA :\n- rapide\nB :\n- solide\n:::\n", "deck")
    assert [c["title"] for c in d["blocks"][0]["parts"][0]["columns"]] == ["A", "B"]


def test_validate_keeps_layout_cover_and_new_parts_and_drops_junk():
    d = dsl.parse(canvas_demo.GALLERY, "deck")
    d["blocks"][0]["layout"] = "nope"
    d["blocks"][1]["layout"] = "statement"
    d["cover"]["media"] = "../etc"
    v = dsl.validate(d)
    assert "layout" not in v["blocks"][0] and v["blocks"][1]["layout"] == "statement"
    assert v["cover"] == {"query": "paysage de montagne"}
    with pytest.raises(dsl.Invalid):
        dsl.validate({**d, "blocks": [{"id": "b1", "parts": [{"t": "compare", "columns": [{"title": "x"}]}]}]})


# ------------------------------------------------------------------ the catalogue


def test_gallery_uses_every_layout_once():
    d, _ = gallery()
    bl = d["blocks"]
    picked = [layouts.pick(b, k, len(bl)) for k, b in enumerate(bl)]
    assert sorted(picked) == sorted(layouts.CATALOGUE) and len(layouts.CATALOGUE) >= 20


@pytest.mark.parametrize("case", FIXTURE, ids=lambda c: f"{c['note']}-{c['index']}-{c['layout']}")
def test_layout_fixture(case):
    """The same cases are run by tests/js/canvas-layouts.test.mjs: the preview and the .pptx pick the same layout."""
    assert layouts.pick(case["block"], case["index"], case["total"]) == case["layout"]
    assert layouts.compatible(case["block"]) == case["fits"]


def test_a_hint_that_does_not_fit_is_ignored_never_forced():
    b = {"title": "Contexte", "layout": "figure", "parts": [{"t": "list", "items": ["a", "b"]}]}
    assert layouts.pick(b, 0, 3) == "bullets"
    b["layout"] = "cards"
    assert layouts.pick(b, 0, 3) == "cards"  # a list of two items can be two cards
    assert "figure" not in layouts.compatible(b)


def test_picture_slides_alternate_and_a_closing_closes():
    long = "un point assez long pour ne pas être une légende " * 4
    b = {"title": "x", "parts": [{"t": "list", "items": [long, "deux"]}, {"t": "image", "query": "q"}]}
    assert layouts.pick(b, 0, 4) == "image-right" and layouts.pick(b, 1, 4) == "image-left"
    end = {"title": "Merci", "parts": [{"t": "list", "items": ["Des questions ?"]}]}
    assert layouts.pick(end, 3, 4) == "closing" and layouts.pick(end, 1, 4) == "statement"


def test_variety_counts_the_layouts():
    d, _ = gallery()
    v = layouts.variety(d)
    assert v["cover"] == 1 and len(v) == len(layouts.CATALOGUE) + 1


# ------------------------------------------------------------------ themes


def test_deck_themes_by_words_and_cycle():
    d = dsl.parse("---\ntitle: T\ntheme: nuit\n---\n# A\n- x\n# B\n- y\n", "deck")
    assert d["theme"] == "night"
    ops, _ = patch.direct_ops("passe en thème forêt", d)
    assert ops == [{"op": "theme", "theme": "forest"}]
    ops, _ = patch.direct_ops("change le thème", d)
    assert ops == [{"op": "theme", "theme": "corporate"}]  # night is the last of the four


def test_css_palettes_mirror_the_pptx_palettes():
    css = (ROOT / "birds" / "web" / "static" / "canvas.css").read_text("utf-8")
    for theme, pal in deck_pptx.PALETTES.items():
        m = re.search(r"\.cvt-" + theme + r"\s*\{(.*?)\}", css, re.S)
        assert m, theme
        body = m.group(1)
        for key, value in pal.items():
            got = re.search(r"--d-" + key + r":\s*#([0-9a-fA-F]{6})", body)
            assert got and got.group(1).upper() == value, (theme, key)


# ------------------------------------------------------------------ the .pptx


@pytest.mark.parametrize("theme", dsl.DECK_THEMES)
def test_pptx_draws_every_layout_in_every_theme(theme, tmp_path):
    from pptx import Presentation

    d, data = gallery(theme)
    media = export.media_list(d, data)
    out = deck_pptx.build(tmp_path / "g.pptx", d, media)
    bl = d["blocks"]
    assert out["layouts"] == ["cover"] + [layouts.pick(b, k, len(bl)) for k, b in enumerate(bl)]
    prs = Presentation(str(tmp_path / "g.pptx"))
    assert len(prs.slides) == len(bl) + 1
    fill = prs.slide_master.background.fill
    assert str(fill.fore_color.rgb) == deck_pptx.PALETTES[theme]["bg"]
    titles = [s.shapes.title.text for s in prs.slides if s.shapes.title is not None]
    assert titles[0] == d["title"] and "Ce qu'on attend" in titles  # eyebrow titles kept as written
    pics = sum(1 for s in prs.slides for sh in s.shapes if sh.shape_type == 13)
    assert pics >= 7  # cover, side pictures, full bleed, the three of the grid
    charts = [sh for s in prs.slides for sh in s.shapes if sh.has_chart]
    assert len(charts) == 1
    notes = "\n".join(s.notes_slide.notes_text_frame.text for s in prs.slides if s.has_notes_slide)
    assert "Illustration générée par Bird" in notes  # every picture's credit is in the notes
    assert "Données : 2023 : 12 %" in notes


def test_export_endpoint_path_uses_the_canvas_layouts():
    from pptx import Presentation

    d, data = gallery("warm")
    raw, mime, name = export.export(d, "pptx", data)
    prs = Presentation(io.BytesIO(raw))
    assert len(prs.slides) == len(d["blocks"]) + 1 and name.endswith(".pptx")
    raw, _, _ = export.export(d, "docx", data)  # the same deck as a Word file: compare / steps / cards as text
    from docx import Document

    text = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
    assert "Cadrer" in text and "Option A" in text and "Alice" in text


# ------------------------------------------------------------------ pictures: Openverse, licence, relevance, cache


class FakeFetch:
    def __init__(self, results, fail_urls=()):
        self.results, self.fail, self.calls = results, set(fail_urls), []

    def json(self, url):
        self.calls.append(url)
        if "openverse" in url:
            return {"results": self.results}
        return {"query": {"pages": []}}

    def image(self, url):
        self.calls.append(url)
        if url in self.fail:
            raise ValueError("boom")
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (1200, 800), (40, 90, 200)).save(buf, "JPEG")
        return buf.getvalue()


def _r(i, lic="by", title="Tramway à Lyon", creator="Ada", **kw):
    return {"id": str(i), "title": title, "url": f"https://live.staticflickr.com/{i}.jpg", "creator": creator,
            "license": lic, "license_version": "2.0", "foreign_landing_url": f"https://www.flickr.com/p/{i}",
            "provider": "flickr", "filetype": "jpg", "filesize": 300000, "width": 1600, "height": 1000,
            "tags": [{"name": "tram"}], **kw}  # fmt: skip


def test_openverse_free_licence_relevant_credited_cached():
    images.CACHE.clear()
    f = FakeFetch([_r(1, lic="by-nc"), _r(2, title="Chat sur un canapé"), _r(3, creator=""), _r(4, lic="by-sa")])
    m = images.search_web("tramway lyon", f, mid="w3")
    assert m is not None and m.id == "w3" and m.kind == "web"
    assert m.licence == "CC BY-SA 2.0" and m.source == "https://www.flickr.com/p/4"
    assert m.credit == "Ada — CC BY-SA 2.0 — Flickr via Openverse"
    assert "license=cc0,pdm,by,by-sa" in f.calls[0] and "mature=false" in f.calls[0]
    n = len(f.calls)
    again = images.search_web("tramway lyon", f, mid="w7")  # same query: from the cache, no network
    assert again.id == "w7" and again.credit == m.credit and len(f.calls) == n
    other = images.search_web("tramway lyon", f, exclude=["https://www.flickr.com/p/4"], mid="w8")
    assert other is None  # the only good one is excluded: nothing rather than a wrong picture


def test_openverse_nothing_relevant_falls_back_to_commons_then_none():
    images.CACHE.clear()
    f = FakeFetch([_r(1, title="Coucher de soleil", tags=[])])
    assert images.search_web("tramway lyon", f) is None
    assert any("commons.wikimedia.org" in u for u in f.calls)


def test_commons_original_is_fetched_as_a_1280_thumbnail():
    r = {"url": "https://upload.wikimedia.org/wikipedia/commons/c/ce/Tram_Lyon.jpg", "width": 4000, "filesize": 9e6}
    assert images._big_url(r) == ("https://upload.wikimedia.org/wikipedia/commons/thumb/c/ce/Tram_Lyon.jpg/"
                                  "1280px-Tram_Lyon.jpg")  # fmt: skip
    assert images._big_url({"url": "http://x/y.jpg", "thumbnail": "https://api.openverse.org/t/"}) == (
        "https://api.openverse.org/t/"
    )


def test_the_cover_picture_is_resolved_and_can_be_switched_off():
    d = dsl.parse("---\ntitle: T\nimage: montagne\n---\n# A\n- x\n# B\n- y\n", "deck")
    found = images.resolve(d, images.finder("demo"))
    assert d["cover"]["media"] == found[0]["id"]
    d2 = dsl.parse("---\ntitle: T\nimage: montagne\n---\n# A\n- x\n# B\n- y\n", "deck")
    d2["cover"]["off"] = True
    assert images.resolve(d2, images.finder("demo")) == []
