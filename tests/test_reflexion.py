"""Mode Réflexion (birds/harness/reflexion.py): levels, the model's Auto choice, budget forcing, self-check, review."""

from __future__ import annotations

import json
import threading

import pytest

from birds.harness import Agent, Config, FakeClient
from birds.harness import reflexion as R
from birds.harness.template import TemplateTokenizer

TOK = TemplateTokenizer()


class Tok:
    def apply_chat_template(self, messages, tools=None, enable_thinking=False, tokenize=False, **kw):
        return json.dumps({"think": enable_thinking, "messages": messages}, ensure_ascii=False)


class Routed(FakeClient):
    """A probeable endpoint: the level and router calls are answered by what they ask (they run at the same time),
    the turn's generations come from ``outputs`` in order."""

    router_structured = "structured_outputs"
    url = "https://m.test/v1/completions"

    def __init__(self, outputs, level="faucon", router='{"modules":[],"agent":"off","needs_web":false}'):
        super().__init__(outputs)
        self.level, self.router, self.calls, self.lock = level, router, [], threading.Lock()
        self.max_tokens = []

    def generate(self, prompt, max_tokens, stop, **kw):
        with self.lock:
            if "combien Bird réfléchit" in prompt or "how long Bird thinks" in prompt:
                self.calls.append(("level", kw.get("extra")))
                return {"text": R.decision_json(self.level), "prompt_tokens": 300, "completion_tokens": 6,
                        "seconds": 0.2}  # fmt: skip
            if "Indices" in prompt or "Hints" in prompt:
                self.calls.append(("router", None))
                return {"text": self.router, "prompt_tokens": 800, "completion_tokens": 12, "seconds": 0.3}
            self.calls.append(("gen", None))
            self.max_tokens.append(max_tokens)
        return super().generate(prompt, max_tokens, stop, **kw)


# ---------------------------------------------------------------- levels


def test_five_birds_with_real_budgets():
    assert R.KEYS == ("colibri", "hirondelle", "faucon", "chouette", "albatros")
    budgets = [R.LEVELS[k].think_chars for k in R.KEYS]
    assert budgets == sorted(budgets) and budgets[0] == 0 and not R.LEVELS["colibri"].thinking
    assert [R.LEVELS[k].checks for k in R.KEYS] == [0, 0, 1, 2, 2]
    assert R.LEVELS["faucon"].think_tokens > 1500 and R.LEVELS["colibri"].think_tokens == 0
    assert R.label_line("faucon") == "Bird a pris son vol en Faucon"
    assert R.label_line("chouette", "en") == "Bird took flight as a Owl".replace("a Owl", "a Owl")
    assert R.normalize(True) == "hirondelle" and R.normalize("bogus") == "auto" and R.normalize("FAUCON") == "faucon"


# ---------------------------------------------------------------- Auto: the model decides


def test_decision_prompt_is_static_and_schema_bound():
    a, b = R.messages("bonjour"), R.messages("analyse le marché")
    assert a[0] == b[0] and "faucon" in a[0]["content"] and a[1]["content"] == "Message : bonjour"
    assert R.messages("hi", "en")[1]["content"] == "Message: hi"
    assert R.schema()["properties"]["level"]["enum"] == list(R.AUTO_LEVELS)
    assert "albatros" not in R.AUTO_LEVELS  # the team decides Albatros, never a guess


def test_decide_reads_the_model_and_falls_back_on_the_cues():
    llm = Routed([], level="chouette")
    c = R.decide(llm, TOK, "combien font 3 x 4 ?", lang="fr", cache_salt="s")
    assert (c.level, c.source) == ("chouette", "model")  # the model, not the cue (« faucon »)
    extra = llm.calls[-1][1]
    assert extra["structured_outputs"] == {"json": R.schema()} and extra["cache_salt"] == "s"
    c = R.decide(FakeClient([]), TOK, "combien font 3 x 4 ?")
    assert (c.level, c.source, c.why) == ("faucon", "hint", "no_endpoint")


@pytest.mark.parametrize(
    "raw,prefix,want",
    [('{"level":"faucon"}', "", "faucon"), ('chouette"}', R.PREFIX, "chouette"), ("{oops", "", ""),
     ("<think>x</think>{\"level\": \"colibri\"}", "", "colibri"), ('{"level":"albatros"}', "", "")],
)  # fmt: skip
def test_parse(raw, prefix, want):
    assert R.parse(raw, prefix) == want


