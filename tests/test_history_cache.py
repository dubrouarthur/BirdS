"""History and prefix-cache invariants (docs/HISTORY_SPEC.md § 7.1). Offline."""

import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from birds.harness import Agent, CompletionsClient, Config, FakeClient
from birds.harness.template import TEMPLATE_PATH, TemplateTokenizer
from birds.render import prompt as render_prompt
from birds.tools import BIRD_TOOLS
from birds.web.backends import (
    IMAGE_TEXT_CHARS,
    HarnessBackend,
    cache_salt,
    log_id,
    prepare_turn,
    run_lang,
)
from birds.web.server import create_app, user_sent_extra
from birds.web.settings import Settings

TOK = TemplateTokenizer()
CID = "0b6f2a9e-3c41-4d8a-9b7e-2f1c0d9e8a7b"


def render(system, kept, user_sent):
    msgs = [{"role": "system", "content": system}, *kept, {"role": "user", "content": user_sent}]
    return render_prompt(TOK, msgs, BIRD_TOOLS, False)


def simulate(seed, turns, budget=2500):
    """A browser + server conversation: returns the rendered prompt of each turn and the cut stats."""
    rng = random.Random(seed)
    messages, prompts, stats = [], [], []
    for _ in range(turns):
        raw = rng.choice(["ok", "oui", "Et la deuxième source ?", "Résume", "x" * rng.randint(10, 3000)])
        images = [("img.jpg", "T" * rng.randint(0, 4000))] if rng.random() < 0.15 else []
        attach = ["notes.txt"] if rng.random() < 0.2 else []
        system, kept, user_sent, st = prepare_turn(
            [*messages, {"role": "user", "content": raw}], "fr", "fr", attach, images, budget, 3168
        )
        prompts.append(render(system, kept, user_sent))
        stats.append(st)
        messages.append({"role": "user", "content": user_sent})  # the client stores the 'user' event
        answer = {"role": "assistant", "content": "R" * rng.randint(20, 1500)}
        if rng.random() < 0.4:
            answer["memo"] = "[Mémo de ce tour — fichiers créés : f.docx]"
        if rng.random() < 0.1:
            answer["interrupted"] = True
        messages.append(answer)
    simulate.messages = messages
    return prompts, stats


@pytest.mark.parametrize("seed", range(40))
def test_u1_prefix_invariant(seed):
    prompts, stats = simulate(seed, random.Random(seed).randint(2, 24))
    for k in range(1, len(prompts)):
        if stats[k]["cut_moved"]:
            continue
        prev = prompts[k - 1]
        stable = prev[: prev.rindex("<|im_start|>user\n")]  # everything before turn k-1's own user message
        assert prompts[k].startswith(stable), f"turn {k}"


def test_u2_cut_monotone_and_bounded():
    from birds.harness import history

    _, stats = simulate(3, 40, budget=2000)
    drops = [s["dropped_turns"] for s in stats]
    assert drops == sorted(drops)
    assert all(s["history_tokens_est"] <= 2000 or s["turns"] - s["dropped_turns"] <= 1 for s in stats)
    total = sum(history.tokens(m["content"]) for m in simulate.messages)
    assert sum(s["cut_moved"] for s in stats) <= -(-total // 1000)  # at most ceil(total / LOW) moves


def test_u3_determinism_across_processes():
    code = (
        "import hashlib,json;from birds.web.backends import prepare_turn;"
        "m=[{'role':'user','content':'a'},{'role':'assistant','content':'b','memo':'[M]'},{'role':'user','content':'c'}];"
        "s,k,u,_=prepare_turn(m,'fr','fr',['n.txt'],[('i.jpg','txt')],6000,3168);"
        "print(hashlib.sha256(json.dumps([s,k,u]).encode()).hexdigest())"
    )
    root = Path(__file__).resolve().parents[1]
    outs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root).stdout for _ in range(2)
    }
    assert len(outs) == 1 and len(outs.pop().strip()) == 64


class _Tok:
    def apply_chat_template(self, messages, tools=None, **_):
        return json.dumps({"tools": [t["function"]["name"] for t in tools or []], "messages": messages})


def _sse(r):
    return [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]


def test_u4_tools_block_identical_with_and_without_attachments():
    llm = FakeClient(["a", "b"])
    app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(llm, _Tok()))
    with TestClient(app) as c:
        c.post("/api/chat", json={"messages": [{"role": "user", "content": "Bonjour"}]})
        att = [{"name": "n.txt", "content": "x"}]
        c.post("/api/chat", json={"messages": [{"role": "user", "content": "Bonjour"}], "attachments": att})
    plain, attached = json.loads(llm.prompts[0])["tools"], json.loads(llm.prompts[1])["tools"]
    # read_file is always offered (it never appears or disappears with an attachment); the only change allowed is the
    # routing rule that withdraws the web tools from a request about an attachment that names no need for the web
    assert "read_file" in plain and "read_file" in attached
    assert [t for t in plain if t not in ("web_search", "read_page")] == attached


def test_u5_languages():
    assert run_lang("ok", "fr") == "fr" and run_lang("oui", "en") == "en" and run_lang("https://x.y", "en") == "en"
    english = "Dear team, please find the report attached. It is the final version and we can discuss it."
    assert run_lang(english, "fr") == "en"  # clearly English: this request in English
    assert run_lang("Can you please summarise this for the team and send it to me", "fr") == "en"
    assert run_lang("to", "fr") == "fr"  # one weak marker is not enough
    llm = FakeClient(["a"])
    app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(llm, _Tok()))
    with TestClient(app) as c:  # the persona follows conv_lang, not the UI language of this request
        c.post("/api/chat", json={"messages": [{"role": "user", "content": "ok"}], "lang": "en", "conv_lang": "fr"})
    assert json.loads(llm.prompts[0])["messages"][0]["content"].startswith("Tu es Bird")


