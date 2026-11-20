import pytest

from birds.parse import parse_output
from birds.scoring import SCORERS, aggregate, detect_lang, identity_violation, is_refusal, score
from birds.tools import BIRD_TOOLS


def out(content="", calls=(), reasoning=""):
    return {"reasoning": reasoning, "content": content, "tool_calls": [{"name": n, "arguments": a} for n, a in calls]}


def it(scorer, **expected):
    return {"id": "t", "suite": "s", "lang": "fr", "scorer": scorer, "expected": expected}


def s(item, output):
    r = score(item, output)
    assert 0.0 <= r["score"] <= 1.0 and isinstance(r["detail"], dict)
    return r["score"]


def test_every_scorer_survives_an_empty_output():
    items = {
        "tool_call": it("tool_call", calls=[{"name": "f", "arguments": {"a": [1]}}]),
        "no_call": it("no_call"),
        "when2call": it("when2call", behavior="ask"),
        "first_tool": it("first_tool", tool="web_search"),
        "grounded": it("grounded", answerable=True, answer="12", reference_answer="Il y en a 12.", fallback="x"),
        "contains_any": it("contains_any", any=["Paris"]),
        "json_schema": it("json_schema", schema={"type": "object", "required": ["a"]}),
        "numbers": it("numbers", facts={"x": 12.5}),
        "identity": it("identity"),
        "language": it("language", lang="fr"),
        "concise": it("concise", any=["Paris"]),
    }
    assert set(items) == set(SCORERS)
    for name, item in items.items():
        assert s(item, out()) == (1.0 if name == "no_call" else 0.0), name
        assert s(item, {}) == (1.0 if name == "no_call" else 0.0), name
    with pytest.raises(KeyError):
        score(it("nope"), out())


# ---------------------------------------------------------------- tool_call

TRIANGLE = it(
    "tool_call", calls=[{"name": "geo.area", "arguments": {"base": [10], "height": [5], "unit": ["units", ""]}}]
)


def test_tool_call_single():
    assert s(TRIANGLE, out(calls=[("geo.area", {"base": 10, "height": 5})])) == 1
    assert (
        s(TRIANGLE, out(calls=[("geo.area", {"base": 10.0, "height": "5", "unit": " Units "})])) == 1
    )  # numeric / loose strings
    assert s(TRIANGLE, out(calls=[("geo.area", {"base": 10, "height": 6})])) == 0  # wrong value
    assert s(TRIANGLE, out(calls=[("geo.area", {"base": 10})])) == 0  # required parameter missing
    assert (
        s(TRIANGLE, out(calls=[("geo.area", {"base": 10, "height": 5, "color": "red"})])) == 0
    )  # unexpected parameter
    assert s(TRIANGLE, out(calls=[("geo.area", {"base": 10, "height": 5, "unit": "cm"})])) == 0  # value not in the list
    assert s(TRIANGLE, out(calls=[("geo_area", {"base": 10, "height": 5})])) == 0  # names are matched as-is
    assert s(TRIANGLE, out("The area is 25.")) == 0
    twice = [("geo.area", {"base": 10, "height": 5})] * 2
    assert s(TRIANGLE, out(calls=twice)) == 0  # one call expected


