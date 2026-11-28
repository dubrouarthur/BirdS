"""The canvas in code mode (birds/canvas/code.py, the code path of birds/web/canvas_web.py, the preview frame)."""

from __future__ import annotations

import json
import random

import pytest

from birds.canvas import code, dsl, intents, turn
from tests.test_canvas import _app, _canvas_body, _chat

HTML = '<!doctype html>\n<html><head><link rel="stylesheet" href="style.css"></head>\n<body><h1>Pain</h1>\n' \
       '<script src="script.js"></script></body></html>'  # fmt: skip
THREE = f"Voici :\n```html index.html\n{HTML}\n```\n```css style.css\nh1 {{ color: red }}\n```\n" \
        "```js script.js\ndocument.querySelector('h1').textContent = 'ok';\n```\nBonne dégustation."  # fmt: skip


# ------------------------------------------------------------------ reading the answer


def test_named_fences_are_files_and_the_prose_stays_around():
    found = code.parse_files(THREE)
    assert [f["name"] for f in found["files"]] == ["index.html", "style.css", "script.js"]
    assert [f["lang"] for f in found["files"]] == ["html", "css", "js"]
    assert found["open"] is None and found["before"] == "Voici :" and found["after"] == "Bonne dégustation."


@pytest.mark.parametrize(
    "answer",
    [
        "**index.html**\n```html\n<p>x</p>\n```\n**style.css**\n```css\np{}\n```",
        "### index.html\n```html\n<p>x</p>\n```\nFichier : style.css\n```css\np{}\n```",
        '```html title="index.html"\n<p>x</p>\n```\n```css:style.css\np{}\n```',
        "```html\n<!-- index.html -->\n<p>x</p>\n```\n```css\n/* style.css */\np{}\n```",
        "```html\n<p>x</p>\n```\n```css\np{}\n```",  # no names: by language
        "```index.html\n<p>x</p>\n```\n```style.css\np{}\n```",
    ],
)
def test_the_usual_ways_a_small_model_names_files(answer):
    found = code.parse_files(answer)
    assert [f["name"] for f in found["files"]] == ["index.html", "style.css"]
    assert [f["lang"] for f in found["files"]] == ["html", "css"]


def test_one_main_file_without_a_page_and_snippets_left_out():
    found = code.parse_files("```bash\npip install x\n```\n```python\nimport x\n\nprint(x.run())\n```")
    assert [(f["name"], f["lang"]) for f in found["files"]] == [("main.py", "python")]
    assert code.parse_files("pas de code") is None
    assert code.parse_files("<svg viewBox='0 0 1 1'></svg>")["files"][0]["name"] == "image.svg"
    assert code.parse_files("```\nflowchart TD\n A-->B\n```", "mermaid")["files"][0]["lang"] == "mermaid"


def test_a_file_still_being_written_is_open():
    found = code.parse_files(THREE[: THREE.index("textContent")])
    assert found["open"] == "script.js" and len(found["files"]) == 3
    found = code.parse_files(THREE[: THREE.index("h1 {")])
    assert found["open"] == "style.css"


def test_unsafe_or_odd_names_never_become_files():
    for bad in ["../etc/passwd", "/abs/x.js", "a b.js", "x.exe", ".env", "C:\\x\\y.html", "x" * 60 + ".js", ""]:
        name = code.safe_name(bad)
        assert name is None or ("/" not in name and "\\" not in name and name != ".env")
    assert code.safe_name("src/app.js") == "app.js"
    assert code.safe_name("`style.css`") == "style.css"


def test_parse_never_fails_on_random_text():
    rng = random.Random(7)
    alphabet = ["```", "```html", "```css x.css", "\n", "<p>", "**a.js**", "~~~", "`", "a", " ", "index.html"]
    for _ in range(400):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        found = code.parse_files(text)
        if found:
            assert 1 <= len(found["files"]) <= code.MAX_FILES
            assert all(code.safe_name(f["name"]) == f["name"] for f in found["files"])


# ------------------------------------------------------------------ the document


def test_validate_checks_every_file_and_keeps_the_old_shape_working():
    doc = {"v": 1, "kind": "code", "code": {"lang": "html", "text": "<p>x</p>"}}
    out = dsl.validate(doc)
    assert out["code"]["files"] == [{"name": "index.html", "lang": "html", "text": "<p>x</p>"}]
    good = {"kind": "code", "code": {"files": [{"name": "index.html", "text": "<p>"}, {"name": "a.js", "text": "1"}]}}
    out = dsl.validate(good)
    assert out["code"]["entry"] == "index.html" and out["code"]["files"][1]["lang"] == "js"
    for bad in (
        [{"name": "../x.js", "text": ""}],
        [{"name": "a.js", "text": ""}, {"name": "A.JS", "text": ""}],
        [{"name": "a.js", "text": 3}],
        [{"name": f"f{i}.js", "text": ""} for i in range(code.MAX_FILES + 1)],
        [{"name": "a.js", "text": "x" * (code.MAX_FILE + 1)}],
        [],
    ):
        with pytest.raises(dsl.Invalid):
            dsl.validate({"kind": "code", "code": {"files": bad}})


