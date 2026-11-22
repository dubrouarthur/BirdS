"""Model endpoint client and user-supplied endpoints: engine shapes, wake-up, SSRF guard, connection test.

The stream fixtures reproduce the SHAPES of each engine's OpenAI-compatible ``/v1/completions`` answers (vLLM,
TGI, llama.cpp). They were written from the engines' documented formats, not captured from live servers: a real
endpoint is still needed to confirm them (see docs/DEPLOY_VERCEL.md, "ce qui reste à vérifier").
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from birds.harness import guard
from birds.harness.llm import STOP, CompletionsClient, EndpointError, normalize_base_url
from birds.web import endpoint as ep
from birds.web.server import create_app
from birds.web.settings import DEFAULT_ENDPOINT_HOSTS, Settings

HOST = "abc123.eu-west-1.aws.endpoints.huggingface.cloud"
URL = f"https://{HOST}"
TOKEN = "hf_" + "Z9y8X7w6V5u4T3s2R1q0" * 2
PUBLIC_IP = "93.184.216.34"


def sse(*chunks) -> bytes:
    return ("".join(f"data: {c if isinstance(c, str) else json.dumps(c)}\n\n" for c in chunks)).encode()


def choice(text, finish=None, **extra):
    return {
        "id": "cmpl-1",
        "object": "text_completion",
        "created": 1,
        "model": "bird",
        "choices": [{"index": 0, "text": text, "logprobs": None, "finish_reason": finish}],
        **extra,
    }


VLLM = sse(
    choice("Bon", usage=None),
    choice("jour", usage=None),
    choice(" !", "stop", usage=None),
    {
        "id": "cmpl-1",
        "object": "text_completion",
        "created": 1,
        "model": "bird",
        "choices": [],
        "usage": {"prompt_tokens": 12, "total_tokens": 15, "completion_tokens": 3},
    },
    "[DONE]",
)
TGI = sse(  # no usage in the stream
    {
        "id": "",
        "object": "text_completion",
        "created": 1,
        "model": "bird",
        "system_fingerprint": "3.3.4-sha",
        "choices": [{"index": 0, "text": "Bon", "logprobs": None, "finish_reason": ""}],
    },
    {
        "id": "",
        "object": "text_completion",
        "created": 1,
        "model": "bird",
        "system_fingerprint": "3.3.4-sha",
        "choices": [{"index": 0, "text": "jour !", "logprobs": None, "finish_reason": "eos_token"}],
    },
    "[DONE]",
)
LLAMACPP = sse(  # usage and timings arrive with the last text chunk
    choice("Bon"),
    choice("jour !"),
    choice(
        "",
        "stop",
        usage={"completion_tokens": 3, "prompt_tokens": 12, "total_tokens": 15},
        timings={"prompt_n": 12, "predicted_n": 3, "predicted_ms": 41.0},
    ),
    "[DONE]",
)
LLAMACPP_NATIVE = sse(  # llama.cpp's own /completion shape, should someone point the client at it
    {"content": "Bon", "stop": False},
    {"content": "jour !", "stop": False},
    {"content": "", "stop": True, "tokens_predicted": 3, "tokens_evaluated": 12},
)
CHAT_STYLE = sse(  # a proxy that answers with chat-completion deltas
    {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "Bon"}}]},
    {
        "choices": [{"index": 0, "delta": {"content": "jour !"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    },
    "[DONE]",
)


def client_for(handler, **kw) -> CompletionsClient:
    kw.setdefault("sleep", lambda s: None)
    return CompletionsClient(
        kw.pop("base", URL), "bird", kw.pop("key", TOKEN), transport=httpx.MockTransport(handler), **kw
    )


def stream_response(body: bytes) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


@pytest.mark.parametrize(
    ("name", "body", "usage"),
    [
        ("vllm", VLLM, (12, 3)),
        ("tgi", TGI, (None, None)),
        ("llama.cpp", LLAMACPP, (12, 3)),
        ("llama.cpp native", LLAMACPP_NATIVE, (12, 3)),
        ("chat-style deltas", CHAT_STYLE, (12, 3)),
    ],
)
def test_stream_shapes_of_each_engine(name, body, usage):
    seen, pieces = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization"), json.loads(request.content)))
        return stream_response(body)

    out = client_for(handler).generate("Bonjour ?", 64, STOP, on_token=pieces.append)
    assert out["text"] == "Bonjour !" == "".join(pieces), name
    assert (out["prompt_tokens"], out["completion_tokens"]) == usage, name
    assert out["prompt_chars"] == 9 and out["completion_chars"] == 9
    url, auth, sent = seen[0]
    assert url == f"{URL}/v1/completions" and auth == f"Bearer {TOKEN}"
    assert (
        sent["prompt"] == "Bonjour ?" and sent["max_tokens"] == 64 and sent["stream"] is True and sent["stop"] == STOP
    )
    assert sent["model"] == "bird" and sent["stream_options"] == {"include_usage": True}


def test_plain_json_answer_when_the_server_does_not_stream():
    body = {
        "choices": [{"text": "Bonjour !<|im_end|>ignored", "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }
    out = client_for(lambda r: httpx.Response(200, json=body)).generate("x", 8, STOP)
    assert (out["text"], out["prompt_tokens"], out["completion_tokens"]) == ("Bonjour !", 5, 3)


def test_stop_sequence_split_across_chunks_is_never_forwarded():
    body = sse(choice("Fin.<|im"), choice("_end|>secret tail"), choice(" more"), "[DONE]")
    pieces = []
    out = client_for(lambda r: stream_response(body)).generate("x", 8, STOP, on_token=pieces.append)
    assert out["text"] == "Fin." == "".join(pieces)


def test_falls_back_when_the_engine_refuses_stream_options_or_many_stops():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "stream_options" in body or len(body["stop"]) > 4:  # TGI: "`stop` supports up to 4 stop sequences"
            return httpx.Response(
                422,
                json={
                    "error": "Input validation error: `stop` supports up to 4 stop sequences. Given: 6",
                    "error_type": "validation",
                },
            )
        return stream_response(TGI)

    out = client_for(handler).generate("x", 8, ["a", "b", "c", "d", "e", "f"])
    assert out["text"] == "Bonjour !" and len(bodies) == 2
    assert "stream_options" not in bodies[1] and bodies[1]["stop"] == ["a", "b", "c", "d"]
    with pytest.raises(EndpointError) as err:  # still refused: reported, not retried forever
        client_for(lambda r: httpx.Response(400, json={"error": "unknown model"})).generate("x", 8, STOP)
    assert err.value.kind == "bad_request" and "unknown model" in str(err.value)


def test_waking_endpoint_is_retried_with_backoff_then_answers():
    calls, waits, statuses = [], [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return (
            httpx.Response(503, text="") if len(calls) < 4 else stream_response(VLLM)
        )  # the HF proxy answers 503 while scaling up

    out = client_for(handler, sleep=waits.append).generate(
        "x", 8, STOP, on_status=lambda s, info: statuses.append((s, info["attempt"]))
    )
    assert out["text"] == "Bonjour !" and out["wake_attempts"] == 3
    assert waits == [3.0, 5.0, 8.0] and statuses == [("waking", 1), ("waking", 2), ("waking", 3)]


def test_waking_gives_up_cleanly_at_the_deadline():
    import time

    waits = []
    client = client_for(lambda r: httpx.Response(503), sleep=waits.append)
    with pytest.raises(EndpointError) as err:
        client.generate("x", 8, STOP, deadline=time.monotonic() + 9)  # room for one 3 s wait, not for the next 5 s one
    assert err.value.kind == "waking" and err.value.status == 503 and waits == [3.0]
    with pytest.raises(EndpointError) as err:
        client.generate("x", 8, STOP, deadline=time.monotonic() - 1)
    assert err.value.kind == "timeout"


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (404, "wrong_route"),
        (405, "wrong_route"),
        (302, "wrong_route"),
        (500, "server"),
        (429, "server"),
    ],
)
def test_http_errors_map_to_stable_kinds_without_leaking_the_token(status, kind):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, headers={"location": "http://169.254.169.254/"}, text=f"denied for Bearer {TOKEN}"
        )

    with pytest.raises(EndpointError) as err:
        client_for(handler).generate("x", 8, STOP)
    assert err.value.kind == kind and err.value.status == status and TOKEN not in str(err.value)


def test_network_failures_are_reported_as_unreachable_or_timeout():
    def refuse(request):
        raise httpx.ConnectError("nope")

    def slow(request):
        raise httpx.ReadTimeout("slow")

    for handler, kind in ((refuse, "unreachable"), (slow, "timeout")):
        with pytest.raises(EndpointError) as err:
            client_for(handler).generate("x", 8, STOP)
        assert err.value.kind == kind


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (URL, f"{URL}/v1"),
        (URL + "/", f"{URL}/v1"),
        (URL + "/v1", f"{URL}/v1"),
        (URL + "/v1/", f"{URL}/v1"),
        (URL + "/v1/completions", f"{URL}/v1"),
        (URL + "/v1/chat/completions", f"{URL}/v1"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080/v1"),
        ("  http://localhost:8080/v1  ", "http://localhost:8080/v1"),
    ],
)
def test_base_url_is_normalised(given, expected):
    assert normalize_base_url(given) == expected


# ------------------------------------------------------------------ SSRF guard for user-supplied endpoints


@pytest.fixture
def dns(monkeypatch):
    table = {
        HOST: [PUBLIC_IP],
        "private.endpoints.huggingface.cloud": ["10.0.0.5"],
        "mixed.endpoints.huggingface.cloud": [PUBLIC_IP, "192.168.1.9"],
        "models.example.org": [PUBLIC_IP],
    }

    def fake(host):
        if host not in table:
            raise OSError("unknown host")
        return table[host]

    monkeypatch.setattr(guard, "resolve", fake)
    return table


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("", "invalid_url"),
        ("http://" + HOST, "https_only"),
        ("ftp://" + HOST, "https_only"),
        ("https://" + HOST + ":8443", "port"),
        ("https://user:pw@" + HOST, "invalid_url"),
        ("https://" + HOST + "/v1?x=1", "invalid_url"),
        ("https://" + HOST + "/v1#frag", "invalid_url"),
        ("https://" + HOST + "/a b", "invalid_url"),
        ("https://example.org", "host_not_allowed"),
        ("https://endpoints.huggingface.cloud", "host_not_allowed"),  # the bare suffix is not an endpoint
        ("https://endpoints.huggingface.cloud.evil.test", "host_not_allowed"),
        ("https://evil.test/.endpoints.huggingface.cloud", "host_not_allowed"),
        ("https://127.0.0.1", "host_not_allowed"),
        ("https://[::1]", "host_not_allowed"),
        ("https://169.254.169.254", "host_not_allowed"),
        ("https://localhost", "host_not_allowed"),
        ("https://private.endpoints.huggingface.cloud", "address"),  # allowed name, private address
        ("https://mixed.endpoints.huggingface.cloud", "address"),  # one private address among several is enough
        ("https://nxdomain.endpoints.huggingface.cloud", "address"),
        ("https://" + "a" * 300 + ".endpoints.huggingface.cloud", "invalid_url"),
    ],
)
def test_user_endpoint_rejections(dns, url, code):
    with pytest.raises(ep.EndpointRejected) as err:
        ep.validate_user_endpoint(url, DEFAULT_ENDPOINT_HOSTS)
    assert err.value.code == code, url


def test_user_endpoint_accepted_and_host_allowlist_can_be_extended(dns):
    for given in (URL, URL + "/", URL + "/v1", URL + "/v1/completions", URL.upper().replace("HTTPS", "https")):
        base, policy = ep.validate_user_endpoint(given, DEFAULT_ENDPOINT_HOSTS)
        assert base.lower() == f"{URL}/v1" and policy.allowed_ports == (443,)
    with pytest.raises(ep.EndpointRejected):
        ep.validate_user_endpoint("https://models.example.org", DEFAULT_ENDPOINT_HOSTS)
    hosts = Settings.from_env({"BIRD_ENDPOINT_ALLOWED_HOSTS": "*.example.org, .other.test"}).endpoint_allowed_hosts
    assert hosts == ("endpoints.huggingface.cloud", "example.org", "other.test")
    assert ep.validate_user_endpoint("https://models.example.org", hosts)[0] == "https://models.example.org/v1"


def test_token_and_model_shapes():
    assert ep.clean_token("  " + TOKEN + " ") == TOKEN and ep.clean_token("") is None
    assert (
        ep.clean_model("", "bird") == "bird" and ep.clean_model("org/Bird-4B_v1.2:latest") == "org/Bird-4B_v1.2:latest"
    )
    for bad in ("a\r\nX-Injected: 1", "tok en", "é" * 10, "x" * 500):
        with pytest.raises(ep.EndpointRejected):
            ep.clean_token(bad)
    for bad in ("bi\nrd", "a b", "../x" * 60):
        with pytest.raises(ep.EndpointRejected):
            ep.clean_model(bad)


def test_egress_client_pins_the_validated_address_and_refuses_redirects(dns):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx.Response(307, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    _, policy = ep.validate_user_endpoint(URL, DEFAULT_ENDPOINT_HOSTS)
    client = client_for(handler, egress=policy)
    with pytest.raises(EndpointError) as err:
        client.generate("x", 8, STOP)
    assert err.value.kind == "wrong_route"  # the redirect is reported, never followed
    assert seen == [(PUBLIC_IP, HOST, HOST)]  # connected to the address we validated, with the right TLS name
    dns[HOST] = ["10.1.2.3"]  # DNS rebinding between two requests: re-checked before every request
    with pytest.raises(EndpointError) as err:
        client.generate("x", 8, STOP)
    assert err.value.kind == "blocked" and len(seen) == 1


# ------------------------------------------------------------------ API: modes, test button, secrets


def env_settings(**env) -> Settings:
    s = Settings.from_env({"BIRD_SIGNING_SECRET": "s", **env})
    s.demo_delay, s.rate_limit = 0.0, 0
    return s


def test_user_endpoint_default_is_on_only_without_a_server_endpoint():
    assert Settings.from_env({}).allow_user_endpoint is True
    assert Settings.from_env({"BIRD_BASE_URL": URL}).allow_user_endpoint is False
    assert Settings.from_env({"BIRD_BASE_URL": URL, "BIRD_ALLOW_USER_ENDPOINT": "1"}).allow_user_endpoint is True
    assert Settings.from_env({"BIRD_ALLOW_USER_ENDPOINT": "0"}).allow_user_endpoint is False


def test_signing_secret_sources():
    assert Settings.from_env({"BIRD_SIGNING_SECRET": "abc"}).signing == "configured"
    a, b = Settings.from_env({"BIRD_API_KEY": "k"}), Settings.from_env({"BIRD_API_KEY": "k"})
    assert a.signing == "derived" and a.signing_secret == b.signing_secret  # stable across instances
    assert Settings.from_env({"VERCEL_DEPLOYMENT_ID": "dpl_1"}).signing == "derived"
    c, d = Settings.from_env({}), Settings.from_env({})
    assert c.signing == "ephemeral" and c.signing_secret != d.signing_secret


HEADERS = {"X-Bird-Mode": "user", "X-Bird-Endpoint": URL, "X-Bird-Token": TOKEN, "X-Bird-Model": "bird"}


def patch_transport(monkeypatch, handler):
    """Every CompletionsClient built by the app talks to ``handler`` instead of the network."""
    real = CompletionsClient.__init__

    def init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        kw["sleep"] = lambda s: None
        real(self, *a, **kw)

    monkeypatch.setattr(CompletionsClient, "__init__", init)


@pytest.mark.parametrize(
    ("response", "status", "words"),
    [
        (
            httpx.Response(
                200, json={"choices": [{"text": "!"}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
            ),
            "ok",
            "Connexion réussie",
        ),
        (httpx.Response(200, json={"choices": [{"text": "!"}]}), "ok_no_usage", "estimé"),
        (httpx.Response(401, text="Invalid token"), "unauthorized", "jeton"),
        (httpx.Response(503, text=""), "waking", "se réveille"),
        (httpx.Response(404, text="Not Found"), "wrong_route", "/v1/completions"),
        (httpx.Response(400, json={"error": "model not found"}), "bad_request", "nom du modèle"),
        (httpx.Response(500, text="boom"), "server", "erreur"),
    ],
)
def test_endpoint_test_button_explains_in_plain_french(dns, monkeypatch, response, status, words):
    patch_transport(monkeypatch, lambda request: response)
    with TestClient(create_app(env_settings())) as client:
        data = client.post("/api/endpoint/test", json={"lang": "fr"}, headers=HEADERS).json()
    assert data["status"] == status and data["ok"] is status.startswith("ok") and words in data["message"]
    assert TOKEN not in json.dumps(data) and HOST not in json.dumps(data)  # nothing typed is echoed back


def test_endpoint_test_rejections_and_modes(dns, monkeypatch):
    patch_transport(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"text": "!"}]}))
    with TestClient(create_app(env_settings())) as client:

        def status(**headers):
            return client.post("/api/endpoint/test", json={"lang": "en"}, headers={**HEADERS, **headers}).json()[
                "status"
            ]

        assert status(**{"X-Bird-Endpoint": "http://" + HOST}) == "https_only"
        assert status(**{"X-Bird-Endpoint": "https://example.org"}) == "host_not_allowed"
        assert status(**{"X-Bird-Endpoint": "https://private.endpoints.huggingface.cloud"}) == "address"
        assert status(**{"X-Bird-Token": "bad token"}) == "invalid_token"
        assert status(**{"X-Bird-Mode": "demo"}) == "demo"
        assert status(**{"X-Bird-Mode": "server"}) == "not_configured"
    with TestClient(create_app(env_settings(BIRD_BASE_URL="http://127.0.0.1:9/v1"))) as client:  # server configured
        assert client.get("/api/health").json()["modes"] == {"demo": True, "server": True, "user": False}
        assert client.post("/api/endpoint/test", json={}, headers=HEADERS).json()["status"] == "disabled"
        body = {"messages": [{"role": "user", "content": "x"}]}
        assert client.post("/api/chat", json=body, headers=HEADERS).status_code == 403


def test_chat_through_a_user_endpoint_never_logs_or_echoes_the_token(dns, monkeypatch, capsys, caplog):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.host,
                request.headers["host"],
                request.headers.get("authorization"),
                json.loads(request.content)["model"],
            )
        )
        return stream_response(VLLM)

    patch_transport(monkeypatch, handler)
    with caplog.at_level("DEBUG"), TestClient(create_app(env_settings())) as client:
        health = client.get("/api/health").json()
        response = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "Bonjour"}]},
            headers={**HEADERS, "X-Bird-Model": "org/bird-4b"},
        )
    assert response.status_code == 200
    events = [json.loads(f[6:]) for f in response.text.split("\n\n") if f.startswith("data: ")]
    answer = next(e for e in events if e["type"] == "answer")
    usage = next(e for e in events if e["type"] == "usage")
    assert answer["content"] == "Bonjour !" and usage["model"] == "org/bird-4b" and usage["prompt_tokens"] == 12
    assert seen == [(PUBLIC_IP, HOST, f"Bearer {TOKEN}", "org/bird-4b")]
    everything = response.text + json.dumps(health) + capsys.readouterr().out + capsys.readouterr().err + caplog.text
    assert TOKEN not in everything and HOST not in everything
    assert '"event": "run"' in everything  # the audit log did run, it simply never sees the endpoint parameters


def test_chat_with_a_sleeping_user_endpoint_is_a_calm_status_then_a_retryable_error(dns, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else stream_response(VLLM)

    patch_transport(monkeypatch, handler)
    body = {"messages": [{"role": "user", "content": "Bonjour"}]}
    with TestClient(create_app(env_settings())) as client:
        events = [
            json.loads(f[6:])
            for f in client.post("/api/chat", json=body, headers=HEADERS).text.split("\n\n")
            if f.startswith("data: ")
        ]
    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["status", "status"] and events[0]["state"] == "waking" and "answer" in kinds
    calls.clear()
    patch_transport(monkeypatch, lambda request: httpx.Response(503))
    s = env_settings()
    s.max_seconds = 4.0  # not enough time to wait for a wake-up: give up at once, calmly
    with TestClient(create_app(s)) as client:
        events = [
            json.loads(f[6:])
            for f in client.post("/api/chat", json=body, headers=HEADERS).text.split("\n\n")
            if f.startswith("data: ")
        ]
    error = next(e for e in events if e["type"] == "error")
    assert error["code"] == "waking" and "se réveille" in error["message"]


def test_bad_user_endpoint_is_refused_before_any_request(dns, monkeypatch):
    patch_transport(monkeypatch, lambda request: pytest.fail("no request must leave"))
    with TestClient(create_app(env_settings())) as client:
        for url, code in (
            ("http://" + HOST, "https_only"),
            ("https://127.0.0.1", "host_not_allowed"),
            ("https://private.endpoints.huggingface.cloud", "address"),
        ):
            response = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "x"}]},
                headers={**HEADERS, "X-Bird-Endpoint": url},
            )
            assert response.status_code == 400 and response.json()["detail"]["code"] == code
            assert url not in response.text


def test_wrong_model_name_is_reported_as_such():
    from birds.harness.llm import _http_error

    vllm = '{"error":{"message":"The model `bird` does not exist. Valid aliases: adubrou/Bird-S-4B.","code":404}}'
    err = _http_error(404, vllm)
    assert err.kind == "unknown_model" and "adubrou/Bird-S-4B" in str(err)
    assert _http_error(404, "Not Found").kind == "wrong_route"
