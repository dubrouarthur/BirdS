"""Offline tests of the text converters, on hand-made rows that mirror the upstream shapes."""

import json

import pytest

from birds.schema import errors
from birds.sources import text as T

SRC = {s.name: s for s in T.SOURCES}
LONG = "x" * 7000


def conv(name, row):
    out = SRC[name].convert(row)
    for j, r in enumerate(out):
        full = {
            "id": f"{name}-{j}",
            "source": name,
            "license": SRC[name].license,
            "task": r.get("task") or SRC[name].task,
            **r,
        }
        assert errors(full) == [], errors(full)
        assert r["lang"] in ("fr", "en") and isinstance(r["thinking"], bool)
    assert out == SRC[name].convert(row)  # deterministic
    return out


def one(name, row):
    out = conv(name, row)
    assert len(out) == 1, T.why(name, row)
    return out[0]


def chat(*turns, system=None):
    roles = ["user", "assistant"] * len(turns)
    msgs = [{"role": r, "content": c} for r, c in zip(roles, turns, strict=False)]
    return ([{"role": "system", "content": system}] if system is not None else []) + msgs


def test_registry_is_complete_and_never_raises():
    assert len(SRC) == len(T.SOURCES) == 21
    assert SRC["bird_medium"].data_files == "train.jsonl" and SRC["grounded_qa"].split == "train"
    assert SRC["frenchqa"].cap == 15000 and SRC["openthoughts"].data_files
    for s in T.SOURCES:
        for row in (
            {},
            {"messages": None},
            {"messages": [1, 2]},
            {"conversations": "x", "documents": 3, "answers": 4},
            {"messages": [{"role": "user"}], "chat_template_kwargs": 5, "from": 7, "language": "fr", "lang": "fr"},
        ):
            assert s.convert(row) == []


# ---------------------------------------------------------------------------------------------- shared filters


@pytest.mark.parametrize(
    "answer,why",
    [
        ("I am ChatGPT, a large language model trained by OpenAI.", "other_assistant"),
        ("Je suis Claude, un assistant créé par Anthropic.", "other_assistant"),
        ("As an AI language model, I cannot have opinions on that.", "ai_refusal"),
        ("Yes.", "one_word"),
        ("The word is 你好 in Chinese.", "cjk"),
        ("<think>hmm</think> The answer is four.", "markup"),
        ("", "empty"),
    ],
)
def test_shared_filters(answer, why):
    row = {"messages": chat("What is two plus two, and who are you?", answer), "source": "smol-magpie-ultra-short"}
    assert T.why("smol_smoltalk", row) == why and conv("smol_smoltalk", row) == []


def test_names_of_people_and_products_are_not_identity_claims():
    row = {
        "messages": chat(
            "Who painted the Water Lilies?", "Claude Monet painted them; Google Arts shows several versions."
        ),
        "source": "smol-magpie-ultra-short",
    }
    assert one("smol_smoltalk", row)["lang"] == "en"


# ---------------------------------------------------------------------------------------------- bird_medium


def bm(**kw):
    base = {
        "id": "emails-1",
        "source": "emails",
        "lang": "fr",
        "thinking": False,
        "reasoning_effort": None,
        "thread_prev": None,
        "task": None,
        "messages": chat("Écris un mail à Paul pour décaler la réunion.", "Objet : Report\n\nBonjour Paul,\n\n…"),
    }
    return {**base, **kw}


def test_bird_medium_keeps_source_as_task_and_renames_the_system_prompt():
    r = one(
        "bird_medium",
        bm(
            messages=chat(
                "Bonjour, un mail pour Paul ?",
                "Bonjour Paul, voici le point.",
                system="Tu es Bird-Medium, un modèle de langage français.",
            )
        ),
    )
    assert r["task"] == "emails" and r["lang"] == "fr" and r["thinking"] is False
    assert r["messages"][0]["content"] == "Tu es Bird, un modèle de langage français."
    en = one(
        "bird_medium",
        bm(
            lang="en",
            source="slides",
            messages=chat("Make slides", "## Slide 1 — Title", system="You are BIRD-M, a model."),
        ),
    )
    assert en["messages"][0]["content"] == "You are Bird, a model." and en["task"] == "slides"


