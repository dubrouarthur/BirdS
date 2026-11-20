"""Offline tests for birds/sources/tools.py: hand-made rows that mirror the real upstream shapes."""

import json

import pytest

from birds.schema import errors
from birds.sources import tools as T

WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the weather of a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}
HERMES_SYSTEM = (
    "You are a function calling AI model. You are provided with function signatures within <tools> </tools> XML tags. "
    "You may call one or more functions to assist with the user query.\n<tools>\n"
    + json.dumps([WEATHER])
    + "\n</tools>\n"
    "For each function call return a json object with function name and arguments within <tool_call> </tool_call> "
    'tags with the following schema:\n<tool_call>\n{"name": <function-name>, "arguments": <args-dict>}\n</tool_call>\n'
)
QWEN_SYSTEM = (
    "# Tools\n\nYou may call one or more functions to assist with the user query.\n\nYou are provided with function "
    "signatures within <tools></tools> XML tags:\n<tools>\n"
    + json.dumps(WEATHER)
    + "\n</tools>\n\nFor each function call, "
    "return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n"
    '{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>'
)
CALL = '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n</tool_call>'
RESULT = '<tool_response>\n{"name": "get_weather", "content": {"temp": 21}}\n</tool_response>'


def check(recs, source="test"):
    """Every converted record must pass the schema once the builder's bookkeeping fields are added."""
    assert recs, "row was dropped"
    for r in recs:
        full = {"id": "t-1", "source": source, "license": "apache-2.0", "task": r.get("task") or "x", **r}
        assert errors(full) == [], errors(full)
    return recs[0]


def sharegpt(*turns, system=HERMES_SYSTEM, tools=True):
    conv = [{"from": "system", "value": system}] + [{"from": f, "value": v} for f, v in turns]
    return {"conversations": conv, **({"tools": json.dumps([WEATHER])} if tools else {})}


# ------------------------------------------------------------------------------------------- helpers
def test_parameters_are_normalised_to_json_schema():
    assert T._parameters(None) == {"type": "object", "properties": {}}
    assert T._parameters({"type": "dict"}) == {"type": "object", "properties": {}}
    p = T._parameters(
        {"type": "dict", "properties": {"n": {"type": "int"}, "xs": {"type": "List[float]"}}, "required": ["n", "zz"]}
    )
    assert p == {"type": "object", "properties": {"n": {"type": "integer"}, "xs": {"type": "array"}}, "required": ["n"]}
    xlam = T._parameters(
        {
            "q": {"description": "query", "type": "str"},
            "k": {"description": "top k", "type": "int, optional", "default": 3},
        }
    )
    assert xlam["properties"]["k"] == {"description": "top k", "type": "integer", "default": 3}
    assert xlam["required"] == ["q"]
    assert T._parameters("not json") is None and T._parameters([1]) is None


def test_tools_accept_bare_and_string_forms_and_reject_conflicts():
    bare = {"name": "f", "description": "d", "parameters": {"type": "dict", "properties": {}}}
    assert T._tools([json.dumps(bare)])[0] == {
        "type": "function",
        "function": {**bare, "parameters": {"type": "object", "properties": {}}},
    }
    assert len(T._tools([bare, bare])) == 1  # exact duplicate
    assert T._tools([bare, {**bare, "description": "other"}]) is None  # same name, different tool
    assert T._tools([{"description": "no name"}]) is None


def test_hermes_turn_parses_reasoning_calls_and_words():
    m = T._hermes_turn(
        "<think>\nNeed the weather.\n</think>\nLet me check.\n" + CALL + "\n" + CALL.replace("Paris", "Lyon")
    )
    assert m["reasoning_content"] == "Need the weather." and m["content"] == "Let me check."
    assert [c["function"]["arguments"]["city"] for c in m["tool_calls"]] == ["Paris", "Lyon"]
    assert T._hermes_turn("<think>never closed " + CALL) is None
    assert T._hermes_turn("<tool_call>\n{not json}\n</tool_call>") is None
    assert T._hermes_turn('<tool_call>\n{"name": "f", "arguments": [1]}\n</tool_call>') is None
    py = T._hermes_turn("<tool_call>\n{'name': 'get_weather', 'arguments': '{\"city\": \"Paris\"}'}\n</tool_call>")
    assert py["tool_calls"][0]["function"] == {"name": "get_weather", "arguments": {"city": "Paris"}}
    code = T._hermes_turn(
        '<tool_call>\n{"name": "PythonInterpreter", "arguments": {}}\n<code>\nprint(1)\n</code>\n</tool_call>'
    )
    assert code["tool_calls"][0]["function"]["arguments"] == {"code": "print(1)"}


