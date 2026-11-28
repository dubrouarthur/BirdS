"""Bird local (birds/web/local.py, scripts/bird_local.py): the loopback guard, CORS and Private Network Access,
the pairing code, the vLLM probe (mocked), the hosted page's narrow CSP exception. docs/LOCAL.md."""

from __future__ import annotations

import json
import stat

import httpx
import pytest
from fastapi.testclient import TestClient

from birds.harness import router
from birds.web import local
from birds.web.server import create_app, csp_for
from birds.web.settings import Settings

PORT = 8765
HOSTED = "https://bird-s.vercel.app"
CODE = "ABCD-EFGH"
LOCAL_URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def app():
    s = Settings(rate_limit=1000, demo_delay=0.0, local_bird_port=PORT)
    a = create_app(s)
    local.install(a, local.LocalConfig(code=CODE, port=PORT, origins=(HOSTED,), fail_per_minute=3))
    return a


@pytest.fixture
def client(app):
    return TestClient(app, base_url=LOCAL_URL)


def chat(client, headers):
    body = {"messages": [{"role": "user", "content": "Bonjour"}], "lang": "fr"}
    return client.post("/api/chat", json=body, headers={"X-Bird-Mode": "demo", **headers})


# ---------------------------------------------------------------- pure checks


def test_code_shape_and_constant_time_compare():
    code = local.new_code()
    assert len(code) == 9 and code[4] == "-" and all(c in local.CODE_ALPHABET for c in code.replace("-", ""))
    assert local.code_ok("abcd efgh", CODE) and local.code_ok("ABCDEFGH", CODE) and local.code_ok(" abcd-efgh ", CODE)
    assert not local.code_ok("ABCD-EFGX", CODE) and not local.code_ok("", CODE) and not local.code_ok(None, CODE)
    assert not local.code_ok("ABCD", CODE)


def test_host_header_must_name_the_loopback_port():
    assert local.host_ok("127.0.0.1:8765", 8765) and local.host_ok("LOCALHOST:8765", 8765)
    for bad in (
        "evil.example:8765",
        "127.0.0.1",
        "127.0.0.1:8000",
        "rebind.example",
        "",
        None,
        "127.0.0.1.nip.io:8765",
    ):
        assert not local.host_ok(bad, 8765), bad


def test_origins_are_exact_and_https_except_the_loopback():
    assert local.clean_origins(["https://bird-s.vercel.app/", " HTTPS://Bird-S.vercel.app"]) == (HOSTED,)
    assert local.clean_origins(["http://127.0.0.1:9300"]) == ("http://127.0.0.1:9300",)
    for bad in ("*", "https://*.vercel.app", "http://bird-s.vercel.app", "https://bird-s.vercel.app/path", "null"):
        with pytest.raises(ValueError):
            local.clean_origins([bad])
    assert local.origin_kind(None, PORT, (HOSTED,)) == ""
    assert local.origin_kind(LOCAL_URL, PORT, (HOSTED,)) == "self"
    assert local.origin_kind(HOSTED, PORT, (HOSTED,)) == "allowed"
    assert local.origin_kind("https://bird-s.vercel.app.evil.example", PORT, (HOSTED,)) is None
    assert local.origin_kind("null", PORT, (HOSTED,)) is None


# ---------------------------------------------------------------- the guard in front of the app


def test_dns_rebinding_host_is_refused(app):
    c = TestClient(app, base_url=f"http://rebind.example:{PORT}")
    assert c.get("/api/health").status_code == 421
    assert c.get("/").status_code == 421
    assert TestClient(app, base_url=f"http://localhost:{PORT}").get("/api/health").status_code == 200


