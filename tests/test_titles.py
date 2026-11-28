"""R14: the conversation's title is summarised by the model after its first answer (one structured call, checked)."""

import json

from fastapi.testclient import TestClient

from birds.harness import FakeClient
from birds.harness import titles as T
from birds.web.backends import HarnessBackend
from birds.web.server import create_app
from birds.web.settings import Settings


class Tok:
    def apply_chat_template(self, messages, tools=None, **_):
        return json.dumps({"messages": messages}, ensure_ascii=False)


class Probe(FakeClient):
    router_structured = "structured_outputs"
    url = "https://m.test/v1/completions"

    def generate(self, prompt, max_tokens, stop, **kw):
        self.extra = kw.get("extra")
        return super().generate(prompt, max_tokens, stop, **kw)


def test_clean_and_parse_keep_only_a_short_title():
    assert T.clean("« Fuite sous l'évier ».") == "Fuite sous l'évier"
    assert T.clean("Titre : **budget 2026**") == "Budget 2026"
    for bad in ["", "ok", "x " * 30, "voir https://a.b", "<b>x</b>", "a" * 61]:
        assert T.clean(bad) == "", bad
    assert T.parse('{"title": "Le vélo en ville"}') == "Le vélo en ville"
    assert T.parse('Le vélo en ville"}', T.PREFIX) == "Le vélo en ville"
    assert T.parse("Le vélo en ville", T.PREFIX) == "Le vélo en ville"  # stopped at the newline, before the quote
    assert T.parse("not json") == ""
    assert T.from_result({"subject": "Demande de congé vendredi"}) == "Demande de congé vendredi"
    assert T.from_result(None) == ""


def test_propose_makes_one_structured_call_and_checks_it():
    llm = Probe(['{"title": "Fuite dans la salle de bains"}'])
    got = T.propose(llm, Tok(), "Écris un mail à mon propriétaire pour la fuite", "Voici un brouillon…")
    assert got["title"] == "Fuite dans la salle de bains" and got["source"] == "model"
    assert len(llm.prompts) == 1 and "structured_outputs" in llm.extra and llm.extra["temperature"] == 0
    assert "Fuite" not in T.propose(Probe(['{"title": "x"}']), Tok(), "q", "a")["title"]
    assert T.propose(FakeClient(["{}"]), Tok(), "q", "a") == {"title": "", "source": "none", "reason": "no_endpoint"}


def test_api_title_uses_the_mail_subject_then_the_model():
    llm = Probe(['{"title": "Recette des crêpes"}'])
    app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(llm, Tok()))
    with TestClient(app) as c:
        r = c.post("/api/title", json={"question": "Écris un mail", "answer": "…", "subject": "Demande de congé"})
        assert r.json() == {"title": "Demande de congé", "source": "result"} and not llm.prompts  # no call
        r = c.post("/api/title", json={"question": "Donne-moi une recette de crêpes", "answer": "Pour 4 personnes…"})
        assert r.json() == {"title": "Recette des crêpes", "source": "model"}
        demo = c.post("/api/title", headers={"X-Bird-Mode": "demo"}, json={"question": "Bonjour"})
        assert demo.json()["title"] == ""  # nothing to summarise with: the app keeps the start of the question
        assert c.post("/api/title", json={"question": ""}).status_code == 422