def test_tool_call_parallel_any_order_and_nested_values():
    item = it(
        "tool_call",
        calls=[
            {"name": "play", "arguments": {"artist": ["Taylor Swift"], "duration": [20]}},
            {"name": "play", "arguments": {"artist": ["Maroon 5"], "duration": [15]}},
        ],
    )
    good = [("play", {"artist": "maroon 5", "duration": 15}), ("play", {"artist": "Taylor Swift", "duration": 20})]
    assert s(item, out(calls=good)) == 1
    assert s(item, out(calls=good[:1])) == 0
    assert s(item, out(calls=[good[0], good[0]])) == 0
    assert (
        s(
            item,
            out(
                calls=[
                    ("play", {"artist": "Maroon 5", "duration": 20}),
                    ("play", {"artist": "Taylor Swift", "duration": 15}),
                ]
            ),
        )
        == 0
    )

    nested = it(
        "tool_call",
        calls=[
            {
                "name": "order",
                "arguments": {
                    "id": ["latte"],
                    "prefs": [{"size": ["large"], "milk": ["coconut", "oat"], "note": ["", "hot"]}],
                    "tags": [["a", "b"]],
                    "gift": [True],
                    "after": ["", None],
                },
            }
        ],
    )
    assert (
        s(
            nested,
            out(
                calls=[
                    (
                        "order",
                        {"id": "latte", "prefs": {"size": "Large", "milk": "oat"}, "tags": ["a", "b"], "gift": True},
                    )
                ]
            ),
        )
        == 1
    )
    assert (
        s(
            nested,
            out(
                calls=[
                    (
                        "order",
                        {"id": "latte", "prefs": {"size": "large", "milk": "soy"}, "tags": ["a", "b"], "gift": True},
                    )
                ]
            ),
        )
        == 0
    )
    assert (
        s(
            nested,
            out(
                calls=[
                    ("order", {"id": "latte", "prefs": {"size": "large", "milk": "oat"}, "tags": ["a"], "gift": True})
                ]
            ),
        )
        == 0
    )
    assert (
        s(
            nested,
            out(
                calls=[
                    ("order", {"id": "latte", "prefs": {"size": "large", "milk": "oat"}, "tags": ["a", "b"], "gift": 1})
                ]
            ),
        )
        == 0
    )
    assert (
        s(
            nested,
            out(
                calls=[
                    (
                        "order",
                        {
                            "id": "latte",
                            "prefs": {"size": "large", "milk": "oat"},
                            "tags": ["a", "b"],
                            "gift": "true",
                            "after": "null",
                        },
                    )
                ]
            ),
        )
        == 1
    )


def test_tool_call_from_native_qwen_text():
    raw = (
        "<tool_call>\n<function=geo.area>\n<parameter=base>\n10\n</parameter>\n<parameter=height>\n5\n</parameter>\n"
        "</function>\n</tool_call><|im_end|>"
    )
    assert s(TRIANGLE, parse_output(raw)) == 1


def test_no_call():
    assert s(it("no_call"), out("Je ne peux pas faire cela avec ces outils.")) == 1
    assert s(it("no_call"), out(calls=[("anything", {})])) == 0


def test_when2call():
    call, ask, decline = (it("when2call", behavior=b, tool="get_weather") for b in ("call", "ask", "decline"))
    called = out(calls=[("get_weather", {"city": "Paris"})])
    question = out("Which city do you mean?")
    refusal = out("Sorry, I cannot do that with the tools I have.")
    assert [s(call, o) for o in (called, question, refusal)] == [1, 0, 0]
    assert [s(ask, o) for o in (called, question, refusal)] == [0, 1, 0]
    assert [s(decline, o) for o in (called, question, refusal)] == [0, 0, 1]
    assert s(call, out(calls=[("other_tool", {})])) == 0
    assert s(decline, out()) == 0  # saying nothing is not declining


def test_first_tool():
    item = it("first_tool", tool="draft_email", args_contains=["a@b.fr", "f-2291"])
    assert s(item, out(calls=[("draft_email", {"to": ["A@B.fr"], "subject": "Facture F-2291", "body": "…"})])) == 1
    assert s(item, out(calls=[("draft_email", {"to": ["a@b.fr"], "subject": "Relance", "body": "…"})])) == 0
    assert s(item, out(calls=[("web_search", {"query": "a@b.fr f-2291"})])) == 0
    assert (
        s(item, out(calls=[("web_search", {}), ("draft_email", {"to": ["a@b.fr"], "subject": "F-2291"})])) == 0
    )  # first call counts
    none = it("first_tool", tool="none")
    assert s(none, out("30.")) == 1 and s(none, out(calls=[("run_python", {"code": "print(30)"})])) == 0
    assert s(it("first_tool", tool="web_search"), out(calls=[("web_search", {"query": "x"})])) == 1


# ---------------------------------------------------------------- text scorers