def test_bird_medium_reasoning_and_drops():
    msgs = chat("Quelle est la TVA sur 100 € ?", "20 €")
    msgs[-1]["reasoning_content"] = "100 × 0,20 = 20."
    r = one("bird_medium", bm(source="finance_fr", thinking=True, messages=msgs))
    assert r["thinking"] and r["messages"][-1]["reasoning_content"] == "100 × 0,20 = 20."
    assert (
        "reasoning_content"
        not in one("bird_medium", bm(source="finance_fr", thinking=False, messages=msgs))["messages"][-1]
    )
    assert conv("bird_medium", bm(source="identity", messages=chat("Qui es-tu ?", "Je suis un assistant."))) == []
    for bad in ("Je suis BIRD-M, votre assistant.", "Je suis Bird-Medium.", "Construit à partir de Qwen3.8-27B."):
        assert T.why("bird_medium", bm(messages=chat("Qui es-tu ?", bad))) == "old_identity"
    think = chat("Bonjour ?", "Bonjour à vous.")
    think[-1]["reasoning_content"] = "Je suis Bird-Medium, je salue."
    assert conv("bird_medium", bm(thinking=True, messages=think)) == []


# ---------------------------------------------------------------------------------------------- grounded answers

RAG = {
    "question": "What changed?",
    "answer_mode": "Grounded",
    "system_prompt": "You are a conversational AI assistant…",
    "documents": "Document:0\n\nTitle: Alpha report\n\nText: Sales rose by ten percent.\n\nDocument:1\n\nTitle: Beta memo\n\nText: Costs fell.",
    "answer": "Cited Documents: 0, 1\nAnswer: Two things changed. <co:0>Sales rose by ten percent</co>. Also <co: 1>costs fell</co:1>.",
}


def test_rag_glaive_brackets_and_numbered_documents():
    r = one("rag_glaive", RAG)
    system, user, answer = (m["content"] for m in r["messages"])
    assert "[1]" in system and "only" in system
    assert (
        user == "[1] Alpha report\nSales rose by ten percent.\n\n[2] Beta memo\nCosts fell.\n\nQuestion: What changed?"
    )
    assert answer == "Two things changed. Sales rose by ten percent [1]. Also costs fell [2]."
    assert "own knowledge" in one("rag_glaive", {**RAG, "answer_mode": "Mixed"})["messages"][0]["content"]
    plain = one(
        "rag_glaive", {**RAG, "answer": "Cited Documents: None\nAnswer: The documents do not say what changed."}
    )
    assert plain["messages"][-1]["content"] == "The documents do not say what changed."


def test_rag_glaive_rejects_broken_markup():
    assert T.why("rag_glaive", {**RAG, "answer": "Cited Documents: 0\nAnswer: <co:0>Sales rose."}) == "citation_markup"
    assert (
        T.why("rag_glaive", {**RAG, "answer": "Cited Documents: 7\nAnswer: <co:7>Sales rose</co>."})
        == "citation_markup"
    )
    assert T.why("rag_glaive", {**RAG, "answer": "Sales rose."}) == "answer_format"
    assert T.why("rag_glaive", {**RAG, "documents": "Some text without headers"}) == "documents_format"


GQA = {
    "id": "gqa-1",
    "language": "fr",
    "domain": "x",
    "question": "Quel est le délai de préavis ?",
    "answerable": True,
    "documents": [
        {"title": "Contrat", "text": "Le préavis est de 30 jours."},
        {"title": "Annexe", "text": "Tarifs 2026."},
    ],
    "answer": "30 jours",
    "reference_answer": "Le délai de préavis est de 30 jours.",
    "fallback": "Je n'ai pas trouvé la réponse dans les documents fournis.",
    "chosen": "Le délai de préavis est de 30 jours.",
}