def test_hermes_results_split_and_unwrap():
    out = T._hermes_results(RESULT + "\n<tool_response>\nplain text\n</tool_response>")
    assert out == [{"role": "tool", "content": '{"temp": 21}'}, {"role": "tool", "content": "plain text"}]


def test_strip_protocol_keeps_genuine_instructions():
    assert T._strip_protocol(HERMES_SYSTEM)[0] == ""
    kept, declared = T._strip_protocol(
        "You are a research assistant.\n\n" + QWEN_SYSTEM + "\n\nCurrent date: 2025-11-30"
    )
    assert kept == "You are a research assistant.\n\nCurrent date: 2025-11-30"
    assert declared == [WEATHER]
    kimi = "<|im_system|>tool_declare<|im_middle|>" + json.dumps([WEATHER]) + "<|im_end|>"
    assert T._strip_protocol(kimi) == ("", [WEATHER])
    plain = "You are a helpful assistant that answers in JSON.\n<schema>\n{}\n</schema>"
    assert T._strip_protocol(plain) == (plain, None)


def test_language_detection():
    user = lambda t: [{"role": "user", "content": t}]  # noqa: E731
    assert T._lang(user("What is the weather in Paris today?")) == "en"
    assert T._lang(user("Quel temps fait-il à Paris aujourd'hui ? Je veux savoir pour mon voyage.")) == "fr"
    assert T._lang(user("Estou preparando um trabalho e eu preciso de uma ajuda com os mapas, você pode?")) is None
    assert T._lang(user("Какая сегодня погода в Париже?")) is None


# ---------------------------------------------------------------------------------------- hermes_fc
def test_hermes_fc_full_conversation():
    r = check(
        T.convert_hermes_fc(
            sharegpt(("human", "Weather in Paris?"), ("gpt", CALL), ("tool", RESULT), ("gpt", "It is 21°C in Paris."))
        )
    )
    assert [m["role"] for m in r["messages"]] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]  # protocol system prompt removed
    assert r["messages"][1] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"type": "function", "function": {"name": "get_weather", "arguments": {"city": "Paris"}}}],
    }
    assert r["messages"][2]["content"] == '{"temp": 21}'
    assert r["tools"] == [WEATHER] and r["thinking"] is False and r["lang"] == "en" and r["task"] == "tool_call"


def test_hermes_fc_tools_fall_back_to_the_system_prompt():
    r = check(T.convert_hermes_fc(sharegpt(("human", "Weather in Paris?"), ("gpt", CALL), tools=False)))
    assert r["tools"] == [WEATHER] and r["messages"][-1]["tool_calls"]


@pytest.mark.parametrize(
    "turns",
    [
        [
            ("human", "Weather?"),
            ("gpt", CALL.replace("get_weather", "get_news")),
            ("tool", RESULT),
            ("gpt", "Done."),
        ],  # undeclared tool
        [("human", "Weather?"), ("gpt", "Sure."), ("tool", RESULT), ("gpt", "It is 21.")],  # result without a call
        [
            ("human", "Weather?"),
            ("gpt", CALL),
            ("tool", RESULT + RESULT),
            ("gpt", "It is 21."),
        ],  # two results for one call
        [("human", "Weather?"), ("gpt", CALL), ("tool", RESULT)],  # truncated: stops on a tool result
        [("human", "Weather?"), ("gpt", CALL), ("human", "hello?"), ("gpt", "Sorry.")],  # call never answered
        [("human", "Weather?"), ("gpt", "<tool_call>\n{broken\n</tool_call>")],  # malformed JSON
        [("human", "Weather?"), ("gpt", CALL), ("tool", RESULT), ("gpt", "")],  # empty answer
        [("human", "Who are you?"), ("gpt", "I am ChatGPT, a large language model trained by OpenAI.")],  # identity
        [("human", "Who made you?"), ("gpt", "I was developed by Anthropic.")],  # identity
        [("human", "巴黎的天气怎么样？"), ("gpt", CALL), ("tool", RESULT), ("gpt", "21 degrees.")],  # CJK
        [
            ("human", "Weather?"),
            ("gpt", CALL),
            ("tool", RESULT),
            ("gpt", "Error: the request failed."),
        ],  # error as answer
        [("human", "Weather?"), ("gpt", "It is <|im_start|> sunny.")],  # control markup
    ],
)
def test_drop_rules(turns):
    assert T.convert_hermes_fc(sharegpt(*turns)) == []