def test_merge_keeps_unwritten_files_and_refuses_a_file_not_shown():
    base = code.parse_files(THREE)["files"]
    new = code.parse_files("```css style.css\nh1 { color: green }\n```")["files"]
    merged, refused = code.merge(base, new)
    assert [f["name"] for f in merged] == ["index.html", "style.css", "script.js"] and not refused
    assert merged[1]["text"] == "h1 { color: green }" and merged[0] == base[0]
    # an unnamed fence replaces the only file of its language
    merged, _ = code.merge(base, code.parse_files("```js\nconsole.log(2)\n```")["files"])
    assert merged[2]["text"] == "console.log(2)" and len(merged) == 3
    # a file shown cut to the model is never rewritten from its cut copy
    merged, refused = code.merge(base, new, shown={"index.html"})
    assert refused == ["style.css"] and merged[1] == base[1]
    assert code.diff(base, merged) == []


def test_diff_counts_lines_per_file():
    a = [{"name": "index.html", "text": "a\nb\nc"}, {"name": "old.js", "text": "1\n2"}]
    b = [{"name": "index.html", "text": "a\nB\nc\nd"}, {"name": "new.js", "text": "z"}]
    assert code.diff(a, b) == [
        {"name": "index.html", "status": "changed", "plus": 2, "minus": 1},
        {"name": "new.js", "status": "added", "plus": 1, "minus": 0},
        {"name": "old.js", "status": "removed", "plus": 0, "minus": 2},
    ]  # same numbers as canvas-code.js diffFiles (tests/js/canvas-code.test.mjs)
    assert code.diff_text(code.diff(a, b)) == "index.html +2 −1, new.js +1 −0 (nouveau), old.js +0 −2 (retiré)"


def test_prompt_files_names_a_file_too_long_to_show():
    files = [{"name": "index.html", "lang": "html", "text": "x" * 100}, {"name": "big.js", "lang": "js",
                                                                          "text": "y\n" * 9000}]  # fmt: skip
    text, shown = code.prompt_files(files)
    assert shown == {"index.html"} and "```html index.html" in text and "big.js" in text and "yyy" not in text


def test_hints_for_the_next_step_chips():
    h = code.hints(code.parse_files(THREE)["files"])
    assert h == {"web": True, "lang": "html", "dark": False, "mobile": False, "js": True, "files": 3}
    css = "@media (prefers-color-scheme: dark) {}\n@media (max-width: 600px) {}"
    h = code.hints([{"name": "index.html", "lang": "html", "text": f"<style>{css}</style>"}])
    assert h["dark"] and h["mobile"] and not h["js"]


# ------------------------------------------------------------------ a turn


def test_create_then_patch_one_file(monkeypatch):
    from fastapi.testclient import TestClient

    app, llm = _app([THREE, "Voilà :\n```css style.css\nh1 { color: green }\n```"])
    with TestClient(app) as client:
        events = _chat(client, "Crée une landing page pour une boulangerie")
        streams = [e for e in events if e["type"] == "canvas" and e["phase"] == "stream"]
        final = [e for e in events if e["type"] == "canvas"][-1]
        assert [f["name"] for f in final["doc"]["code"]["files"]] == ["index.html", "style.css", "script.js"]
        assert "open" not in final["doc"]["code"] and "changes" not in final
        assert any((s["doc"]["code"].get("open")) for s in streams) or len(streams) >= 1
        answer = next(e for e in events if e["type"] == "answer")
        assert "3 fichiers (index.html, style.css, script.js)" in answer["content"]
        assert answer["canvas"]["kind"] == "code" and answer["canvas"]["hints"]["js"] is True
        spec = json.loads(llm.prompts[0])["messages"][-1]["content"]
        assert "```html index.html" in spec and "aucune ressource externe" in spec
        events = _chat(client, "mets le titre en vert", canvas=_canvas_body(final["doc"], final["aid"], 1))
    prompt = json.loads(llm.prompts[1])["messages"][-1]["content"]
    assert "```css style.css\nh1 { color: red }\n```" in prompt and "Ne réécris pas les autres" in prompt
    final = [e for e in events if e["type"] == "canvas"][-1]
    files = {f["name"]: f["text"] for f in final["doc"]["code"]["files"]}
    assert files["style.css"] == "h1 { color: green }" and "querySelector" in files["script.js"]
    assert final["changes"] == [{"name": "style.css", "status": "changed", "plus": 1, "minus": 1}]
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["content"].startswith("Nouvelle version du code : style.css +1 −1.")