def test_grounded_qa_languages_and_fallback():
    r = one("grounded_qa", GQA)
    assert r["lang"] == "fr" and r["task"] == "grounded_qa" and GQA["fallback"] in r["messages"][0]["content"]
    assert (
        r["messages"][1]["content"].startswith("[1] Contrat\nLe préavis")
        and r["messages"][-1]["content"] == GQA["reference_answer"]
    )
    no = one("grounded_qa", {**GQA, "answerable": False, "answer": None, "reference_answer": GQA["fallback"]})
    assert no["messages"][-1]["content"] == GQA["fallback"] and no["task"] == "grounded_qa_unanswerable"
    en = one(
        "grounded_qa", {**GQA, "language": "en", "fallback": "I couldn't find the answer in the provided documents."}
    )
    assert en["lang"] == "en" and en["messages"][0]["content"].startswith("Answer the question")
    for lang in ("de", "ar", "zh", "ja"):
        assert conv("grounded_qa", {**GQA, "language": lang}) == []


CONTEXT = (
    "Le 22 novembre 1990, la pièce est mise en scène pour la première fois au Royaume-Uni par Phyllida Lloyd, au Royal Exchange "
    "Theatre de Manchester. Le 17 septembre 1995, elle est diffusée sur BBC Radio dans une captation radiophonique."
)


def fqa(i, title="piaf", answer="Phyllida Lloyd"):
    return {
        "id": str(i),
        "title": title,
        "context": CONTEXT,
        "question": "Qui met en scène la pièce au Royaume-Uni ?",
        "answers": {"text": [answer] if answer else [], "answer_start": [0] if answer else []},
    }


def test_frenchqa_answerable_and_unanswerable():
    yes = [r for i in range(60) for r in conv("frenchqa", fqa(i))]
    no = [r for i in range(400) for r in conv("frenchqa", fqa(i, "piaf_v2", None))]
    assert len(yes) > 30 and 60 < len(no) < 200  # thinning rates: 82 % and 30 %
    assert {r["task"] for r in yes} == {"doc_qa"} and {r["task"] for r in no} == {"doc_qa_unanswerable"}
    for r in yes:
        a = r["messages"][-1]["content"]
        assert "Phyllida Lloyd" in a and a.endswith(".") and len(a) < 60 and r["lang"] == "fr"
    targets = {r["messages"][-1]["content"] for r in no}
    assert 6 <= len(targets) <= 8 and all("document" in t or "texte" in t for t in targets)
    layouts = {r["messages"][0]["role"] for r in yes + no}
    assert layouts == {"system", "user"} and all(CONTEXT in r["messages"][-2]["content"] for r in yes)
    long_span = "la pièce est mise en scène pour la première fois au Royaume-Uni"
    spans = {r["messages"][-1]["content"] for i in range(30) for r in conv("frenchqa", fqa(i, answer=long_span))}
    assert spans == {"La pièce est mise en scène pour la première fois au Royaume-Uni."}


def test_frenchqa_exclusions():
    assert all(T.why("frenchqa", fqa(i, "fquad_v2", None)) == "sub_dataset_excluded" for i in range(20))
    assert all(T.why("frenchqa", fqa(i, "lincoln/newsquadfr")) == "sub_dataset_excluded" for i in range(20))
    assert {T.why("frenchqa", fqa(i, answer="Peter Brook")) for i in range(40)} <= {"thinned", "span_not_in_document"}


# ---------------------------------------------------------------------------------------------- writing

EMAIL = "Hey Sarah,\n\nSo, I've been getting a bunch of complaints about slow browsers. Could you take a look? It's kinda urgent.\n\nThanks!"