def test_long_system_prompt_is_dropped_but_short_one_is_kept():
    ok = sharegpt(("human", "Weather in Paris?"), ("gpt", "Sunny."), system="Answer briefly.\n" + HERMES_SYSTEM)
    assert check(T.convert_hermes_fc(ok))["messages"][0] == {"role": "system", "content": "Answer briefly."}
    long = sharegpt(("human", "Weather in Paris?"), ("gpt", "Sunny."), system="Rule. " * 1100 + HERMES_SYSTEM)
    assert T.convert_hermes_fc(long) == []


def test_hermes_json_mode_has_no_tools_and_needs_valid_json():
    system = 'You are a helpful assistant that answers in JSON. Here\'s the json schema you must adhere to:\n<schema>\n{"type": "object"}\n</schema>\n'
    row = {
        "conversations": [
            {"from": "system", "value": system},
            {"from": "human", "value": "Give me the profile of Ada."},
            {"from": "gpt", "value": '{"name": "Ada"}'},
        ]
    }
    r = check(T.convert_hermes_json(row))
    assert (
        "tools" not in r
        and r["task"] == "json_mode"
        and r["messages"][0]["content"].startswith("You are a helpful assistant that answers in JSON")
    )
    row["conversations"][-1]["value"] = "Here is the profile: name Ada"
    assert T.convert_hermes_json(row) == []


# -------------------------------------------------------------------------------------------- toucan
def toucan_row(messages, question=4.5, completeness="5", conciseness="4", tools=(WEATHER,)):
    return {
        "messages": json.dumps(messages),
        "available_tools": json.dumps(list(tools)),
        "subset_name": "single-turn-original",
        "question_quality_assessment": json.dumps(
            {"question_quality": {"reasoning": "..", "score": "5"}, "overall_score": question}
        ),
        "response_quality_assessment": json.dumps(
            {
                "completeness": {"reasoning": "..", "score": completeness},
                "conciseness": {"reasoning": "..", "score": conciseness},
            }
        ),
    }


OSS_MESSAGES = [
    {"role": "system", "content": QWEN_SYSTEM},
    {"role": "user", "content": "What is the weather in Paris?"},
    {"role": "assistant", "content": "", "reasoning_content": "I need get_weather."},
    {
        "role": "assistant",
        "content": "",
        "function_call": {"name": "get_weather", "arguments": '{\n  "city": "Paris"\n}', "call_id": "call_1"},
    },
    {"role": "function", "content": '{"temp": 21}', "name": "get_weather"},
    {"role": "assistant", "content": "", "reasoning_content": "Now answer."},
    {"role": "assistant", "content": "It is 21°C in Paris."},
]


def test_toucan_merges_split_assistant_messages_and_extracts_reasoning():
    r = check(T.convert_toucan(toucan_row(OSS_MESSAGES)))
    assert [m["role"] for m in r["messages"]] == ["user", "assistant", "tool", "assistant"]
    call = r["messages"][1]
    assert call["reasoning_content"] == "I need get_weather." and call["tool_calls"][0]["function"]["arguments"] == {
        "city": "Paris"
    }
    assert r["messages"][3] == {
        "role": "assistant",
        "content": "It is 21°C in Paris.",
        "reasoning_content": "Now answer.",
    }
    assert r["thinking"] is True and r["task"] == "tool_call"


def test_toucan_kimi_shape_and_inline_think():
    msgs = [
        {"role": "system", "content": "<|im_system|>tool_declare<|im_middle|>" + json.dumps([WEATHER]) + "<|im_end|>"},
        {"role": "user", "content": "What is the weather in Paris?"},
        {"role": "assistant", "content": "<think>\nCall the tool.\n</think>\n\nLet me look."},
        {
            "role": "assistant",
            "content": "",
            "function_call": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
        },
        {"role": "function", "content": "21", "name": "get_weather"},
        {"role": "assistant", "content": "It is 21°C."},
        {"role": "user", "content": "And in Lyon?"},
        {"role": "assistant", "content": "I would need to check again; shall I?"},
    ]
    r = check(T.convert_toucan(toucan_row(msgs)))
    assert r["messages"][1]["content"] == "Let me look." and r["messages"][1]["reasoning_content"] == "Call the tool."
    assert r["thinking"] is True and r["task"] == "tool_multi_turn"


