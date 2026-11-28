"""Word-like documents in the canvas: templates chosen by the model and checked by the code, the page look
(cover, table of contents, numbering, callouts, figures, notes), the .docx export faithful to the preview, one card
per deliverable (docs/CANVAS.md, section 9)."""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from birds.canvas import docx_out, dsl, export, intents, templates, turn

ROOT = Path(__file__).resolve().parents[1]

CADRAGE = """---
title: Projet CRM
subtitle: Note de cadrage du programme
template: note de cadrage
author: Claire Martin
---
# Contexte
Le service commercial utilise trois outils[^src].
## Situation actuelle
Les données sont dispersées.
::: cle
Un seul outil pour toute l'équipe.
:::
# Objectifs
- Centraliser les contacts
- Suivre les opportunités
  - par région
# Périmètre
Ventes et service client.
::: image query="équipe commerciale" caption="Une équipe au travail"
:::
# Planning
| Phase | Date | Responsable |
|---|---|---|
| Cadrage | T1 2027 | DSI |
| Pilote | T2 2027 | Ventes |
::: chart type=bar unit="k€" title="Budget par année"
2025: 120
2026: 140
:::
# Risques
::: attention
Adhésion des équipes.
:::
[^src]: Inventaire interne, 2026.
"""


def _doc(src: str = CADRAGE, words: str = "Rédige une note de cadrage du projet CRM pour Claire Martin") -> dict:
    d = dsl.parse(src, "doc")
    turn.finish_doc(d, "doc", words, "fr")
    return d


# ------------------------------------------------------------------ the format and the templates


def test_front_matter_template_author_footnotes_and_tones():
    d = _doc()
    assert d["template"] == "cadrage" and d["template_by"] == "model"
    assert d["author"] == "Claire Martin"  # named in the request: kept
    assert d["footnotes"] == [{"n": "src", "text": "Inventaire interne, 2026."}]
    assert not any("[^src]:" in (p.get("text") or "") for b in d["blocks"] for p in b["parts"])
    tones = [p["tone"] for b in d["blocks"] for p in b["parts"] if p["t"] == "callout"]
    assert tones == ["key", "warn"]
    img = next(p for b in d["blocks"] for p in b["parts"] if p["t"] == "image")
    assert img["caption"] == "Une équipe au travail"
    v = dsl.validate(dsl.clone(d))  # the browser sends it back: the fields survive validation
    assert (v["template"], v["author"], v["footnotes"][0]["n"], v["date"]) == ("cadrage", "Claire Martin", "src",
                                                                              d["date"])  # fmt: skip
    assert dsl.parse(dsl.to_dsl(v, ids=False), "doc")["footnotes"] == v["footnotes"]  # round trip (patch turns)


def test_an_invented_author_is_dropped_and_a_missing_template_comes_from_the_words():
    src = "---\ntitle: CR\nauthor: Jean Dupont\n---\n# Participants\n- Paul\n# Décisions\nOui.\n# Actions\n- x\n"
    repairs: list[str] = []
    d = dsl.parse(src, "doc")
    turn.finish_doc(d, "doc", "Rédige le compte rendu de la réunion de lundi", "fr", repairs)
    assert "author" not in d and any("author" in r for r in repairs)
    assert (d["template"], d["template_by"]) == ("compte-rendu", "hint")
    assert templates.check(d)["complete"] == 1.0


@pytest.mark.parametrize(
    "value,expected",
    [("cadrage", "cadrage"), ("Note de cadrage", "cadrage"), ("compte-rendu", "compte-rendu"),
     ("Compte rendu", "compte-rendu"), ("minutes", "compte-rendu"), ("Rapport", "rapport"), ("report", "rapport"),
     ("proposition commerciale", "proposition"), ("proposal", "proposition"), ("procédure", "procedure"),
     ("Lettre", "lettre"), ("letter", "lettre"), ("poème", None), ("", None)],
)  # fmt: skip
def test_the_model_choice_is_read_leniently(value, expected):
    assert templates.of(value) == expected


def test_structure_check_and_next_steps_never_add_content():
    d = _doc("---\ntitle: X\ntemplate: cadrage\n---\n# Contexte\nTexte.\n# Objectifs\n- a\n- b\n")
    before = dsl.to_dsl(d)
    st = templates.check(d)
    assert st["found"] == ["Contexte", "Objectifs"] and "Risques" in st["missing"] and st["complete"] == 0.4
    chips = templates.next_steps(d, "fr")
    assert 2 <= len(chips) <= 3 and chips[0]["prompt"] == "Ajoute une section Périmètre au document"
    assert dsl.to_dsl(d) == before
    for c in chips:  # every chip is an edit of the open document, never a new artifact
        assert intents.edit_ask(c["prompt"], "doc"), c
    assert templates.next_steps(d, "en")[0]["label"].startswith("Add")


