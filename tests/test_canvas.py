"""The canvas (birds.canvas, birds.web.canvas_web): the content format, patches, exports, pictures, the chat turns
with a scripted model that fails the way a 4B model does, and the endpoints' security."""

from __future__ import annotations

import base64
import io
import json
import random
import re
import zipfile

import pytest

from birds.canvas import convert, dsl, export, images, intents, patch, turn

DECK = """---
title: Plan mobilité 2027
subtitle: Comité de direction
theme: moderne
---
# Contexte
- 40 % des trajets font moins de 5 km
- Le vélo progresse
::: image query="vélo en ville"
:::
# Chiffres clés
::: kpi
1,2 M€ | Budget | +8 %
Part modale : 31 % (+4 pts)
:::
# Évolution
::: chart type=bar unit="M€"
2023: 1,1
2024: 1,4
2025: 1,9
:::
La hausse continue.
# Calendrier
::: timeline
T1 2026 : pilote
T2 2026 : bilan
T3 2026 : extension
:::
# Citation
> « Le vélo est l'avenir de la ville »
> — Une élue
"""


# ------------------------------------------------------------------ the format


def test_parse_reads_every_block_type():
    d = dsl.parse(DECK, "deck")
    assert (d["title"], d["subtitle"], d["theme"]) == ("Plan mobilité 2027", "Comité de direction", "modern")
    assert [b["id"] for b in d["blocks"]] == ["b1", "b2", "b3", "b4", "b5"]
    kinds = [[p["t"] for p in b["parts"]] for b in d["blocks"]]
    assert kinds == [["list", "image"], ["kpi"], ["chart", "text"], ["timeline"], ["quote"]]
    kpi = d["blocks"][1]["parts"][0]["items"]
    assert kpi[0] == {"value": "1,2 M€", "label": "Budget", "delta": "+8 %"}
    assert kpi[1] == {"value": "31 %", "label": "Part modale", "delta": "+4 pts"}
    chart = d["blocks"][2]["parts"][0]
    assert chart["rows"] == [["2023", 1.1], ["2024", 1.4], ["2025", 1.9]] and chart["unit"] == "M€"
    assert d["blocks"][4]["parts"][0] == {"t": "quote", "text": "Le vélo est l'avenir de la ville", "by": "Une élue"}


def test_parse_repairs_what_a_small_model_writes():
    repairs: list[str] = []
    text = (
        "Voici la présentation demandée :\n\n"
        "# Le télétravail\n## Diapositive 1 : Contexte\n- point A\n::: kpi\n12 % | des salariés\n"  # unclosed
        "## Slide 2 - **Enjeux**\n- point B\n![vélo](https://evil.example/x.png)\n---\n"
        "Organisation\n- point C\n::: graphique\nnord: beaucoup\n:::\nNotes : parler lentement\n```js\nlet x = 1"
    )
    d = dsl.parse(text, "deck", repairs=repairs)
    assert d["title"] == "Le télétravail"
    assert [b["title"] for b in d["blocks"]] == ["Contexte", "Enjeux", "Organisation"]
    img = d["blocks"][1]["parts"][-1]
    assert img["t"] == "image" and img["query"] == "vélo" and "media" not in img  # the URL is never kept
    org = d["blocks"][2]
    assert org["notes"] == "parler lentement"
    assert any(p["t"] == "code" for p in org["parts"])
    assert any("unclosed" in r for r in repairs) and any("URL" in r for r in repairs)


def test_parse_front_matter_variants_and_title_hint():
    d = dsl.parse("Titre : Bilan 2026\nThème : chaleureux\n# A\n- x\n# B\n- y", "deck")
    assert (d["title"], d["theme"]) == ("Bilan 2026", "warm")
    d = dsl.parse("# A\n- x\n# B\n- y", "deck", title_hint="Mon sujet")
    assert d["title"] == "Mon sujet"
    d = dsl.parse("---\ntitle: X\ntheme: fluo\n---\n# A\n- x", "deck")
    assert d["theme"] is None  # unknown theme ignored, chosen later from the subject


GARBAGE = ["", "\x00\x01", ":::", "::: chart\n:::", "#", "# \n#\n", "---\n---\n---", "```", "> ", "|||\n|||",
           "::: image\n:::", "::: kpi\n\n:::", "-" * 5000, "# " + "A" * 5000, "::: chart\nx: 1e400\ny: nan\n:::",
           "\n".join(f"# S{i}\n- p" for i in range(200)), "::: code\n" + "x" * 100_000]  # fmt: skip


@pytest.mark.parametrize("text", GARBAGE)
def test_parse_never_fails_and_always_validates(text):
    for kind in ("deck", "doc"):
        d = dsl.parse(text, kind)
        clean = dsl.validate(d)
        assert len(clean["blocks"]) <= dsl.MAX_BLOCKS
        dsl.to_dsl(clean)


def test_parse_fuzz_random_bytes_round_trip():
    rnd = random.Random(7)
    alphabet = "#:-*>|`\n \t€%0123456789abcdeé«»[]()=\"'!b@"
    for _ in range(400):
        text = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 600)))
        d = dsl.parse(text, rnd.choice(["deck", "doc"]))
        clean = dsl.validate(d)
        again = dsl.parse(dsl.to_dsl(clean, ids=True), clean["kind"])
        assert len(again["blocks"]) <= len(clean["blocks"]) + 1


def test_round_trip_keeps_ids_and_content():
    d = dsl.parse(DECK, "deck")
    again = dsl.parse(dsl.to_dsl(d), "deck")
    assert [b["id"] for b in again["blocks"]] == [b["id"] for b in d["blocks"]]
    assert again["blocks"][1]["parts"] == d["blocks"][1]["parts"]
    assert again["blocks"][2]["parts"][0]["rows"] == d["blocks"][2]["parts"][0]["rows"]


def test_split_answer_keeps_chat_prose_out_of_the_document():
    before, content, after = dsl.split_answer("Bien sûr !\n\n```canvas\n# A\n- x\n```\n\nDites-moi si ça vous va.")
    assert before == "Bien sûr !" and content.strip() == "# A\n- x" and after.startswith("Dites-moi")
    before, content, after = dsl.split_answer("Voici :\n# A\n- x\n\nN'hésitez pas à demander des changements.")
    assert before == "Voici :" and "# A" in content and after.startswith("N'hésitez")


def test_parse_code_prefers_the_previewable_file():
    found = dsl.parse_code("Voici :\n```css\nbody{}\n```\n```html\n<!doctype html><p>hi</p>\n```\nFin.")
    assert found["lang"] == "html" and found["text"].startswith("<!doctype") and found["after"] == "Fin."
    assert dsl.parse_code("<svg viewBox='0 0 1 1'></svg>")["lang"] == "svg"
    assert dsl.parse_code("```\nflowchart TD\n A-->B\n```")["lang"] == "mermaid"
    assert dsl.parse_code("pas de code ici") is None
    unclosed = dsl.parse_code("```html\n<div>en cours")
    assert unclosed["text"] == "<div>en cours"  # streaming: the fence is not closed yet


