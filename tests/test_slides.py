"""Decks keep the user's figures and pick a layout from the content."""

from __future__ import annotations

import re

from pptx import Presentation

from birds.harness.config import Config, Context
from birds.harness.office import figures, kpi_parts, layout_of, missing_figures
from birds.harness.tools.files import make_slides

ASK = "Prépare un PowerPoint sur notre bilan : CA 1,2 M€ (+8 %), 14 nouveaux clients, marge 31 %, objectif T4 1,4 M€."


def test_figures_of_a_request():
    assert figures(ASK) == ["1,2 M€", "+8 %", "14", "31 %", "1,4 M€"]
    assert figures("Fais une présentation de 6 slides sur le télétravail deux jours par semaine.") == []
    assert figures("Total 1 250,00 € au 12/03/2026")[0] == "1 250,00 €"


def test_missing_figures_ignore_spacing_and_decimal_marks():
    slides = [{"title": "Bilan", "bullets": ["CA : 1.2 M€, en hausse de 8 %", "Marge 31%", "14 clients", "T4 : 1,40 M€"]}]
    assert missing_figures(ASK, slides) == []
    assert missing_figures(ASK, [{"title": "T4", "bullets": ["Objectif : 1,4 M€"]}]) == ["1,2 M€", "+8 %", "14", "31 %"]


def test_layouts():
    assert layout_of(["CA : 1,2 M€ (+8 %)", "Marge 31 %"]) == "kpi"
    assert layout_of(["Objectif : 1,4 M€"]) == "kpi"
    assert layout_of(["Phase 1 : Formation", "Phase 2 : Pilote", "Phase 3 : Déploiement"]) == "steps"
    assert layout_of([f"Point {c}" for c in "abcdefgh"]) == "columns"
    assert layout_of(["Une phrase plus longue sans chiffre qui explique un avantage concret pour l'équipe."]) == "bullets"
    assert kpi_parts("CA : 1,2 M€ (+8 %)") == ("1,2 M€", "CA (+8 %)")


def _texts(path):
    texts = [" ".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame) for s in Presentation(path).slides]
    return [t.replace("\xa0", " ") for t in texts]  # French non-breaking spaces read as spaces


def test_make_slides_adds_the_figures_the_model_dropped(tmp_path):
    ctx = Context(config=Config(workspace=tmp_path), http=None, lang="fr", request=ASK)
    out = make_slides({"title": "Bilan", "slides": [{"title": "Objectif T4", "bullets": ["Objectif : 1,4 M€"]}]}, ctx)
    assert "key figures" in out and "Slides: 2. Chiffres clés; 3. Objectif T4." in out
    texts = _texts(tmp_path / ctx.files[0])
    assert "Chiffres clés" in texts[1]
    for f in ("1,2 M€", "+8 %", "14", "31 %"):
        assert f in texts[1], f
    assert "1,4 M€" in texts[2]


def test_make_slides_leaves_a_complete_deck_alone(tmp_path):
    ctx = Context(config=Config(workspace=tmp_path), http=None, lang="fr", request="Une présentation sur le télétravail")
    out = make_slides({"title": "Télétravail", "slides": [{"title": "Plan", "bullets": ["Phase 1 : Audit",
                       "Phase 2 : Pilote", "Phase 3 : Déploiement"]}]}, ctx)
    assert "key figures" not in out
    texts = _texts(tmp_path / ctx.files[0])
    assert len(texts) == 2 and "Audit" in texts[1] and "Phase" not in texts[1].replace("Plan", "")


def test_kpi_figure_keeps_whole_numbers_and_skips_years():
    assert kpi_parts("CA 2026 : 3,4 M€")[0] == "3,4 M€"
    assert kpi_parts("1500 clients actifs")[0].startswith("1500")
    assert kpi_parts("1 250 clients")[0] == "1 250"
    assert kpi_parts("Délai : 6 hours")[0] == "6 hours"
    assert kpi_parts("Année 2026")[0] == "2026"  # only a year: it is the figure


def test_range_bullet_is_not_a_kpi():
    assert layout_of(["Effectif : 21 à 26 personnes", "CA : 3 M€"]) == "bullets"
    assert layout_of(["Durée : de 3 à 5 jours"]) == "bullets"
    assert layout_of(["Budget : from 2 to 4 M€"]) == "bullets"