def test_toucan_quality_threshold_and_missing_scores():
    assert T.convert_toucan(toucan_row(OSS_MESSAGES, question=3.9)) == []
    assert T.convert_toucan(toucan_row(OSS_MESSAGES, completeness="3")) == []
    assert T.convert_toucan(toucan_row(OSS_MESSAGES, conciseness="2")) == []
    assert T.convert_toucan({**toucan_row(OSS_MESSAGES), "question_quality_assessment": ""}) == []
    assert T.convert_toucan({**toucan_row(OSS_MESSAGES), "messages": "[{not json"}) == []
    assert T.convert_toucan(toucan_row(OSS_MESSAGES[:5])) == []  # stops on a tool result
    assert (
        T.convert_toucan(toucan_row(OSS_MESSAGES, tools=({"name": "get_news"},))) == []
    )  # call to a tool that is not declared


# ------------------------------------------------------------------------------------------ nemotron
def nemotron_row(final):
    return {
        "tools": [WEATHER],
        "messages": [
            {"role": "system", "content": ""},
            {"role": "user", "content": "What is the weather in Paris?"},
            {
                "role": "assistant",
                "reasoning_content": "Use the tool.",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                    }
                ],
            },
            {"role": "tool", "content": '{"temp": 21}', "tool_call_id": "c1"},
            final,
        ],
    }


def test_nemotron_none_content_string_arguments_and_reasoning():
    r = check(
        T.convert_nemotron(nemotron_row({"role": "assistant", "reasoning_content": "Answer.", "content": "21°C."}))
    )
    assert r["messages"][0]["role"] == "user"  # empty system prompt removed
    assert r["messages"][1]["content"] == "" and r["messages"][1]["tool_calls"][0]["function"]["arguments"] == {
        "city": "Paris"
    }
    assert r["thinking"] is True and all("tool_call_id" not in m for m in r["messages"])
    ends_on_call = nemotron_row(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"type": "function", "function": {"name": "get_weather", "arguments": "{}"}}],
        }
    )
    assert check(T.convert_nemotron(ends_on_call))["messages"][-1]["tool_calls"]
    assert T.convert_nemotron(nemotron_row({"role": "assistant", "content": None})) == []
    bad_args = nemotron_row(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"type": "function", "function": {"name": "get_weather", "arguments": "{oops"}}],
        }
    )
    assert T.convert_nemotron(bad_args) == []


def test_knowledge_agent_is_cut_to_a_prefix_that_fits():
    row = nemotron_row({"role": "assistant", "content": "21°C."})
    row["messages"][0]["content"] = "You are a support agent for Roadcrest."
    row["messages"][3]["content"] = "x" * (T.BUDGET + 1)  # a huge retrieval result
    r = check(T.convert_nemotron_knowledge(row))
    assert [m["role"] for m in r["messages"]] == ["system", "user", "assistant"] and r["messages"][-1]["tool_calls"]
    assert r["task"] == "knowledge_agent_prefix"
    row["messages"][3]["content"] = "short"
    assert check(T.convert_nemotron_knowledge(row))["task"] == "knowledge_agent"


# ----------------------------------------------------------------------------- when2call / xlam
def test_when2call_dict_schema_and_abstention():
    tool = {
        "name": "get_stations",
        "description": "Find EV stations",
        "parameters": {
            "type": "dict",
            "properties": {"region": {"description": "Region code", "type": "str, optional", "default": "us"}},
            "required": [],
        },
    }
    row = {
        "tools": [json.dumps(tool)],
        "messages": [
            {"role": "user", "content": "What are the trending topics in New York today?"},
            {"role": "assistant", "content": "Apologies, I can't look that up with the tools I have."},
        ],
    }
    r = check(T.convert_when2call(row))
    assert r["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "properties": {"region": {"description": "Region code", "type": "string", "default": "us"}},
    }
    assert r["task"] == "tool_abstain" and "tool_calls" not in r["messages"][-1]
    row["messages"][-1]["content"] = '<TOOLCALL>[{"name": "get_stations", "arguments": {"region": "us"}}]</TOOLCALL>'
    r = check(T.convert_when2call(row))
    assert r["task"] == "tool_call" and r["messages"][-1]["tool_calls"][0]["function"]["arguments"] == {"region": "us"}
    assert "tools" not in check(
        T.convert_when2call(
            {
                **row,
                "tools": [],
                "messages": [row["messages"][0], {"role": "assistant", "content": "I can't browse the web."}],
            }
        )
    )