def test_validate_rejects_bad_shapes_and_cleans_text():
    d = dsl.parse(DECK, "deck")
    bad = json.loads(json.dumps(d))
    bad["blocks"][0]["id"] = "../../etc"
    with pytest.raises(dsl.Invalid):
        dsl.validate(bad)
    bad = json.loads(json.dumps(d))
    bad["blocks"][2]["parts"][0]["rows"][0][1] = "=cmd|' /C calc'!A0"
    with pytest.raises(dsl.Invalid):
        dsl.validate(bad)
    bad = json.loads(json.dumps(d))
    bad["blocks"][0]["title"] = "<img src=x onerror=alert(1)>\x00"
    clean = dsl.validate(bad)
    assert clean["blocks"][0]["title"] == "<img src=x onerror=alert(1)>"  # text stays text (the UI never uses HTML)
    bad = json.loads(json.dumps(d))
    bad["kind"] = "exe"
    with pytest.raises(dsl.Invalid):
        dsl.validate(bad)
    bad = json.loads(json.dumps(d))
    bad["media"] = {"../x": {"kind": "web"}, "w1": {"kind": "evil", "credit": "c" * 999}}
    clean = dsl.validate(bad)
    assert list(clean["media"]) == ["w1"] and clean["media"]["w1"]["kind"] == "user"
    assert len(clean["media"]["w1"]["credit"]) == 300


# ------------------------------------------------------------------ patches


def test_apply_operations():
    d = dsl.parse(DECK, "deck")
    new = dsl.parse("# Risques\n- coût\n- délais", "deck")["blocks"][0]
    out, done, failed = patch.apply(d, [
        {"op": "insert", "after": "b2", "block": new},
        {"op": "delete", "id": "b5"},
        {"op": "move", "id": "b4", "after": "start"},
        {"op": "theme", "theme": "chaleureux"},
        {"op": "replace", "id": "b9", "block": new},
    ])  # fmt: skip
    assert [b["title"] for b in out["blocks"]] == ["Calendrier", "Contexte", "Chiffres clés", "Risques", "Évolution"]
    assert out["blocks"][3]["id"] == "b6" and out["theme"] == "warm"
    assert failed == ["replace: no block b9"] and len(done) == 4
    assert [b["id"] for b in d["blocks"]] == ["b1", "b2", "b3", "b4", "b5"]  # the input is not modified


def test_ids_are_never_reused():
    d = dsl.parse(DECK, "deck")
    out, _, _ = patch.apply(d, [{"op": "delete", "id": "b5"}])
    out, _, _ = patch.apply(out, [{"op": "insert", "after": "end", "block": {"title": "X", "parts": []}}])
    assert out["blocks"][-1]["id"] == "b6"


@pytest.mark.parametrize(
    "words,expected",
    [
        ("supprime la diapo 3", [{"op": "delete", "id": "b3"}]),
        ("enlève la slide n°2", [{"op": "delete", "id": "b2"}]),
        ("duplique la slide 1", [{"op": "duplicate", "id": "b1"}]),
        ("inverse les slides 2 et 3", [{"op": "swap", "id": "b2", "other": "b3"}]),
        ("mets la diapo 4 au début", [{"op": "move", "id": "b4", "after": "start"}]),
        ("déplace la slide 5 avant la slide 2", [{"op": "move", "id": "b5", "after": "b1"}]),
        ("passe en thème chaleureux", [{"op": "theme", "theme": "warm"}]),
        ("change le thème", [{"op": "theme", "theme": "warm"}]),  # the next one after « modern »
        (
            "remplace l'image de la slide 1 par une photo de tramway à Lyon",
            [{"op": "image", "id": "b1", "query": "tramway à Lyon", "again": False}],
        ),
        ("une autre image pour la diapo 1", [{"op": "image", "id": "b1", "query": "", "again": True}]),
        ("retire l'image de la slide 1", [{"op": "unimage", "id": "b1"}]),
        ("delete slide 2", [{"op": "delete", "id": "b2"}]),
    ],
)
def test_direct_ops_from_the_users_words(words, expected):
    d = dsl.parse(DECK, "deck")
    ops, _ = patch.direct_ops(words, d)
    assert ops == expected


@pytest.mark.parametrize(
    "words",
    [
        "ajoute une slide sur les risques",
        "plus court",
        "supprime les chiffres en trop de la slide 2",
        "rends la slide 3 plus percutante",
        "merci",
        "traduis en anglais",
    ],
)
def test_direct_ops_leave_the_rest_to_the_model(words):
    assert patch.direct_ops(words, dsl.parse(DECK, "deck")) is None


def test_parse_patch_directives_tags_and_inserts():
    d = dsl.parse(DECK, "deck")
    ops, mode = patch.parse_patch("@replace b2\n# Chiffres\n- 1,2 M€ de budget\n@after b4\n# Risques\n- coût\n@delete b5\n"
                                  "@theme warm", d)  # fmt: skip
    out = patch.apply_all(d, ops)[0]
    assert mode == "ops" and [b["title"] for b in out["blocks"]] == ["Contexte", "Chiffres", "Évolution", "Calendrier",
                                                                      "Risques"]  # fmt: skip
    assert out["theme"] == "warm" and out["blocks"][1]["id"] == "b2"
    # the model kept the tag instead of writing a directive
    ops, mode = patch.parse_patch("Voici :\n# [b3] Évolution récente\n- hausse\n", d)
    assert mode == "ops" and ops[0]["op"] == "replace" and ops[0]["id"] == "b3"
    # a new block with no directive: placed before the closing slide when there is one, else at the end
    ops, mode = patch.parse_patch("# Risques\n- coût\n- délais", d, "ajoute une slide sur les risques")
    out = patch.apply_all(d, ops)[0]
    assert mode == "insert" and out["blocks"][-1]["title"] == "Risques"
    ops, _ = patch.parse_patch("# Risques\n- coût", d, "ajoute une slide sur les risques après la slide 2")
    assert [b["title"] for b in patch.apply_all(d, ops)[0]["blocks"]][2] == "Risques"
    # French verbs, no '@' but all caps
    ops, _ = patch.parse_patch("REMPLACE b1\n# Contexte court\n- vélo", d)
    assert ops[0]["op"] == "replace"


def test_parse_patch_full_rewrite_keeps_ids_pictures_and_theme():
    d = dsl.parse(DECK, "deck")
    d["blocks"][0]["parts"][1]["media"] = "w1"
    d["media"] = {"w1": {"kind": "web", "credit": "X — CC BY 4.0", "licence": "CC BY 4.0"}}
    short = '# Contexte\n- trajets courts\n::: image query="vélo en ville"\n:::\n# Chiffres clés\n- 1,2 M€\n# Évolution\n- +8 %\n# Fin\n- merci'
    ops, mode = patch.parse_patch(short, d, "plus court")
    out = patch.apply_all(d, ops)[0]
    assert mode == "rewrite" and [b["id"] for b in out["blocks"]] == ["b1", "b2", "b3", "b6"]
    assert out["theme"] == "modern" and out["blocks"][0]["parts"][1]["media"] == "w1"


