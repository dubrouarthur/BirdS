"""birds.web.tidy: deterministic repairs of a raw answer, and parse-only syntax checks of its code blocks."""

import json
from pathlib import Path

import pytest

from birds.web.tidy import code_checks, tidy

ANSWERS = json.loads((Path(__file__).parent / "fixtures" / "answers_fr.json").read_text())
FENCE = "```"


@pytest.mark.parametrize("item", ANSWERS, ids=[a["id"] for a in ANSWERS])
def test_live_answers_are_left_alone_except_the_loop(item):
    out = tidy(item["answer"], item["stop_reason"])
    again = tidy(out.text, out.stop_reason)
    assert again.text == out.text and again.repairs == []  # idempotent
    if item["id"] == "plan":
        assert out.repairs == ["loop_trimmed"] and out.stop_reason == "repetition"
        items = [ln for ln in out.text.splitlines() if ln.startswith("- ")]
        assert 12 <= len(items) <= 5 + 2 * 8  # the 5 lead items, then two cycles of the period-8 loop
        assert item["answer"].startswith(out.text)  # only the tail is cut: the prefix cache keeps its bytes
    else:
        assert out.text is item["answer"] and out.repairs == [] and out.stop_reason == item["stop_reason"]


@pytest.mark.parametrize(
    ("raw", "fixed", "repair"),
    [
        (f"Voici :\n\n{FENCE}python\nx = 1\n", f"Voici :\n\n{FENCE}python\nx = 1\n{FENCE}", "fence_closed"),
        (f"Le code :{FENCE}python\nx = 1\n{FENCE}", f"Le code :\n{FENCE}python\nx = 1\n{FENCE}", "fence_glued"),
        (f"{FENCE}sh\nls\n{FENCE} Puis lancez-le.", f"{FENCE}sh\nls\n{FENCE}\nPuis lancez-le.", "fence_glued"),
        ("| a | b |\n| 1 | 2 |\n| 3 | 4 |", "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |", "table_sep_missing"),
        ("| a | b |\n|---|\n| 1 | 2 |", "| a | b |\n|---|---|\n| 1 | 2 |", "table_sep_width"),
        ("| a | b | |---|---| | 1 | 2 |", "| a | b |\n|---|---|\n| 1 | 2 |", "table_inline"),
        ("| a | b |\n|---|---|\n| 1 | 2 |\n\n| 3 | 4 |", "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |", "table_blank"),
        ("Sécurité\n\nSécurité\n- a", "Sécurité\n\nSécurité\n- a", None),  # bare lines are not headings here
        ("## Sécurité\n\n**Sécurité** :\n- a", "## Sécurité\n- a", "heading_duplicate"),
        ("Texte.\n\n[Mémo de ce tour — web_search: x]", "Texte.", "memo_echo"),
        ("Texte.\n[Memo of this turn — none]\nSuite.", "Texte.\nSuite.", "memo_echo"),
        ("Texte coupé [réponse interrompue]", "Texte coupé", "interrupted_echo"),
        ("Bird : Bonjour !", "Bonjour !", "role_echo"),
        ("a\r\nb", "a\nb", "newlines"),
    ],
)
def test_each_repair(raw, fixed, repair):
    out = tidy(raw)
    assert out.text == fixed
    assert out.repairs == ([repair] if repair else [])
    assert tidy(out.text).repairs == []


def test_code_inside_fences_is_never_touched():
    raw = f"{FENCE}\n| a | b |\n| 1 | 2 |\n## T\n## T\n[Mémo de ce tour — x]\n{FENCE}"
    assert tidy(raw).text is raw


def test_hostile_markup_and_redaction_markers_pass_through():
    raw = '<img src=x onerror="alert(1)"> [x](javascript:alert(1)) [secret masqué]'
    assert tidy(raw).text is raw


def test_loop_trim_needs_a_cut_answer_and_a_real_cycle():
    cyc = "\n".join(f"- {d} mars : étape {'ABCD'[d % 4]}" for d in range(30, 0, -1))
    assert tidy(cyc, "answer").repairs == []  # a complete answer is never cut
    out = tidy(cyc, "length")
    assert out.repairs == ["loop_trimmed"] and len(out.text.splitlines()) == 8
    distinct = "\n".join(f"- étape {i} : action {i}" for i in range(20))
    assert tidy(distinct, "length").repairs == []


def test_code_checks_parse_but_never_run(tmp_path):
    marker = tmp_path / "ran"
    py = f"import pathlib\npathlib.Path({str(marker)!r}).write_text('x')\n"
    text = (
        f"{FENCE}python\n{py}{FENCE}\n\n{FENCE}python\ndef f(:\n    pass\n{FENCE}\n\n"
        f"{FENCE}py\n>>> 1 +\n{FENCE}\n\n{FENCE}json\n{{\"a\": 1}}\n{FENCE}\n\n{FENCE}json\n{{\"a\": 1,}}\n{FENCE}\n\n"
        f"{FENCE}json\n{{\"a\": 1, ...}}\n{FENCE}\n\n{FENCE}sql\nSELECT 1\n{FENCE}"
    )
    checks = code_checks(text)
    assert not marker.exists()
    assert [(c["i"], c["lang"], c["kind"]) for c in checks] == [
        (0, "python", "ok"),
        (1, "python", "error"),
        (2, "python", "excerpt"),
        (3, "json", "ok"),
        (4, "json", "error"),
        (5, "json", "excerpt"),
    ]
    assert checks[1]["line"] == 1 and checks[1]["n"] == 2 and checks[4]["line"] == 1
    assert code_checks(f"{FENCE}python\nx = (\n") == []  # an unclosed block gets no verdict


def test_answer_event_is_tidied_and_carries_code_checks():
    from fastapi.testclient import TestClient

    from tests.test_web import harness_app, one, post_chat

    app, _ = harness_app([f"Voici :{FENCE}python\ndef f(x):\n    return x * 2\n"])
    with TestClient(app) as client:
        events = post_chat(client, {"messages": [{"role": "user", "content": "Une fonction qui double"}]})
    answer = one(events, "answer")
    assert answer["content"] == f"Voici :\n{FENCE}python\ndef f(x):\n    return x * 2\n{FENCE}"
    assert answer["tidy"] == ["fence_glued", "fence_closed"]
    assert answer["code_checks"] == [{"i": 0, "n": 2, "lang": "python", "ok": True, "kind": "ok"}]
