"""The brand bench's rubric rewards an answer, never a refusal that happens to contain the right word."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("brand_eval", ROOT / "scripts" / "brand_eval.py")
brand_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand_eval)
score = brand_eval.score


def test_a_refusal_scores_no_install_point():
    refusal = ("Je ne connais pas de produit appelé Bird ; je n'en ai donc pas d'infos d'installation. "
               "Vérifiez le nom exact sur le site officiel.")  # fmt: skip
    c = score("identity", "fr", refusal)
    assert not c["place"] and not c["light"] and not c["france"]
    assert not score("identity", "en", "I don't know any product called Bird, so no install details.")["place"]


def test_affirmative_install_answers_score():
    for lang, text in [
        ("fr", "Bird s'installe où vous le souhaitez : sur votre machine ou dans le centre de données de votre choix."),
        ("fr", "Bird s'installe sur n'importe quelle source d'énergie : solaire, éolien ou réseau."),
        ("en", "You can install Bird wherever you want, on premises or in your data centre."),
    ]:
        assert score("identity", lang, text)["place"], text


def test_saying_when_it_does_not_know_is_not_a_refusal():
    c = score(
        "identity", "en", "Bird: a small, frugal work assistant. I say when I don't know and keep your data close."
    )
    assert c["light"]


def test_a_bare_install_word_is_not_an_answer():
    assert not score("identity", "fr", "Pour l'installation, voyez la documentation.")["place"]


def test_saved_measurements_match_the_current_rubric():
    """The committed raw answers carry the checks the current rubric gives them (re-scored, not hand-edited)."""
    for f in sorted((ROOT / "docs" / "measures").glob("brand-eval-*.json")):
        for r in json.loads(f.read_text(encoding="utf-8")):
            if r["answer"].strip():
                assert r["checks"] == score(r["kind"], r["lang"], r["answer"]), (f.name, r["ask"])


class _FakeLLM:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, max_tokens, stop, *, on_token=None, think_limit=None, **_):
        self.calls += 1
        return {"text": "ok"}


def test_the_generation_budget_is_counted_from_the_first_run_and_never_exceeded():
    import inspect

    import pytest

    inner = _FakeLLM()
    llm = brand_eval.GenBudget(inner, limit=5, spent=2)  # 2 already spent today: 3 left
    assert "think_limit" in inspect.signature(llm.generate).parameters  # the harness sees the client's keywords
    for _ in range(3):
        llm.generate("p", 10, [])
    with pytest.raises(brand_eval.BudgetExhausted):
        llm.generate("p", 10, [])
    assert inner.calls == 3 and llm.used == 5
