import re

from birds.schema import errors
from birds.sources.identity import DEFAULT_SYSTEM, generate

RECS = generate(900, 500, 0)


def _answer(r):
    return r["messages"][-1]["content"]


def test_deterministic_and_seeded():
    assert generate(60, 40, 3) == generate(60, 40, 3)
    assert generate(60, 40, 3) != generate(60, 40, 4)


def test_schema_counts_and_bookkeeping():
    assert len(RECS) == 1400 and sum(r["lang"] == "fr" for r in RECS) == 900
    assert all(errors(r) == [] for r in RECS)
    assert len({r["id"] for r in RECS}) == len(RECS)
    assert {(r["source"], r["license"], r["task"]) for r in RECS} == {("bird_identity", "apache-2.0", "identity")}
    assert all(len([m for m in r["messages"] if m["role"] != "system"]) == 2 for r in RECS)  # single turn


def test_variety():
    pairs = {(r["messages"][-2]["content"], _answer(r)) for r in RECS}
    assert len(pairs) == len(RECS)
    assert len({_answer(r) for r in RECS}) >= 0.85 * len(RECS)
    assert len({r["messages"][-2]["content"] for r in RECS}) >= 0.5 * len(RECS)


def test_system_prompt_and_thinking_shares():
    n = len(RECS)
    default = sum(r["messages"][0]["content"] in DEFAULT_SYSTEM.values() for r in RECS)
    company = sum(r["messages"][0]["role"] == "system" for r in RECS) - default
    assert abs(default / n - 0.35) < 0.02 and abs(company / n - 0.15) < 0.02
    thinking = [r for r in RECS if r["thinking"]]
    assert abs(len(thinking) / n - 0.25) < 0.02
    assert all(0 < len(r["messages"][-1]["reasoning_content"]) < 200 for r in thinking)
    assert all("reasoning_content" not in r["messages"][-1] for r in RECS if not r["thinking"])


def test_facts_present():
    text = " ".join(_answer(r) for r in RECS)
    for fact in ("Bird Models", "Qwen3.5-4B", "Apache 2.0", "4 milliards de paramètres", "4 billion parameters"):
        assert fact in text
    for r in RECS:
        q = r["messages"][-2]["content"].lower()
        if "qwen" in q or "chatgpt" in q or "claude" in q or "gemini" in q:
            assert "Bird" in _answer(r)
    company = [r for r in RECS if r["messages"][0]["role"] == "system" and r["messages"][0]["content"] not in DEFAULT_SYSTEM.values()]
    named = [r for r in company if re.search(r"qui es-tu|qui êtes-vous|who are you", r["messages"][-2]["content"], re.I)]
    assert named and all("Bird" in _answer(r) for r in named)


def test_forbidden_claims_absent():
    claim = re.compile(r"\b(?:je suis|je m'appelle|i am|i'm|my name is)\s+(?:un modèle\s+)?(?:qwen|chatgpt|claude|gemini|gpt|bird-m)\b", re.I)
    unit = re.compile(r"\d\s*(?:w|kw|kwh|wh|watts?|g|grammes?|grams?|kg|co2|%|joules?)\b", re.I)
    for r in RECS:
        for m in r["messages"]:
            if m["role"] != "assistant":
                continue
            text = m["content"] + " " + m.get("reasoning_content", "")
            assert not claim.search(text), text
            assert not unit.search(text), text
            assert "BIRD-M" not in text and "Qwen3.8" not in text and "Excellente question" not in text
            rest = text
            for ok in ("Qwen3.5-4B", "Apache 2.0", "4 milliards", "4 billion"):
                rest = rest.replace(ok, "")
            assert not re.search(r"\d", rest), text  # no other figure is ever given


def test_french_register_follows_the_user():
    for r in RECS:
        if r["lang"] != "fr":
            continue
        q, a = r["messages"][-2]["content"].lower(), _answer(r).lower()
        if re.search(r"\b(?:tu|toi|ton|ta|t'a)\b|-tu\b", q):
            assert not re.search(r"\b(?:vous|votre|vos)\b", a), (q, a)
        elif re.search(r"\b(?:vous|votre|vos)\b", q):
            assert not re.search(r"\b(?:tu|toi|ton|ta|tes)\b", a), (q, a)
