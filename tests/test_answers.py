"""Answer content (cluster C2 of the chat audit): tool labels, math, citations, copy, mail recipient, feedback."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from birds.harness.tools import TOOLS
from birds.web.server import STATIC_DIR

ROOT = Path(__file__).parent


def _keys(text: str, lang: str) -> set[str]:
    """The string keys of one language block of an i18n file (``fr: {`` … ``en: {`` …)."""
    fr, en = text.split("\n  en: {", 1)
    block = fr.split("fr: {", 1)[1] if lang == "fr" else en.split("\n};", 1)[0]
    return set(re.findall(r'^\s+"([a-z][\w.]*)":', block, re.M))


def _labels(lang: str) -> set[str]:
    keys = set()
    for name in ("i18n.js", "answers-i18n.js"):
        keys |= _keys((STATIC_DIR / name).read_text(), lang)
    return keys


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_every_tool_has_a_human_label(lang):
    """R10: the steps line never shows a tool id such as « lookup_entity »."""
    keys = _labels(lang)
    missing = sorted(name for name in TOOLS if f"tool.{name}" not in keys)
    assert not missing, missing
    assert "tool.unknown" in keys  # the fallback for a tool added without its label


def test_answer_strings_have_french_english_parity():
    text = (STATIC_DIR / "answers-i18n.js").read_text()
    fr, en = _keys(text, "fr"), _keys(text, "en")
    assert fr and fr == en, sorted(fr ^ en)
    base = _keys((STATIC_DIR / "i18n.js").read_text(), "fr")
    assert not fr & base, sorted(fr & base)  # added, never overriding a string of i18n.js


def test_tool_label_falls_back_to_a_word_never_the_id():
    core = (STATIC_DIR / "core.js").read_text()
    body = core.split("export const toolLabel", 1)[1].split("};", 1)[0]
    assert 't("tool.unknown")' in body and "String(tool)" not in body


def test_answers_node_unit_tests():
    """tests/js/answers.test.mjs: math, citations, rich copy, feedback (pure parts)."""
    if shutil.which("node") is None:
        pytest.skip("Node not installed")
    result = subprocess.run(
        ["node", "--test", str(ROOT / "js" / "answers.test.mjs")],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "CI": "1"},
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]


# ------------------------------------------------------------------ R20: the mail card never invents a recipient


def _ctx(**kw):
    from birds.harness.config import Config, Context

    return Context(config=Config(workspace=Path(".")), http=None, **kw)


def test_draft_email_drops_an_address_the_user_never_gave():
    from birds.harness.tools.actions import draft_email

    c = _ctx(request="Écris un mail à mon propriétaire pour signaler une fuite d'eau")
    r = draft_email({"to": ["proprietaire@email.com"], "subject": "Fuite", "body": "Bonjour"}, c)
    assert c.drafts[0]["to"] == [] and "to_hint" not in c.drafts[0]
    assert "proprietaire@email.com" in r and "never gave" in r and "To: (none)" in r


def test_draft_email_keeps_addresses_from_the_conversation_or_an_attached_document():
    from birds.harness.tools.actions import draft_email

    c = _ctx(request="Relance-le", said="Mon bailleur : Jean Roux <J.Roux@Agence.fr>\nRelance-le")
    draft_email({"to": ["j.roux@agence.fr"], "subject": "Relance", "body": "Bonjour"}, c)
    assert c.drafts[0]["to"] == ["j.roux@agence.fr"]
    c = _ctx(request="Réponds à l'expéditeur du document", fetched=[["file", "De : compta@client.fr"], ["web", "x"]])
    draft_email({"to": ["compta@client.fr", "boss@client.fr"], "subject": "Re", "body": "Bonjour"}, c)
    assert c.drafts[0]["to"] == ["compta@client.fr"]  # boss@ was written by nobody
    c = _ctx(request="Écris au service client de Calor", fetched=[["web", "Contact : support@calor.example"]])
    draft_email({"to": ["support@calor.example"], "subject": "Panne", "body": "Bonjour"}, c)
    assert c.drafts[0]["to"] == ["support@calor.example"]  # read on their contact page, not invented


def test_agent_hands_the_whole_conversation_to_the_tools():
    """ctx.said is filled from every user message, the earlier turns too (the address given two turns ago)."""
    from birds.harness import agent

    src = Path(agent.__file__).read_text()
    assert 'ctx.said = "\\n".join(' in src and 'm.get("role") == "user"' in src.split("ctx.said =", 1)[1][:200]


# ------------------------------------------------------------------ R7: the entity card's picture


def _png(w=4, h=4) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 200)).save(buf, "PNG")
    return buf.getvalue()


def _client(handler):
    import httpx

    return httpx.Client(transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False)


def test_image_fetch_retries_once_when_wikimedia_is_busy(monkeypatch):
    """upload.wikimedia.org answers 429 to bursts from shared egress IPs: the proxy gave 502 and a broken picture."""
    import httpx

    from birds.harness import Config, guard

    monkeypatch.setattr(guard, "resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(guard.time, "sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, content=b"slow down")
        return httpx.Response(200, headers={"content-type": "image/png"}, content=_png())

    cfg = Config(workspace=Path("."), audit_file=None, pin_dns=False)
    ctype, body = guard.fetch_image(_client(handler), cfg, "https://upload.wikimedia.org/a/330px-x.png")
    assert ctype == "image/png" and body.startswith(b"\x89PNG") and len(calls) == 2

    calls.clear()
    always = lambda request: calls.append(1) or httpx.Response(429)  # noqa: E731
    try:
        guard.fetch_image(_client(always), cfg, "https://upload.wikimedia.org/a/330px-x.png")
        raise AssertionError("a host that stays busy is an upstream error")
    except guard.FetchError as err:
        assert err.code == "upstream" and len(calls) == 2  # one retry, never a loop

    calls.clear()
    gone = lambda request: calls.append(1) or httpx.Response(404)  # noqa: E731
    try:
        guard.fetch_image(_client(gone), cfg, "https://upload.wikimedia.org/a/330px-x.png")
    except guard.FetchError:
        assert len(calls) == 1  # a missing picture is not retried