def test_smoltalk_rewrite_and_summarize():
    sys_rw = (
        "You're an AI assistant for text re-writing. Rewrite the input text to make it more professional and formal."
    )
    seen = set()
    for i in range(12):
        row = {
            "messages": chat(
                f"{EMAIL} ({i})",
                "Dear Sarah, several users report slow browsers. Could you investigate?",
                system=sys_rw,
            )
        }
        r = one("smol_rewrite", row)
        seen.add(len(r["messages"]))
        text = " ".join(m["content"] for m in r["messages"][:-1])
        assert (
            "Rewrite the input text to make it more professional" in text
            and "AI assistant for text" not in text
            and r["lang"] == "en"
        )
    assert seen == {2, 3}  # instruction either as system prompt or inside the user turn
    s = one(
        "smol_summarize",
        {
            "messages": chat(
                EMAIL,
                "Sarah is asked to fix slow browsers urgently.",
                system="Provide a concise, objective summary of the input text.",
            )
        },
    )
    assert s["messages"][-1]["content"].startswith("Sarah is asked")
    assert conv("smol_summarize", {"messages": chat(EMAIL, "Slow browsers.", system="Summarise.")}) == []
    assert conv("smol_rewrite", {"messages": chat(EMAIL, "Dear Sarah, please look at it.")}) == []  # no instruction


def test_coedit():
    rows = [
        {
            "_id": str(i),
            "task": "gec",
            "src": f"Fix grammar in this sentence: The team have went to the {i}th office yesterday morning.",
            "tgt": f"The team went to the {i}th office yesterday morning.",
        }
        for i in range(200)
    ]
    kept = [r for row in rows for r in conv("coedit", row)]
    assert 10 < len(kept) < 70 and kept[0]["task"] == "edit_gec"  # thinned to ~16 %
    assert kept[0]["messages"][0]["content"].startswith("Fix grammar in this sentence: The team")
    same = {
        "task": "gec",
        "src": "Fix grammar: The team went to the office yesterday morning.",
        "tgt": "The team went to the office yesterday morning.",
    }
    assert T.why("coedit", same) == "no_change"
    assert (
        T.why(
            "coedit",
            {
                "task": "neutralize",
                "src": "Remove points of view: gaming system, a dice pool system where dice decide",
                "tgt": "gaming system, a unique dice pool system",
            },
        )
        == "fragment"
    )
    assert (
        T.why(
            "coedit",
            {"task": "gec", "src": "Fix grammar: courage can change lives", "tgt": "Courage can change lives."},
        )
        == "too_short"
    )


def test_smol_smoltalk_multi_turn_and_sources():
    row = {
        "messages": chat(
            "Hey!",
            "Hello! How can I help you today?",
            "What pets are popular?",
            "Dogs, cats and fish are popular pets.",
        ),
        "source": "everyday-conversations",
    }
    assert len(one("smol_smoltalk", row)["messages"]) == 4
    assert conv("smol_smoltalk", {**row, "source": "smollm-rewrite-30k"}) == []
    assert conv("smol_smoltalk", {**row, "source": "longalign"}) == []
    assert (
        T.why(
            "smol_smoltalk", {"messages": chat(LONG + LONG, "This is far too long.", "more", "And more again."), "source": "x"}
        )
        == "too_long"
    )
    assert T.why("smol_smoltalk", {"messages": chat("Hello there")}) == "shape"


def test_aya_fr():
    row = {
        "inputs": "Quels président des États-Unis ne s'est jamais marié ?",
        "targets": "James Buchanan est le seul président qui ne s'est jamais marié.",
        "language": "French",
        "language_code": "fra",
        "annotation_type": "original-annotations",
        "user_id": "u",
    }
    assert one("aya_fr", row)["lang"] == "fr"
    assert conv("aya_fr", {**row, "language_code": "som"}) == []
    assert conv("aya_fr", {**row, "targets": "Buchanan"}) == []
    assert conv("aya_fr", {**row, "targets": "Je ne sais pas. Réponse correcte: oui"}) == []


# ---------------------------------------------------------------------------------------------- reasoning

REASON = "The user asks for the sum of two and two. Adding them gives four. I should answer briefly and clearly."