def test_hint_level_is_only_a_fallback_cue():
    assert R.hint_level("bonjour !") == "colibri"
    assert R.hint_level("rédige un mail à Paul pour décaler la réunion") == "hirondelle"
    assert R.hint_level("3 devis à 1 250 €, 980 € et 1 410 € : lequel est le moins cher ?") == "faucon"
    assert R.hint_level("analyse les risques du télétravail pour une PME de 40 personnes") == "chouette"


# ---------------------------------------------------------------- self-check


@pytest.mark.parametrize(
    "text,wrong",
    [("14,90 € × 24 = 357,60 €", 0), ("14,90 € × 24 = 375,60 €", 1), ("(3 + 4) × 2 = 14", 0),
     ("3 + 4 × 2 = 14", 0), ("1 200 € × 20 % = 240 €", 0), ("20 % de 1 200 € = 250 €", 1), ("7 x 8 = 54", 1),
     ("1 284,37 + 15,63 = 1 300", 0), ("12.5 x 4 = 50", 0), ("1 200 € + 20 % = 1 440 €", 0), ("≈ 33 %", 0),
     ("69 ÷ 2 300 = 3 %", 0), ("81 ÷ 3 100 = 3,1 %", 1),
     # « n × p % = q % »: compared in percent points, never « 0,10 (not 10) »
     ("2 × 5 % = 10 %", 0), ("3 % × 4 = 12 %", 0), ("10 % ÷ 2 = 5 %", 0), ("2 × 5 % = 12 %", 1),
     ("2 × 5 % = 0,10", 0)],
)  # fmt: skip
def test_calculations_are_recomputed(text, wrong):
    assert len(R.calc_errors(text)[1]) == wrong


def test_wrong_calc_names_the_right_figure():
    _, wrong = R.calc_errors("Total : 14,90 € × 24 = 375,60 €")
    assert wrong == [{"expr": "14,90 € × 24", "shown": "375,60", "right": "357,60"}]
    assert "14,90 € × 24 = 357,60 (not 375,60)" in R.nudge(R.Verdict(1, wrong))


def test_a_percent_times_n_is_judged_in_percent_points(tmp_path):
    assert R.calc_errors("2 × 5 % = 12 %")[1] == [{"expr": "2 × 5 %", "shown": "12", "right": "10"}]
    llm = FakeClient(["<think>Deux hausses de 5 %.</think>La hausse cumulée simple est 2 × 5 % = 10 %."])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Deux hausses de 5 %, ça fait combien sans composer ?",
                                                             lang="fr", reflexion="faucon")  # fmt: skip
    assert len(llm.prompts) == 1 and not run.reflexion["corrected"] and run.answer.endswith("= 10 %.")


def test_points_asked_are_checked_one_by_one():
    req = "1. le prix TTC\n2. la TVA\n3. le délai de livraison"
    assert R.missing_points(req, "Le prix TTC est 1 440 €, dont 240 € de TVA.") == (3, ["le délai de livraison"])
    assert R.missing_points("Quel est le prix ?", "10 €") == (0, [])  # one point: nothing to tick
    two = "Quel est le prix TTC ? Et quand arrive la livraison ?"
    assert R.missing_points(two, "Le prix TTC est 1 440 € ; livraison sous 5 jours.")[1] == []


def test_a_wrong_figure_thought_and_written_counts():
    v = R.verify("combien ?", "Le total est 375,60 €.", "14,90 × 24 = 375,60")
    assert not v.ok and v.calc_wrong[0]["right"] == "357,60"
    assert R.verify("combien ?", "Le total est 357,60 €.", "14,90 × 24 = 375,60, non pardon").ok  # not reached


# ---------------------------------------------------------------- reasoning summary and recovery


def test_summary_is_the_models_own_lines():
    r = ("Bon, voyons. L'abonnement mensuel coûte 14,90 € × 24 = 357,60 €. L'annuel coûte 298 €. "
         "Donc l'annuel est le moins cher de 59,60 €.")  # fmt: skip
    got = R.summary(r)
    assert got and all(line in r for line in got) and "59,60" in got[-1]
    assert not any(line.startswith("Bon") for line in got)