def test_preflight_answers_the_hosted_origin_only_with_private_network(client):
    pre = {
        "Origin": HOSTED,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-bird-pair",
    }
    r = client.options("/api/chat", headers={**pre, "Access-Control-Request-Private-Network": "true"})
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == HOSTED
    assert r.headers["access-control-allow-private-network"] == "true"
    assert "x-bird-pair" in r.headers["access-control-allow-headers"]
    assert "access-control-allow-credentials" not in r.headers  # no cookie ever crosses
    assert "Origin" in r.headers["vary"]
    plain = client.options("/api/chat", headers=pre)  # no PNA request: no PNA grant
    assert plain.status_code == 204 and "access-control-allow-private-network" not in plain.headers
    evil = client.options("/api/chat", headers={**pre, "Origin": "https://evil.example",
                                                "Access-Control-Request-Private-Network": "true"})  # fmt: skip
    assert evil.status_code == 403 and "access-control-allow-origin" not in evil.headers
    assert "access-control-allow-private-network" not in evil.headers


def test_other_origins_are_refused_without_cors_headers(client):
    for origin in ("https://evil.example", "http://127.0.0.1:9999", "null"):
        r = chat(client, {"Origin": origin, "X-Bird-Pair": CODE})
        assert r.status_code == 403 and "access-control-allow-origin" not in r.headers, origin
        r = client.get("/api/health", headers={"Origin": origin})
        assert r.status_code == 403 and "access-control-allow-origin" not in r.headers, origin