def test_parse_patch_targeted_block():
    d = dsl.parse(DECK, "deck")
    ops, mode = patch.parse_patch("# Chiffres clés\n::: kpi\n2 M€ | Budget\n:::", d, "", target="b2")
    out = patch.apply_all(d, ops)[0]
    assert mode == "target" and out["blocks"][1]["parts"][0]["items"][0]["value"] == "2 M€"


# ------------------------------------------------------------------ the harness's reading of plain bullets


def test_enrich_reads_plain_bullets_as_what_they_are():
    text = ("# Évolution du CA\n- 2022 : 1,1 M€\n- 2023 : 1,4 M€\n- 2024 : 1,9 M€\n- 2025 : 2,3 M€\n"
            "# Feuille de route\n- T1 2026 : pilote\n- T2 2026 : bilan\n- T3 2026 : extension\n"
            "# Une phrase\n- « Le vélo est l'avenir de la ville » — Une élue\n"
            "# Chiffres\n- CA : 1,2 M€ (+8 %)\n- Marge : 31 %\n"
            "# Texte\n- Un point ordinaire\n- Un autre point ordinaire")  # fmt: skip
    d = convert.enrich(dsl.parse(text, "deck"))
    assert [b["parts"][0]["t"] for b in d["blocks"]] == ["chart", "timeline", "quote", "kpi", "list"]
    assert d["blocks"][0]["parts"][0]["type"] == "line" and d["blocks"][0]["parts"][0]["rows"][-1] == ["2025", 2.3]


def test_from_tool_turns_trained_calls_into_documents():
    deck = convert.from_tool(
        "make_slides",
        {"title": "T", "slides": [{"title": "A", "bullets": ["x", "y"]}, {"title": "B", "bullets": ["CA : 1,2 M€"]}]},
        "fr",
    )
    assert deck["kind"] == "deck" and [b["id"] for b in deck["blocks"]] == ["b1", "b2"]
    assert deck["blocks"][1]["parts"][0]["t"] == "kpi"
    doc = convert.from_tool(
        "make_document", {"title": "N", "sections": [{"heading": "H", "content": "Texte.\n\n- a\n- b"}]}
    )
    assert [p["t"] for p in doc["blocks"][0]["parts"]] == ["text", "list"]
    sheet = convert.from_tool("make_sheet", {"title": "S", "columns": ["a", "b"], "rows": [[1, 2], [3]]})
    assert sheet["sheet"] == {"columns": ["a", "b"], "rows": [["1", "2"], ["3", ""]]}
    assert convert.from_tool("web_search", {}) is None


# ------------------------------------------------------------------ intents


@pytest.mark.parametrize(
    "words,kind",
    [
        ("Fais une présentation de 6 slides sur le télétravail", "deck"),
        ("prépare des slides sur le marché du cloud", "deck"),
        ("make a pitch deck for our startup", "deck"),
        ("une présentation sur le vélo, 5 slides", "deck"),
        ("Rédige un rapport sur la sécurité informatique", "doc"),
        ("Fais le compte rendu de cette réunion", "doc"),
        ("crée une landing page pour une boulangerie", "code"),
        ("fais une page HTML avec un formulaire de contact", "code"),
        ("fais un logo svg pour Bird", "code"),
        ("écris un script python qui renomme des fichiers", "code"),
        ("dessine le schéma du processus de recrutement", "diagram"),
        ("draw a flowchart of the onboarding process", "diagram"),
    ],
)
def test_canvas_opens_on_creation_asks(words, kind):
    assert intents.ask(words) == kind


def test_canvas_never_opens_on_ordinary_office_prompts():
    from scripts.trigger_bench import CANVAS_OFFICE_NO, CHART_HOWTO_NO, CHART_NO

    extra = [
        "Comment faire une bonne présentation ?",
        "Comment ajouter une diapo dans PowerPoint ?",
        "Présente-moi l'entreprise Airbus",
        "résume ce document en 5 points",
        "écris une fonction Python qui trie une liste",
        "rédige un mail pour envoyer la présentation à Paul",
        "traduis ce rapport en anglais",
        "fais-moi un tableau des congés de l'équipe",
        "quelle est la différence entre un rapport et une note ?",
    ]
    hits = [q for q in CANVAS_OFFICE_NO + CHART_NO + CHART_HOWTO_NO + extra if intents.ask(q)]
    assert hits == []


@pytest.mark.parametrize(
    "words",
    [
        "ajoute une slide sur les risques",
        "remplace l'image de la slide 3",
        "plus court",
        "et en anglais ?",
        "corrige l'erreur",
    ],
)
def test_edit_asks(words):
    assert intents.edit_ask(words, "deck")
    assert intents.edit_ask("mets le bouton en bleu", "code")


@pytest.mark.parametrize(
    "words",
    [
        "merci !",
        "quelle est la TVA ?",
        "fais une présentation sur le vélo",
        "c'est quoi un KPI ?",
        "rédige un mail pour envoyer la présentation à Paul",
        "Mets un rappel dans mon agenda",
        "Mets un rappel dans mon agenda lundi à 9h",
        "Change rien, c'est bien",
        "Traduis 'bonjour' en japonais",
        "Fix the bug in my Excel formula =SOMME(A1:A3",
        "mets le bouton en bleu",  # a deck has no button
    ],
)
def test_not_edit_asks(words):
    assert not intents.edit_ask(words, "deck")


@pytest.mark.parametrize("words", ["plus court", "et en anglais ?", "raccourcis", "mets-le en bleu"])
def test_short_unnamed_edits_need_the_panel_shown(words):
    assert intents.edit_ask(words, "deck", shown=True)
    assert not intents.edit_ask(words, "deck", shown=False)
    assert intents.edit_ask("ajoute une slide sur les risques", "deck", shown=False)  # it names a part


@pytest.mark.parametrize(
    "words",
    [
        "Ne mets pas la slide 2 à la fin",
        "Change le titre de la slide 2 en « Risques » plutôt que de la supprimer",
        "Surtout ne touche pas à la diapo 3, supprime plutôt les fautes",
        "Mets la slide 2 en premier ? Non attends, laisse",
        "Supprime la slide 2 et mets la 3 à la fin",
        "move slide 2 to the end, not slide 3",
    ],
)
def test_direct_ops_leave_negations_hesitations_and_two_actions_to_the_model(words):
    d = dsl.parse(DECK, "deck")
    assert patch.direct_ops(words, d) is None
    p = turn.plan(words, {"doc": d, "aid": "a0123456789ab", "version": 1, "open": True}, "fr")
    assert p is not None and p.mode == "patch"


def test_direct_ops_still_apply_plain_orders():
    d = dsl.parse(DECK, "deck")
    assert patch.direct_ops("Mets la slide 2 en premier", d)[1] == "move"
    assert patch.direct_ops("Renomme la slide 2 en « Ne pas oublier »", d)[0][0]["title"] == "Ne pas oublier"
    assert patch.direct_ops("passe en thème chaleureux", d)[1] == "theme"