def test_close_text_keeps_the_reasoning_and_closes_it():
    out = R.close_text("<think>Je calcule 3 x 4 = 12. Puis je vérif", "think_budget", "fr")
    assert out.startswith("Je calcule 3 x 4 = 12.") and "Budget de réflexion atteint" in out
    assert out.endswith("</think>\n\n") and "vérif" not in out


def test_review_keeps_the_draft_on_ok():
    draft = "Voici une réponse complète et juste, avec ses chiffres : 357,60 €."
    assert R.review_kept(draft, "OK") == (draft, False)
    assert R.review_kept(draft, "Ok.") == (draft, False)
    assert R.review_kept(draft, "") == (draft, False)
    fixed = "Voici une réponse complète et corrigée, avec ses chiffres : 298 € contre 357,60 €."
    assert R.review_kept(draft, fixed) == (fixed, True)


# ---------------------------------------------------------------- in the agent


def test_auto_runs_the_level_choice_and_sets_the_budget(tmp_path):
    llm = Routed(["<think>14,90 × 24 = 357,60.</think>Sur deux ans : 14,90 € × 24 = 357,60 €."], level="faucon")
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Combien coûtent 24 mois à 14,90 € ?", lang="fr",
                                                             reflexion="auto")  # fmt: skip
    kinds = [k for k, _ in llm.calls]
    assert kinds.count("level") == 1 and kinds.count("router") == 1 and kinds.count("gen") == 1
    assert run.reflexion["level"] == "faucon" and run.reflexion["auto"] and run.reflexion["source"] == "model"
    assert llm.max_tokens == [1024 + R.LEVELS["faucon"].think_tokens]
    assert json.loads(llm.prompts[0])["think"] is True
    assert run.reflexion["checks"]["calcs"] == 1 and run.reflexion["checks"]["calc_wrong"] == 0
    assert any(u.get("kind") == "reflexion" for u in run.usage)
    assert run.answer.startswith("Sur deux ans")


def test_colibri_answers_without_reasoning(tmp_path):
    llm = FakeClient(["Bonjour !"])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("bonjour", lang="fr", reflexion="colibri")
    assert json.loads(llm.prompts[0])["think"] is False and run.reflexion["level"] == "colibri"
    assert run.reflexion["source"] == "user" and not run.reflexion["auto"] and len(llm.prompts) == 1


def test_faucon_corrects_a_wrong_calculation_once(tmp_path):
    llm = FakeClient(["<think>Je calcule.</think>Sur deux ans : 14,90 € × 24 = 375,60 €.",
                      "<think>Je recalcule.</think>Sur deux ans : 14,90 € × 24 = 357,60 €."])  # fmt: skip
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Combien coûtent 24 mois à 14,90 € ?", lang="fr",
                                                             reflexion="faucon")  # fmt: skip
    assert len(llm.prompts) == 2 and "357,60 (not 375,60)" in llm.prompts[1]
    assert run.answer == "Sur deux ans : 14,90 € × 24 = 357,60 €."
    assert run.reflexion["corrected"] and run.reflexion["checks"]["calc_wrong"] == 0
    assert run.reflexion["checks"]["fixed"] and run.reflexion["rounds"] == 1
    assert run.reflexion["calc_fixed"] and not run.reflexion["points_fixed"]


def test_a_missing_point_fixed_is_never_reported_as_a_calculation_fixed(tmp_path):
    llm = FakeClient(["<think>.</think>Le total : 120 × 3 = 360 €.",
                      "<think>.</think>Le total : 120 × 3 = 360 €. La date limite de dépôt est le 15 décembre."])
    req = "Quel est le total de 120 € × 3 ? Et quelle est la date limite de dépôt ?"
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run(req, lang="fr", reflexion="faucon")
    pub = R.public(run.reflexion)
    assert len(llm.prompts) == 2 and pub["corrected"]
    assert pub["points_fixed"] and not pub["calc_fixed"] and pub["checks"]["calc_wrong"] == 0


def test_hirondelle_does_not_check(tmp_path):
    llm = FakeClient(["<think>.</think>14,90 € × 24 = 375,60 €."])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Combien ?", lang="fr", reflexion="hirondelle")
    assert len(llm.prompts) == 1 and not run.reflexion["corrected"]