def test_a_letter_has_its_own_chips_and_completeness():
    d = _doc("---\ntitle: Résiliation\ntemplate: lettre\n---\n# Lettre\n" + "Madame, Monsieur, " * 6 + "\n",
             "Rédige une lettre en Word pour résilier mon abonnement")  # fmt: skip
    assert templates.check(d)["complete"] == 1.0
    assert [c["label"] for c in templates.next_steps(d)] == ["Plus formelle", "Plus courte"]


def test_template_flags_match_the_preview_table():
    """canvas-doc.js keeps the same template table (cover, toc, numbered, letter) as birds/canvas/templates.py."""
    js = (ROOT / "birds/web/static/canvas-doc.js").read_text(encoding="utf-8")
    for t in templates.TEMPLATES.values():
        m = re.search(rf'(?:"{t.id}"|\b{t.id}):\s*\{{([^}}]*)\}}', js)
        assert m, t.id
        row = m.group(1)
        for flag in ("cover", "toc", "numbered", "letter"):
            assert re.search(rf"\b{flag}:\s*{str(getattr(t, flag)).lower()}\b", row), (t.id, flag)


# ------------------------------------------------------------------ when the canvas opens


@pytest.mark.parametrize(
    "words,expected",
    [("Rédige un document Word : note de cadrage pour un projet de CRM", "doc"),
     ("Rédige une lettre en Word pour résilier mon abonnement", "doc"),
     ("Rédige le compte rendu en docx", "doc"),
     ("Résume ce document en Word", None), ("Rédige un mail en Word", None),
     ("Rédige un rapport Word et un PowerPoint", None), ("Comment faire un document Word ?", None),
     ("Rédige une lettre de motivation", None), ("Fais une présentation pptx sur le vélo", None)],
)  # fmt: skip
def test_a_word_document_opens_the_canvas(words, expected):
    assert intents.ask(words) == expected


# ------------------------------------------------------------------ the .docx follows the preview


def _png(w: int = 64, h: int = 40) -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 200)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _with_picture(d: dict) -> dict:
    img = next(p for b in d["blocks"] for p in b["parts"] if p["t"] == "image")
    img["media"] = "w1"
    d["media"] = {"w1": {"kind": "web", "alt": "Équipe", "credit": "Photo : A. Auteur — Wikimedia Commons",
                         "licence": "CC BY-SA 4.0", "source": "https://commons.wikimedia.org/wiki/File:X.jpg",
                         "w": 64, "h": 40}}  # fmt: skip
    return dsl.validate(d)


def _paras(data: bytes):
    import docx

    D = docx.Document(io.BytesIO(data))
    return D, [(p.style.name, p.text) for p in D.paragraphs if p.text.strip()]


def test_docx_export_is_the_outline_of_the_preview():
    d = _with_picture(_doc())
    plan = docx_out.outline(d)
    data, mime, name = export.export(d, "docx", {"w1": _png()})
    assert name == "Projet-CRM.docx" and mime.endswith("document")
    D, paras = _paras(data)
    heads = [(s, t) for s, t in paras if s.startswith("Heading")]
    want = [x["text"] for x in plan if x["k"] in ("h1", "h2", "h3")] + ["Notes"]
    assert [t for _, t in heads] == want
    assert want[:3] == ["1. Contexte", "1.1 Situation actuelle", "2. Objectifs"]
    assert heads[1][0] == "Heading 2" and heads[0][0] == "Heading 1"
    styles = [s for s, _ in paras]
    # cover page: the template's name, title, subtitle, date and the author named by the user; then the contents
    assert paras[0] == ("Bird Cover Date", "NOTE DE CADRAGE") and paras[1] == ("Title", "Projet CRM")
    assert any(s == "Bird Cover Date" and "Claire Martin" in t and d["date"] in t for s, t in paras)
    assert "TOC Heading" in styles and styles.count("TOC 1") == 5
    # callouts with their label, a table with a header row, two figures (picture + chart) with captions
    texts = [t for _, t in paras]
    assert "À retenir : Un seul outil pour toute l'équipe." in texts and "Attention : Adhésion des équipes." in texts
    assert len(D.tables) == 1 and [c.text for c in D.tables[0].rows[0].cells] == ["Phase", "Date", "Responsable"]
    assert len(D.inline_shapes) == 2
    caps = [t for s, t in paras if s == "Caption"]
    assert "Une équipe au travail" in caps[0] and "CC BY-SA 4.0" in caps[0] and "A. Auteur" in caps[0]
    assert "Budget par année" in caps[1]
    xml = D.element.xml
    assert xml.count('w:instr="SEQ Figure') == 2 and 'w:instr="PAGE"' in D.sections[0].footer._element.xml
    # the footnote: a superscript call in the text, the note at the end, same number
    sup = [r for p in D.paragraphs for r in p.runs if r.font.superscript]
    assert [r.text for r in sup] == ["1", "1"]
    assert paras[-1] == ("Bird Source", "1 Inventaire interne, 2026.")


