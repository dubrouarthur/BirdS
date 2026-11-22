"""The chat preview of a generated file describes the file as written: final slides with their drawn shapes,
document blocks, displayed cells."""

from __future__ import annotations

import json

from birds.harness.config import Config, Context
from birds.harness.office import build_docx, build_xlsx, shown_value
from birds.harness.tools.files import make_document, make_sheet, make_slides
from birds.web.backends import file_preview, written_preview

ASK = "Prépare un PowerPoint sur notre bilan : CA 1,2 M€ (+8 %), 14 nouveaux clients, marge 31 %."


def _deck(tmp_path, slides, request=ASK, lang="fr"):
    ctx = Context(config=Config(workspace=tmp_path), http=None, lang=lang, request=request)
    make_slides({"title": "Bilan du trimestre", "subtitle": "Comité", "slides": slides}, ctx)
    return ctx.step_info["preview"]


def test_deck_preview_lists_the_slides_as_written(tmp_path):
    long = [f"Point numéro {i} assez long pour occuper une ligne de texte entière" for i in range(1, 12)]
    p = _deck(
        tmp_path,
        [
            {"title": "Ambition", "bullets": []},
            {"title": "Objectif", "bullets": ["Objectif T4 : 1,4 M€"]},
            {"title": "Plan", "bullets": ["Phase 1 : Audit", "Phase 2 : Pilote : un site", "Phase 3 : Déploiement"]},
            {"title": "Points", "bullets": long},
            {"title": "Merci", "bullets": []},
        ],
    )
    assert (p["kind"], p["v"], p["title"], p["subtitle"]) == ("slides", 2, "Bilan du trimestre", "Comité")
    kinds = [s["kind"] for s in p["slides"]]
    # the title slide, the key-figures slide added first, a numbered section, a split slide, the closing slide
    assert kinds[0] == "title" and kinds[1] == "kpi" and p["slides"][1]["title"] == "Chiffres clés"
    assert kinds[2] == "section" and p["slides"][2]["number"] == "01"
    assert kinds[-1] == "closing" and p["total"] == len(p["slides"])
    assert [s["n"] for s in p["slides"]] == list(range(1, p["total"] + 1))
    ca = next(f for f in p["slides"][1]["items"] if f["value"].replace("\xa0", " ") == "1,2 M€")
    assert ca["label"] == "CA" and ca["delta"] == "+8 %"
    assert p["slides"][3]["eyebrow"] == "AMBITION"
    steps = p["slides"][4]
    assert steps["kind"] == "steps" and [i["n"] for i in steps["items"]] == ["1", "2", "3"]
    assert steps["items"][1] == {"n": "2", "label": "Pilote", "text": "un site"}
    parts = [s for s in p["slides"] if s["title"].startswith("Points")]
    assert [s["title"] for s in parts] == ["Points (1/2)", "Points (2/2)"]
    assert parts[1]["items"][0]["n"] == len(parts[0]["items"]) + 1  # the numbering continues


def test_deck_preview_shapes_are_the_drawn_slide(tmp_path):
    p = _deck(tmp_path, [{"title": "Contexte", "bullets": ["Un marché en hausse", "Des prix sous pression"]}], "x")
    title, content = p["slides"]
    assert title["shapes"][0] == {"x": 0, "y": 0, "w": 1280, "h": 720, "f": "0B1B3F"}  # full-bleed navy
    heads = [sh for sh in content["shapes"] if sh.get("ti")]
    assert len(heads) == 1 and heads[0]["p"][0]["r"][0] == {"t": "Contexte", "s": 30, "c": "0B1B3F", "b": 1}
    texts = [r["t"] for sh in content["shapes"] for par in sh.get("p", []) for r in par["r"]]
    assert "Un marché en hausse" in texts and "2 / 2" in texts and "Bilan du trimestre" in texts
    for sh in content["shapes"]:
        assert 0 <= sh["x"] <= 1280 and 0 <= sh["y"] <= 720 and sh["w"] > 0 and sh["h"] > 0


def test_deck_preview_stays_small(tmp_path):
    slides = [{"title": f"Partie {i}", "bullets": ["x" * 300] * 6} for i in range(60)]
    p = _deck(tmp_path, slides, "x")
    assert len(p["slides"]) == 40 < p["total"]
    runs = [r for s in p["slides"] for sh in s["shapes"] for par in sh.get("p", []) for r in par["r"]]
    assert all(len(r["t"]) <= 400 for r in runs)
    assert len(json.dumps(p)) < 400_000


