"""R1: a document attached in an earlier message no longer hijacks later turns (it stays readable)."""

import importlib.util
import json
from pathlib import Path

from birds.web.backends import prepare_turn

ROOT = Path(__file__).resolve().parents[1]


def _bench():
    spec = importlib.util.spec_from_file_location("attach_bench", ROOT / "scripts" / "attach_context_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fixed_set_turn_two_is_not_joined_to_the_earlier_file():
    bench = _bench()
    rows = bench.offline(json.loads(bench.FIXTURE.read_text(encoding="utf-8")))
    assert len(rows) == 10
    assert not any(r["note"] for r in rows)  # never « [Fichier joint : …] » on a message that brings no file
    assert not any(r["plan"] for r in rows)  # never « lecture de … » to do first
    assert all(r["readable"] for r in rows)  # the file stays readable when the request is about it
    general = [r for r in rows if not r["about_doc"]]
    assert sum(r["nowebs"] for r in general) <= 1  # a general question keeps its web tools


def test_the_message_that_brings_the_file_is_still_noted():
    _, _, sent, _ = prepare_turn([{"role": "user", "content": "Résume"}], "fr", "fr", ["a.txt"], [], 6000, 3168)
    assert sent == "Résume\n\n[Fichier joint : a.txt]"


def test_earlier_file_noted_by_the_history_adds_nothing():
    msgs = [
        {"role": "user", "content": "Résume\n\n[Fichier joint : a.txt]"},
        {"role": "assistant", "content": "Voici."},
        {"role": "user", "content": "Capitale de l'Australie ?"},
    ]
    _, _, sent, _ = prepare_turn(msgs, "fr", "fr", [], [], 6000, 3168, earlier_names=["a.txt"])
    assert sent == "Capitale de l'Australie ?"


def test_earlier_file_whose_note_was_cut_is_named_as_optional():
    msgs = [{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Bonjour !"},
            {"role": "user", "content": "Et le budget ?"}]  # fmt: skip
    _, _, sent, _ = prepare_turn(msgs, "fr", "fr", [], [], 6000, 3168, earlier_names=["a.txt"])
    assert "[Fichier joint" not in sent
    assert sent.endswith("[Document de la conversation, à lire seulement si la demande porte dessus : a.txt]")
    _, _, en, _ = prepare_turn(msgs, "en", "en", [], [], 6000, 3168, earlier_names=["a.txt"])
    assert en.endswith("[Document from this conversation, to read only if the request is about it : a.txt]")


def test_r23_demo_continue_prompt_matches_the_app_and_resumes():
    import re

    from fastapi.testclient import TestClient

    from birds.web.backends import CONTINUE_PROMPTS, DemoBackend, demo_continuation
    from birds.web.server import create_app
    from birds.web.settings import Settings

    js = (ROOT / "birds" / "web" / "static" / "conversation-i18n.js").read_text(encoding="utf-8")
    sent = re.findall(r'"cx\.continue\.prompt": "([^"]+)"', js)
    assert tuple(sent) == CONTINUE_PROMPTS  # French, then English
    q = {"role": "user", "content": "Bonjour"}
    assert demo_continuation([q, {"role": "assistant", "content": "x"}, {"role": "user", "content": sent[0]}]) is None
    app = create_app(Settings(rate_limit=0), demo=DemoBackend(delay=0))
    with TestClient(app) as c:
        def answer(messages):
            r = c.post("/api/chat", headers={"X-Bird-Mode": "demo"}, json={"messages": messages})
            return next(json.loads(ln[5:]) for ln in r.text.splitlines() if '"type": "answer"' in ln)["content"]

        whole = answer([q])
        part = whole[:30]
        rest = answer([q, {"role": "assistant", "content": part, "interrupted": True}, {"role": "user", "content": sent[0]}])
    assert part + rest == whole