def test_openthoughts_and_glaive_reasoning():
    ot = {
        "difficulty": 7,
        "source": "organic-chemistry-questions",
        "domain": "science",
        "conversations": [
            {"from": "human", "value": "What is two plus two?"},
            {"from": "gpt", "value": f"<think> {REASON} </think>\n\nFour."},
        ],
    }
    r = one(
        "openthoughts",
        {
            **ot,
            "conversations": [
                ot["conversations"][0],
                {"from": "gpt", "value": f"<think> {REASON} </think>\n\nIt is four."},
            ],
        },
    )
    assert r["thinking"] and r["messages"][-1] == {
        "role": "assistant",
        "content": "It is four.",
        "reasoning_content": REASON,
    }
    assert r["task"] == "reasoning_science"
    assert T.why("openthoughts", ot) == "one_word"
    long = {
        **ot,
        "conversations": [ot["conversations"][0], {"from": "gpt", "value": f"<think>{LONG}</think>It is four."}],
    }
    assert T.why("openthoughts", long) == "reasoning_too_long"
    cut = {
        **ot,
        "conversations": [ot["conversations"][0], {"from": "gpt", "value": f"<think>{REASON} it never closes"}],
    }
    assert T.why("openthoughts", cut) == "think_format"
    g = one(
        "glaive_reasoning",
        {"prompt": "What is two plus two?", "response": f"<think>\n{REASON}\n</think>\n\nTwo plus two is four."},
    )
    assert (
        g["thinking"]
        and g["messages"][-1]["reasoning_content"] == REASON
        and "think>" not in g["messages"][-1]["content"]
    )
    assert (
        T.why("glaive_reasoning", {"prompt": "Q?", "response": f"<think>{LONG}</think>Two plus two is four."})
        == "reasoning_too_long"
    )
    assert T.why("glaive_reasoning", {"prompt": "Q?", "response": "Two plus two is four."}) == "think_format"


def test_multilingual_thinking_keeps_french_and_english_reasoning():
    row = {
        "reasoning_language": "French",
        "developer": "You are a concise assistant.",
        "user": "Can you show me the latest trends?",
        "analysis": "D'accord, l'utilisateur demande les tendances. Je ne peux pas accéder à des données en temps réel, je dois le dire.",
        "final": "I can't check live data, but here is how to find the trends yourself.",
        "messages": [],
    }
    r = one("multilingual_thinking", row)
    assert (
        r["thinking"]
        and r["lang"] == "en"
        and r["messages"][0]["content"] == "Reasoning language: French.\n\nYou are a concise assistant."
    )
    assert r["messages"][-1]["reasoning_content"].startswith("D'accord")
    assert conv("multilingual_thinking", {**row, "reasoning_language": "German"}) == []
    assert T.why("multilingual_thinking", {**row, "reasoning_language": "English"}) == "reasoning_language_mismatch"


# ---------------------------------------------------------------------------------------------- tables, SQL, JSON


def test_table_gpt_and_text_to_sql():
    row = {
        "task": "DataImputation",
        "dataset": "Synthetic-DI",
        "prompt": "Fill the [MISSING] cell.\n|A|B|\n|---|---|\n|1|[MISSING]|\nReturn JSON.",
        "completion": '{"value": "2"}',
        "messages": [],
        "prompt_setting": "zero-shot",
        "metadata": "{}",
    }
    r = one("table_gpt", row)
    assert r["task"] == "table_DataImputation" and r["messages"][-1]["content"] == '{"value": "2"}'
    assert conv("table_gpt", {**row, "completion": " "}) == []
    sql = {
        "sql_prompt": "What is the total volume sold?",
        "sql_context": "CREATE TABLE sales (id INT, volume REAL);",
        "sql": "SELECT SUM(volume) FROM sales;",
        "sql_explanation": "Sums the volume column of the sales table.",
    }
    s = one("text_to_sql", sql)
    assert (
        s["messages"][-1]["content"]
        == "```sql\nSELECT SUM(volume) FROM sales;\n```\n\nSums the volume column of the sales table."
    )
    assert (
        "CREATE TABLE sales" in s["messages"][0]["content"]
        and "What is the total volume sold?" in s["messages"][0]["content"]
    )
    assert conv("text_to_sql", {**sql, "sql": ""}) == []