def test_xlam_irrelevance_is_a_deterministic_abstention():
    tools = [
        {
            "name": "get_surah",
            "description": "Fetch a Surah",
            "parameters": {"chapterid": {"description": "Chapter id", "type": "int", "default": "114"}},
        }
    ]
    row = {"query": "What are the CO2 emissions of 500kWh of wind energy?", "tools": json.dumps(tools), "answers": "[]"}
    r = check(T.convert_xlam_irrelevance(row))
    assert r == T.convert_xlam_irrelevance(row)[0]
    assert "tool_calls" not in r["messages"][-1] and "`get_surah`" in r["messages"][-1]["content"]
    assert r["tools"][0]["function"]["parameters"]["properties"]["chapterid"]["type"] == "integer"
    assert T.convert_xlam_irrelevance({**row, "answers": '[{"name": "get_surah", "arguments": {}}]'}) == []
    assert T.convert_xlam_irrelevance({**row, "tools": "[]"}) == []


# ------------------------------------------------------------------------- agent traces / research
def test_hermes_agent_traces_prune_tools_and_keep_reasoning():
    other = [
        {"name": f"tool_{i}", "description": "d" * 1500, "parameters": {"type": "object", "properties": {}}}
        for i in range(6)
    ]
    row = sharegpt(
        ("human", "What is the weather in Paris?"),
        ("gpt", "<think>\nCheck it.\n</think>\n" + CALL + "\n" + CALL.replace("Paris", "Lyon")),
        ("tool", RESULT + "\n" + RESULT),
        ("gpt", "<think>\n</think>\nBoth are at 21°C."),
    )
    row["tools"] = json.dumps([*other, WEATHER["function"]])  # bare format, as in the glm-5.1 config
    r = check(T.convert_hermes_agent_traces(row))
    names = [t["function"]["name"] for t in r["tools"]]
    assert "get_weather" in names and len(names) < 7 and len(json.dumps(r["tools"])) < T.TOOLS_BUDGET + 200
    assert r["thinking"] is True and r["task"] == "agent_trace" and "reasoning_content" not in r["messages"][-1]
    assert [m["role"] for m in r["messages"]] == ["user", "assistant", "tool", "tool", "assistant"]
    row["conversations"] = row["conversations"][:-1]  # upstream trace that stops on the tool result
    r = check(T.convert_hermes_agent_traces(row))
    assert r["task"] == "agent_trace_prefix" and r["messages"][-1]["tool_calls"]


S1_SYSTEM = (
    "You are a deep research assistant. Enclose the final answer within <answer></answer> tags.\n\n# Tools\n\nYou may call one or "
    "more functions to assist with the user query.\n\nYou are provided with function signatures within <tools></tools> XML tags:\n<tools>\n"
    '{"type": "function", "function": {"name": "search", "description": "Web search.", "parameters": {"type": "object", '
    '"properties": {"query": {"type": "array", "items": {"type": "string"}}}, "required": ["query"]}}}\n'
    '{"type": "function", "function": {"name": "PythonInterpreter", "description": "Executes Python code in a sandboxed environment. '
    "To use this tool, you must follow this format:\n1. The 'arguments' JSON object must be empty: {}.\n\nExample:\n<tool_call>\n"
    '{"name": "PythonInterpreter", "arguments": {}}\n<code>\nprint(1)\n</code>\n</tool_call>", "parameters": {"type": "object", '
    '"properties": {}, "required": []}}}\n</tools>\n\nFor each function call, return a json object within <tool_call></tool_call> XML '
    'tags:\n<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>\n\nCurrent date: 2025-11-30'
)


