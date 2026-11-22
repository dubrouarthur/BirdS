"""A small model can fall into a degenerate loop: it must be stopped early, one copy kept, the user told."""

from __future__ import annotations

import json

import httpx

from birds.harness import Agent, Config, FakeClient
from birds.harness.llm import STOP, CompletionsClient, find_loop

PARA = (
    "Bird est un petit modèle de langage conçu pour les tâches de bureau. Il répond en français et en anglais, "
    "cite ses sources et affiche une estimation de son énergie. "
)


def test_detects_a_repeated_paragraph_and_keeps_one_copy():
    text = "Voici la réponse.\n\n" + (PARA + "\n\n") * 6
    cut = find_loop(text)
    assert cut is not None
    kept = text[:cut]
    assert kept.count("Bird est un petit modèle") == 1
    assert kept.startswith("Voici la réponse.")


def test_detects_short_units():
    assert find_loop("Réponse : " + "je ne sais pas, " * 60) is not None
    assert find_loop("ok" + "!" * 4000) is not None
    assert find_loop("Liste :\n" + "- Oui\n" * 200) is not None


def test_two_copies_or_short_runs_are_not_loops():
    assert find_loop(PARA * 2) is None  # quoting twice is fine
    assert find_loop("Titre\n" + "=" * 120 + "\nTexte normal.") is None
    assert find_loop("ha" * 50) is None
    assert find_loop("|" + "-" * 900 + "|\n") is None  # a wide table rule
    assert find_loop("| a | b |\n" + "|        |        |\n" * 40) is None  # empty table rows


def test_ordinary_long_outputs_are_left_alone():
    table = "| Mois | Ventes | Coût |\n|---|---|---|\n" + "".join(
        f"| M{i} | {i * 137} € | {i * 59} € |\n" for i in range(1, 80)
    )
    code = "\n".join(f"def f{i}(x):\n    return x * {i} + {i * i}\n" for i in range(60))
    prose = " ".join(f"Le point {i} concerne le dossier {i * 7} et sa date {i % 28 + 1}." for i in range(120))
    csv = "\n".join(f"{i},Client {i},{i * 3.5:.2f},actif" for i in range(300))
    for text in (table, code, prose, csv):
        assert find_loop(text) is None, text[:60]


def _stream_transport(pieces, served):
    def handler(request: httpx.Request) -> httpx.Response:
        def body():
            for p in pieces:
                served.append(p)
                chunk = {"choices": [{"index": 0, "text": p, "finish_reason": None}]}
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    return httpx.MockTransport(handler)


def test_client_stops_reading_the_stream_when_the_model_loops():
    pieces = ["Début. "] + [PARA] * 400  # the server would go on until max_tokens
    served, shown = [], []
    client = CompletionsClient("https://m.test/v1", "bird", transport=_stream_transport(pieces, served))
    out = client.generate("p", 4096, STOP, on_token=shown.append)
    assert out["finish_reason"] == "repetition"
    assert out["text"].count("Bird est un petit modèle") == 1
    assert len(served) < 10  # the connection was closed early: the server aborts the request, the GPU stops


def test_client_leaves_a_normal_stream_alone():
    pieces = [f"Phrase numéro {i} sur un sujet différent. " for i in range(200)]
    served = []
    client = CompletionsClient("https://m.test/v1", "bird", transport=_stream_transport(pieces, served))
    out = client.generate("p", 4096, STOP)
    assert out["finish_reason"] != "repetition"
    assert len(served) == len(pieces)


class Tok:
    def apply_chat_template(self, messages, tools=None, tokenize=False, add_generation_prompt=True, **kw):
        return "\n".join(str(m.get("content")) for m in messages)


def test_agent_marks_the_run_and_keeps_one_copy(tmp_path):
    agent = Agent(FakeClient(["Voici. " + PARA * 8]), Tok(), Config(workspace=tmp_path))
    run = agent.run("Présente Bird.", lang="fr")
    assert run.stop_reason == "repetition"
    assert run.answer.count("Bird est un petit modèle") == 1


def test_agent_explains_a_loop_during_reasoning(tmp_path):
    agent = Agent(FakeClient(["<think>Je réfléchis encore. " * 80]), Tok(), Config(workspace=tmp_path))
    run = agent.run("Question ?", lang="fr", thinking=True)
    assert run.stop_reason == "repetition"
    assert "boucle" in run.answer