EXT = {
    "id": "ext-1",
    "doc_type": "invoice",
    "language": "fr",
    "document": "Facture n° 12 du 3 mars 2025, total 120,50 EUR.",
    "schema": json.dumps({"type": "object", "properties": {"total": {"type": "number"}}}),
    "extraction": '{"total": 120.5}',
}


def test_structured_extraction_outputs_valid_json():
    layouts = set()
    for i in range(10):
        r = one("structured_extraction", {**EXT, "document": EXT["document"] + f" Réf {i}."})
        assert json.loads(r["messages"][-1]["content"]) == {"total": 120.5} and r["lang"] == "fr"
        prompt = " ".join(m["content"] for m in r["messages"][:-1])
        assert "Schéma JSON" in prompt and '"total"' in prompt and "Facture n° 12" in prompt
        layouts.add(len(r["messages"]))
    assert layouts == {2, 3}
    assert one("structured_extraction", {**EXT, "language": "en"})["messages"][0]["content"].startswith("Extract")
    assert T.why("structured_extraction", {**EXT, "extraction": '{"total": 120.5'}) == "invalid_json"
    assert T.why("structured_extraction", {**EXT, "extraction": "[1, 2]"}) == "invalid_json"
    assert conv("structured_extraction", {**EXT, "language": "it"}) == []


def test_slides_officesmith():
    deck = json.dumps(
        {"version": "bird-deck/0.1", "slides": [{"layout": "title", "title": "Bilan"}]}, ensure_ascii=False
    )
    row = {
        "id": "officesmith-1",
        "task_id": "slides.deck",
        "lang": "fr",
        "source": "hf:Benitoow/OfficeSmith-PPTX-IR",
        "license": "apache-2.0",
        "messages": [{"role": "user", "content": "Créer une présentation de 6 slides."}],
        "target": deck,
    }
    r = one("slides_officesmith", row)
    assert r["lang"] == "fr" and json.loads(r["messages"][-1]["content"])["slides"]
    assert conv("slides_officesmith", {**row, "target": "{not json"}) == []
    assert conv("slides_officesmith", {**row, "target": '{"slides": []}'}) == []


# ---------------------------------------------------------------------------------------------- French sources


def test_is_french():
    assert T._is_french("Quelle est la meilleure façon de préparer une réunion avec les équipes ?")
    assert not T._is_french("What is the best way to prepare a meeting with the teams?")
    assert not T._is_french("¿Cuál es la mejor manera de preparar una reunión con los equipos?")
    assert not T._is_french("Como posso evitar clichês na escrita e garantir a originalidade no meu trabalho?")
    assert not T._is_french("Wie kann ich die Besprechung mit den Teams am besten vorbereiten und nicht zu spät sein?")


def test_nemotron_fr():
    row = {
        "uuid": "u",
        "license": "CC BY 4.0",
        "generator": "DeepSeek-R1-0528",
        "version": "v2",
        "category": "multilingual_fr",
        "reasoning": "on",
        "messages": [
            {"role": "system", "content": ""},
            {"role": "user", "content": "Quelle est la somme de deux et de deux dans ce problème ?"},
            {"role": "assistant", "content": f"<think>\n{REASON}\n</think>\n\nLa somme est quatre."},
        ],
    }
    r = one("nemotron_fr", row)
    assert r["lang"] == "fr" and r["thinking"] and [m["role"] for m in r["messages"]] == ["user", "assistant"]
    assert r["messages"][-1] == {"role": "assistant", "content": "La somme est quatre.", "reasoning_content": REASON}
    off = {**row, "messages": [*row["messages"][:2], {"role": "assistant", "content": "La somme est quatre."}]}
    assert one("nemotron_fr", off)["thinking"] is False
    long = {
        **row,
        "messages": [
            *row["messages"][:2],
            {"role": "assistant", "content": f"<think>{LONG}</think>La somme est quatre."},
        ],
    }
    assert T.why("nemotron_fr", long) == "reasoning_too_long"
    en = {
        **row,
        "messages": [
            row["messages"][0],
            {"role": "user", "content": "What is the sum of two and two in this problem?"},
            row["messages"][2],
        ],
    }
    assert T.why("nemotron_fr", en) == "not_french"