def test_docx_minutes_have_no_cover_and_no_numbers_and_a_letter_no_headings():
    cr = _doc("---\ntitle: Réunion d'équipe\ntemplate: compte-rendu\n---\n# Participants\n- Paul\n- Marie\n"
              "# Décisions\nTélétravail deux jours.\n# Actions\n| Action | Qui |\n|---|---|\n| Charte | Paul |\n",
              "Rédige le compte rendu")  # fmt: skip
    _, paras = _paras(export.export(dsl.validate(cr), "docx", {})[0])
    assert paras[0] == ("Bird Cover Date", "COMPTE RENDU") and ("Title", "Réunion d'équipe") in paras
    assert [t for s, t in paras if s == "Heading 1"] == ["Participants", "Décisions", "Actions"]
    assert not any(s.startswith("TOC") for s, _ in paras)
    lt = _doc("---\ntitle: Résiliation de mon abonnement\ntemplate: lettre\nrecipient: Salle de sport Forme+, "
              "12 rue des Lilas, 75011 Paris\n---\n# Lettre\nMadame, Monsieur,\n\nJe vous prie de résilier mon "
              "abonnement.\n\nVeuillez agréer mes salutations distinguées.\n",
              "Rédige une lettre en Word pour résilier mon abonnement à la salle de sport Forme+")  # fmt: skip
    assert lt.get("recipient")  # its name is in the request
    D, paras = _paras(export.export(dsl.validate(lt), "docx", {})[0])
    assert not any(s.startswith(("Heading", "TOC", "Title")) for s, _ in paras)
    assert ("Normal", "Objet : Résiliation de mon abonnement") in paras
    assert any(t.startswith("Le ") and lt["date"] in t for _, t in paras)
    assert paras[-1][1].startswith("Veuillez agréer")


def test_docx_export_renders_with_libreoffice_when_available(tmp_path):
    import shutil
    import subprocess

    if not shutil.which("soffice"):
        pytest.skip("no LibreOffice here")
    d = _with_picture(_doc())
    f = tmp_path / "cadrage.docx"
    f.write_bytes(export.export(d, "docx", {"w1": _png(640, 400)})[0])
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(f)],
                   check=True, capture_output=True, timeout=120)  # fmt: skip
    pdf = (tmp_path / "cadrage.pdf").read_bytes()
    assert pdf.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page\b", pdf)) >= 3  # cover, contents, body


# ------------------------------------------------------------------ one deliverable, one card


def test_an_adopted_word_document_opens_in_the_canvas_with_one_card():
    from birds.web import canvas_web

    answer = ("Le document de cadrage est prêt.\n\n**Fichier :** `note-de-cadrage-crm-20261128.docx`\n\n"
              "Dites-moi si vous voulez l'ajuster.")  # fmt: skip
    args = {"title": "Note de cadrage CRM", "sections": [{"heading": "Objectifs", "content": "- a\n- b"},
                                                          {"heading": "Risques", "content": "Adhésion."}]}  # fmt: skip
    run = SimpleNamespace(steps=[SimpleNamespace(tool="make_document", error=None, arguments=args)], canvas=None,
                          answer=answer, files=["note-de-cadrage-crm-20261128.docx"])  # fmt: skip
    canvas_web.adopt_files(run, None, "fr", "Rédige un document Word : note de cadrage pour un projet de CRM")
    ref = canvas_web.ref(run)
    assert ref["open"] is True and ref["kind"] == "doc" and ref["files"] == ["note-de-cadrage-crm-20261128.docx"]
    assert ref["doc"]["template"] == "cadrage" and ref["structure"]["template"] == "cadrage"
    assert 2 <= len(ref["next"]) <= 3
    assert "Fichier" not in run.answer and ".docx" not in run.answer
    assert run.answer.startswith("Le document de cadrage est prêt.") and run.answer.endswith("l'ajuster.")