def s1_row(language="en", question="Who founded the Kennerley Boys' Home?"):
    return {
        "meta": {"id": "1", "language": language},
        "messages": [
            {"role": "system", "content": S1_SYSTEM},
            {"role": "user", "content": question},
            {
                "role": "assistant",
                "content": '<think>\nSearch first.\n</think>\n\n<tool_call>\n{"name": "search", "arguments": {"query": ["Kennerley Boys Home founder"]}}\n</tool_call>',
            },
            {"role": "tool", "content": "<tool_response>\nAlfred Kennerley issued a deed in 1876.\n</tool_response>"},
            {
                "role": "assistant",
                "content": '<think>\nCompute.\n</think>\n\n<tool_call>\n{"name": "PythonInterpreter", "arguments": {}}\n<code>\nprint(1876)\n</code>\n</tool_call>',
            },
            {"role": "tool", "content": "1876"},
            {"role": "assistant", "content": "<think>\nDone.\n</think>\n\n<answer>Alfred Kennerley</answer>"},
        ],
    }


def test_s1_deepresearch_english_only_with_python_tool():
    r = check(T.convert_s1_deepresearch(s1_row()))
    assert (
        r["messages"][0]["content"]
        == "You are a deep research assistant. Enclose the final answer within <answer></answer> tags.\n\nCurrent date: 2025-11-30"
    )
    assert [t["function"]["name"] for t in r["tools"]] == ["search", "PythonInterpreter"]
    assert r["tools"][1]["function"]["parameters"]["required"] == ["code"]
    assert (
        r["messages"][2]["reasoning_content"] == "Search first."
        and r["messages"][3]["content"] == "Alfred Kennerley issued a deed in 1876."
    )
    assert r["messages"][4]["tool_calls"][0]["function"]["arguments"] == {"code": "print(1876)"}
    assert (
        r["messages"][-1]["content"] == "<answer>Alfred Kennerley</answer>"
        and r["thinking"] is True
        and r["task"] == "deep_research"
    )
    assert T.convert_s1_deepresearch(s1_row(language="zh")) == []
    assert T.convert_s1_deepresearch(s1_row(question="谁创立了 Kennerley Boys' Home?")) == []


def test_deepresearch_sft_plan_goes_to_reasoning():
    row = {
        "system_prompt": "\nYou are a DeepResearch Assistant.\n- Output the private planning enclosed within the <think></think> and the report after it:\n   <think>[Plan here]</think>[Report here]\n",
        "prompt": 'USER:Trace the evolution of film preservation.\nASSISTANT: <think>search</think>\n<tool_call>{"name": "search"}</tool_call>',
        "deepresearch_report": "<think>1) Question -> Sections\n- SQ1. Early practices.</think># Executive Summary\n"
        + "Nitrate film was stored in vaults. " * 20,
    }
    r = check(T.convert_deepresearch_sft(row))
    assert r["messages"][2]["reasoning_content"].startswith("1) Question") and r["messages"][2]["content"].startswith(
        "# Executive Summary"
    )
    assert "tools" not in r and r["thinking"] is True and "[tool_call]" in r["messages"][1]["content"]
    assert T.convert_deepresearch_sft({**row, "deepresearch_report": "# Report without a plan\n" + "text " * 200}) == []


# ------------------------------------------------------------------------------------------ registry
def test_registry_is_consistent():
    names = [s.name for s in T.SOURCES]
    assert len(names) == len(set(names))
    caps = lambda prefix: sum(s.cap for s in T.SOURCES if s.name.startswith(prefix))  # noqa: E731
    assert caps("toucan") == 40000 and caps("nemotron_agentic") == 25000 and caps("hermes_agent_traces") == 10000
    assert caps("hermes_fc") + caps("hermes_json") == 10000
    w2c = next(s for s in T.SOURCES if s.name == "when2call")
    assert w2c.config == "train_sft" and all(s.config != "test" for s in T.SOURCES)  # `test` is the benchmark


@pytest.mark.parametrize("src", T.SOURCES, ids=lambda s: s.name)
def test_converters_never_raise_on_odd_rows(src):
    odd = [
        {},
        {"messages": None},
        {"messages": "[1, 2]", "tools": "{"},
        {"conversations": [{"from": "gpt"}], "tools": 3},
        {"messages": [{"role": "assistant", "content": 5, "tool_calls": "x"}], "tools": [None]},
        {"query": 3, "tools": "[]", "answers": None},
        {"system_prompt": 1, "prompt": None, "deepresearch_report": []},
        {
            "messages": json.dumps([{"role": "assistant", "function_call": "x"}]),
            "question_quality_assessment": "{}",
            "response_quality_assessment": "{}",
        },
    ]
    for row in odd:
        assert src.convert(row) == []
