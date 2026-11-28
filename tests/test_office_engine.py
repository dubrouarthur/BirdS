"""The office engine: themes, every deck layout, pictures (user, free-licence web with fake fetchers, maps),
charts, size caps, text fitting, document figures/contents/sources, the preview payload and the editor."""

from __future__ import annotations

import base64
import io
import json
import zipfile

import pytest
from PIL import Image, ImageDraw
from pptx import Presentation

from birds.harness import office_media as om
from birds.harness.config import Config, Context
from birds.harness.office import build_docx, build_pptx, list_fit, pick_theme, plan_slides
from birds.harness.office_plan import compare_of, expand_deck, quote_of, series_of, table_of, timeline_of
from birds.harness.tools.files import make_document, make_slides


def jpeg(w=1200, h=800, seed=1, quality=92) -> bytes:
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(0, h, 4):
        d.rectangle((0, y, w, y + 4), fill=((seed * 40 + y) % 255, (seed * 90 + y // 2) % 255, 120))
    for i in range(0, w, 37):  # detail, so the JPEG is not tiny
        d.line((i, 0, w - i, h), fill=((i * 7) % 255, 200, (i * 3) % 255), width=3)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def png_logo() -> bytes:
    im = Image.new("RGBA", (400, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, 150, 150), 30, fill=(200, 60, 20, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def photo(mid="u1", kind="user", **kw) -> om.Media:
    return om.prepare(jpeg(seed=len(mid)), mid, kind, **kw)


SLIDES = [
    {"title": "Chiffre d'affaires", "bullets": ["2022 : 1,1 M€", "2023 : 1,2 M€", "2024 : 1,4 M€", "2025 : 1,6 M€",
                                                "Croissance portée par la maintenance [1]"]},
    {"title": "Comparatif des offres", "bullets": ["Offre A : prix 120 €/mois, SLA 4 h", "Offre B : prix 90 €/mois, SLA 8 h"]},
    {"title": "Calendrier", "bullets": ["T1 2026 : audit", "T2 2026 : pilote", "T3 2026 : déploiement"]},
    {"title": "Avant / après", "bullets": ["Avant : saisie manuelle", "Avant : 3 jours", "Après : automatique",
                                           "Après : 4 heures"]},
    {"title": "Avis client", "bullets": ["« Un service rapide et des délais tenus. » — Marie L."]},
    {"title": "Notre équipe", "bullets": ["12 techniciens certifiés", "Astreinte le week-end"]},
]  # fmt: skip


# ------------------------------------------------------------------ reading the plan


def test_detectors_read_what_each_slide_is():
    assert series_of("CA", SLIDES[0]["bullets"])["type"] == "line"
    assert series_of("Parts", ["Paris : 45 %", "Lyon : 30 %", "Lille : 25 %"])["type"] == "pie"
    assert series_of("Bilan", ["CA : 1,2 M€ (+8 %)", "Marge 31 %"]) is None  # two units: KPI tiles, not a chart
    assert table_of(SLIDES[1]["bullets"]) == [["", "Prix", "SLA"], ["Offre A", "120 €/mois", "4 h"],
                                              ["Offre B", "90 €/mois", "8 h"]]  # fmt: skip
    assert table_of(["Formation : deux jours, en présentiel", "Pilote : trois semaines, deux sites"]) is None
    assert timeline_of(SLIDES[2]["bullets"])[0] == ("T1 2026", "audit")
    assert timeline_of(["Phase 1 : Formation", "Phase 2 : Pilote", "Phase 3 : Déploiement"]) is None  # steps layout
    assert quote_of(SLIDES[4]["bullets"]) == ("Un service rapide et des délais tenus.", "Marie L.")
    assert compare_of("Avant / après", SLIDES[3]["bullets"])[0] == "Avant"


def test_themes_from_the_request():
    assert pick_theme("Présentation pour notre restaurant") == "warm"
    assert pick_theme("Pitch de notre startup SaaS") == "modern"
    assert pick_theme("Bilan annuel du comité") == "corporate"
    assert pick_theme("restaurant", "modern") == "modern"  # asked by name (the editor) wins


def test_expansion_adds_agenda_sources_closing_and_places_pictures():
    media = [photo("u1"), photo("w1", "web", alt="équipe de techniciens", title="Techniciens")]
    media[1].credit, media[1].licence = "A. Auteur — CC BY 4.0 — Wikimedia Commons", "CC BY 4.0"
    slides, deck = expand_deck("Bilan", SLIDES, media, "fr", [{"n": 1, "title": "Rapport", "url": "https://x.org/r"}])
    layouts = [s.get("layout") for s in slides]
    assert layouts[0] == "agenda" and layouts[-1] == "closing" and "sources" in layouts
    assert {"chart", "table", "timeline", "compare", "quote"} <= set(layouts)
    assert deck["cover"].id == "u1"  # the user's photo goes on the cover
    team = next(s for s in slides if s["title"] == "Notre équipe")
    assert team["image"].id == "w1" and team["layout"] == "image_side"  # the web picture where its words are
    src = next(s for s in slides if s.get("layout") == "sources")
    assert any("CC BY 4.0" in c for c in src["credits"])  # its credit on the sources slide


def test_a_short_deck_gets_no_agenda_or_closing():
    slides, deck = expand_deck("T", [{"title": "A", "bullets": ["x"]}, {"title": "B", "bullets": ["y"]}], [], "fr")
    assert [s.get("layout") for s in slides] == [None, None] and deck["added"] == []


def test_editor_choices_are_respected():
    media = [photo("u1"), photo("u2")]
    slides = [dict(s) for s in SLIDES]
    slides[5] = {**slides[5], "image": "u2"}
    out, deck = expand_deck("T", slides, media, "fr", options={"cover": "none", "agenda": False, "closing": False})
    assert deck["cover"] is None and out[0].get("layout") != "agenda" and out[-1].get("layout") != "closing"
    assert next(s for s in out if s["title"] == "Notre équipe")["image"].id == "u2"


# ------------------------------------------------------------------ every layout drawn, nothing overflows


def _deck(tmp_path, slides=SLIDES, **kw):
    pv: dict = {}
    p = tmp_path / "d.pptx"
    n = build_pptx(p, "Bilan 2025", slides, "Comité", "fr", pv, **kw)
    return p, pv, n


def test_every_layout_is_drawn_inside_the_slide(tmp_path):
    media = [photo("u1"), photo("u2", alt="atelier"), photo("u3"), photo("u4"), photo("u5")]
    p, pv, n = _deck(tmp_path, media=media, sources=[{"n": 1, "title": "Rapport", "url": "https://x.org/r"}])
    kinds = [s["kind"] for s in pv["slides"]]
    for k in ("title", "agenda", "chart", "table", "timeline", "compare", "quote", "image_side", "sources", "closing"):
        assert k in kinds, k
    assert "grid" in kinds or "image" in kinds  # the photos left over
    prs = Presentation(p)
    assert len(prs.slides) == n == pv["total"]
    for slide in prs.slides:
        for sh in slide.shapes:
            assert sh.left >= -10 and sh.top >= -10, sh.name
            assert sh.left + sh.width <= prs.slide_width + 10 and sh.top + sh.height <= prs.slide_height + 10, sh.name
    charts = [sh for s in prs.slides for sh in s.shapes if sh.has_chart]
    assert charts and charts[0].chart.plots[0].categories[0] == "2022"  # a native, editable chart
    assert any(sh.has_table for s in prs.slides for sh in s.shapes)


def test_long_text_is_fitted_or_split():
    long = ["Une phrase assez longue qui explique un point important pour la direction et ses équipes. " * 2] * 6
    assert list_fit(long[:3], 6 * 914400, 4 * 914400, 22) < 22
    parts = plan_slides([{"title": "Long", "bullets": long, "layout": "image_side", "image": "x"}])
    assert len(parts) > 1 and parts[0]["layout"] == "image_side" and "image" not in parts[1]
    rows = [["Nom", "Valeur"]] + [[f"L{i}", str(i)] for i in range(20)]
    tables = plan_slides([{"title": "T", "bullets": [], "layout": "table", "table": rows}])
    assert len(tables) == 3 and all(t["table"][0] == ["Nom", "Valeur"] for t in tables)  # header repeated


def test_theme_colours_reach_the_file_and_the_preview(tmp_path):
    p, pv, _ = _deck(tmp_path, theme="warm")
    assert pv["theme"] == "warm"
    xml = zipfile.ZipFile(p).read("ppt/slides/slide1.xml").decode()
    assert "3B1F14" in xml  # the warm dark colour on the title slide
    assert any(s.get("bg") == "FFFCF8" for s in pv["slides"])


def test_speaker_notes_carry_the_details(tmp_path):
    p, _, _ = _deck(tmp_path, sources=[{"n": 1, "title": "Rapport annuel", "url": "https://x.org/r"}])
    notes = [s.notes_slide.notes_text_frame.text for s in Presentation(p).slides if s.has_notes_slide]
    chart = next(n for n in notes if n.startswith("Données"))
    assert "2025 : 1,6 M€" in chart and "[1] Rapport annuel — https://x.org/r" in chart


# ------------------------------------------------------------------ pictures: preparation, caps, web licences


def test_pictures_are_reencoded_and_capped():
    big = jpeg(5000, 3300, quality=98)
    m = om.prepare(big, "u1", "user")
    assert m.fmt == "jpeg" and max(m.w, m.h) <= om.MAX_SIDE and len(m.data) <= om.MAX_IMAGE_BYTES
    logo = om.prepare(png_logo(), "u2", "user")
    assert logo.fmt == "png"  # transparency kept
    webp = io.BytesIO()
    Image.open(io.BytesIO(jpeg())).save(webp, "WEBP")
    assert om.prepare(webp.getvalue(), "u3", "user").fmt == "jpeg"  # WebP becomes JPEG for Office
    with pytest.raises(om.ImageError):
        om.prepare(b"<svg/>", "x", "user")
    many = [om.prepare(jpeg(1600, 1100, seed=i, quality=98), f"u{i}", "user") for i in range(12)]
    kept = om.budget(many, total=1_000_000)
    assert len(kept) <= om.MAX_MEDIA and sum(len(m.data) for m in kept) <= 1_000_000


def test_a_deck_full_of_pictures_stays_under_the_response_limit(tmp_path):
    media = om.budget([om.prepare(jpeg(2400, 1600, seed=i, quality=98), f"u{i}", "user") for i in range(10)])
    p, pv, _ = _deck(tmp_path, media=media)
    size = p.stat().st_size
    assert size < 3_000_000  # inline limit; base64 + preview stay under 4.5 MB
    assert size * 4 / 3 + len(json.dumps(pv)) < 4_500_000


class FakeFetch:
    def __init__(self, licence="CC BY-SA 4.0", artist="<a href='x'>Jean Dupont</a>"):
        self.licence, self.artist, self.calls = licence, artist, []

    def json(self, url):
        self.calls.append(url)
        meta = {"LicenseShortName": {"value": self.licence}, "Artist": {"value": self.artist}}
        return {"query": {"pages": [{"imageinfo": [{"extmetadata": meta, "descriptionurl":
                "https://commons.wikimedia.org/wiki/File:Velo.jpg",
                "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Velo.jpg/1280px-Velo.jpg"}]}]}}  # fmt: skip

    def image(self, url):
        self.calls.append(url)
        return jpeg()


CANDS = [
    {"src": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Velo.jpg/640px-Velo.jpg",
     "page": "https://fr.wikipedia.org/wiki/V%C3%A9lo", "title": "Vélo électrique", "alt": "", "origin": "search"},
    {"src": "https://news.example.com/og.jpg", "page": "https://news.example.com/a", "title": "Vélo électrique",
     "alt": "", "origin": "page"},
    {"src": "https://upload.wikimedia.org/wikipedia/fr/a/ab/Affiche.jpg", "page": "https://fr.wikipedia.org/wiki/F",
     "title": "Vélo électrique affiche", "alt": "", "origin": "search"},
]  # fmt: skip


def test_web_pictures_only_with_a_free_licence_and_a_credit():
    f = FakeFetch()
    got = om.web_images(CANDS, f, "le marché du vélo électrique")
    assert [m.kind for m in got] == ["web"] and got[0].credit == "Jean Dupont — CC BY-SA 4.0 — Wikimedia Commons"
    assert got[0].source.startswith("https://commons.wikimedia.org/")
    assert not any("news.example.com" in c or "wikipedia/fr" in c for c in f.calls)  # og:image, non-free: skipped
    assert om.web_images(CANDS, FakeFetch(licence="CC BY-NC 4.0"), "vélo") == []
    assert om.web_images(CANDS, FakeFetch(licence="All rights reserved"), "vélo") == []
    assert om.web_images(CANDS, FakeFetch(artist=""), "vélo") == []  # CC BY without an author: no credit, no picture
    assert len(om.web_images(CANDS, FakeFetch(licence="Public domain", artist=""), "vélo")) == 1
    assert om.web_images(CANDS, FakeFetch(), "comptabilité fournisseurs") == []  # unrelated: left out
    assert om.web_images(CANDS, None, "vélo") == []


def test_web_picture_credit_is_written_in_the_deck(tmp_path):
    [m] = om.web_images(CANDS, FakeFetch(), "vélo électrique")
    slides = [{"title": "Le vélo électrique en ville", "bullets": ["Un usage qui progresse", "Des aides à l'achat"]}]
    p, pv, _ = _deck(tmp_path, slides=slides, media=[m])
    texts = " ".join(sh.text_frame.text for s in Presentation(p).slides for sh in s.shapes if sh.has_text_frame)
    assert "Jean Dupont — CC BY-SA 4.0 — Wikimedia Commons" in texts
    assert pv["media"] and any(sh.get("img") in pv["media"] for s in pv["slides"] for sh in s["shapes"])


class FakeTiles:
    def tile(self, url, headers=None):
        buf = io.BytesIO()
        Image.new("RGB", (256, 256), (230, 228, 220)).save(buf, "PNG")
        return 200, "image/png", buf.getvalue(), {"cache-control": "max-age=86400"}


def test_map_of_the_places_found():
    places = [{"name": "Gare de Lyon", "lat": 48.8443, "lon": 2.3730}, {"name": "Bercy", "lat": 48.8386, "lon": 2.3826}]
    m = om.map_image(places, FakeTiles(), "m1", title="Autour de la gare")
    assert m is not None and m.kind == "map" and m.credit == "© OpenStreetMap contributors" and m.w == 1280
    assert om.map_image(places, None) is None


# ------------------------------------------------------------------ the tools


def test_make_slides_uses_the_attached_pictures_and_reports_additions(tmp_path):
    om.keep_user_images(tmp_path, [{"name": "chantier.jpg", "url": "data:image/jpeg;base64,"
                                    + base64.b64encode(jpeg()).decode()},
                                   {"name": "facture.jpg", "url": "data:image/jpeg;base64,"
                                    + base64.b64encode(jpeg()).decode()}],
                        {"facture.jpg": "Facture n° 12 " * 60})  # fmt: skip
    assert [p.name for p in (tmp_path / om.USER_DIR).iterdir()] == ["01-chantier.jpg"]  # a scanned invoice is not kept
    ctx = Context(config=Config(workspace=tmp_path), http=None, lang="fr", request="Présentation du chantier")
    out = make_slides({"title": "Chantier", "slides": [dict(s) for s in SLIDES]}, ctx)
    assert "1 picture(s) the user attached" in out and "an agenda" in out and "a closing slide" in out
    prs = Presentation(tmp_path / ctx.files[0])
    pics = [sh for s in prs.slides for sh in s.shapes if sh.shape_type == 13]
    assert pics and pics[0].name == "bird-media:u1"
    preview = ctx.step_info["preview"]
    assert preview["v"] == 2 and preview["plan"]["cover"] == "u1" and preview["plan"]["media"][0]["id"] == "u1"


def test_make_document_figures_contents_and_sources(tmp_path):
    import docx

    m = photo("w1", "web", alt="Vélo électrique", title="Vélo électrique")
    m.credit, m.licence, m.source = (
        "J. D. — CC BY 4.0 — Wikimedia Commons",
        "CC BY 4.0",
        "https://commons.wikimedia.org/x",
    )
    secs = [{"heading": f"Partie {i}", "content": "Texte."} for i in range(4)]
    secs[1] = {"heading": "Ventes", "content": "| Année | Ventes |\n|---|---|\n| 2022 | 10 |\n| 2023 | 12 |\n| 2024 | 15 |\n"
                                               "| 2025 | 19 |\n\nImportant : la hausse continue."}  # fmt: skip
    secs[2] = {"heading": "Le vélo électrique", "content": "Un usage qui progresse [1]."}
    pv: dict = {}
    stats = build_docx(tmp_path / "d.docx", "Étude", secs, "", pv, media=[m],
                       sources=[{"n": 1, "title": "Baromètre", "url": "https://x.org/b"}])  # fmt: skip
    assert stats["figures"] == 2 and stats["added"] == ["sources"]  # the table's chart + the picture
    d = docx.Document(tmp_path / "d.docx")
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Sommaire" in text and "Figure  – Ventes" in text and "J. D. — CC BY 4.0 — Wikimedia Commons" in text
    assert "Crédits des images" in text
    xml = zipfile.ZipFile(tmp_path / "d.docx").read("word/document.xml").decode()
    assert 'TOC \\o "1-2"' in xml and "SEQ Figure" in xml and "w:hyperlink" in xml
    kinds = [b["k"] for b in pv["blocks"]]
    assert {"img", "cap", "toc", "toch", "pb", "callout"} <= set(kinds) and pv["media"]
    assert next(b for b in pv["blocks"] if b["k"] == "callout")["c"] == "action"  # « Important : » note callout


def test_make_document_from_a_short_note_stays_compact(tmp_path):
    ctx = Context(config=Config(workspace=tmp_path), http=None, lang="fr")
    out = make_document({"title": "Note", "sections": [{"heading": "A", "content": "x"}]}, ctx)
    assert "1 sections" in out
    kinds = [b["k"] for b in ctx.step_info["preview"]["blocks"]]
    assert kinds[:3] == ["title", "subtitle", "h"] and "toc" not in kinds


# ------------------------------------------------------------------ the editor endpoint


def test_editor_rebuilds_with_the_pictures_of_the_file(tmp_path):
    from fastapi.testclient import TestClient

    from birds.web.server import create_app
    from birds.web.settings import Settings

    om.keep_user_images(tmp_path, [{"name": "equipe.jpg", "url": "data:image/jpeg;base64,"
                                    + base64.b64encode(jpeg()).decode()}])  # fmt: skip
    ctx = Context(config=Config(workspace=tmp_path), http=None, lang="fr", request="Bilan")
    make_slides({"title": "Bilan", "slides": [dict(s) for s in SLIDES]}, ctx)
    plan = ctx.step_info["preview"]["plan"]
    data = base64.b64encode((tmp_path / ctx.files[0]).read_bytes()).decode()
    args = plan["args"]
    args["slides"][0]["title"] = "Chiffre d'affaires 2022-2025"
    args["slides"][5]["image"] = "n1"  # a picture added in the editor
    upload = {"id": "n1", "url": "data:image/png;base64," + base64.b64encode(png_logo()).decode(), "alt": "logo"}
    with TestClient(create_app(Settings(rate_limit=0, demo_delay=0))) as c:
        r = c.post("/api/office", json={"tool": "make_slides", "args": args, "theme": "modern", "cover": plan["cover"],
                                        "media": plan["media"], "file": data, "uploads": [upload]}).json()  # fmt: skip
        assert r["ok"], r
        f = r["files"][0]
        assert f["preview"]["theme"] == "modern" and f["preview"]["plan"]["cover"] == "u1"
        prs = Presentation(io.BytesIO(base64.b64decode(f["data"])))
        names = {sh.name for s in prs.slides for sh in s.shapes if sh.shape_type == 13}
        assert {"bird-media:u1", "bird-media:n1"} <= names  # the old picture kept, the new one placed
        assert "Chiffre d'affaires 2022-2025" in [s.shapes.title.text for s in prs.slides if s.shapes.title]
        bad = c.post("/api/office", json={"tool": "make_slides", "args": {"title": "x", "slides": []}})
        assert bad.status_code == 422
        doc = c.post("/api/office", json={"tool": "make_document", "args": {"title": "N", "sections": [
            {"heading": "A", "content": "Texte"}]}}).json()  # fmt: skip
        assert doc["ok"] and doc["files"][0]["name"].endswith(".docx")
        cross = c.post(
            "/api/office", json={"tool": "make_document", "args": {}}, headers={"origin": "https://evil.example"}
        )
        assert cross.status_code == 403