def test_grounded():
    yes = it(
        "grounded",
        answerable=True,
        answer="2 £",
        fallback="Je n'ai pas trouvé la réponse dans les documents fournis.",
        reference_answer="Le tarif horaire membre de la salle Kestrel passe de £22.00 à £24.00, soit une augmentation de 2 £.",
    )
    assert s(yes, out("Le tarif augmente de 2 £ pour les membres.")) == 1  # key span
    assert s(yes, out("Le tarif horaire de la salle Kestrel passe de £22.00 à £24.00 pour les membres.")) == 1  # F1
    assert s(yes, out("Il augmente de 5 euros.")) == 0
    assert s(yes, out("Je n'ai pas trouvé la réponse dans les documents fournis.")) == 0
    assert (
        s(yes, out("Les documents ne précisent pas ce tarif, mais il pourrait augmenter de 2 £.")) == 0
    )  # refusal wins
    no = it(
        "grounded",
        answerable=False,
        answer=None,
        reference_answer="I couldn't find the answer in the provided documents.",
        fallback="I couldn't find the answer in the provided documents.",
    )
    assert s(no, out("I couldn't find the answer in the provided documents.")) == 1
    assert s(no, out("The documents do not mention the budget for that session.")) == 1
    assert s(no, out("Les documents ne contiennent pas cette information.")) == 1
    assert s(no, out("The budget for that session is 4,500 euros.")) == 0


@pytest.mark.parametrize(
    "text",
    [
        "Le document ne contient pas cette information.",
        "Je n’ai pas trouvé la réponse.",
        "Il n'y a pas d'information à ce sujet.",
        "Ce montant n'est pas précisé dans les documents.",
        "The context does not mention it.",
        "I cannot find this in the documents.",
        "There is no information about that.",
        "That figure is not stated.",
        "The documents don't specify the date.",
    ],
)
def test_refusal_patterns(text):
    assert is_refusal(text)


@pytest.mark.parametrize(
    "text", ["La réunion a lieu le 12 mars.", "The fee is $18 per person.", "Oui, la salle est ouverte le lundi."]
)
def test_not_a_refusal(text):
    assert not is_refusal(text)


def test_contains_any():
    item = it("contains_any", any=["100 000", "cent mille"])
    assert s(item, out("Environ **100 000** salariés.")) == 1
    assert s(item, out("Environ 100000 salariés.")) == 1
    assert s(item, out("Cent mille personnes.")) == 1
    assert s(item, out("Environ 2 100 000 salariés.")) == 0  # not the same number
    assert s(item, out("Environ 10 000 salariés.")) == 0
    accents = it("contains_any", any=["Élysée"])
    assert s(accents, out("au palais de l'elysee")) == 1 and s(accents, out("au lycée")) == 0
    capped = it("contains_any", any=["Paris"], max_words=5)
    assert s(capped, out("C'est Paris.")) == 1 and s(capped, out("Paris " + "mot " * 10)) == 0


def test_json_schema():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer", "minimum": 0}},
        "required": ["name", "age"],
        "additionalProperties": False,
    }
    item = it("json_schema", schema=schema)
    assert s(item, out('{"name": "Léa", "age": 31}')) == 1
    assert s(item, out('```json\n{"name": "Léa", "age": 31}\n```')) == 1
    assert s(item, out('Voici :\n```\n{"name": "Léa", "age": 31}\n```\nBonne journée.')) == 1
    assert s(item, out('{"name": "Léa", "age": -1}')) == 0
    assert s(item, out('{"name": "Léa"}')) == 0
    assert s(item, out('{"name": "Léa", "age": 31, "x": 1}')) == 0
    assert s(item, out('{"name": "Léa", "age": 31')) == 0  # truncated
    assert s(item, out("name: Léa, age: 31")) == 0


def test_numbers():
    item = it("numbers", facts={"marge": 66.9, "bfr": -25.4, "skip": None})
    assert s(item, out("Marge brute : **66,9 %** ; BFR : -25,4 jours.")) == 1
    assert s(item, out("Gross margin 66.9%, working capital −25.4 days")) == 1
    assert s(item, out("Marge brute : 66,9 % ; BFR : 31 jours.")) == 0.5
    assert s(item, out("Aucune idée.")) == 0
    big = it("numbers", facts={"ca": 12089})
    assert s(big, out("CA : 12 089 k€")) == 1 and s(big, out("Revenue: 12,089")) == 1 and s(big, out("12 890")) == 0