def test_synth_fr():
    row = {
        "synth_id": "memorization_french_1",
        "language": "fr",
        "exercise": "memorization",
        "model": "m",
        "constraints": "",
        "script": "",
        "query": "Est-ce que l'agrométéorologie donne de meilleurs résultats que les méthodes traditionnelles dans toutes les régions ?",
        "synthetic_reasoning": "### 1. Query\n" + REASON,
        "seed_license": "CC-By-SA (4.0)",
        "words": 100,
        "synthetic_answer": "L'agrométéorologie est l'étude de l'utilisation des conditions météorologiques pour optimiser les cultures agricoles.",
    }
    r = one("synth_fr", row)
    assert r["lang"] == "fr" and r["thinking"] and r["messages"][-1]["reasoning_content"].startswith("### 1. Query")
    assert conv("synth_fr", {**row, "language": "en"}) == []
    assert conv("synth_fr", {**row, "exercise": "rag"}) == []
    assert T.why("synth_fr", {**row, "synthetic_reasoning": LONG}) == "reasoning_too_long"


def test_smoltalk2_fr_keeps_french_only():
    kw = {"custom_instructions": "", "enable_thinking": False, "python_tools": [], "xml_tools": []}
    fr = {
        "messages": chat(
            "Comment puis-je éviter les clichés dans mon texte et rester original ?",
            "Pour éviter les clichés, lisez beaucoup et variez les tournures que vous utilisez dans vos phrases.",
        ),
        "chat_template_kwargs": kw,
        "source": "smoltalk-multilingual-8languages_lang_5",
    }
    assert one("smoltalk2_fr", fr)["lang"] == "fr"
    pt = {
        **fr,
        "messages": chat(
            "Como posso evitar clichês na escrita e garantir a originalidade no meu trabalho?",
            "Para evitar clichês na escrita, considere as seguintes dicas e leia amplamente.",
        ),
    }
    assert T.why("smoltalk2_fr", pt) == "not_french"
    mixed = {
        **fr,
        "messages": chat(
            fr["messages"][0]["content"],
            "To avoid clichés, read widely and vary the phrases that you use in your writing.",
        ),
    }
    assert T.why("smoltalk2_fr", mixed) == "not_french"


def mail(i=0, **kw):
    body = (
        "Bonjour Lena,\n\nL'exercice incendie obligatoire aura lieu vendredi à 14h00 sur le site. Merci de prévenir ton équipe "
        f"et de vérifier le point de rassemblement numéro {i}.\n\nCordialement\nRichter, Greta\nIngénieur forage, Sinabis Oil\n\n"
        "Ce courriel est confidentiel."
    )
    base = {
        "idx": i,
        "lang": "fr",
        "subject": "Exercice incendie de vendredi",
        "from": {"name": "Richter, Greta", "email": "g@x.com"},
        "to": [{"name": "Zimmermann, Lena", "email": "l@x.com"}],
        "cc": [],
        "message_id": f"m{i}",
        "in_reply_to": "",
        "calendar_method": "",
        "duplicate_of": "",
        "text": body,
        "body": body,
        "case_kind": "single",
    }
    return {**base, **kw}


