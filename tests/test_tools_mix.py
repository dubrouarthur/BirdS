"""scripts/build_tools_mix.py: the supervised set that teaches Bird its modules (router decisions, EXTRA calls)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

from birds.harness import catalog
from birds.harness import router as R
from birds.harness.template import TemplateTokenizer
from birds.render import expand, spans
from birds.schema import errors
from birds.tools import BIRD_TOOLS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_tools_mix as M  # noqa: E402
import router_data as D  # noqa: E402


@pytest.fixture(scope="module")
def mix():
    return M.build(n=1500, seed=0)


def _user(rec) -> str:
    return next(m["content"] for m in reversed(rec["messages"]) if m["role"] == "user")


def test_records_are_valid_mix_records_with_one_thing_to_learn(mix):
    tok = TemplateTokenizer()
    for split in ("train", "eval", "bench_heldout"):
        assert mix[split]
        for r in mix[split][:400]:
            assert errors({k: v for k, v in r.items() if k not in ("family", "label", "template")}) == []
            assert r["source"] == "bird_tools" and r["thinking"] is False and r["lang"] in ("fr", "en")
            assert len(expand(r)) == 1  # a single assistant turn: the few-shot examples are never learnt
            full, sp = spans(tok, r)
            assert len(sp) == 1 and full[sp[0][0] : sp[0][1]].endswith("<|im_end|>")


def test_router_labels_are_schema_valid_grounded_decisions(mix):
    schema = catalog.decision_schema()
    for r in (x for x in mix["train"] if x["task"] == "router"):
        d = json.loads(r["messages"][-1]["content"])
        jsonschema.validate(d, schema)
        words = _user(r).split("Message : ", 1)[-1].split("Message: ", 1)[-1]
        for m in d["modules"]:
            assert catalog.check_args(m["tool"], m["args"])[0] is not None
        assert r["messages"][0]["content"].startswith(catalog.text(r["lang"]))
        assert words


def test_native_records_call_an_extra_tool_after_the_trained_block(mix):
    nat = [x for x in mix["train"] if x["task"] == "tool_call_extra"]
    assert len(nat) > 100
    names = {x["messages"][-1]["tool_calls"][0]["function"]["name"] for x in nat}
    assert {"get_weather", "find_places", "find_company", "convert_currency", "web_search"} <= names
    for x in nat:
        assert x["tools"][: len(BIRD_TOOLS)] == BIRD_TOOLS  # the trained block byte for byte, extras after
        assert [m["role"] for m in x["messages"]] == ["system", "user", "assistant"]


def test_negatives_follow_ups_and_both_languages_are_there(mix):
    st = mix["stats"]["train"]
    assert st["negatives"] / st["router"] > 0.25 and st["follow_ups"] > 50
    assert 0 < st["records"] - st["fr"] < st["records"]


def test_no_duplicate_and_no_bench_phrasing_in_train(mix):
    bench = {R.fold(it["text"]) for it in D.items() if not it["history"]}
    seen = set()
    for r in (x for x in mix["train"] if x["task"] == "router"):
        key = _user(r)
        assert key not in seen
        seen.add(key)
        if "Tour précédent" not in key:  # a follow-up is another request (« ok » after a forecast)
            assert R.fold(key.rsplit("Message : ", 1)[-1].rsplit("Message: ", 1)[-1]) not in bench


def test_held_out_templates_never_reach_train(mix):
    held = set(mix["stats"]["held_out_templates"])
    assert held and all(r["template"] not in held for r in mix["train"])
    assert all(r["template"] in held for r in mix["eval"])


def test_typos_never_touch_an_argument():
    import random

    label = {"modules": [{"tool": "get_weather", "args": {"place": "Strasbourg", "day": "demain"}}]}
    rng = random.Random(3)
    for _ in range(50):
        for v in M.variants("prévisions météo pour Strasbourg demain", "fr", label, rng):
            assert M.check(v, None, label)


def test_data_plan_records_teach_the_analysis_planner(mix):
    from birds.harness.analysis import planner as P

    rows = [r for r in mix["train"] if r["task"] == "data_plan"]
    assert len(rows) >= 100 and mix["stats"]["train"]["data_plan"] == len(rows)
    nulls = [r for r in rows if json.loads(r["messages"][-1]["content"])["analysis"] is None]
    assert 20 <= len(nulls) < len(rows) // 2  # negatives: requests that compute nothing
    for r in rows[:40]:
        assert r["messages"][0]["content"].startswith(P._HEAD[r["lang"]])  # the exact planner prompt
        obj = json.loads(r["messages"][-1]["content"])
        assert set(obj) == {"analysis", "chart"} and obj["chart"] in P.CHARTS
    assert any(r["template"] == "data_heat" for r in mix["eval"])


def test_reflexion_records_teach_the_level_decision(mix):
    from birds.harness import reflexion as RX

    rec = [x for x in mix["train"] if x["task"] == "reflexion"]
    assert len(rec) > 60 and mix["stats"]["train"]["reflexion"] == len(rec)
    assert {json.loads(x["messages"][-1]["content"])["level"] for x in rec} == set(RX.AUTO_LEVELS)
    evals = {R.fold(t) for t, _ in D.REFLEXION_LEVELS}
    for x in rec:
        assert x["messages"][0] == RX.messages("", x["lang"])[0]  # the exact static prompt of reflexion.decide
        assert R.fold(_user(x).split(":", 1)[-1]) not in evals


def test_nextsteps_records_teach_the_users_voice(mix):
    from birds.harness import nextsteps as N

    rec = [x for x in mix["train"] if x["task"] == "nextsteps"]
    assert len(rec) >= 30 and mix["stats"]["train"]["nextsteps"] == len(rec)
    evals = {R.fold(c[2]) for c in D.NEXTSTEPS_CASES}
    empty = 0
    for x in rec:
        assert x["messages"][0] == N.messages("", "", x["lang"], N.capabilities(x["lang"], None, None))[0]
        obj = json.loads(x["messages"][-1]["content"])
        assert N.validate(obj, lang=x["lang"])[1] == []  # every target passes the validation of the live call
        empty += not obj["suggestions"]
        req = _user(x).split("\n", 1)[0].split(":", 1)[-1]
        assert R.fold(req) not in evals
    assert 0 < empty < len(rec) // 2  # small talk teaches « nothing more »
