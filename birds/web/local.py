"""Bird local: the Bird harness on the user's own machine, in front of their vLLM server (docs/LOCAL.md).

``scripts/bird_local.py`` builds the same app as the deployment (``create_app``) with the user's model server as its
backend, then ``install`` puts this guard in front of it. The guard is the whole security of the local side:

- loopback only: the server binds 127.0.0.1 and every request must carry ``Host: 127.0.0.1:<port>`` or
  ``localhost:<port>`` exactly (DNS rebinding: a hostile name resolved to 127.0.0.1 arrives with its own Host);
- browser calls from another origin are accepted only from an exact allow-list (the hosted chat by default), with
  CORS headers for that origin alone, never ``*`` and never credentials; Chrome's Private / Local Network Access
  preflight (``Access-Control-Request-Private-Network``) is answered for those origins only;
- every API call needs the pairing code printed by the local command (``X-Bird-Pair``, constant-time compare);
  wrong codes are rate limited and lock the API for a minute after too many tries;
- only the signed image routes (``/api/img``, ``/api/map``, ``/api/icon``: HMAC-signed by this process) and the
  health check answer without the code, so that the hosted page can find the local Bird and show its pictures.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import stat
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_VLLM_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL = "adubrou/Bird-S-4B"
DEFAULT_ORIGINS = ("https://bird-s.vercel.app",)
PAIR_HEADER = "x-bird-pair"
OPEN_PATHS = frozenset({"/api/health", "/api/local/pair"})
IMAGE_PATHS = frozenset({"/api/img", "/api/map", "/api/icon"})  # signed by this process: no header on <img>
ALLOW_HEADERS = "accept, content-type, x-bird-mode, x-bird-lang, x-bird-pair"
ALLOW_METHODS = "GET, POST"
# Crockford base32 without the look-alikes (no I, L, O, U, 0, 1): 30 symbols, 8 of them = 39 bits, typed once
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LEN = 8
_ORIGIN = re.compile(r"^https?://[a-z0-9.-]+(:\d{1,5})?$")


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
    return raw[:4] + "-" + raw[4:]


def normalize_code(value: str | None) -> str:
    """What the user typed, the way it is compared: upper case, no separator or space."""
    return re.sub(r"[\s\-_.]", "", (value or "")).upper()[:64]


def code_ok(given: str | None, code: str) -> bool:
    """Constant-time comparison of a typed or stored pairing code with the expected one."""
    a, b = normalize_code(given), normalize_code(code)
    return bool(a) and hmac.compare_digest(a.encode("ascii", "replace"), b.encode("ascii", "replace"))


def self_origins(port: int) -> tuple[str, ...]:
    return (f"http://127.0.0.1:{port}", f"http://localhost:{port}")


def host_ok(host: str | None, port: int) -> bool:
    """The Host header names this server on the loopback, nothing else (DNS-rebinding protection)."""
    return (host or "").strip().lower() in (f"127.0.0.1:{port}", f"localhost:{port}")


def clean_origins(values: Iterable[str]) -> tuple[str, ...]:
    """Exact origins (scheme://host[:port], no path, no wildcard); http only for the loopback (tests, a local copy)."""
    out: list[str] = []
    for v in values:
        o = (v or "").strip().lower().rstrip("/")
        if not o:
            continue
        if not _ORIGIN.match(o):
            raise ValueError(f"not an exact origin: {v!r} (expected https://host or https://host:port)")
        host = o.split("://", 1)[1].split(":", 1)[0]
        if o.startswith("http://") and host not in ("127.0.0.1", "localhost"):
            raise ValueError(f"an allowed origin must use https (http only for 127.0.0.1 / localhost): {v!r}")
        if o not in out:
            out.append(o)
    return tuple(out)


def origin_kind(origin: str | None, port: int, allowed: tuple[str, ...]) -> str | None:
    """'self' (the app served by this server), 'allowed' (the hosted chat), None (refused); '' when absent."""
    if origin is None:
        return ""
    o = origin.strip().lower().rstrip("/")
    if o in self_origins(port):
        return "self"
    if o in allowed:
        return "allowed"
    return None


def preflight_headers(origin: str, request_headers) -> dict[str, str]:
    """CORS preflight answer for an allowed origin, Private / Local Network Access included."""
    out = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": ALLOW_METHODS,
        "Access-Control-Allow-Headers": ALLOW_HEADERS,
        "Access-Control-Max-Age": "600",
        "Vary": "Origin, Access-Control-Request-Headers, Access-Control-Request-Private-Network",
    }
    if (request_headers.get("access-control-request-private-network") or "").lower() == "true":
        out["Access-Control-Allow-Private-Network"] = "true"
    return out