def test_u7_server_budget_from_env():
    from birds.web.server import build_server_backend

    s = Settings.from_env(
        {
            "BIRD_BASE_URL": "https://x.endpoints.huggingface.cloud",
            "BIRD_HISTORY_TOKENS": "2000",
            "BIRD_HISTORY_MSG_TOKENS": "1056",
        }
    )
    b = build_server_backend(s)
    assert (b.history_tokens, b.msg_cap_tokens) == (2000, 1056)
    with TestClient(create_app(s, server_backend=b)) as c:
        h = c.get("/api/health").json()
    assert (h["history_tokens"], h["history_msg_tokens"]) == (2000, 1056)


def test_u8_user_event_and_worst_case_extra():
    llm = FakeClient(["Réponse."])
    app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(llm, _Tok()))
    att = [{"name": "notes.txt", "content": "x"}]
    with TestClient(app) as c:
        events = _sse(c.post("/api/chat", json={"messages": [{"role": "user", "content": "Lis"}], "attachments": att}))
    kinds = [e["type"] for e in events]
    assert kinds.index("user") < kinds.index("answer")
    user = events[kinds.index("user")]["content"]
    assert user == json.loads(llm.prompts[0])["messages"][-1]["content"] == "Lis\n\n[Fichier joint : notes.txt]"
    names = [("n" * 160, "T" * (IMAGE_TEXT_CHARS + 500))] * 3
    _, _, sent, _ = prepare_turn([{"role": "user", "content": ""}], "fr", "fr", ["a" * 160] * 4, names, 6000, 3168)
    assert len(sent) <= user_sent_extra(Settings()) and sent.count("T" * IMAGE_TEXT_CHARS) == 3
    assert "T" * (IMAGE_TEXT_CHARS + 1) not in sent and "[Donnée externe" in sent


def test_u9_digest_binds_memo_interrupted_cid_and_lang():
    from birds.web import tokens

    def digest(**kw):
        m = {"role": "assistant", "content": "x", "memo": None, "interrupted": False, **kw.pop("m", {})}
        return tokens.digest({"m": [m], "a": [], "cid": kw.get("cid"), "lang": kw.get("lang")})

    base = digest()
    assert (
        len({base, digest(m={"memo": "[M]"}), digest(m={"interrupted": True}), digest(cid=CID), digest(lang="en")}) == 5
    )


def test_u11_template_pin():
    sha = hashlib.sha256(TEMPLATE_PATH.read_bytes()).hexdigest()
    assert sha == "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715"


@pytest.mark.parametrize("stream", [True, False])
def test_u13_finish_reason_and_cached_tokens(stream, tmp_path):
    def handler(req):
        if stream:
            body = (
                'data: {"choices":[{"text":"Une réponse coupée"}]}\n\n'
                'data: {"choices":[{"text":"","finish_reason":"length"}]}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,'
                '"prompt_tokens_details":{"cached_tokens":528}}}\n\ndata: [DONE]\n\n'
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={
                "choices": [{"text": "Une réponse coupée", "finish_reason": "length"}],
                "usage": {"prompt_tokens": 1},
            },
        )

    llm = CompletionsClient("http://llm.test", "bird", transport=httpx.MockTransport(handler), stream=stream)
    out = llm.generate("p", 5, ["<|im_end|>"])
    assert out["finish_reason"] == "length" and out["cached_tokens"] == (528 if stream else None)
    run = Agent(llm, TOK, Config(workspace=tmp_path, search_default="none")).run("Bonjour")
    assert run.stop_reason == "length" and run.answer == "Une réponse coupée"


def test_u14_cache_salt():
    assert cache_salt(CID) == cache_salt(CID) != cache_salt(CID.replace("0b6f", "1b6f"))
    assert cache_salt(None) != cache_salt(None) and cache_salt(CID) != log_id(CID) and len(log_id(CID)) == 16
    seen = []

    class Spy(FakeClient):
        def generate(self, prompt, max_tokens, stop, **kw):
            seen.append((kw.get("extra") or {}).get("cache_salt"))
            return super().generate(prompt, max_tokens, stop, **kw)

    app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(Spy(["a"]), _Tok()))
    with TestClient(app) as c:
        c.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}], "conversation_id": CID})
        bad = c.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}], "conversation_id": "123"})
    assert seen == [cache_salt(CID)] and bad.status_code == 422
def test_system_message_ends_with_the_date_of_the_day():
    from datetime import datetime

    msgs = [{"role": "user", "content": "Quel jour sommes-nous ?"}]
    morning = lambda: datetime(2026, 11, 22, 8, 1)  # noqa: E731
    evening = lambda: datetime(2026, 11, 22, 23, 59)  # noqa: E731
    fr, *_ = prepare_turn(msgs, "fr", "fr", [], [], 6000, 3168, clock=morning)
    en, *_ = prepare_turn(msgs, "en", "en", [], [], 6000, 3168, clock=morning)
    assert fr.endswith("Date du jour : dimanche 22 novembre 2026 (Europe/Paris).")
    assert en.endswith("Today: Sunday 22 November 2026 (Europe/Paris).")
    again, *_ = prepare_turn(msgs, "fr", "fr", [], [], 6000, 3168, clock=evening)
    assert again == fr  # same day, byte-identical: the cached prompt prefix survives