def test_emails_subject_task_is_faithful():
    r = one("emails_fr_en", mail())
    user, answer = r["messages"][0]["content"], r["messages"][1]["content"]
    assert answer == "Exercice incendie de vendredi" and r["task"] == "emails" and r["lang"] == "fr"
    assert "exercice incendie obligatoire" in user and "confidentiel" not in user and "Richter, Greta" not in user
    assert (
        len({one("emails_fr_en", mail(i))["messages"][0]["content"].replace(str(i), "") for i in range(40)}) >= 4
    )  # phrasings vary
    assert T.why("emails_fr_en", mail(in_reply_to="m0")) == "reply_or_calendar"
    assert T.why("emails_fr_en", mail(subject="RE: Exercice incendie de vendredi")) == "subject"
    assert conv("emails_fr_en", mail(lang="de")) == [] and conv("emails_fr_en", mail(lang="it")) == []
    en = [r for i in range(300) for r in conv("emails_fr_en", mail(i, lang="en"))]
    assert 10 < len(en) < 70 and en[0]["lang"] == "en"  # English thinned to ~11 %


TOOLS = "\n".join(
    json.dumps(
        {
            "type": "function",
            "function": {
                "name": n,
                "description": d,
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
        }
    )
    for n, d in [("final_answer", "Provides a final answer."), ("web_search", "Performs a web search.")]
)


def tc(*assistant_and_tool, user="En quelle année le Congo belge est-il devenu indépendant de la Belgique ?"):
    msgs = [{"role": "user", "content": user}]
    for k, text in enumerate(assistant_and_tool):
        msgs.append({"role": "assistant" if k % 2 == 0 else "tool", "content": text})
    return {
        "messages": msgs,
        "source": "smolagents-toolcalling-traces",
        "chat_template_kwargs": {
            "custom_instructions": "",
            "enable_thinking": True,
            "python_tools": [],
            "xml_tools": [TOOLS],
        },
    }


CALL = "<think>I need the year, so I search.</think>\n<tool_call>{'name': 'web_search', 'arguments': {'query': 'Belgian Congo independence'}}</tool_call>"
FINAL = "<think>The result says 1960.</think>\n<tool_call>{'name': 'final_answer', 'arguments': {'answer': 'En 1960.\\n'}}</tool_call>"


def test_toolcall_fr_structured_calls():
    r = one("toolcall_fr", tc(CALL, "Observation:\nThe Belgian Congo became independent in 1960.", FINAL))
    assert r["lang"] == "fr" and r["thinking"] and [t["function"]["name"] for t in r["tools"]] == ["web_search"]
    assert [m["role"] for m in r["messages"]] == ["user", "assistant", "tool", "assistant"]
    call = r["messages"][1]
    assert call["content"] == "" and call["reasoning_content"] == "I need the year, so I search."
    assert call["tool_calls"] == [
        {"type": "function", "function": {"name": "web_search", "arguments": {"query": "Belgian Congo independence"}}}
    ]
    assert r["messages"][2]["content"] == "The Belgian Congo became independent in 1960."
    assert r["messages"][3] == {
        "role": "assistant",
        "content": "En 1960.",
        "reasoning_content": "The result says 1960.",
    }
    assert "tool_call" not in json.dumps(r["messages"][3]) and "<think>" not in json.dumps(r)


def test_toolcall_fr_drops():
    obs = "Observation:\nIt was 1960."
    undeclared = CALL.replace("web_search", "visit_webpage")
    assert T.why("toolcall_fr", tc(undeclared, obs, FINAL)) == "undeclared_tool"
    assert (
        T.why("toolcall_fr", tc(CALL.replace("{'query': 'Belgian Congo independence'}", "'oops'"), obs, FINAL))
        == "call_format"
    )
    assert T.why("toolcall_fr", tc(CALL, obs, FINAL.replace("En 1960.\\n", "1960"))) == "one_word"
    assert (
        T.why("toolcall_fr", tc(CALL, obs, FINAL, user="In which year did the Belgian Congo become independent?"))
        == "not_french"
    )
    assert T.why("toolcall_fr", tc(CALL, obs)) == "unfinished"
    assert T.why("toolcall_fr", tc(FINAL)) == "no_tool_call"