def test_document_preview_blocks(tmp_path):
    preview: dict = {}
    build_docx(
        tmp_path / "d.docx",
        "Compte rendu",
        [
            {"heading": "Points", "content": "Le module est prêt à **90 %**.\n\n1. Un\n2. Deux\n\n- Haut\n  - Bas"},
            {"heading": "Décisions", "content": "- Décision : la recette est décalée."},
            {
                "heading": "Budget",
                "content": "| Poste | Montant |\n|---|---|\n| Loyer | 1 200 € |\n| Total | 1 200 € |",
            },
            {"heading": "Note", "content": "> À relire\n\n```\ncode\n```"},
        ],
        "Projet ERP",
        preview,
    )
    blocks = preview["blocks"]
    assert (preview["kind"], preview["v"]) == ("document", 2)
    assert [b["k"] for b in blocks[:3]] == ["title", "subtitle", "h"]
    assert {"k": "p", "r": [["Le module est prêt à ", 0], ["90 %", 1], [".", 0]]} in blocks
    assert [b.get("n") for b in blocks if b["k"] == "li"][:2] == [1, 2]
    assert {"k": "li", "r": [["Bas", 0]], "l": 1} in blocks
    callout = next(b for b in blocks if b["k"] == "callout")
    assert callout["c"] == "decision" and callout["r"][0] == ["Décision : ", 1]
    table = next(b for b in blocks if b["k"] == "table")
    assert table["rows"][0]["c"] == [["Poste"], ["Montant", 1]] and table["rows"][2].get("total") == 1
    assert any(b["k"] == "quote" for b in blocks) and any(b["k"] == "code" and b["t"] == "code" for b in blocks)


def test_document_preview_says_how_much_is_cut(tmp_path):
    preview: dict = {}
    sections = [{"heading": f"Partie {i}", "content": "\n\n".join(f"Paragraphe {j}." for j in range(5))} for i in range(40)]
    build_docx(tmp_path / "d.docx", "Long", sections, "", preview)
    assert len(preview["blocks"]) == 120 and preview["more"] == 2 + 40 * 6 - 120  # title, date, then 6 blocks a section
    small: dict = {}
    build_docx(tmp_path / "s.docx", "Court", sections[:2], "", small)
    assert "more" not in small


def test_sheet_preview_shows_formats_and_computed_totals(tmp_path):
    preview: dict = {}
    build_xlsx(
        tmp_path / "s.xlsx",
        "Facture",
        ["Désignation", "Quantité", "Prix", "Total"],
        [["Audit", 2, "1 800,00 €", "=B2*C2"], ["Total HT", "", "", "=SUM(D2:D2)"], ["TVA", "", "", "=D3*0.2"]],
        preview,
    )
    assert preview["kinds"] == ["text", "num", "num", "num"]
    rows = preview["rows"]
    assert rows[0]["c"] == ["Audit", "2", "1 800,00\xa0€", "3 600,00\xa0€"]
    assert rows[1]["c"][3] == "3 600,00\xa0€" and rows[1]["t"] == 1
    assert rows[2]["c"][3] == "720,00\xa0€" and rows[2]["t"] == 2  # the last total row is the grand total
    assert shown_value(0.716, "0.0 %") == "71,6 %" and shown_value(1234.5, "#,##0.00", "en") == "1,234.50"


def test_tools_leave_the_preview_in_the_step_info(tmp_path):
    ctx = Context(config=Config(workspace=tmp_path), http=None)
    make_document({"title": "T", "sections": [{"heading": "H", "content": "x"}]}, ctx)
    assert ctx.step_info["preview"]["kind"] == "document"
    ctx = Context(config=Config(workspace=tmp_path), http=None)
    make_sheet({"title": "T", "columns": ["a"], "rows": [[1]]}, ctx)
    assert ctx.step_info["preview"]["kind"] == "sheet"
    args = {"title": "T", "columns": ["a"], "rows": [[1]]}
    assert written_preview("make_sheet", args, ctx.step_info)["v"] == 2
    assert written_preview("make_sheet", args, {}) == file_preview("make_sheet", args)  # the old path is kept
