"""Web chat: API contract, demo scenarios, confirm flow, file serving, security headers, Markdown safety."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from birds.web.backends import (
    ChatRequest,
    DemoBackend,
    RunContext,
    pick_scenario,
    sanitize_filename,
    step_event,
    usage_event,
)
from birds.web.server import CSP, STATIC_DIR, apply_carbon, create_app

ROOT = Path(__file__).resolve().parents[1]
USAGE_KEYS = {
    "type",
    "prompt_tokens",
    "completion_tokens",
    "seconds",
    "tool_calls",
    "bytes_fetched",
    "energy_wh",
    "energy_kind",
    "co2_g",
    "model",
    "thinking",
}
STEP_KEYS = {"type", "index", "tool", "arguments", "status", "summary", "seconds", "flags"}


@pytest.fixture
def app(tmp_path):
    return create_app(DemoBackend(delay=0), workspace=tmp_path / "ws", confirm_timeout=5)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def parse_sse(text: str) -> list[dict]:
    return [json.loads(frame[6:]) for frame in text.split("\n\n") if frame.startswith("data: ")]


def chat(client, text: str, lang: str = "fr", thinking: bool = False) -> list[dict]:
    body = {"messages": [{"role": "user", "content": text}], "thinking": thinking, "lang": lang}
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert events[-1] == {"type": "done"}
    assert [e["type"] for e in events].count("done") == 1
    return events


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def answer_when_pending(app, client, allow: bool) -> threading.Thread:
    """Answer the next confirmation from another thread, as the browser would."""

    def run() -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pending = app.state.confirms.pending()
            if pending:
                assert client.post("/api/confirm", json={"id": pending[0], "allow": allow}).status_code == 200
                return
            time.sleep(0.01)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


# ------------------------------------------------------------------ API contract


def test_health(client):
    data = client.get("/api/health").json()
    assert data["model"] == "bird-demo"
    assert data["backend"] == "demo"
    assert data["tools"] == ["web_search", "read_page", "draft_email", "make_slides"]
    assert data["thinking_default"] is False
    assert data["grid_intensity_g_per_kwh"] is None


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_plain_answer(client, lang):
    events = chat(client, "Bonjour" if lang == "fr" else "Hello", lang=lang)
    assert types(events) == ["answer", "usage", "done"]
    answer, usage = events[0], events[1]
    assert set(answer) == {"type", "content", "sources", "files", "draft_email"}
    assert "Bird" in answer["content"] and ("démo" in answer["content"] or "demo" in answer["content"])
    assert answer["sources"] == [] and answer["files"] == [] and answer["draft_email"] is None
    assert set(usage) == USAGE_KEYS
    assert usage["tool_calls"] == 0 and usage["bytes_fetched"] == 0
    assert usage["model"] == "bird-demo" and usage["thinking"] is False


def test_demo_never_invents_energy(client):
    for prompt in ["Bonjour", "Cherche des sources", "Prépare des diapositives"]:
        usage = next(e for e in chat(client, prompt) if e["type"] == "usage")
        assert usage["energy_wh"] is None and usage["energy_kind"] is None and usage["co2_g"] is None


def test_demo_is_deterministic(client):
    def strip(events):
        return [{k: v for k, v in e.items() if k != "seconds"} for e in events]

    assert strip(chat(client, "Rédige le compte rendu")) == strip(chat(client, "Rédige le compte rendu"))


def test_thinking_emits_reasoning_only_when_on(client):
    on = chat(client, "Bonjour", thinking=True)
    assert types(on) == ["reasoning", "answer", "usage", "done"]
    assert on[0]["content"]
    assert on[2]["thinking"] is True
    assert "reasoning" not in types(chat(client, "Bonjour", thinking=False))


def test_minutes_scenario_has_table(client):
    events = chat(client, "Rédige le compte rendu de notre réunion")
    assert types(events) == ["answer", "usage", "done"]
    assert "|---|---|---|" in events[0]["content"] and "## " in events[0]["content"]
    assert "Minutes" in chat(client, "Write the minutes of our meeting", lang="en")[0]["content"]


def test_search_scenario_steps_sources_citations(client):
    events = chat(client, "Cherche pourquoi les petits modèles consomment moins, cite tes sources")
    assert types(events) == ["step", "step", "step", "step", "answer", "usage", "done"]
    steps = events[:4]
    assert all(set(s) == STEP_KEYS for s in steps)
    assert [(s["index"], s["tool"], s["status"]) for s in steps] == [
        (0, "web_search", "running"),
        (0, "web_search", "done"),
        (1, "read_page", "running"),
        (1, "read_page", "done"),
    ]
    answer, usage = events[4], events[5]
    assert [s["n"] for s in answer["sources"]] == [1, 2]
    assert all(s["url"].startswith("https://example.org/demo/") and s["title"] for s in answer["sources"])
    assert "[1]" in answer["content"] and "[2]" in answer["content"]
    assert usage["tool_calls"] == 2 and usage["bytes_fetched"] == 47_500


def test_slides_scenario_writes_a_downloadable_file(app, client):
    events = chat(client, "Prépare une présentation de 5 diapositives")
    assert types(events) == ["step", "step", "answer", "usage", "done"]
    assert events[0]["tool"] == "make_slides" and events[1]["status"] == "done"
    (file,) = events[2]["files"]
    assert file["url"] == f"/files/{file['name']}"
    assert (app.state.workspace / file["name"]).is_file()
    response = client.get(file["url"])
    assert response.status_code == 200 and len(response.content) > 100
    assert "attachment" in response.headers["content-disposition"]


def test_email_scenario_flags_injection_and_confirm_allow(app, client):
    worker = answer_when_pending(app, client, allow=True)
    events = chat(client, "Prépare un mail de réponse à Camille")
    worker.join(5)
    assert types(events) == ["step", "step", "step", "confirm", "step", "answer", "usage", "done"]
    assert events[1]["tool"] == "read_page" and events[1]["flags"] == ["possible_injection"]
    confirm = events[3]
    assert set(confirm) == {"type", "id", "tool", "arguments", "reason"}
    assert confirm["tool"] == "draft_email" and confirm["reason"]
    assert set(confirm["arguments"]) == {"to", "subject", "body"}
    assert events[4]["tool"] == "draft_email" and events[4]["status"] == "done"
    assert events[5]["draft_email"] == confirm["arguments"]
    assert app.state.confirms.pending() == []


def test_email_scenario_confirm_deny(app, client):
    worker = answer_when_pending(app, client, allow=False)
    events = chat(client, "Draft a reply email to Camille", lang="en")
    worker.join(5)
    step = [e for e in events if e["type"] == "step"][-1]
    assert step["tool"] == "draft_email" and step["status"] == "denied"
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["draft_email"] is None


def test_confirm_times_out_as_denied(tmp_path):
    app = create_app(DemoBackend(delay=0), workspace=tmp_path, confirm_timeout=0.15)
    with TestClient(app) as client:
        events = chat(client, "Prépare un mail")
    assert [e for e in events if e["type"] == "step"][-1]["status"] == "denied"


def test_confirm_unknown_id(client):
    assert client.post("/api/confirm", json={"id": "nope", "allow": True}).status_code == 404
    assert client.post("/api/confirm", json={"id": "nope"}).status_code == 422


def test_error_scenario(client):
    events = chat(client, "Simule une erreur")
    assert types(events) == ["step", "step", "error", "done"]
    assert "démo" in events[2]["message"]


def test_hostile_markdown_is_passed_as_text_not_altered(client):
    answer = chat(client, "test xss")[0]
    assert "<img src=x onerror=" in answer["content"] and "javascript:alert(1)" in answer["content"]


def test_chat_validation(client):
    bad = [
        {"messages": [], "thinking": False, "lang": "fr"},
        {"messages": [{"role": "system", "content": "x"}]},
        {"messages": [{"role": "user", "content": "x"}], "lang": "de"},
        {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]},
    ]
    for body in bad:
        assert client.post("/api/chat", json=body).status_code == 422


def test_scenario_routing():
    assert pick_scenario("Bonjour") == "plain"
    assert pick_scenario("Draft a reply email") == "email"
    assert pick_scenario("Prepare a 5-slide deck") == "slides"
    assert pick_scenario("Search why small models use less energy") == "search"
    assert pick_scenario("Write the minutes of our project meeting") == "minutes"
    assert pick_scenario("simulate an error") == "error"


# ------------------------------------------------------------------ energy and CO2


class EnergyBackend:
    kind, model, tools = "completions", "fake-4b", ["web_search"]

    def __init__(self, energy, kind):
        self.energy, self.energy_kind = energy, kind

    def run(self, request: ChatRequest, ctx: RunContext) -> None:
        ctx.emit(step_event(0, "web_search", {"query": "q"}, "done", "ok", 0.1))
        ctx.emit({"type": "answer", "content": "ok", "sources": [], "files": [], "draft_email": None})
        ctx.emit(
            usage_event(
                model=self.model,
                thinking=False,
                prompt_tokens=10,
                completion_tokens=2,
                energy_wh=self.energy,
                energy_kind=self.energy_kind,
            )
        )


@pytest.mark.parametrize(
    ("energy", "kind", "grid", "expected"),
    [
        (2.0, "measured", 50.0, (2.0, "measured", 0.1)),
        (2.0, "estimated", 400.0, (2.0, "estimated", 0.8)),
        (2.0, "measured", None, (2.0, "measured", None)),  # no configured intensity -> no CO2
        (None, None, 50.0, (None, None, None)),  # no energy -> nothing derived
        (2.0, "guessed", 50.0, (None, None, None)),  # unknown provenance is not shown
    ],
)
def test_co2_only_from_reported_energy_and_configured_grid(tmp_path, energy, kind, grid, expected):
    app = create_app(EnergyBackend(energy, kind), workspace=tmp_path, grid_intensity=grid)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["grid_intensity_g_per_kwh"] == grid
        usage = next(e for e in chat(client, "x") if e["type"] == "usage")
    assert (usage["energy_wh"], usage["energy_kind"], usage["co2_g"]) == expected


def test_apply_carbon_ignores_other_events():
    event = {"type": "answer", "content": "x"}
    assert apply_carbon(dict(event), 50.0) == event


def test_backend_exception_becomes_error_event(tmp_path):
    class Broken:
        kind, model, tools = "completions", "m", []

        def run(self, request, ctx):
            raise ValueError("boom")

    with TestClient(create_app(Broken(), workspace=tmp_path)) as client:
        events = chat(client, "x")
    assert events == [{"type": "error", "message": "boom"}, {"type": "done"}]


# ------------------------------------------------------------------ files


def test_files_path_traversal_rejected(app, client, tmp_path):
    (tmp_path / "secret.txt").write_text("secret")
    workspace = app.state.workspace
    (workspace / "ok.txt").write_text("fine")
    (workspace / ".hidden").write_text("hidden")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "inner.txt").write_text("inner")
    assert client.get("/files/ok.txt").text == "fine"
    for name in [
        "../secret.txt",
        "..%2Fsecret.txt",
        "%2e%2e%2fsecret.txt",
        "..%5Csecret.txt",
        "%2e%2e",
        "..",
        ".hidden",
        "sub",
        "sub/inner.txt",
        "sub%2Finner.txt",
        "ok.txt%00.png",
        "missing.txt",
        "/etc/passwd",
        "%2Fetc%2Fpasswd",
    ]:
        response = client.get(f"/files/{name}")
        assert response.status_code in (404, 405), name
        assert "secret" not in response.text and "root:" not in response.text


def test_files_symlink_escape_rejected(app, client, tmp_path):
    (tmp_path / "secret.txt").write_text("secret")
    (app.state.workspace / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert client.get("/files/link.txt").status_code == 404


def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\x\\Compte rendu final.docx") == "Compte-rendu-final.docx"
    assert sanitize_filename("...") == "fichier"
    assert sanitize_filename("") == "fichier"
    assert sanitize_filename("a..b.pptx") == "a.b.pptx"
    assert "/" not in sanitize_filename("x/y<z>.md")


# ------------------------------------------------------------------ security headers and static frontend


def test_csp_and_security_headers_everywhere(client):
    for path in ["/", "/api/health", "/static/app.js", "/static/app.css", "/nope"]:
        response = client.get(path)
        assert response.headers["content-security-policy"] == CSP, path
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in CSP and "script-src 'self'" in CSP and "style-src 'self'" in CSP
    assert "unsafe" not in CSP and "http" not in CSP and "*" not in CSP and "data:" not in CSP


def test_index_has_no_inline_code_and_no_external_origin(client):
    response = client.get("/")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    html = response.text
    assert 'lang="fr"' in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "inline script"
    assert "<style" not in html and not re.search(r"\sstyle=", html), "inline style"
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler"
    assert not re.search(r"https?://|//[a-z]", html), "external origin in index.html"
    css = (STATIC_DIR / "app.css").read_text()
    assert "url(" not in css and "@import" not in css and "@font-face" not in css
    for name in ["app.js", "markdown.js", "i18n.js", "theme.js", "bird.svg"]:
        assert client.get(f"/static/{name}").status_code == 200
    js = "".join((STATIC_DIR / n).read_text() for n in ["app.js", "markdown.js", "theme.js"])
    assert "eval(" not in js and "new Function" not in js and "document.write" not in js


def test_i18n_dictionaries_have_the_same_keys():
    text = (STATIC_DIR / "i18n.js").read_text()
    fr_block, en_block = text.split("\n  en: {", 1)
    key = re.compile(r'^\s+"?([\w.]+)"?:', re.M)
    fr, en = set(key.findall(fr_block.split("fr: {", 1)[1])), set(key.findall(en_block.split("\n};", 1)[0]))
    assert fr and fr == en, fr ^ en


# ------------------------------------------------------------------ Markdown renderer (run with Node when available)

MD_CASES = {
    "img": "<img src=x onerror=alert(1)>",
    "script": "<script>alert(1)</script>",
    "js_link": "[x](javascript:alert(1))",
    "js_link_case": "[x](JaVaScRiPt:alert(1))",
    "data_link": "[x](data:text/html,<script>alert(1)</script>)",
    "attr_break": '[x](https://e.org/"onmouseover="alert(1))',
    "bold_attr": '**a"onmouseover="alert(1)**',
    "code": "`<b>x</b>` and ```\n<script>\n```",
    "ok_link": "[ok](https://example.org/a?b=1&c=2)",
    "cite": "fact [1] and [7]",
    "table": "| a | b |\n|---|---|\n| <i>1</i> | **2** |",
    "heading": "# <u>t</u>\n\n- one\n- two\n\n1. x\n2. y",
    "nul": "a\u0000<b>0\u0000",
}
MD_SCRIPT = """
import { renderMarkdown } from %s;
const cases = JSON.parse(process.argv[1]);
const out = {};
for (const [k, v] of Object.entries(cases)) out[k] = renderMarkdown(v, { cites: [1], anchor: "src-t" });
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node not installed (renderer is also covered by Playwright runs)"
)
def test_markdown_renderer_is_safe():
    script = MD_SCRIPT % json.dumps((STATIC_DIR / "markdown.js").as_uri())
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(MD_CASES)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr[-500:]
    out = json.loads(result.stdout)
    allowed = re.compile(
        r"</?(?:p|br|strong|em|code|pre|ul|ol|li|h[2-5]|hr|blockquote|table|thead|tbody|tr|th|td|sup|div|a)(?:\s[^<>]*)?>"
    )
    for name, html in out.items():
        assert "\u0000" not in html, name
        leftover = allowed.sub("", html)
        assert "<" not in leftover and ">" not in leftover, (name, html)  # every tag is one the renderer wrote
        for tag in re.findall(r"<[a-z][^>]*>", html):
            assert not re.search(r"\son\w+=", tag), (name, tag)  # no event-handler attribute inside any tag
        for href in re.findall(r'href="([^"]*)"', html):
            assert href.startswith(("https://", "http://", "#src-t-")), (name, href)
    assert "<a " not in out["js_link"] and "<a " not in out["js_link_case"] and "<a " not in out["data_link"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in out["img"]
    assert "[x](javascript:alert(1))" in out["js_link"]  # shown as inert text
    assert 'href="https://example.org/a?b=1&amp;c=2"' in out["ok_link"]
    assert 'rel="noopener noreferrer"' in out["ok_link"] and 'target="_blank"' in out["ok_link"]
    assert 'href="#src-t-1"' in out["cite"] and "[7]" in out["cite"]
    assert "<table>" in out["table"] and "&lt;i&gt;1&lt;/i&gt;" in out["table"] and "<strong>2</strong>" in out["table"]
    assert "<h3>" in out["heading"] and "<ul><li>one</li><li>two</li></ul>" in out["heading"]
    assert "<ol><li>x</li><li>y</li></ol>" in out["heading"]
    assert "<code>&lt;b&gt;x&lt;/b&gt;</code>" in out["code"]


# ------------------------------------------------------------------ CLI


def test_serve_cli_arguments():
    import importlib.util

    spec = importlib.util.spec_from_file_location("bird_serve", ROOT / "scripts" / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    args = serve.parse_args(["--demo", "--port", "9001", "--grid-intensity", "56"])
    assert args.demo and args.port == 9001 and args.grid_intensity == 56
    assert isinstance(serve.build_backend(args), DemoBackend)
    for bad in [
        [],
        ["--demo", "--local", "m"],
        ["--base-url", "http://x/v1"],
        ["--demo", "--adapter", "d"],
        ["--demo", "--grid-intensity", "-1"],
    ]:
        with pytest.raises(SystemExit):
            serve.parse_args(bad)