def cors_headers(origin: str) -> dict[str, str]:
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}


@dataclass
class LocalConfig:
    code: str
    port: int = DEFAULT_PORT
    origins: tuple[str, ...] = DEFAULT_ORIGINS
    rate_per_minute: int = 240  # every request of the page (chat, tools, images) on this machine
    fail_per_minute: int = 8  # wrong pairing codes before the API locks for a minute
    vllm_url: str = DEFAULT_VLLM_URL
    model: str = DEFAULT_MODEL
    structured: str = ""  # the structured-output form the model server enforces ('' when none)
    measured: bool = False  # energy sampled with nvidia-smi on this machine
    extra: dict = field(default_factory=dict)

    def public(self, paired: bool) -> dict:
        """What /api/health says about the local Bird: never the code, never the vLLM URL to another origin."""
        out = {"version": 1, "port": self.port, "paired": paired, "pair_header": "X-Bird-Pair"}
        if paired:
            out.update(model=self.model, structured=self.structured or None, measured=self.measured)
        return out


def install(app, cfg: LocalConfig) -> None:
    """Put the local guard in front of ``app`` (outermost middleware) and add ``POST /api/local/pair``."""
    from fastapi import Request
    from fastapi.responses import JSONResponse, PlainTextResponse, Response

    from .server import RateLimiter

    limiter = RateLimiter(cfg.rate_per_minute)
    fails = RateLimiter(cfg.fail_per_minute)
    locked_until = [0.0]  # while locked, every code is refused, the right one too: guessing gets no answer to read
    app.state.bird_local = cfg

    def refuse(status: int, code: str, message: str, origin: str | None) -> Response:
        headers = cors_headers(origin) if origin else {}
        return JSONResponse({"detail": {"code": code, "message": message}}, status_code=status, headers=headers)

    @app.post("/api/local/pair", include_in_schema=False)
    def pair() -> dict:
        # reached only with a valid code (the guard below checks it first)
        return {"ok": True, **cfg.public(True)}

    @app.middleware("http")
    async def bird_local_guard(request: Request, call_next):
        if not host_ok(request.headers.get("host"), cfg.port):
            return PlainTextResponse("Bird local answers on 127.0.0.1 only", status_code=421)
        origin = request.headers.get("origin")
        kind = origin_kind(origin, cfg.port, cfg.origins)
        if kind is None:
            return PlainTextResponse("origin refused", status_code=403)  # no CORS header: the page cannot read it
        cross = kind == "allowed"
        path = request.url.path
        site = request.headers.get("sec-fetch-site") or ""
        if request.method == "OPTIONS":
            if not cross or not request.headers.get("access-control-request-method"):
                return PlainTextResponse("preflight refused", status_code=403)
            if not limiter.allow("preflight"):
                return PlainTextResponse("too many requests", status_code=429)
            return Response(status_code=204, headers=preflight_headers(origin, request.headers))
        api = path.startswith("/api/")
        # another site may link to the app (a navigation) or show its signed pictures, never call its API blind
        if api and not kind and site in ("cross-site", "same-site") and path not in IMAGE_PATHS:
            return PlainTextResponse("cross-site request refused", status_code=403)
        if not limiter.allow("api" if api else "page"):
            return refuse(429, "rate_limited", "too many requests, wait a minute", origin if cross else None)
        paired = code_ok(request.headers.get(PAIR_HEADER), cfg.code)
        if api and path not in IMAGE_PATHS and path != "/api/health":
            now = time.monotonic()
            if request.headers.get(PAIR_HEADER) and not paired and not fails.allow("pair", now):
                locked_until[0] = now + 60
            if now < locked_until[0]:
                return refuse(429, "pair_locked", "too many wrong pairing codes, wait a minute", origin if cross else None)
            if not paired:
                given = bool(request.headers.get(PAIR_HEADER))
                return refuse(401, "pair_invalid" if given else "pair_required", "a valid pairing code is required",
                              origin if cross else None)  # fmt: skip
        request.state.bird_local_cross = cross
        request.state.bird_local_paired = paired
        response = await call_next(request)
        if cross:
            for k, v in cors_headers(origin).items():
                response.headers[k] = v
        if path in IMAGE_PATHS:  # the hosted page shows them in <img>: readable by other origins, they are pictures
            response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        return response