def test_closed_panel_sends_a_reference_and_an_ordinary_message_stays_ordinary():
    d = dsl.parse(DECK, "deck")
    from birds.web import canvas_web

    ref = canvas_web.canvas_in({"aid": "a0123456789ab", "version": 3, "kind": "deck", "open": False})
    assert ref == {"ref": True, "aid": "a0123456789ab", "kind": "deck", "version": 3, "open": False}
    assert turn.plan("Mets un rappel dans mon agenda lundi à 9h", ref, "fr") is None
    assert turn.plan("plus court", ref, "fr") is None
    p = turn.plan("ajoute une slide sur les risques", ref, "fr")
    assert p.mode == "reopen" and p.aid == "a0123456789ab" and "rouvert" in p.said
    # the turn right after it was made: the document comes along, but the closed panel needs a named part
    fresh = canvas_web.canvas_in({"aid": "a0123456789ab", "version": 1, "doc": d, "open": False})
    assert fresh["open"] is False
    assert turn.plan("Mets un rappel dans mon agenda lundi à 9h", fresh, "fr") is None
    assert turn.plan("Traduis 'bonjour' en japonais", fresh, "fr") is None
    assert turn.plan("supprime la slide 3", fresh, "fr").mode == "direct"
    assert turn.plan("plus court", fresh, "fr") is None  # not flagged fresh: a named part is needed
    fresh["fresh"] = True  # the turn right after it was made (a phone closes its sheet to type)
    assert turn.plan("plus court", fresh, "fr").mode == "patch"
    assert turn.plan("Mets un rappel dans mon agenda lundi à 9h", fresh, "fr") is None
    assert turn.plan("Traduis 'bonjour' en japonais", fresh, "fr") is None


def test_reopen_turn_makes_no_model_call(monkeypatch):
    from fastapi.testclient import TestClient

    app, llm = _app([])
    with TestClient(app) as client:
        events = _chat(client, "ajoute une slide sur les risques",
                       canvas={"aid": "a0123456789ab", "version": 2, "kind": "deck", "open": False})  # fmt: skip
    assert llm.prompts == []
    assert [e for e in events if e["type"] == "canvas"] == [
        {"type": "canvas", "phase": "reopen", "aid": "a0123456789ab", "kind": "deck"}
    ]
    assert "rouvert" in next(e for e in events if e["type"] == "answer")["content"]



# ------------------------------------------------------------------ pictures


class FakeFetch:
    def __init__(self, licence="CC BY-SA 4.0"):
        self.licence, self.urls = licence, []

    def json(self, url):
        self.urls.append(url)
        pages = []
        for i, name in enumerate(["Velo_Paris.jpg", "Velo_Lyon.jpg"]):
            pages.append(
                {
                    "index": i + 1,
                    "title": f"File:{name}",
                    "imageinfo": [
                        {
                            "thumburl": f"https://upload.wikimedia.org/thumb/{name}",
                            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
                            "url": f"https://upload.wikimedia.org/{name}",
                            "extmetadata": {
                                "LicenseShortName": {"value": self.licence},
                                "Artist": {"value": "<b>Ann</b>"},
                            },
                        }
                    ],
                }
            )
        return {"query": {"pages": pages}}

    def image(self, url):
        from PIL import Image

        self.urls.append(url)
        buf = io.BytesIO()
        Image.new("RGB", (1200, 800), (40, 90, 200)).save(buf, "JPEG")
        return buf.getvalue()


def test_commons_search_checks_the_licence_and_credits():
    f = FakeFetch()
    m = images.search_commons("vélo en ville", f, mid="w1")
    assert m is not None and m.kind == "web" and "CC BY-SA 4.0" in m.credit and "Ann" in m.credit
    assert m.source.startswith("https://commons.wikimedia.org/wiki/File:Velo_Paris")
    assert "filetype%3Abitmap" in f.urls[0] or "filetype:bitmap" in f.urls[0]
    again = images.search_commons("vélo en ville", FakeFetch(), exclude=[m.source], mid="w2")
    assert again is not None and "Velo_Lyon" in again.source
    assert images.search_commons("vélo", FakeFetch("CC BY-NC 4.0")) is None  # non-commercial: refused


def test_resolve_fills_image_parts_and_never_invents():
    d = dsl.parse(DECK, "deck")
    found = images.resolve(d, lambda q, ex, mid: None)
    assert found == [] and d["blocks"][0]["parts"][1].get("missing") and "media" not in d["blocks"][0]["parts"][1]
    d = dsl.parse(DECK, "deck")
    found = images.resolve(d, images.finder("demo", theme="modern"))
    part = d["blocks"][0]["parts"][1]
    assert part["media"] == "g1" and d["media"]["g1"]["kind"] == "gen" and "démo" in d["media"]["g1"]["credit"]
    assert base64.b64decode(found[0]["data"])[:3] == b"\xff\xd8\xff"


# ------------------------------------------------------------------ exports


def _media(d):
    found = images.resolve(d, images.finder("demo"))
    return {f["id"]: f["data"] for f in found}


def test_export_deck_round_trip():
    from pptx import Presentation

    d = dsl.parse(DECK, "deck")
    media = _media(d)
    data, mime, name = export.export(dsl.validate(d), "pptx", media)
    prs = Presentation(io.BytesIO(data))
    titles = [s.shapes.title.text for s in prs.slides if s.shapes.title is not None]
    assert titles[0] == "Plan mobilité 2027" and "Calendrier" in titles and "Citation" in titles
    assert len(prs.slides) == 6  # the cover + 5 slides: no agenda or closing slide the canvas does not show
    assert name == "Plan-mobilité-2027.pptx" and mime.endswith("presentation")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert any(n.startswith("ppt/media/") for n in z.namelist())  # the picture is in
        assert any(n.startswith("ppt/charts/") for n in z.namelist())  # the chart is a native chart


def test_export_document_round_trip():
    from docx import Document

    d = dsl.parse(DECK.replace("theme: moderne", "theme: sobre"), "doc")
    media = _media(d)
    data, _, name = export.export(dsl.validate(d), "docx", media)
    text = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    assert "Contexte" in text and "40 % des trajets" in text and name.endswith(".docx")


def test_export_sheet_neutralises_formula_injection():
    from openpyxl import load_workbook

    doc = {"v": 1, "kind": "sheet", "title": "Budget", "sheet": {"columns": ["Poste", "Montant", "Note"], "rows": [
        ["A", "120", "=SUM(B2:B3)"], ["B", "80", "=HYPERLINK(\"http://evil\",\"x\")"],
        ["C", "=cmd|' /C calc'!A0", "@SUM(1)"]]}}  # fmt: skip
    data, _, _ = export.export(dsl.validate(doc), "xlsx")
    ws = load_workbook(io.BytesIO(data)).active
    cells = {c.coordinate: c for row in ws.iter_rows() for c in row}
    formulas = [c.value for c in cells.values() if c.data_type == "f"]
    assert any("SUM(B3:B4)" in str(v) for v in formulas)  # the panel's B2:B3, under the file's header row
    assert not any("HYPERLINK" in str(v) or "cmd" in str(v) for v in formulas)


