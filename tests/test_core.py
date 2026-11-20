import pytest
from transformers import AutoTokenizer

from birds.parse import parse_output
from birds.render import IGNORE, encode, expand, prompt, spans
from birds.schema import errors

TOOLS = [{"type": "function", "function": {"name": "web_search", "description": "Search the web",
          "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}]


def rec(**kw):
    base = {"id": "t-1", "source": "test", "license": "apache-2.0", "lang": "fr", "task": "x", "thinking": False,
            "messages": [{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Salut."}]}
    return {**base, **kw}


def agent_rec(thinking):
    return rec(thinking=thinking, tools=TOOLS, messages=[
        {"role": "system", "content": "Tu es Bird."},
        {"role": "user", "content": "Cours du cuivre ?"},
        {"role": "assistant", "content": "", "reasoning_content": "Je dois chercher." if thinking else "",
         "tool_calls": [{"type": "function", "function": {"name": "web_search", "arguments": {"query": "cours cuivre", "n": 3}}}]},
        {"role": "tool", "content": "9 800 USD/t"},
        {"role": "assistant", "content": "Environ 9 800 USD la tonne.", **({"reasoning_content": "Résultat clair."} if thinking else {})},
    ])


@pytest.fixture(scope="module")
def tok():
    return AutoTokenizer.from_pretrained("Qwen/Qwen3.5-4B")


def test_schema_accepts_and_rejects():
    assert errors(rec()) == []
    assert errors(agent_rec(True)) == []
    assert errors(rec(lang="de"))
    assert errors(rec(messages=[{"role": "user", "content": "a"}]))
    assert errors(rec(messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "<think>x</think>b"}]))
    bad = agent_rec(False)
    bad["tools"] = []
    assert any("undeclared" in e for e in errors(bad))
    assert errors(rec(messages=[{"role": "user", "content": "a"},
                                {"role": "assistant", "content": "b", "reasoning_content": "r"}]))


def test_expand_one_example_per_query():
    r = rec(messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                      {"role": "user", "content": "c"}, {"role": "assistant", "content": "d"}])
    ex = expand(r)
    assert [len(e["messages"]) for e in ex] == [2, 4] and ex[0]["id"] != ex[1]["id"]


@pytest.mark.parametrize("thinking", [False, True])
def test_labels_cover_exactly_what_the_model_must_generate(tok, thinking):
    r = agent_rec(thinking)
    full, sp = spans(tok, r)
    assert len(sp) == 2
    learned = [full[a:b] for a, b in sp]
    assert all(s.endswith("<|im_end|>") for s in learned)
    assert "<function=web_search>" in learned[0] and "9 800 USD la tonne" in learned[1]
    if thinking:
        assert learned[0].startswith("Je dois chercher.") and "</think>" in learned[0]
    else:
        assert learned[0].startswith("<tool_call>") and "think" not in "".join(learned)
    # the text before the first learned span is exactly the inference-time prompt
    assert full[: sp[0][0]] == prompt(tok, r["messages"][:2], TOOLS, thinking)
    e = encode(tok, r, 4096)
    kept = tok.decode([t for t, lab in zip(e["input_ids"], e["labels"], strict=True) if lab != IGNORE])
    assert "Cours du cuivre" not in kept and "9 800 USD/t" not in kept and "Tu es Bird" not in kept
    assert "web_search" in kept and "Environ 9 800" in kept


def test_encode_drops_too_long(tok):
    assert encode(tok, rec(), 5) is None


def test_parse_roundtrip_of_native_tool_call(tok):
    r = agent_rec(True)
    full, sp = spans(tok, r)
    out = parse_output(full[sp[0][0]: sp[0][1]])
    assert out["reasoning"] == "Je dois chercher."
    assert out["tool_calls"] == [{"name": "web_search", "arguments": {"query": "cours cuivre", "n": 3}}]
    assert parse_output("Bonjour.<|im_end|>") == {"reasoning": "", "content": "Bonjour.", "tool_calls": []}