def test_every_api_call_needs_the_pairing_code(client):
    hosted = {"Origin": HOSTED, "Sec-Fetch-Site": "cross-site"}
    r = chat(client, hosted)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "pair_required"
    assert r.headers["access-control-allow-origin"] == HOSTED  # the page can read why
    assert chat(client, {**hosted, "X-Bird-Pair": "WXYZ-WXYZ"}).json()["detail"]["code"] == "pair_invalid"
    ok = chat(client, {**hosted, "X-Bird-Pair": "abcd-efgh"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == HOSTED
    assert '"type": "answer"' in ok.text
    # the page served by Bird local itself needs it too (another local program or tab cannot use the API blind)
    assert chat(client, {}).status_code == 401
    assert chat(client, {"Origin": LOCAL_URL, "X-Bird-Pair": CODE}).status_code == 200
    for path in ("/api/endpoint/test", "/api/tool", "/api/export", "/api/canvas/check", "/api/local/pair"):
        assert client.post(path, json={}, headers=hosted).status_code == 401, path


def test_wrong_codes_lock_the_api_for_a_minute(client):
    hosted = {"Origin": HOSTED}
    codes = [
        client.post("/api/local/pair", headers={**hosted, "X-Bird-Pair": f"WRNG-000{i}"}).status_code for i in range(5)
    ]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    r = client.post("/api/local/pair", headers={**hosted, "X-Bird-Pair": "WRNG-0009"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "pair_locked"
    # a real lock: the right code is refused too, so a guesser cannot tell when it hit (no oracle while locked)
    r = client.post("/api/local/pair", headers={**hosted, "X-Bird-Pair": CODE})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "pair_locked"
    assert r.headers["access-control-allow-origin"] == HOSTED  # the page can say « wait a minute »
    assert client.get("/api/health").status_code == 200  # the health check still answers


def test_pair_and_health(client):
    h = client.get("/api/health", headers={"Origin": HOSTED}).json()
    assert h["bird_local"] == {"version": 1, "port": PORT, "paired": False, "pair_header": "X-Bird-Pair"}
    assert h["local_bird"] is None  # Bird local does not look for another Bird local
    assert CODE not in json.dumps(h) and "8000" not in json.dumps(h["bird_local"])  # never the code, never vLLM
    r = client.post("/api/local/pair", headers={"Origin": HOSTED, "X-Bird-Pair": CODE})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["paired"] and r.json()["model"]
    assert client.get("/api/health", headers={"X-Bird-Pair": CODE}).json()["bird_local"]["paired"] is True


def test_cross_site_blind_calls_are_refused_but_signed_pictures_load(client):
    # a form post or a no-cors call from another site has no readable answer, and is refused before the route
    r = client.post("/api/chat", headers={"Sec-Fetch-Site": "cross-site", "X-Bird-Pair": CODE}, json={})
    assert r.status_code == 403
    pic = client.get("/api/icon?d=example.org&s=bad", headers={"Sec-Fetch-Site": "cross-site"})
    assert pic.status_code != 403 or pic.headers.get("cross-origin-resource-policy") == "cross-origin"
    assert pic.headers["cross-origin-resource-policy"] == "cross-origin"  # the hosted page may show local pictures
    page = client.get("/", headers={"Sec-Fetch-Site": "cross-site"})  # a link to the app opens it
    assert page.status_code == 200


def test_rate_limit(app):
    a = create_app(Settings(rate_limit=1000, demo_delay=0.0))
    local.install(a, local.LocalConfig(code=CODE, port=PORT, origins=(HOSTED,), rate_per_minute=3))
    c = TestClient(a, base_url=LOCAL_URL)
    got = [c.get("/api/health").status_code for _ in range(5)]
    assert got == [200, 200, 200, 429, 429]


# ---------------------------------------------------------------- the hosted page: narrow CSP exception


def test_hosted_csp_names_exactly_the_two_loopback_origins_of_the_port():
    csp = csp_for(8765)
    assert "connect-src 'self' http://127.0.0.1:8765 http://localhost:8765;" in csp
    assert "img-src 'self' blob: http://127.0.0.1:8765 http://localhost:8765;" in csp
    assert csp.count("http://") == 4 and "*" not in csp and ":8000" not in csp
    off = csp_for(None)
    assert "http" not in off and "connect-src 'self';" in off
    hosted = TestClient(create_app(Settings(local_bird_port=None)))
    assert "127.0.0.1" not in hosted.get("/").headers["content-security-policy"]
    assert hosted.get("/api/health").json()["local_bird"] is None
    on = TestClient(create_app(Settings()))
    assert on.get("/api/health").json()["local_bird"] == {"port": 8765}
    assert "bird_local" not in on.get("/api/health").json()


def test_local_port_setting_from_env():
    assert Settings.from_env({}).local_bird_port == 8765
    assert Settings.from_env({"BIRD_LOCAL_BIRD_PORT": "off"}).local_bird_port is None
    assert Settings.from_env({"BIRD_LOCAL_BIRD_PORT": "9876"}).local_bird_port == 9876
    assert Settings.from_env({"BIRD_LOCAL_BIRD_PORT": "80"}).local_bird_port == 8765  # privileged: refused


def test_hosted_server_still_refuses_cross_origin_calls():
    c = TestClient(create_app(Settings(demo_delay=0.0)))
    r = chat(c, {"Origin": "http://127.0.0.1:8765", "X-Bird-Pair": CODE})
    assert r.status_code == 403  # the guard's exception exists only inside a Bird local


# ---------------------------------------------------------------- the vLLM probe (mocked)


def fake_vllm(models=("adubrou/Bird-S-4B",), structured=True, status=200):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/v1/models":
            if status != 200:
                return httpx.Response(status, json={"error": "no"})
            return httpx.Response(200, json={"data": [{"id": m} for m in models]})
        body = json.loads(request.content)
        if "structured_outputs" in body and structured:
            return httpx.Response(200, json={"choices": [{"text": '{"probe": "bird-router-ok"}'}]})
        if "structured_outputs" not in body and any(k in body for k in router.STRUCTURED_KINDS):
            return httpx.Response(400, json={"error": "unknown field"})
        return httpx.Response(200, json={"choices": [{"text": "bonjour"}]})

    return httpx.MockTransport(handler), seen


@pytest.fixture(autouse=True)
def _router_cache():
    router._cache.clear()
    yield
    router._cache.clear()


def test_probe_picks_the_served_model_and_detects_structured_outputs():
    transport, seen = fake_vllm(models=("other/model", "adubrou/Bird-S-4B"))
    st = local.probe_vllm("http://127.0.0.1:8000", transport=transport)
    assert st.ok and st.model == "adubrou/Bird-S-4B" and st.structured == "structured_outputs"
    assert st.base_url == "http://127.0.0.1:8000/v1" and "/v1/models" in seen and "/v1/completions" in seen


def test_probe_without_structured_outputs_still_ok():
    router._cache.clear()
    transport, _ = fake_vllm(models=("my-bird",), structured=False)
    st = local.probe_vllm("http://127.0.0.1:8000/v1", transport=transport)
    assert st.ok and st.model == "my-bird" and st.structured == ""


def test_probe_explicit_model_must_be_served():
    transport, _ = fake_vllm(models=("a", "b"))
    assert (
        local.probe_vllm("http://127.0.0.1:8000/v1", model="b", transport=transport, check_structured=False).model
        == "b"
    )
    st = local.probe_vllm("http://127.0.0.1:8000/v1", model="c", transport=transport)
    assert not st.ok and st.status == "no_models" and st.models == ["a", "b"]
    assert local.pick_model([]) is None and local.pick_model(["x", "y"]) == "x"


def test_probe_down_and_unauthorized():
    def refuse(request):
        raise httpx.ConnectError("refused")

    st = local.probe_vllm("http://127.0.0.1:8000/v1", transport=httpx.MockTransport(refuse))
    assert not st.ok and st.status == "down"
    transport, _ = fake_vllm(status=401)
    assert local.probe_vllm("http://127.0.0.1:8000/v1", transport=transport).status == "unauthorized"
    bad = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))
    assert local.probe_vllm("http://127.0.0.1:8000/v1", transport=bad).status == "error"


def test_vllm_command_is_loopback_and_has_no_secret():
    cmd = local.vllm_command()
    assert cmd == "vllm serve adubrou/Bird-S-4B --host 127.0.0.1 --port 8000"
    assert "key" not in cmd.lower() and "token" not in cmd.lower()


def test_pairing_code_is_kept_with_owner_only_permissions(tmp_path):
    path = tmp_path / "bird" / "local.json"
    a = local.load_or_create_code(path)
    assert local.load_or_create_code(path) == a
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    b = local.load_or_create_code(path, rotate=True)
    assert b != a and local.load_or_create_code(path) == b


# ---------------------------------------------------------------- the command


def test_command_refuses_wide_origins_and_prints_the_vllm_command(capsys, monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("bird_local", Path(__file__).parents[1] / "scripts" / "bird_local.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(SystemExit):
        mod.parse_args(["--allow-origin", "*"])
    args = mod.parse_args([])
    assert args.origins == (HOSTED,) and args.port == 8765 and args.vllm_url == "http://127.0.0.1:8000/v1"
    monkeypatch.setattr(
        local, "probe_vllm", lambda *a, **k: local.VllmStatus(False, "down", "http://127.0.0.1:8000/v1")
    )
    assert mod.main(["--no-browser"]) == 2
    out = capsys.readouterr().out
    assert "vllm serve adubrou/Bird-S-4B --host 127.0.0.1 --port 8000" in out and "Aucun serveur" in out


def test_command_output_never_crashes_on_a_cp1252_console():
    """Windows: a console or redirected output in cp1252 has no « ─ »; the banner is printed with replacements."""
    import importlib.util
    import io
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("bird_local", Path(__file__).parents[1] / "scripts" / "bird_local.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(UnicodeEncodeError):
        "─".encode("cp1252")
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252")
    mod.safe_console(out)
    print("─" * 4 + " → Réglages", file=out, flush=True)
    assert raw.getvalue().endswith("???? ? Réglages\n".encode("cp1252"))


def test_command_says_when_the_served_model_is_not_bird(capsys, monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("bird_local", Path(__file__).parents[1] / "scripts" / "bird_local.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ok = local.VllmStatus(True, "ok", "http://127.0.0.1:8000/v1", models=["meta/llama"], model="meta/llama")
    monkeypatch.setattr(local, "probe_vllm", lambda *a, **k: ok)
    monkeypatch.setattr(mod, "port_free", lambda port: False)  # stop before serving
    assert mod.main(["--no-browser"]) == 3
    assert "pas un modèle Bird" in capsys.readouterr().out
    assert mod.main(["--no-browser", "--model", "meta/llama"]) == 3  # chosen on purpose: no warning
    assert "pas un modèle Bird" not in capsys.readouterr().out