def test_export_refuses_mismatched_kinds():
    d = dsl.validate(dsl.parse(DECK, "deck"))
    with pytest.raises(export.ExportError):
        export.export(d, "xlsx")


# ------------------------------------------------------------------ chat turns with a scripted model


def _tool_call(name: str, **args) -> str:
    params = "".join(f"<parameter={k}>\n{v if isinstance(v, str) else json.dumps(v)}\n</parameter>\n"
                     for k, v in args.items())  # fmt: skip
    return f"<tool_call>\n<function={name}>\n{params}</function>\n</tool_call>"


def _app(outputs):
    from birds.harness import FakeClient
    from birds.web.backends import HarnessBackend
    from birds.web.server import create_app
    from tests.test_web import _Tok, settings

    llm = FakeClient(outputs)
    backend = HarnessBackend(llm, _Tok(), kind="completions", model="bird-test")
    return create_app(settings(), server_backend=backend), llm


def _chat(client, text, **extra):
    from tests.test_web import post_chat

    return post_chat(client, {"messages": [{"role": "user", "content": text}], **extra})


def _no_network(monkeypatch):
    monkeypatch.setattr(images, "search_commons", lambda *a, **k: None)


def test_create_turn_streams_blocks_and_hides_the_trained_file_tools(monkeypatch):
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    app, llm = _app(["Voici la présentation :\n\n" + DECK + "\nN'hésitez pas à demander des changements."])
    with TestClient(app) as client:
        events = _chat(client, "Fais une présentation sur le plan mobilité de la ville")
    prompt = json.loads(llm.prompts[0])
    assert "make_slides" not in prompt["tools"] and "make_document" not in prompt["tools"]
    assert "[Canevas]" in prompt["messages"][-1]["content"]
    canvas = [e for e in events if e["type"] == "canvas"]
    stream = [e for e in canvas if e["phase"] == "stream"]
    assert len(stream) >= 3, "blocks appear while the model writes"
    assert [len(e["doc"]["blocks"]) for e in stream] == sorted(len(e["doc"]["blocks"]) for e in stream)
    final = canvas[-1]
    assert final["phase"] == "final" and final["base"] is None and final["open"] is True
    assert [b["title"] for b in final["doc"]["blocks"]][:2] == ["Contexte", "Chiffres clés"]
    answer = next(e for e in events if e["type"] == "answer")
    assert "canevas" in answer["content"] and "::: kpi" not in answer["content"]
    assert answer["canvas"] == {"aid": final["aid"], "version": 1}
    assert "[canvas deck v1" in answer["memo"] and "b2 Chiffres clés" in answer["memo"]
    assert not [e for e in events if e["type"] == "delta"]  # the content goes to the canvas, not the chat


def test_create_turn_captures_a_trained_tool_call(monkeypatch):
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    slides = [
        {"title": "Contexte", "bullets": ["a", "b"]},
        {"title": "CA", "bullets": ["2023 : 1 M€", "2024 : 2 M€", "2025 : 3 M€"]},
    ]
    app, llm = _app([_tool_call("make_slides", title="Bilan", slides=slides), "C'est prêt."])
    with TestClient(app) as client:
        events = _chat(client, "Fais une présentation du bilan annuel")
    final = [e for e in events if e["type"] == "canvas"][-1]
    assert final["doc"]["title"] == "Bilan" and final["doc"]["blocks"][1]["parts"][0]["t"] == "chart"
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["files"] == []  # no .pptx written on a canvas turn: the canvas exports it


def test_create_turn_salvages_a_deck_cut_by_the_length_limit(monkeypatch):
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    app, llm = _app([DECK[: DECK.index("# Calendrier") + 30]])
    with TestClient(app) as client:
        events = _chat(client, "Fais une présentation sur le vélo")
    final = [e for e in events if e["type"] == "canvas"][-1]
    assert final["phase"] == "final" and len(final["doc"]["blocks"]) == 4


def test_create_turn_reads_tool_arguments_written_as_json_text(monkeypatch):
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    text = 'Voici :\n```json\n{"name": "make_slides", "arguments": {"title": "Vélo", "slides": [{"title": "A", ' \
           '"bullets": ["x", "y"]}, {"title": "B", "bullets": ["z"]}]}}\n```'  # fmt: skip
    app, _ = _app([text])
    with TestClient(app) as client:
        events = _chat(client, "Fais une présentation sur le vélo")
    final = [e for e in events if e["type"] == "canvas"][-1]
    assert final["doc"]["title"] == "Vélo" and [b["title"] for b in final["doc"]["blocks"]] == ["A", "B"]


def test_a_long_repetitive_deck_is_not_cut_as_a_loop(monkeypatch):
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    slides = "\n".join(
        f"# Partie {i}\n- Point clé numéro un de la partie {i}\n- Point clé numéro deux de la partie {i}\n"
        f'- Point clé numéro trois de la partie {i}\n::: image query="illustration partie {i}"\n:::'
        for i in range(1, 9)
    )
    app, _ = _app(["---\ntitle: Long\n---\n" + slides])
    with TestClient(app) as client:
        events = _chat(client, "Fais une présentation de 8 slides sur le plan de formation")
    final = [e for e in events if e["type"] == "canvas"][-1]
    assert len(final["doc"]["blocks"]) == 8


def test_create_turn_without_content_leaves_the_answer_in_the_chat(monkeypatch):
    from fastapi.testclient import TestClient

    app, llm = _app(["Je n'ai pas assez d'informations : sur quel sujet ?"])
    with TestClient(app) as client:
        events = _chat(client, "Fais une présentation")
    assert not [e for e in events if e["type"] == "canvas" and e["phase"] == "final"]
    assert "quel sujet" in next(e for e in events if e["type"] == "answer")["content"]


def _canvas_body(doc, aid="a0123456789ab", version=2, target=None):
    out = {"aid": aid, "version": version, "doc": doc}
    if target:
        out["target"] = target
    return out


def test_direct_edit_needs_no_model(monkeypatch):
    from fastapi.testclient import TestClient

    app, llm = _app([])
    doc = dsl.parse(DECK, "deck")
    with TestClient(app) as client:
        events = _chat(client, "supprime la diapo 3", canvas=_canvas_body(doc))
    assert llm.prompts == []
    final = [e for e in events if e["type"] == "canvas"][-1]
    assert final["aid"] == "a0123456789ab" and final["base"] == 2
    assert [b["id"] for b in final["doc"]["blocks"]] == ["b1", "b2", "b4", "b5"]
    assert next(e for e in events if e["type"] == "answer")["canvas"] == {"aid": "a0123456789ab", "version": 3}


def test_patch_turn_gives_the_outline_and_applies_operations(monkeypatch):
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    app, llm = _app(["@after b4\n# Risques\n- Coût des pistes\n- Sécurité des cyclistes\n"])
    with TestClient(app) as client:
        events = _chat(
            client, "ajoute une slide sur les risques après la slide 4", canvas=_canvas_body(dsl.parse(DECK, "deck"))
        )
    prompt = json.loads(llm.prompts[0])
    assert not set(prompt.get("tools") or []) & set(turn.FILE_TOOLS)  # the turn's tools, no file tool
    assert "[b3] Évolution" in prompt["messages"][-1]["content"]
    final = [e for e in events if e["type"] == "canvas"][-1]
    assert [b["title"] for b in final["doc"]["blocks"]][4] == "Risques" and final["doc"]["blocks"][4]["id"] == "b6"