def test_a_deck_made_by_the_trained_tool_opens_in_the_canvas_as_one_card():
    """« un ppt sur … » (a phrasing the canvas hint misses): the model's make_slides deck opens in the canvas, its
    card replaces the old file card and the « Fichier : t.pptx » line, as a document does."""
    from birds.web import canvas_web

    run = SimpleNamespace(steps=[SimpleNamespace(tool="make_slides", error=None, arguments={
        "title": "T", "slides": [{"title": "A", "bullets": ["x"]}, {"title": "B", "bullets": ["y"]}]})],
        canvas=None, answer="La présentation est prête.\n\nFichier : t.pptx", files=["t.pptx"])  # fmt: skip
    canvas_web.adopt_files(run, None, "fr", "")
    ref = canvas_web.ref(run)
    assert ref["open"] is True and ref["kind"] == "deck" and ref["files"] == ["t.pptx"]
    assert run.answer == "La présentation est prête."


def test_strip_file_lines_keeps_the_rest():
    from birds.web.canvas_web import strip_file_lines

    text = "Voici le document.\n\nFichier : rapport.docx\n\n- point gardé\n\nTéléchargement : `rapport.docx`."
    assert strip_file_lines(text, ["rapport.docx"]) == "Voici le document.\n\n- point gardé"


def test_chat_text_of_a_document_says_its_template_and_version():
    d = _doc()
    assert "note de cadrage, 5 sections" in turn.chat_text("doc", d, "fr")
    assert turn.chat_text("doc", d, "fr", verb="patch", version=3).startswith("Version 3 du document")
    assert "Fichier" not in turn.chat_text("doc", d, "fr")


def test_code_the_model_wrote_as_a_document_opens_as_code_with_its_preview():
    """« code moi une mini calculatrice web » answered with make_document(title='mini-calculatrice.html'): the canvas
    shows the page in code mode (live preview), never a one-section « Rapport » with .docx / PDF buttons."""
    from birds.web import canvas_web

    page = "<!DOCTYPE html><html><body><button id='b'>1</button><script>document.title='ok'</script></body></html>"
    run = SimpleNamespace(steps=[SimpleNamespace(tool="make_document", error=None, arguments={
        "title": "mini-calculatrice.html", "sections": [{"heading": "Code", "content": page}]})],
        canvas=None, answer="Voici votre mini calculatrice :\n\nmini-calculatrice.html", files=["mini-calculatrice.html.docx"])  # fmt: skip
    canvas_web.adopt_files(run, None, "fr", "code moi une mini calculatrice web")
    ref = canvas_web.ref(run)
    assert ref["kind"] == "code" and ref["open"] is True and ref["files"] == ["mini-calculatrice.html.docx"]
    assert [f["name"] for f in ref["doc"]["code"]["files"]] == ["mini-calculatrice.html"]


def test_a_minisite_written_as_a_report_then_index_html_opens_the_site():
    """« cree un minisite pour parler des Lychaons » (production): make_document(prose), then
    make_document(index.html). The site is the deliverable: the canvas opens the code, never the « Rapport »."""
    from birds.web import canvas_web

    page = "<!DOCTYPE html><html><head><style>body{background:#111}</style></head><body><h1>Lychaons</h1></body></html>"
    prose = {"title": "Lychaons – Les chiens de la nuit", "sections": [
        {"heading": "Qui sont les Lychaons ?", "content": "Des chiens sauvages d'Afrique.\n- Chasse en meute"},
        {"heading": "Conclusion", "content": "Une espèce menacée."}]}  # fmt: skip
    run = SimpleNamespace(steps=[
        SimpleNamespace(tool="make_document", error=None, arguments=prose),
        SimpleNamespace(tool="make_document", error=None, arguments={
            "title": "index.html", "sections": [{"heading": "Code", "content": page}]}),
    ], canvas=None, answer="Voici un minisite.", files=["lychaons.docx", "index.html.docx"])  # fmt: skip
    canvas_web.adopt_files(run, None, "fr", "cree un minisite pour parler des Lychaons")
    ref = canvas_web.ref(run)
    assert ref["kind"] == "code" and ref["open"] is True
    assert [f["name"] for f in ref["doc"]["code"]["files"]] == ["index.html"]


def test_a_minisite_is_a_web_request():
    from birds.canvas import intents

    for text in ("cree un minisite pour parler des Lychaons", "fais-moi un mini-site sur le Mont-Saint-Michel",
                 "un petit site pour ma boulangerie"):  # fmt: skip
        assert intents.ask(text) == "code", text
