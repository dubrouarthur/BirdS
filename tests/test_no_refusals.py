"""Bird uses its tools instead of refusing (docs/HARNESS.md § 19): the final check's refusal retry, an attached
file read whatever path the model wrote, a misspelt name found, the translation asked, a picture follow-up."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import httpx
import pytest

from birds.harness import Agent, Config, Context, FakeClient, facts, refusal
from birds.harness import router as R
from birds.harness.guard import Blocked, ToolError
from birds.harness.opendata_route import near_grounded
from birds.harness.tools import StaticBackend
from birds.harness.tools.files import read_file
from birds.harness.tools.opendata import entity

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_chart import Tok, call  # noqa: E402


def make(tmp_path, outputs, **cfg):
    search = StaticBackend([{"title": "Natalité en France", "url": "https://news.test/n", "snippet": "1,62 en 2024"}])
    llm = FakeClient(outputs)
    return Agent(llm, Tok(), Config(workspace=tmp_path, **cfg), search=search, http=httpx.Client()), llm


# ---------------------------------------------------------------- the hint


@pytest.mark.parametrize(
    "text",
    [
        "Je ne peux pas générer de graphique directement ici, mais voici les données : 2020 1,75",
        "Je ne peux pas générer de graphe ici.",
        "Je n'ai pas accès à votre bureau local.",
        "Non, je n'ai ni accès à Internet ni à la mémoire entre nos échanges.",
        "I can't create charts here, but here are the figures.",
        "Utilisez Excel pour tracer la courbe.",
    ],
)
def test_refusals_seen_live_are_recognised(text):
    assert refusal.refuses(text)


@pytest.mark.parametrize(
    "text",
    [
        "Voici le graphique de la natalité.",
        "Je peux faire un graphique si vous voulez.",
        "Le chat ne peut pas voir certaines couleurs.",
        "On sélectionne les données, puis Insertion > Graphique.",
        "Here you go: Thank you for your help.",
    ],
)
def test_ordinary_answers_are_not_refusals(text):
    assert not refusal.refuses(text)


def test_the_retry_names_only_the_tools_this_deployment_has():
    assert refusal.nudge(set()) is None
    got = refusal.nudge(refusal.capable({"make_chart", "web_search", "read_file"}, attached=False))
    assert "make_chart" in got and "web_search" in got and "read_file" not in got
    assert "read_file" in refusal.capable({"read_file"}, attached=True)


# ---------------------------------------------------------------- the final check


def test_a_chart_refusal_is_sent_back_once_with_make_chart(tmp_path):
    outs = [
        "Je ne peux pas générer de graphique ici, mais voici les données : 2023 1,68 ; 2024 1,62.",
        call("make_chart", title="Natalité", columns=["Année", "ICF"], rows=[["2023", 1.68], ["2024", 1.62]]),
        "Voici la courbe : la natalité baisse.",
    ]
    agent, llm = make(tmp_path, outs)
    run = agent.run("graphique de la natalité : 2023 1,68 ; 2024 1,62")
    sent = [json.loads(p) for p in llm.prompts]
    assert any("Your answer says you cannot do this" in str(m.get("content")) for m in sent[1]["messages"])
    assert "make_chart" in sent[1]["tools"]
    assert run.refusal_retry and run.charts and "ne peux pas" not in run.answer


def test_a_second_refusal_is_delivered_as_it_is(tmp_path):
    outs = ["Je n'ai pas accès à Internet.", "Je n'ai pas accès à Internet."]
    agent, llm = make(tmp_path, outs)
    run = agent.run("donne-moi une image du lynx")
    assert len(llm.prompts) <= 3 and run.refusal_retry


def test_no_retry_without_a_refusal(tmp_path):
    agent, llm = make(tmp_path, ["Le vent soulève les feuilles."])
    run = agent.run("écris un haïku sur l'automne")
    assert len(llm.prompts) == 1 and not run.refusal_retry


def test_a_translation_left_in_french_is_sent_back(tmp_path):
    (tmp_path / "mail.txt").write_text("Bonjour Claire, merci pour votre retour rapide.", encoding="utf-8")
    french = ("Bonjour Claire,\n\nMerci pour votre retour rapide. Je vous confirme notre rendez-vous de jeudi à 14 h "
              "dans nos locaux de Lyon. Pourriez-vous m'envoyer le devis signé avant mercredi ?\n\nBien cordialement,\nJulien")  # fmt: skip
    outs = [call("read_file", path="mail.txt"), french, "Hi Claire,\n\nThank you for your quick reply."]
    agent, llm = make(tmp_path, outs)
    run = agent.run("Traduis ce mail en anglais\n\n[Fichier joint : mail.txt]", attached=True)
    assert "translation into English" in json.loads(llm.prompts[2])["messages"][-1]["content"]
    assert run.answer.startswith("Hi Claire")


def test_translation_target():
    assert facts.translation_target("Traduis ce mail en anglais") == "en"
    assert facts.translation_target("Translate this email into French") == "fr"
    assert facts.translation_target("écris en anglais") == ""


# ---------------------------------------------------------------- the attached file


def _ctx(ws: Path) -> Context:
    return Context(config=Config(workspace=ws, audit_file=None), http=None)


@pytest.mark.parametrize(
    "path", ["mail.txt", "/Users/moi/Bureau/mail.txt", "C:\\Users\\moi\\Desktop\\MAIL.TXT", "../mail.txt"]
)
def test_the_attached_file_is_read_whatever_folder_the_model_names(path):
    ws = Path(tempfile.mkdtemp())
    (ws / "mail.txt").write_text("Bonjour", encoding="utf-8")
    assert read_file({"path": path}, _ctx(ws)) == "Bonjour"


def test_the_attachments_folder_is_searched_and_a_wrong_name_lists_the_files():
    ws = Path(tempfile.mkdtemp())
    (ws / "pieces-jointes").mkdir()
    (ws / "pieces-jointes" / "mail.txt").write_text("Bonjour", encoding="utf-8")
    assert read_file({"path": "mail.txt"}, _ctx(ws)) == "Bonjour"
    with pytest.raises(ToolError, match="files here: pieces-jointes/mail.txt"):
        read_file({"path": "autre.txt"}, _ctx(ws))


def test_a_file_outside_the_workspace_is_never_read():
    ws, out = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    (out / "secret.txt").write_text("x", encoding="utf-8")
    with pytest.raises((Blocked, ToolError)):
        read_file({"path": str(out / "secret.txt")}, _ctx(ws))


# ---------------------------------------------------------------- a misspelt name


def test_a_misspelt_name_is_grounded_but_never_another_name():
    assert near_grounded("Georges Pompidou", "qui est georges pompidoo")
    assert near_grounded("Emmanuel Macron", "qui est emanuel macron")
    assert not near_grounded("Marine Le Pen", "qui est marie lepen")
    assert not near_grounded("Georges Brassens", "qui est georges pompidoo")


def test_lookup_entity_follows_wikipedias_spelling_suggestion(monkeypatch):
    calls = []
    good = {"type": "standard", "title": "Georges Pompidou", "wikibase_item": "Q2105", "extract": "Homme d'État "
            "français, président de la République de 1969 à 1974.", "description": "homme d'État français",
            "content_urls": {"desktop": {"page": "https://fr.wikipedia.org/wiki/Georges_Pompidou"}}}  # fmt: skip

    def fake_get(ctx, url, **kw):
        calls.append(url)
        if "page/summary/georges_pompidoo" in url:
            raise ToolError("HTTP 404")
        if "page/summary/Georges_Pompidou" in url:
            return good
        if "wbsearchentities" in url:
            return {"search": []}
        if "list=search" in url:
            return {"query": {"searchinfo": {"suggestion": "georges pompidou"}, "search": []}}
        if "wbgetentities" in url:
            return {"entities": {}}
        raise AssertionError(url)

    monkeypatch.setattr(entity.http, "get", fake_get)
    monkeypatch.setattr(entity, "_summary", lambda ctx, title, lang: (
        good if entity._fold(title) == "georges pompidou" else None))  # fmt: skip
    ctx = _ctx(Path(tempfile.gettempdir()))
    text = entity.lookup_entity({"name": "georges pompidoo"}, ctx)
    assert "Georges Pompidou" in text and "1974" in text and ctx.step_info["found"] == 1


def test_a_far_suggestion_is_not_taken(monkeypatch):
    monkeypatch.setattr(entity, "_summary", lambda *a: None)
    monkeypatch.setattr(entity, "_search", lambda *a: [])
    monkeypatch.setattr(entity.http, "get", lambda ctx, url, **kw: {
        "query": {"searchinfo": {"suggestion": "zorro"}, "search": [{"title": "Zorglub (personnage)"}]}})  # fmt: skip
    ctx = _ctx(Path(tempfile.gettempdir()))
    assert "n'invente rien" in entity.lookup_entity({"name": "Zorglub Industries"}, ctx)


# ---------------------------------------------------------------- « une image » after a topic


def test_the_router_grounds_a_picture_subject_in_the_previous_request():
    history = [{"role": "user", "content": "parle-moi du cheval tigré"},
               {"role": "assistant", "content": "Le cheval tigré porte une robe tachetée."}]  # fmt: skip
    context = R.previous_summary(history, "fr")
    assert R.ground(R.Call("images", {"subject": "cheval tigré"}), "une image", context) == ""
    # the model's own text never grounds a subject
    assert R.ground(R.Call("images", {"subject": "robe tachetée"}), "une image", context)


def test_the_picture_subject_the_harness_searched_gates_the_pictures():
    from birds.web import backends

    src = Path(backends.__file__).read_text(encoding="utf-8")
    assert 'getattr(run, "picture_subject", "")' in src