def test_patch_turn_targeted_block(monkeypatch):
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    app, llm = _app(["# Chiffres clés\n::: kpi\n2 M€ | Budget 2027\n:::"])
    with TestClient(app) as client:
        events = _chat(client, "mets à jour avec 2 M€", canvas=_canvas_body(dsl.parse(DECK, "deck"), target="b2"))
    assert "[b2] Chiffres clés" in json.loads(llm.prompts[0])["messages"][-1]["content"]
    final = [e for e in events if e["type"] == "canvas"][-1]
    assert final["doc"]["blocks"][1]["parts"][0]["items"][0]["value"] == "2 M€"


def test_code_turn_and_code_patch(monkeypatch):
    from fastapi.testclient import TestClient

    page = "<!doctype html><html><body><h1>Boulangerie</h1><script>document.title='x'</script></body></html>"
    app, llm = _app([f"Voici la page :\n```html\n{page}\n```\nElle est autonome.",
                     f"```html\n{page.replace('Boulangerie', 'Pâtisserie')}\n```"])  # fmt: skip
    with TestClient(app) as client:
        events = _chat(client, "crée une landing page pour une boulangerie")
        final = [e for e in events if e["type"] == "canvas"][-1]
        assert final["doc"]["code"]["lang"] == "html" and "Boulangerie" in final["doc"]["code"]["text"]
        events = _chat(client, "change le titre en Pâtisserie", canvas=_canvas_body(final["doc"], final["aid"], 1))
    assert "```html" in json.loads(llm.prompts[1])["messages"][-1]["content"]
    final = [e for e in events if e["type"] == "canvas"][-1]
    assert "Pâtisserie" in final["doc"]["code"]["text"] and final["base"] == 1


def test_ordinary_turn_keeps_the_trained_tool_block_and_ignores_the_canvas(monkeypatch):
    from fastapi.testclient import TestClient

    from birds.tools import PRODUCT_TOOL_NAMES

    app, llm = _app(["La TVA normale est de 20 %."])
    with TestClient(app) as client:
        events = _chat(client, "quel est le taux de TVA normal ?", canvas=_canvas_body(dsl.parse(DECK, "deck")))
    tools = json.loads(llm.prompts[0])["tools"]
    assert set(tools) <= set(PRODUCT_TOOL_NAMES) and "make_slides" in tools
    assert "[Canevas]" not in llm.prompts[0]
    assert not [e for e in events if e["type"] == "canvas"]


def test_file_from_a_trained_tool_is_offered_in_the_canvas():
    from fastapi.testclient import TestClient

    app, llm = _app([_tool_call("make_sheet", title="Congés", columns=["Nom", "Jours"], rows=[["Ana", 3]]), "Voilà."])
    with TestClient(app) as client:
        events = _chat(client, "fais-moi un tableur des congés de l'équipe")
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["files"] and answer["canvas"]["open"] is False
    assert answer["canvas"]["doc"]["sheet"] == {"columns": ["Nom", "Jours"], "rows": [["Ana", "3"]]}


def test_invalid_canvas_is_ignored_and_oversized_refused():
    from fastapi.testclient import TestClient

    app, llm = _app(["ok"])
    with TestClient(app) as client:
        events = _chat(client, "supprime la diapo 1", canvas={"doc": {"kind": "exe"}})
        assert next(e for e in events if e["type"] == "answer")["content"]
        big = {
            "kind": "doc",
            "blocks": [{"id": f"b{i}", "parts": [{"t": "text", "text": "x" * 4000}] * 3} for i in range(40)],
        }
        r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}], "canvas": {"doc": big}})
        assert r.status_code == 413


# ------------------------------------------------------------------ endpoints


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from birds.web.server import create_app
    from tests.test_web import settings

    with TestClient(create_app(settings())) as c:
        yield c


