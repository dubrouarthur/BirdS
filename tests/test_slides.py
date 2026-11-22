"""Decks keep the user's figures and pick a layout from the content."""

from __future__ import annotations

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
    return [" ".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame) for s in Presentation(path).slides]


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