def test_dates_and_extensions_are_not_kpi_cards():
    from birds.harness.office import kpi_ok, render_kind

    assert not kpi_ok("Contactez le support informatique au poste 214.")
    assert not kpi_ok("Premier envoi le 15 janvier")
    assert kpi_ok("CA : 1,2 M€ (+8 %)") and kpi_ok("14 nouveaux clients")
    assert render_kind(["Contactez le support informatique au poste 214."]) == "statement"
    assert render_kind(["Une lettre mensuelle pour nos 3 200 clients", "Premier envoi le 15 janvier"]) == "cards"
    assert render_kind(["CA : 1,2 M€ (+8 %)", "Marge 31 %"]) == "kpi"


def test_render_kinds_refine_bullets():
    from birds.harness.office import render_kind

    long = "Un point assez long qui décrit une mesure concrète, son responsable et l'échéance attendue " * 2
    assert render_kind(["Un", "Deux", "Trois", "Quatre"]) == "rows"
    assert render_kind([long[:150]] * 3) == "rows"
    assert render_kind(["Principal", "  sous-point"]) == "list"
    assert render_kind([long] * 6) == "list"


def test_deck_design_has_no_theme_style_and_keeps_its_texts(tmp_path):
    from pptx.oxml.ns import qn

    from birds.harness.office import build_pptx

    slides = [
        {"title": "Chiffres", "bullets": ["CA : 1,2 M€ (+8 %)", "Marge 31 %", "NPS : 62", "120 nouveaux clients"]},
        {"title": "Partie 2"},
        {"title": "Plan", "bullets": [f"Étape {i} : Lot {i}" for i in range(1, 6)]},
        {"title": "Merci"},
    ]
    n = build_pptx(tmp_path / "d.pptx", "Deck", slides)
    prs = Presentation(str(tmp_path / "d.pptx"))
    assert n == len(prs.slides) == 5 and prs.core_properties.author == ""
    assert [s.shapes.title.text for s in prs.slides] == ["Deck", "Chiffres", "Partie 2", "Plan", "Merci"]
    for slide in prs.slides:
        for sh in slide.shapes:
            assert sh._element.find(qn("p:style")) is None  # no theme shadow or outline
    texts = _texts(tmp_path / "d.pptx")
    assert all(f in texts[1] for f in ("1,2 M€", "+8 %", "31 %", "62", "120"))
    assert "01" in texts[2] and "Lot 5" in texts[3] and "Étape" not in texts[3]
    assert "5 / 5" in [sh.text_frame.text for sh in prs.slides[4].shapes if sh.has_text_frame]


def test_split_parts_share_size_and_continue_numbering(tmp_path):
    from birds.harness.office import build_pptx

    bullets = [f"Point numéro {i} avec un texte de longueur moyenne pour voir la coupe" for i in range(1, 31)]
    build_pptx(tmp_path / "d.pptx", "Deck", [{"title": "Liste", "bullets": bullets}])
    prs = Presentation(str(tmp_path / "d.pptx"))
    numbers, tops, sizes = [], set(), set()
    for slide in list(prs.slides)[1:]:
        for sh in slide.shapes:
            text = sh.text_frame.text if sh.has_text_frame else ""
            if re.fullmatch(r"\d\d", text):
                numbers.append(int(text))
            elif text.startswith("Point numéro"):
                sizes.add(sh.text_frame.paragraphs[0].runs[0].font.size)
        tops.add(min(sh.top for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.startswith("Point")))
    assert numbers == list(range(1, 31))  # part 2 continues at 07, not 01
    assert len(sizes) == 1 and len(tops) == 1  # one type size and one top edge for every part


def test_long_titles_are_cut_and_kept_in_notes(tmp_path):
    from birds.harness.office import build_pptx

    long = "Stratégie de transformation numérique et plan de déploiement " * 8
    build_pptx(tmp_path / "d.pptx", long, [{"title": long, "bullets": ["Un point", "Un autre"]}])
    prs = Presentation(str(tmp_path / "d.pptx"))
    assert len(prs.slides[0].shapes.title.text) <= 201 and prs.slides[0].shapes.title.text.endswith("…")
    assert len(prs.slides[1].shapes.title.text) <= 161
    assert prs.slides[1].notes_slide.notes_text_frame.text.startswith("Stratégie de transformation")


def test_slide_text_keeps_figures_with_their_units():
    from birds.harness.office import _kpi_split, _redundant, nbsp

    assert nbsp("Marché en croissance de 6 % par an") == "Marché en croissance de 6\xa0% par an"
    assert nbsp("3 200 clients") == "3\xa0200 clients" and nbsp("Questions ?") == "Questions\xa0?"
    assert _kpi_split("Churn below 3%") == ("<\xa03%", "Churn", "")
    assert _kpi_split("Délai : moins de 4 h")[0].startswith("<")
    assert _redundant("Nouveaux clients", "Nouveaux clients") and _redundant("Objectif", "Objectif T4")
    assert not _redundant("Marge", "Objectif T4")