def test_identity():
    item = it("identity")
    ok = [
        "Je suis Bird, l'assistant conçu par Bird Models.",
        "Non, je ne suis pas ChatGPT. Je m'appelle Bird.",
        "I'm Bird. I am built from the open Qwen3.5-4B model, then specialised by Bird Models.",
        "Bird, a small model made by Bird Models on top of Qwen3.5-4B (developed by Alibaba, Apache 2.0).",
        "I'm not Claude or Gemini, I'm Bird.",
    ]
    bad = [
        "Je suis Qwen, un modèle développé par Alibaba Cloud.",  # no Bird, other identity
        "I am ChatGPT, but you can call me Bird.",
        "Je suis Bird, et j'ai été créé par OpenAI.",
        "Bird here. I was developed by Alibaba Cloud.",
        "Je suis un assistant d'intelligence artificielle.",  # never says Bird
        "I love birdwatching.",
    ]
    for text in ok:
        assert s(item, out(text)) == 1, text
    for text in bad:
        assert s(item, out(text)) == 0, text
    assert identity_violation("My name is Claude.") and identity_violation("Je suis Bird.") is None


def test_language():
    fr, en = it("language", lang="fr"), it("language", lang="en")
    french = "Bonjour à tous, la réunion de lundi est reportée à mercredi. Merci de votre compréhension."
    english = "Hi all, the Monday meeting is moved to Wednesday. Thanks for your understanding."
    assert s(fr, out(french)) == 1 and s(fr, out(english)) == 0
    assert s(en, out(english)) == 1 and s(en, out(french)) == 0
    assert s(fr, out("42")) == 0 and detect_lang("42")[0] is None
    assert s(fr, out(french + " " + english)) == 0  # mixed answer


def test_concise():
    item = it("concise", any=["Canberra"], max_words=60)
    assert s(item, out("Canberra.")) == 1
    assert s(item, out("La capitale de l'Australie est Canberra.")) == 1
    assert s(item, out("Sydney.")) == 0
    assert s(item, out("Excellente question ! C'est Canberra.")) == 0
    assert s(item, out("Great question! It is Canberra.")) == 0
    assert s(item, out("As an AI, I believe it is Canberra.")) == 0
    assert s(item, out("Canberra " + "blabla " * 60)) == 0
    keys = it("concise", any=["ctrl+c", "ctrl + c"])
    assert s(keys, out("`Ctrl` + `C`")) == 1 and s(keys, out("**Ctrl+C**")) == 1


# ---------------------------------------------------------------- aggregate and tools


def test_aggregate():
    rows = [
        {"suite": "a", "lang": "fr", "score": 1.0},
        {"suite": "a", "lang": "en", "score": 0.0},
        {"suite": "b", "lang": "fr", "score": 1.0},
        {"suite": "b", "lang": "fr", "score": 1.0},
        {"suite": "b", "lang": "fr", "score": 1.0},
        {"suite": "a_think", "lang": "en", "score": 0.0},
    ]
    agg = aggregate(rows)
    assert agg["suites"]["a"] == {"n": 2, "score": 0.5} and agg["suites"]["b"]["score"] == 1.0
    assert agg["langs"]["fr"] == {"n": 4, "score": 1.0} and agg["langs"]["en"]["score"] == 0.0
    assert agg["overall"] == 0.75 and agg["overall_think"] == 0.0 and agg["n"] == 6
    assert aggregate([])["overall"] is None


def test_bird_tools_are_valid_openai_tools():
    import jsonschema

    names = [t["function"]["name"] for t in BIRD_TOOLS]
    assert names == [
        "web_search",
        "read_page",
        "read_file",
        "draft_email",
        "make_slides",
        "make_document",
        "make_sheet",
        "run_python",
    ]
    for t in BIRD_TOOLS:
        fn = t["function"]
        assert t["type"] == "function" and fn["description"] and fn["parameters"]["type"] == "object"
        jsonschema.Draft202012Validator.check_schema(fn["parameters"])
        assert set(fn["parameters"]["required"]) <= set(fn["parameters"]["properties"])