def test_a_patch_that_changes_nothing_makes_no_version(monkeypatch):
    from fastapi.testclient import TestClient

    app, _ = _app([THREE, "```css style.css\nh1 { color: red }\n```"])
    with TestClient(app) as client:
        final = [e for e in _chat(client, "Crée une landing page pour un fleuriste") if e["type"] == "canvas"][-1]
        events = _chat(client, "corrige le bouton", canvas=_canvas_body(final["doc"], final["aid"], 1))
    assert not [e for e in events if e["type"] == "canvas" and e["phase"] == "final"]
    assert "resté identique" in next(e for e in events if e["type"] == "answer")["content"]


def test_fix_request_is_an_edit_and_its_quoted_error_does_not_switch_language():
    from birds.web.backends import run_lang

    ask = ("Corrige cette erreur de l'aperçu (script.js, ligne 5) : « Uncaught TypeError: Cannot read properties "
           "of null (reading 'addEventListener') »")  # fmt: skip
    assert intents.edit_ask(ask, "code")
    assert run_lang(ask, "fr") == "fr"
    assert run_lang("Please fix the error in the script and the page", "fr") == "en"


@pytest.mark.parametrize(
    ("words", "kind"),
    [
        ("Fais une todo list en HTML, CSS et JavaScript : ajouter, cocher, supprimer", "code"),
        ("Crée une petite application web de quiz", "code"),
        ("Code un convertisseur d'unités en JavaScript", "code"),
        ("Fais ma todo list pour demain", None),
        ("Rédige un mail en html pour mes clients", None),
        ("Comment faire une todo list en JS ?", None),
        ("fais un résumé en html de ce texte", None),
    ],
)
def test_code_intent_hints(words, kind):
    assert intents.ask(words) == kind


def test_memo_line_lists_the_files():
    doc = {"kind": "code", "title": "Pain", "code": code.make_code(code.parse_files(THREE)["files"])}
    assert turn.memo_line({"doc": doc, "version": 2}) == "[canvas code v2 « Pain »: index.html, style.css, script.js]"


# ------------------------------------------------------------------ the preview frame


def test_frame_policy_and_refusal_of_other_frames():
    from fastapi.testclient import TestClient

    from birds.web.canvas_web import FRAME_CSP, FRAME_SANDBOX

    app, _ = _app([])
    with TestClient(app) as client:
        r = client.get("/canvas/frame", headers={"Sec-Fetch-Dest": "iframe"})
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        for part in ("connect-src 'none'", "form-action 'none'", "frame-src 'none'", "worker-src 'none'",
                     "img-src data: blob:", "frame-ancestors 'self'", f"sandbox {FRAME_SANDBOX}"):  # fmt: skip
            assert part in csp
        assert "allow-same-origin" not in FRAME_CSP and "allow-popups" not in FRAME_CSP
        assert "allow-top-navigation" not in FRAME_CSP and "allow-modals" not in FRAME_CSP
        assert r.headers["x-dns-prefetch-control"] == "off"
        for path in ("/", "/api/health", "/api/img?u=x", "/static/app.js"):
            assert client.get(path, headers={"Sec-Fetch-Dest": "iframe"}).status_code == 403, path
        assert client.get("/", headers={"Sec-Fetch-Dest": "document"}).status_code == 200
        body = r.text
    # the shims: no WebRTC (CSP does not cover it), no beacon, modals shown inside the page, storage in memory
    for part in ("RTCPeerConnection", "sendBeacon", "window.alert=", "localStorage", "e.source !== parent"):
        assert part in body


def test_a_name_alone_on_the_first_line_is_the_name_not_code():
    # seen live (28/11/2026, 2 pages out of 6): ```js, then « script.js » on its own line, then the code; the line ran
    # as JavaScript (« script is not defined »)
    answer = "```html\nindex.html\n<!DOCTYPE html><p>x</p>\n```\n```js\nscript.js\nconst a = 1;\n```"
    found = code.parse_files(answer)
    assert [(f["name"], f["text"]) for f in found["files"]] == [
        ("index.html", "<!DOCTYPE html><p>x</p>"),
        ("script.js", "const a = 1;"),
    ]
    assert code.parse_files("```css style.css\nstyle.css\nh1{}\n```")["files"][0]["text"] == "h1{}"
    # a first line that is code stays code
    assert code.parse_files("```js\nconsole.log(1)\n```")["files"][0]["text"] == "console.log(1)"
