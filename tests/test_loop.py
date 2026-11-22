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
    # the reasoning loops, then the direct answer loops too: the user is told, nothing is invented
    agent = Agent(FakeClient(["<think>Je réfléchis encore. " * 80, "Je réfléchis encore. " * 80]), Tok(), Config(workspace=tmp_path))
    run = agent.run("Question ?", lang="fr", thinking=True)
    assert run.stop_reason == "repetition" and run.think_cut
    assert run.answer == "Je réfléchis encore."  # one copy kept, the repeats dropped, the UI says it was cut


def test_soft_loops_are_caught_and_data_lists_are_not():
    from birds.harness.llm import find_soft_loop

    counter = "Plan.\n" + "".join(f"Étape {i} : vérifier le dossier du client et relancer le juridique.\n" for i in range(1, 30))
    cut = find_soft_loop(counter)
    assert cut is not None and counter[:cut].count("vérifier le dossier") == 2
    circling = "Intro.\n" + ("Il faut bien préparer la réunion. Une réunion préparée est une bonne réunion. " * 25)
    assert find_soft_loop(circling) is not None
    salaries = "".join(f"- {i} années d'expérience : {30000 + i * 3171} €\n" for i in range(1, 30))
    csv = "\n".join(f"{i},Client {i},{i * 3.5:.2f},actif" for i in range(300))
    table = "| Mois | Ventes |\n|---|---|\n" + "".join(f"| M{i} | {i * 10} |\n" for i in range(80))
    code = "```python\n" + "".join(f"x{i} = compute({i})\n" for i in range(200)) + "```"
    for text in (salaries, csv, table, code, PARA * 2):
        assert find_soft_loop(text) is None, text[:40]


def test_reasoning_that_never_ends_is_cut_and_the_step_answers_directly(tmp_path):
    long_think = "<think>" + " ".join(f"Hypothèse {i} : le coût {i * 37} € change la marge de {i % 9} points." for i in range(400))
    llm = FakeClient([long_think, "Voici la réponse."])
    agent = Agent(llm, Tok(), Config(workspace=tmp_path, think_chars=3000))
    run = agent.run("Question difficile ?", lang="fr", thinking=True)
    assert run.think_cut and run.answer == "Voici la réponse." and run.stop_reason == "answer"
    assert len(llm.prompts) == 2


def test_a_reasoning_loop_also_falls_back_to_a_direct_answer(tmp_path):
    llm = FakeClient(["<think>" + "Je pèse le pour et le contre, une hypothèse après l'autre. " * 400, "Voici la réponse."])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Question ?", lang="fr", thinking=True)
    assert run.think_cut and run.answer == "Voici la réponse."


def test_a_failed_tool_loop_ends_with_a_last_answer_not_the_generic_fallback(tmp_path):
    from birds.harness.agent import FALLBACK

    bad = "<tool_call>\n<function=web_search>\n<parameter=query>\n\n</parameter>\n</function>\n</tool_call>"
    llm = FakeClient([bad, bad, "Je n'ai pas pu chercher en ligne, mais voici l'essentiel : un CDI n'a pas de terme."])
    run = Agent(llm, Tok(), Config(workspace=tmp_path, max_steps=2)).run("Différence CDD CDI ?", lang="fr")
    assert run.salvaged and run.stop_reason == "answer" and run.answer != FALLBACK["fr"]
    assert "CDI" in run.answer and "Consigne interne" in llm.prompts[-1]
    assert not any("Consigne interne" in str(m.get("content")) for m in run.messages)  # never kept in history
    assert len(run.usage) == 3


def test_the_generic_fallback_stays_when_the_last_answer_is_empty_too(tmp_path):
    from birds.harness.agent import FALLBACK

    bad = "<tool_call>\n<function=web_search>\n<parameter=query>\n\n</parameter>\n</function>\n</tool_call>"
    run = Agent(FakeClient([bad, bad, ""]), Tok(), Config(workspace=tmp_path, max_steps=2)).run("Question ?", lang="fr")
    assert not run.salvaged and run.answer == FALLBACK["fr"]


def test_an_announced_action_is_done_in_the_same_turn(tmp_path):
    (tmp_path / "facture.jpg.txt").write_text("Total TTC : 1 250,00 €")
    call = "<tool_call>\n<function=read_file>\n<parameter=path>\nfacture.jpg\n</parameter>\n</function>\n</tool_call>"
    llm = FakeClient(["Je reviens sur l'image pour récupérer les totaux.", call, "Le total TTC est de 1 250,00 €."])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Il manque les totaux", lang="fr")
    assert run.answer == "Le total TTC est de 1 250,00 €." and [s.tool for s in run.steps] == ["read_file"]


def test_a_question_back_is_not_pushed(tmp_path):
    llm = FakeClient(["Je vais vérifier : voulez-vous les montants HT ou TTC ?"])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Il manque les totaux", lang="fr")
    assert run.answer.endswith("?") and len(llm.prompts) == 1
