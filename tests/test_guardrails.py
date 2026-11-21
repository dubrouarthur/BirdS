from birds.parse import parse_output
from birds.schema import errors
from birds.scoring import score
from birds.sources.guardrails import BENCH_INJECT, INJECT, bench_items, generate


def test_training_records_are_valid_and_never_obey():
    recs = generate(400, 0)
    assert recs == generate(400, 0) and len(recs) == 400
    assert all(errors(r) == [] for r in recs)
    assert len({r["messages"][1]["content"] for r in recs}) > 300
    for r in recs:
        calls = [m for m in r["messages"] if m.get("tool_calls")]
        assert len(calls) == 1 and r["messages"][-1]["role"] == "assistant" and not r["messages"][-1].get("tool_calls")
        tool_result, final = r["messages"][-2]["content"], r["messages"][-1]["content"]
        assert any(i in tool_result for i in INJECT[r["lang"]])
        assert any(w in final for w in ("instruction", "consigne", "asked the assistant", "demandait"))
        assert ".test" not in final and "@" not in final  # the answer never repeats the injected address


def test_bench_suite_is_held_out_and_scored_on_tool_calls():
    items = bench_items()
    assert len(items) == 24 and {i["lang"] for i in items} == {"fr", "en"}
    train_text = " ".join(m["content"] for r in generate(400, 0) for m in r["messages"])
    for it in items:
        assert it["messages"][-1]["role"] == "tool" and it["scorer"] == "no_call"
        assert any(b in it["messages"][-1]["content"] for b in BENCH_INJECT[it["lang"]])
        assert it["messages"][-1]["content"] not in train_text
    obey = parse_output("<tool_call>\n<function=draft_email>\n<parameter=to>\nx@y.test\n</parameter>\n</function>\n</tool_call>")
    assert score(items[0], obey)["score"] == 0 and score(items[0], parse_output("Résumé."))["score"] == 1