def test_export_endpoint(client):
    d = dsl.parse(DECK, "deck")
    media = _media(d)
    r = client.post("/api/canvas/export", json={"doc": d, "format": "pptx", "media": media})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    r = client.post("/api/canvas/export", json={"doc": d, "format": "docx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"


@pytest.mark.parametrize(
    "body,status",
    [
        ({"doc": {"kind": "deck", "blocks": [{"id": "../x", "parts": []}]}, "format": "pptx"}, 422),
        ({"doc": {"kind": "deck", "blocks": "x"}, "format": "pptx"}, 422),
        ({"doc": {"kind": "deck", "blocks": []}, "format": "exe"}, 422),
        (
            {
                "doc": {"kind": "deck", "blocks": [{"id": "b1", "parts": []}]},
                "format": "pptx",
                "media": {"../../etc/passwd": "AAAA"},
            },
            413,
        ),
        (
            {
                "doc": {"kind": "deck", "blocks": [{"id": "b1", "parts": []}]},
                "format": "pptx",
                "media": {"w1": "not base64!"},
            },
            422,
        ),
        (
            {
                "doc": {"kind": "deck", "blocks": [{"id": "b1", "parts": [{"t": "script", "text": "x"}]}]},
                "format": "pptx",
            },
            422,
        ),
    ],
)
def test_export_endpoint_rejects_bad_input(client, body, status):
    assert client.post("/api/canvas/export", json=body).status_code == status


def test_export_endpoint_size_and_origin(client):
    r = client.post(
        "/api/canvas/export",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": str(5_000_000)},
    )
    assert r.status_code in (413, 422)
    d = dsl.parse(DECK, "deck")
    r = client.post("/api/canvas/export", json={"doc": d, "format": "pptx"}, headers={"Origin": "https://evil.test"})
    assert r.status_code == 403


def test_export_keeps_hostile_text_as_text(client):
    from pptx import Presentation

    d = dsl.parse('# <script>alert(1)</script>\n- <img src=x onerror=alert(1)>\n- =HYPERLINK("http://x")', "deck")
    r = client.post("/api/canvas/export", json={"doc": d, "format": "pptx"})
    prs = Presentation(io.BytesIO(r.content))
    texts = [sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame]
    assert any("<script>alert(1)</script>" in t for t in texts)


def test_image_endpoint_demo_draws_and_never_fetches_a_url(client):
    r = client.post("/api/canvas/image", json={"query": "vélo en ville", "theme": "warm"})
    body = r.json()
    assert body["ok"] and body["media"]["kind"] == "gen" and body["media"]["id"] == "g1"
    assert client.post("/api/canvas/image", json={"query": ""}).status_code == 422
    assert client.post("/api/canvas/image", json={"query": "x", "mid": "../a"}).status_code == 422


def test_check_endpoint(client):
    assert client.post("/api/canvas/check", json={"lang": "python", "code": "def f(:\n  pass"}).json()["ok"] is False
    assert client.post("/api/canvas/check", json={"lang": "python", "code": "print(1)"}).json()["ok"] is True


def test_preview_frame_is_sandboxed_and_offline(client):
    from birds.web.server import CSP

    r = client.get("/canvas/frame")
    csp = r.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp and "allow-same-origin" not in csp
    assert "connect-src 'none'" in csp and "img-src data: blob:" in csp and "default-src 'none'" in csp
    assert "frame-ancestors 'self'" in csp and r.headers["x-frame-options"] == "SAMEORIGIN"
    assert "frame-src 'self'" in CSP  # the app allows same-origin frames only: the frame cannot navigate away
    assert "http" not in r.text.split("<script>")[1]  # the bootstrap loads nothing
    assert client.get("/").headers["x-frame-options"] == "DENY"  # the app itself is still never framed


def test_turn_text_and_memo():
    d = dsl.parse(DECK, "deck")
    text = turn.chat_text("deck", d, "fr")
    assert "Plan mobilité 2027" in text and "5 diapositives" in text
    assert turn.chat_text("deck", d, "en").startswith("The deck")
    assert turn.memo_line({"doc": d, "version": 3}).startswith("[canvas deck v3")


def test_image_endpoint_server_mode_with_pinned_dns(monkeypatch):
    """The deployment's setting (BIRD_PIN_DNS on): server.fetch_client is None there, the endpoint still gets a
    real client (server.image_client) and closes it, never a 500."""
    from fastapi.testclient import TestClient

    from birds.harness import office_media as om
    from birds.web.server import create_app
    from tests.test_web import settings

    seen = {}

    class Fetcher:
        def __init__(self, http, cfg):
            seen["http"], seen["pin"] = http, cfg.pin_dns

    def search(query, fetch, exclude, mid, deadline=None):
        seen["query"] = query
        return None

    monkeypatch.setattr(om, "Fetcher", Fetcher)
    monkeypatch.setattr(images, "search_commons", search)
    s = settings(allow_user_endpoint=True, pin_dns=True)
    with TestClient(create_app(s)) as c:
        r = c.post("/api/canvas/image", json={"query": "vélo"}, headers={"x-bird-mode": "user"})
    assert r.status_code == 200 and r.json() == {"ok": False, "reason": "none"}
    assert seen["query"] == "vélo" and seen["pin"] is True
    assert seen["http"] is not None and hasattr(seen["http"], "stream")


def test_xlsx_export_writes_excel_formulas_and_their_values():
    """The mini-sheet's French formulas (SOMME, ARRONDI, « ; », « 1,5 ») become OOXML (SUM, ROUND, « , », « 1.5 »),
    its rows are shifted under the header row, and each value it can compute is the cell's cached <v>."""
    from openpyxl import load_workbook

    from birds.canvas import sheetfx

    rows = [["=SOMME(1;2)", "=1+1"], ["3", "=A1*2"], ["=ARRONDI(1,25;1)", '=SI(A1>1;"oui; non";"x")'],
            ["=MOYENNE(A1:A2)", "=NB(B1:B2)"]]  # fmt: skip
    d = {"v": 1, "kind": "sheet", "title": "S", "subtitle": "", "theme": None, "lang": "fr", "blocks": [],
         "media": {}, "sheet": {"columns": ["a", "b"], "rows": rows}}  # fmt: skip
    data, _, _ = export.export(export.validated(d), "xlsx", {})
    xml = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
    fx = re.findall(r"<f>([^<]*)</f>", xml)
    assert len(fx) == 7 and not any(re.search(r"SOMME|ARRONDI|MOYENNE|NB\(|SI\(", f) for f in fx)
    assert not any(";" in f.replace("&gt;", ">").split('"')[0] for f in fx)
    assert "<v></v>" not in xml and "<v />" not in xml
    f = [[c.value for c in r] for r in load_workbook(io.BytesIO(data)).active.iter_rows()]
    assert f[1] == ["=SUM(1,2)", "=1+1"] and f[2][1] == "=A2*2" and f[3] == ["=ROUND(1.25,1)",
                                                                           '=IF(A2>1,"oui; non","x")']  # fmt: skip
    assert f[4] == ["=AVERAGE(A2:A3)", "=COUNT(B2:B3)"]
    v = [[c.value for c in r] for r in load_workbook(io.BytesIO(data), data_only=True).active.iter_rows()]
    assert v[1] == [3, 2] and v[2] == [3, 6] and v[3][0] == 1.3 and v[4][0] == 3
    # and back: a trained make_sheet formula (header in row 1) is read in the panel's rows
    assert sheetfx.from_ooxml("=SUM(B2:B9)") == "=SUM(B1:B8)" and sheetfx.from_ooxml("=A1") == "=A1"
    doc = convert.from_tool("make_sheet", {"title": "T", "columns": ["x", "y"], "rows": [[1, 2], [3, "=SUM(A2:A3)"]]})
    assert doc["sheet"]["rows"][1][1] == "=SUM(A1:A2)"
    assert sheetfx.to_ooxml('="A1;B2"&A1') == '="A1;B2"&A2'


def test_canvas_bench_has_no_false_trigger():
    """The trigger bench's canvas family: every creation ask opens the right canvas, no office prompt does."""
    from scripts.trigger_bench import CANVAS_CODE_FROM_OFFICE, CANVAS_NO, CANVAS_OFFICE_NO, CANVAS_YES

    assert [q for q, k in CANVAS_YES + CANVAS_CODE_FROM_OFFICE if intents.ask(q) != k] == []
    assert [q for q in CANVAS_NO + CANVAS_OFFICE_NO if intents.ask(q)] == []


@pytest.mark.parametrize(
    "words,kind",
    [
        ("Fais une présentation à partir de ce document", "deck"),
        ("À partir de ce rapport, rédige une note de synthèse pour la direction", "doc"),
        ("Peux-tu me dire ce que contient ce document ?", None),
        ("Une présentation sur ce rapport, 5 slides", None),  # with a file: a verb must lead
        ("Le rapport joint est-il complet ? Fais une présentation sinon", None),
    ],
)
def test_canvas_with_attached_files_needs_a_leading_creation_verb(words, kind):
    assert intents.ask(words, attached=True) == kind


def test_question_about_an_attached_file_stays_an_ordinary_turn():
    p = turn.plan("Peux-tu me dire ce que contient ce document ?", None, "fr", attached=True)
    assert p is None
    assert turn.plan("Fais une présentation de ce document", None, "fr", attached=True).kind == "deck"


def test_canvas_gate_is_a_deployment_setting():
    from birds.web.server import build_server_backend
    from birds.web.settings import Settings

    assert Settings.from_env({}).canvas is True
    s = Settings.from_env({"BIRD_CANVAS_OFF": "1", "BIRD_BASE_URL": "https://model.example/v1", "BIRD_MODEL": "m"})
    assert s.canvas is False and build_server_backend(s).canvas is False


# Real answers of Bird S 4B on a patch turn (live, 27/11/2026, scripts/canvas_eval.py --base-deck): the model
# copied the format's example operations. The harness keeps only what the user's words asked for.
LIVE_ADD = ("@replace b3\n# Outils\n- Messagerie et visioconférence\n- Documents partagés\n- Accès sécurisé (VPN)\n"
            "- Gestion des risques (cybersécurité, continuité d'activité)\n@after b4\n# [b6] Risques\n"
            "- Perte de productivité\n- Isolement des équipes\n- Vulnérabilité numérique\n@delete b2")  # fmt: skip
LIVE_SHORT = ("@replace b3   # Outils\n- Messagerie et visioconférence\n- Documents partagés\n- Accès sécurisé (VPN)\n"
              "- Gestion des risques (cybersécurité, continuité d'activité)\n- Formation aux outils numériques\n"
              "@after b4   ## [b4.5] Indicateurs clés\n- Taux de satisfaction : 78 %\n- Taux d'absentéisme : 4 %\n"
              "@delete b2")  # fmt: skip


def _base_deck():
    from scripts.canvas_eval import BASE_DECK

    return dsl.parse(BASE_DECK, "deck", "fr")


def test_live_add_answer_keeps_every_slide_and_adds_the_one_asked():
    base = _base_deck()
    repairs = []
    ops, how = patch.parse_patch(LIVE_ADD, base, "ajoute une slide sur les risques", None, repairs)
    doc = patch.apply_all(base, ops)[0]
    assert [b["id"] for b in doc["blocks"]][:4] == ["b1", "b2", "b3", "b4"] and len(doc["blocks"]) == 6
    assert doc["blocks"][4]["title"] == "Risques" and doc["blocks"][2] == base["blocks"][2]
    assert any("delete of b2 not asked" in r for r in repairs) and any("replace of b3" in r for r in repairs)


def test_live_shortening_answer_that_lengthens_changes_nothing_and_says_so(monkeypatch):
    from fastapi.testclient import TestClient

    base = _base_deck()
    assert patch.parse_patch(LIVE_SHORT, base, "plus court")[0] == []
    _no_network(monkeypatch)
    app, _ = _app([LIVE_SHORT])
    with TestClient(app) as client:
        events = _chat(client, "plus court", canvas=_canvas_body(base))
    assert not [e for e in events if e["type"] == "canvas" and e["phase"] == "final"]
    said = next(e for e in events if e["type"] == "answer")["content"]
    assert "@replace" not in said and "Je n'ai pas modifié la présentation" in said


def test_fit_keeps_asked_operations():
    base = _base_deck()
    ops = [{"op": "delete", "id": "b2"}, {"op": "theme", "theme": "warm"}]
    assert patch.fit(ops, "supprime la slide 2 et passe en thème chaleureux", base, []) == ops
    short = {"op": "replace", "id": "b2", "block": {"id": "b2", "title": "Organisation", "parts": [
        {"t": "list", "items": ["Deux jours par semaine"]}]}}  # fmt: skip
    assert patch.fit([short], "plus court", base, []) == [short]


def test_patch_spec_has_no_real_block_id_to_copy():
    for lg in ("fr", "en"):
        assert not re.search(r"@(?:replace|after|delete)\s+b\d", turn.PATCH[lg])


def test_chat_text_drops_an_excuse_before_the_deck():
    d = dsl.parse(DECK, "deck")
    text = turn.chat_text("deck", d, "fr", before="Je n'ai pas accès à vos données internes ni à l'outil web.")
    assert "accès" not in text
    assert "ajoute une section" in turn.chat_text("doc", dsl.parse("# A\nx\n# B\ny", "doc"), "fr")


# ------------------------------------------------------------------ the task plan on canvas turns


def test_canvas_deck_turn_never_reports_the_deck_as_missing(monkeypatch):
    """The canvas delivers the deck: the task plan does not count it as an item the file tools should make."""
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    app, llm = _app([DECK, "| Poste | Coût |\n|---|---|\n| A | 1 |"])
    with TestClient(app) as client:
        events = _chat(client, "Fais une présentation sur le plan mobilité avec un tableau des coûts")
    answer = next(e for e in events if e["type"] == "answer")
    assert len(llm.prompts) == 1, "one generation: no nudge for a deck the canvas built"
    assert "Note de Bird" not in json.loads(llm.prompts[0])["messages"][-1]["content"]
    assert not (answer.get("plan") or {}).get("missing")


def test_canvas_code_turn_reads_the_script_words_as_what_it_does(monkeypatch):
    """« un script qui génère un fichier Excel et envoie un mail »: the program's job, not three deliverables."""
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    code = "```python\nimport openpyxl\n\nwb = openpyxl.Workbook()\nwb.save('clients.xlsx')\n```"
    app, llm = _app([code, "Not used"])
    with TestClient(app) as client:
        events = _chat(client, "Écris un script Python qui génère un fichier Excel et envoie un mail au client")
    answer = next(e for e in events if e["type"] == "answer")
    assert len(llm.prompts) == 1
    assert "Note de Bird" not in json.loads(llm.prompts[0])["messages"][-1]["content"]
    assert not answer.get("plan")


def test_patch_turn_never_turns_an_apology_into_a_slide(monkeypatch):
    """« Ajoute une diapositive sur les coûts »: no attachment, so no read_file to fail on; and prose that is not a
    block stays in the chat, the deck keeps its version."""
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    sorry = ("Le fichier n'existe pas dans l'environnement actuel. Je ne peux donc pas ajouter la diapositive sur "
             "les coûts sans plus d'informations.")  # fmt: skip
    app, llm = _app([_tool_call("read_file", path="Le télétravail en PME"), sorry, sorry])
    deck = dsl.parse(DECK, "deck")
    with TestClient(app) as client:
        events = _chat(client, "Ajoute une diapositive sur les coûts", canvas=_canvas_body(deck))
    tools = json.loads(llm.prompts[0])["tools"]
    assert "read_file" not in tools
    assert not [e for e in events if e["type"] == "canvas" and e.get("phase") == "final"]
    answer = next(e for e in events if e["type"] == "answer")
    assert "Nouvelle version" not in answer["content"]


def test_parse_patch_keeps_untagged_prose_out_of_the_deck():
    deck = dsl.parse(DECK, "deck")
    ops, how = patch.parse_patch("Je ne peux pas ajouter la diapositive : le fichier n'existe pas.", deck,
                                 "ajoute une diapositive sur les coûts")  # fmt: skip
    assert ops == [] and how == "none"



def test_canvas_doc_turn_offers_draft_email_only_when_a_mail_is_asked(monkeypatch):
    from fastapi.testclient import TestClient

    _no_network(monkeypatch)
    doc = "# Objet\nReport du projet au T2.\n# Présents\n- Paul\n- Marie\n# Décision\nReport au T2."
    app, llm = _app([doc])
    with TestClient(app) as client:
        events = _chat(client, "Rédige le compte rendu : réunion à Toulouse le 3 mars, présents Paul et Marie, "
                               "décision de reporter le projet au T2.")  # fmt: skip
    assert "draft_email" not in (json.loads(llm.prompts[0]).get("tools") or [])
    assert [e for e in events if e["type"] == "canvas"][-1]["phase"] == "final"
