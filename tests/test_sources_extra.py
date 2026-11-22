import json

from birds.schema import errors
from birds.sources.extra import convert_xlam_fc

ROW = {"query": "Giveaways for beta access and games?",
       "tools": json.dumps([{"name": "live_giveaways_by_type", "description": "Retrieve live giveaways.",
                             "parameters": {"type": {"description": "The type.", "type": "str", "default": "game"},
                                            "limit": {"description": "Max.", "type": "int"}}}]),
       "answers": json.dumps([{"name": "live_giveaways_by_type", "arguments": {"type": "beta"}},
                              {"name": "live_giveaways_by_type", "arguments": {"type": "game"}}])}


def test_xlam_direct_parallel_calls():
    (r,) = convert_xlam_fc(ROW)
    full = {"id": "x", "source": "xlam_fc", "license": "cc-by-4.0", **r}
    assert errors(full) == [] and r["task"] == "tool_call_parallel"
    assert len(r["messages"][-1]["tool_calls"]) == 2 and r["messages"][-1]["content"] == ""
    p = r["tools"][0]["function"]["parameters"]
    assert p["properties"]["type"]["type"] == "string" and p["properties"]["limit"]["type"] == "integer"
    assert p["required"] == ["limit"]


def test_xlam_drops_bad_rows():
    assert convert_xlam_fc({}) == [] and convert_xlam_fc({**ROW, "answers": "[]"}) == []
    assert convert_xlam_fc({**ROW, "answers": json.dumps([{"name": "other", "arguments": {}}])}) == []
    assert convert_xlam_fc({**ROW, "tools": "not json"}) == []