def test_a_correct_answer_costs_no_extra_generation(tmp_path):
    llm = FakeClient(["<think>ok</think>1. Le prix TTC : 1 440 €.\n2. La TVA : 240 €."])
    req = "Pour 1 200 € HT :\n1. le prix TTC\n2. la TVA"
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run(req, lang="fr", reflexion="faucon")
    assert len(llm.prompts) == 1 and run.reflexion["checks"]["points"] == 2


def test_budget_forcing_keeps_what_was_reasoned(tmp_path):
    long_think = "<think>" + " ".join(f"Hypothèse {i} : le coût {i * 37} € change la marge." for i in range(400))
    llm = FakeClient([long_think, "La marge baisse de 3 points."])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Analyse la marge.", lang="fr", reflexion="hirondelle")
    assert run.think_cut and run.reflexion["cut"] == "think_budget"
    second = llm.prompts[1]
    assert "Hypothèse 1 :" in second and "Budget de réflexion atteint" in second and second.endswith("</think>\n\n")
    assert run.answer == "La marge baisse de 3 points." and run.stop_reason == "answer"
    assert 1000 < run.reflexion["think_chars"] <= R.LEVELS["hirondelle"].think_chars + 400


def test_a_looping_reasoning_is_closed_not_thrown_away(tmp_path):
    llm = FakeClient(["<think>Le total est 240 €. " + "Je pèse le pour et le contre, une hypothèse après l'autre. " * 400,
                      "Le total est 240 €."])  # fmt: skip
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run("Total ?", lang="fr", reflexion="faucon")
    assert run.reflexion["cut"] == "repetition" and "Je tourne en rond" in llm.prompts[1]
    assert run.answer == "Le total est 240 €."


def test_chouette_reviews_its_draft_without_streaming_ok(tmp_path):
    shown = []
    from birds.harness.agent import Hooks

    llm = FakeClient(["<think>a</think>Le mensuel revient à 357,60 € sur deux ans, l'annuel à 298 €.", "OK"])
    agent = Agent(llm, Tok(), Config(workspace=tmp_path), hooks=Hooks(on_token=shown.append))
    run = agent.run("Mensuel à 14,90 € ou annuel à 149 € ?", lang="fr", reflexion="chouette")
    assert len(llm.prompts) == 2 and R.REVIEW in llm.prompts[1]
    assert run.reflexion["reviewed"] and not run.reflexion["review_changed"]
    assert "OK" not in "".join(shown) and run.answer.startswith("Le mensuel")


def test_resume_keeps_the_level(tmp_path, monkeypatch):
    from birds.harness import guard

    calls = iter(["pause", "confirmed"])
    monkeypatch.setattr(guard, "gate", lambda *a, **k: next(calls, "allow"))
    mail = ("<tool_call>\n<function=draft_email>\n<parameter=to>\n[\"a@b.fr\"]\n</parameter>\n<parameter=subject>\n"
            "Test\n</parameter>\n<parameter=body>\nBonjour\n</parameter>\n</function>\n</tool_call>")  # fmt: skip
    llm = FakeClient(["<think>x</think>" + mail, "<think>y</think>C'est prêt."])
    agent = Agent(llm, Tok(), Config(workspace=tmp_path))
    first = agent.run("Écris à a@b.fr", lang="fr", reflexion="faucon")
    assert first.stop_reason == "confirm" and first.state["reflexion"] == "faucon"
    again = agent.run(resume=json.loads(json.dumps(first.state)), decision=True)
    assert again.reflexion["level"] == "faucon" and again.answer == "C'est prêt."
    assert json.loads(llm.prompts[-1])["think"] is True


def test_public_field_for_the_interface():
    info = {"level": "faucon", "auto": True, "source": "model", "think_chars": 230, "cut": None,
            "summary": ["a = b"], "checks": {"calcs": 3, "calc_wrong": 0, "points": 2, "missing": 0}}  # fmt: skip
    pub = R.public(info, "fr")
    assert pub["line"] == "Bird a pris son vol en Faucon" and pub["label"] == "Précis" and pub["checks"]["calcs"] == 3
    assert R.public(info, "en")["bird"] == "Falcon" and R.public({"level": "x"}) is None