# ---------------------------------------------------------------- the user's model server (vLLM)


@dataclass
class VllmStatus:
    ok: bool
    status: str  # "ok" | "down" | "no_models" | "unauthorized" | "error"
    base_url: str
    models: list[str] = field(default_factory=list)
    model: str | None = None
    structured: str = ""
    detail: str = ""


def pick_model(models: list[str], wanted: str | None = None) -> str | None:
    """The model to use: the one asked for, else a served Bird, else the only (first) one served."""
    if not models:
        return None
    if wanted:
        return wanted if wanted in models else None
    for m in models:
        if "bird" in m.lower():
            return m
    return models[0]


def probe_vllm(
    base_url: str, *, model: str | None = None, api_key: str | None = None, transport=None, timeout: float = 5.0,
    check_structured: bool = True,
) -> VllmStatus:  # fmt: skip
    """Read ``/v1/models``, pick the served model, detect structured outputs (birds.harness.router). Never raises."""
    import httpx

    from birds.harness.llm import normalize_base_url

    base = normalize_base_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with httpx.Client(timeout=timeout, transport=transport, trust_env=False, follow_redirects=False) as http:
            r = http.get(base + "/models", headers=headers)
    except httpx.HTTPError as e:
        return VllmStatus(False, "down", base, detail=type(e).__name__)
    if r.status_code in (401, 403):
        return VllmStatus(False, "unauthorized", base, detail=f"HTTP {r.status_code}")
    if r.status_code >= 300:
        return VllmStatus(False, "error", base, detail=f"HTTP {r.status_code}")
    try:
        data = r.json()
        models = [str(m["id"]) for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
    except (ValueError, AttributeError, KeyError, TypeError):
        return VllmStatus(False, "error", base, detail="not an OpenAI-compatible /v1/models answer")
    chosen = pick_model(models, model)
    if chosen is None:
        detail = f"{model} is not served" if model and models else "no model served"
        return VllmStatus(False, "no_models", base, models=models, detail=detail)
    kind = ""
    if check_structured:
        from birds.harness import router
        from birds.harness.llm import CompletionsClient

        kind = router.structured_kind(CompletionsClient(base, chosen, api_key, timeout=20.0, transport=transport))
    return VllmStatus(True, "ok", base, models=models, model=chosen, structured=kind)


def vllm_command(model: str = DEFAULT_MODEL, port: int = 8000) -> str:
    """The exact command to start the model server on this machine (loopback only, no secret)."""
    return f"vllm serve {model} --host 127.0.0.1 --port {port}"


# ---------------------------------------------------------------- the pairing code, kept between runs


def code_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "bird" / "local.json"


def load_or_create_code(path: Path | None = None, *, rotate: bool = False) -> str:
    """The pairing code survives restarts (pair once, « Se souvenir »); ``rotate`` makes a new one. File mode 0600."""
    path = path or code_file()
    if not rotate:
        try:
            got = json.loads(path.read_text(encoding="utf-8")).get("code")
            if isinstance(got, str) and len(normalize_code(got)) == CODE_LEN:
                return got
        except (OSError, ValueError, AttributeError):
            pass
    code = new_code()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"code": code}, f)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # not kept: a new code next time, nothing breaks
    return code
