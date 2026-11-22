"""FastAPI app for the Bird web chat: static frontend + a small stateless API (see docs/WEB.md).

Nothing is kept in memory between requests except a best-effort rate-limit window: the app runs unchanged on a
long-lived local server (scripts/serve.py) and on serverless functions (app.py, Vercel).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import endpoint as ep
from . import tokens
from .backends import Backend, Cancelled, ChatRequest, DemoBackend, Event, HarnessBackend, RunContext, sanitize_filename
from .settings import Settings

STATIC_DIR = Path(__file__).parent / "static"

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; "
    "manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
MODES = ("demo", "server", "user")


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    memo: str | None = Field(default=None, max_length=4000)  # compact record of the tools of that turn


class ImageIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=32, max_length=1_500_000)  # data:image/(png|jpeg|webp);base64,...


class Attachment(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: str
    encoding: Literal["text", "base64"] = "text"  # base64: an office file or PDF, read by read_file on the server


BINARY_ATTACHMENTS = (".pdf", ".docx", ".xlsx", ".pptx")


class ChatBody(BaseModel):
    messages: list[Message] = Field(min_length=1)
    thinking: bool = False
    lang: Literal["fr", "en"] = "fr"
    attachments: list[Attachment] = Field(default_factory=list)
    images: list[ImageIn] = Field(default_factory=list, max_length=3)  # for the last user message only
    approved: list[str] = Field(default_factory=list, max_length=1)  # confirm token the user approved
    denied: list[str] = Field(default_factory=list, max_length=1)  # confirm token the user refused


class TestBody(BaseModel):
    lang: Literal["fr", "en"] = "fr"


class ExportBody(BaseModel):
    format: Literal["docx", "md"] = "docx"
    title: str = Field(default="Bird", max_length=200)
    content: str = Field(min_length=1, max_length=120_000)


class ToolBody(BaseModel):
    tool: Literal["make_slides", "make_document", "make_sheet"]
    arguments: dict
    lang: Literal["fr", "en"] = "fr"


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status, {"code": code, "message": message})


def apply_carbon(event: Event, grid_intensity: float | None) -> Event:
    """Fill ``co2_g`` only from a reported energy and an explicitly configured grid intensity."""
    if event.get("type") != "usage":
        return event
    energy = event.get("energy_wh")
    if energy is None or event.get("energy_kind") not in ("measured", "estimated"):
        event["energy_wh"], event["energy_kind"], event["co2_g"] = None, None, None
    elif grid_intensity is None:
        event["co2_g"] = None
    else:
        event["co2_g"] = round(float(energy) / 1000.0 * grid_intensity, 4)
    return event


class RateLimiter:
    """Sliding one-minute window per client address, in this process only.

    On serverless this is best effort: each instance has its own window and instances come and go. A real limit
    needs shared storage (Vercel KV / Upstash) or the platform firewall.
    """

    def __init__(self, per_minute: int, max_clients: int = 5000):
        self.per_minute, self.max_clients = per_minute, max_clients
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str, now: float | None = None) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > self.max_clients:
                self._hits.clear()
            window = self._hits.setdefault(client, deque())
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= self.per_minute:
                return False
            window.append(now)
            return True


def harness_config(s: Settings) -> dict:
    return {
        "searxng_url": s.searxng_url,
        "brave_api_key": s.brave_api_key,
        "tavily_api_key": s.tavily_api_key,
        "search_default": s.search_default,
        "search_contact": s.search_contact,
        "pin_dns": s.pin_dns,
        "gpu_watts": s.gpu_watts,
        "gpu_label": s.gpu_label,
        "pue": s.pue,
        "measure_gpu": s.measure_gpu,
        "wh_per_1k_tokens": s.wh_per_1k_tokens,
        "calibration_source": s.calibration_source,
        "max_steps": s.max_steps,
        "max_calls_per_step": s.max_calls_per_step,
        "max_tokens": s.max_tokens,
        "timeout_s": s.max_seconds,
    }


def build_server_backend(s: Settings) -> Backend | None:
    """The operator's model: an OpenAI-compatible endpoint, or a model loaded in this process (local use)."""
    if s.local_llm is not None:
        return HarnessBackend(
            s.local_llm, s.local_tok, kind="local", model=s.model, workspace=s.workspace, config=harness_config(s)
        )
    if not s.base_url:
        return None
    from birds.harness import CompletionsClient

    tok = None
    if s.tokenizer:  # optional: the real tokenizer instead of the vendored chat template (needs transformers)
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(s.tokenizer)
    llm = CompletionsClient(s.base_url, s.model, s.api_key, timeout=s.max_seconds)
    return HarnessBackend(
        llm,
        tok,
        kind="completions",
        model=s.model,
        workspace=s.workspace,
        config=harness_config(s),
        http=fetch_client(s),
    )


def fetch_client(s: Settings):
    """read_page's HTTP client. Behind a filtering egress proxy (BIRD_PIN_DNS=0) it uses the proxy settings."""
    if s.pin_dns:
        return None  # the harness default: no proxy variables, connection pinned to the validated address
    import httpx

    return httpx.Client(follow_redirects=False)


TOOL_TEXT = {  # why a tool is on or off on this deployment, for the "available tools" panel
    "web_search": ("Recherche : {label}", "Search: {label}"),
    "web_search_off": (
        "Désactivée par l'exploitant (BIRD_SEARCH_DEFAULT=none)",
        "Switched off (BIRD_SEARCH_DEFAULT=none)",
    ),
    "read_page": ("Lit une page publique (http/https, adresses publiques, 2 Mo au plus)", "Reads a public page"),
    "read_file": ("Actif quand vous joignez un fichier texte au message", "Active when you attach a text file"),
    "read_file_ws": ("Lit les fichiers du dossier de travail du serveur", "Reads files in the server workspace"),
    "draft_email": ("Prépare un brouillon ; rien n'est envoyé", "Prepares a draft; nothing is sent"),
    "make_slides": ("Crée un .pptx, téléchargeable ici", "Creates a .pptx, downloadable here"),
    "make_document": ("Crée un .docx, téléchargeable ici", "Creates a .docx, downloadable here"),
    "make_sheet": ("Crée un .xlsx, téléchargeable ici", "Creates a .xlsx, downloadable here"),
    "run_python": (
        "Désactivé : exécuter du code demande un vrai bac à sable, absent de ce déploiement",
        "Off: running code needs a real sandbox, which this deployment does not have",
    ),
}


def tools_info(s: Settings, backend) -> dict:
    """Which tools the model may use here, which are off, and why. Also which search backend answers."""
    from birds.tools import BIRD_TOOL_NAMES

    offered = set(getattr(backend, "tools", []) or [])
    search = getattr(backend, "search_info", None) or {}
    out = []
    for name in BIRD_TOOL_NAMES:
        state = "on" if name in offered else "off"
        key = name
        if name == "read_file" and s.workspace is None and getattr(backend, "kind", "") != "demo":
            state, key = "attach", "read_file"
        elif name == "read_file":
            key = "read_file_ws"
        elif name == "web_search" and state == "off":
            key = "web_search_off"
        fr, en = TOOL_TEXT.get(key, ("", ""))
        label = search.get("label") or ""
        out.append({"name": name, "state": state, "fr": fr.format(label=label), "en": en.format(label=label)})
    return {"tools": out, "search": search}


def create_app(
    settings: Settings | None = None, *, server_backend: Backend | None = None, demo: Backend | None = None
) -> FastAPI:
    """Build the app. ``server_backend`` / ``demo`` override what the settings would build (tests)."""
    s = settings or Settings()
    if s.grid_intensity is not None and s.grid_intensity < 0:
        raise ValueError("grid_intensity must be >= 0")
    demo = demo or DemoBackend(delay=s.demo_delay)
    server = server_backend if server_backend is not None else build_server_backend(s)
    limiter = RateLimiter(s.rate_limit)

    app = FastAPI(title="Bird", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.demo, app.state.server_backend = s, demo, server

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        path = request.url.path
        if path.startswith("/static/"):
            # browsers revalidate; a CDN in front may keep a copy until the next deployment
            response.headers["Cache-Control"] = "public, max-age=0, s-maxage=86400, must-revalidate"
        elif path == "/" or path == "/manifest.webmanifest":
            response.headers["Cache-Control"] = "no-cache"
        elif path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ------------------------------------------------------------------ request guards

    def client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")

    def guard_request(request: Request) -> None:
        """Same-origin only (no CORS headers are ever sent), then the best-effort rate limit."""
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
            if origin.split("://", 1)[-1].rstrip("/").lower() != host.lower():
                raise ApiError(403, "cross_origin", "cross-origin requests are not accepted")
        if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            raise ApiError(403, "cross_origin", "cross-origin requests are not accepted")
        if not limiter.allow(client_ip(request)):
            raise ApiError(429, "rate_limited", "too many requests, wait a minute")

    def default_mode() -> str:
        return "server" if server is not None else "demo"

    def resolve_mode(request: Request) -> str:
        mode = (request.headers.get("x-bird-mode") or "").strip().lower() or default_mode()
        if mode not in MODES:
            raise ApiError(400, "invalid_mode", "unknown mode")
        if mode == "server" and server is None:
            raise ApiError(400, "not_configured", "no model endpoint is configured on this server")
        if mode == "user" and not s.allow_user_endpoint:
            raise ApiError(403, "disabled", "user-supplied endpoints are disabled on this deployment")
        if mode != "demo" and s.access_code:
            given = request.headers.get("x-bird-access") or ""
            if not hmac.compare_digest(given.encode("utf-8"), s.access_code.encode("utf-8")):
                raise ApiError(401, "access_code", "a valid access code is required")
        return mode

    def user_client(request: Request, timeout: float):
        """Client for the endpoint typed in the app's settings. Its URL, token and model are never logged or echoed."""
        from birds.harness import CompletionsClient

        try:
            base, policy = ep.validate_user_endpoint(
                request.headers.get("x-bird-endpoint") or "", s.endpoint_allowed_hosts
            )
            token = ep.clean_token(request.headers.get("x-bird-token"))
            model = ep.clean_model(request.headers.get("x-bird-model"), s.model)
        except ep.EndpointRejected as e:
            lang = "en" if (request.headers.get("x-bird-lang") or "") == "en" else "fr"
            raise ApiError(400, e.code, ep.explain(e.code, lang)) from None
        return CompletionsClient(base, model, token, timeout=timeout, egress=policy), model, base

    def backend_for(mode: str, request: Request) -> tuple[Backend, str]:
        """(backend, binding): the binding ties a confirm token to the backend that issued it."""
        if mode == "demo":
            return demo, "demo"
        if mode == "server":
            return server, "server:" + tokens.digest([server.kind, server.model])[:16]
        llm, model, base = user_client(request, s.max_seconds)
        cfg = harness_config(s)
        cfg.update(wh_per_1k_tokens=None, calibration_source=None, measure_gpu=False)  # not the operator's hardware
        backend = HarnessBackend(
            llm, kind="completions", model=model, config=cfg, http=fetch_client(s), history_tokens=s.history_tokens
        )
        return backend, "user:" + tokens.digest([base, model])[:16]

    # ------------------------------------------------------------------ API

    @app.get("/api/health")
    def health() -> dict:
        shown = server if server is not None else demo
        return {
            "model": shown.model,
            "model_label": s.model_label,
            "backend": shown.kind,
            "tools": list(shown.tools),
            "tools_info": tools_info(s, shown),
            "energy": {
                "gpu_watts": s.gpu_watts,
                "gpu_label": s.gpu_label,
                "gpu_source": s.gpu_source,
                "pue": s.pue,
                "calibrated": s.wh_per_1k_tokens is not None,
                "calibration_source": s.calibration_source,
                "measured": bool(s.measure_gpu or s.local_llm is not None),
            },
            "compare": {
                "active_params_b": s.active_params_b,
                "classes": [{"fr": fr, "en": en, "active_params_b": b} for fr, en, b in s.compare_classes],
                "reference": s.reference,
            },
            "thinking_default": False,
            "default_mode": default_mode(),
            "modes": {"demo": True, "server": server is not None, "user": bool(s.allow_user_endpoint)},
            "demo_model": demo.model,
            "access_required": bool(s.access_code),
            "images": bool(getattr(shown, "images", False)),
            "image_limits": {"min_pixels": IMAGE_MIN_PIXELS, "min_side": IMAGE_MIN_SIDE, "max_side": 1568, "max": 3},
            "history_tokens": s.history_tokens,
            "endpoint_hosts": ["*." + h for h in s.endpoint_allowed_hosts],
            "signing": s.signing,
            "grid_intensity_g_per_kwh": s.grid_intensity,
            "equivalent": s.equivalent,
            "limits": {
                "max_messages": s.max_messages,
                "max_message_chars": s.max_message_chars,
                "max_attachments": s.max_attachments,
                "max_attachment_chars": s.max_attachment_chars,
                "max_binary_chars": s.max_binary_chars,
                "max_seconds": s.max_seconds,
                "rate_per_minute": s.rate_limit,
            },
        }

    @app.post("/api/endpoint/test")
    def endpoint_test(body: TestBody, request: Request) -> dict:
        guard_request(request)
        mode = (request.headers.get("x-bird-mode") or "").strip().lower() or default_mode()
        if mode == "demo":
            return {"ok": True, "status": "demo", "message": ep.explain("demo", body.lang)}
        try:
            mode = resolve_mode(request)
        except ApiError as e:
            if e.detail["code"] in ("disabled", "not_configured"):
                return {"ok": False, "status": e.detail["code"], "message": ep.explain(e.detail["code"], body.lang)}
            raise
        if mode == "server":
            llm = getattr(server, "llm", None)
            if not hasattr(llm, "probe"):
                return {"ok": True, "status": "ok", "message": ep.explain("ok", body.lang)}
            return ep.probe(llm, body.lang)
        try:
            llm, _, _ = user_client(request, 20.0)
        except ApiError as e:
            return {"ok": False, "status": e.detail["code"], "message": ep.explain(e.detail["code"], body.lang)}
        return ep.probe(llm, body.lang)

    def check_access(request: Request) -> None:
        if s.access_code:
            given = request.headers.get("x-bird-access") or ""
            if not hmac.compare_digest(given.encode("utf-8"), s.access_code.encode("utf-8")):
                raise ApiError(401, "access_code", "a valid access code is required")

    @app.post("/api/export")
    def export(body: ExportBody, request: Request):
        """Any answer as a .docx (or .md): headings, lists and tables of its Markdown are kept. No model call."""
        guard_request(request)
        from fastapi.responses import Response

        name = sanitize_filename((body.title or "bird")[:60]).rsplit(".", 1)[0] or "bird"
        if body.format == "md":
            data, mime, ext = body.content.encode("utf-8"), "text/markdown; charset=utf-8", "md"
        else:
            import tempfile as _tmp

            from birds.harness.office import docx_from_markdown

            with _tmp.TemporaryDirectory(prefix="bird-export-") as tmp:
                path = Path(tmp) / "export.docx"
                docx_from_markdown(path, body.title or "Bird", body.content)
                data = path.read_bytes()
            mime, ext = "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
        if len(data) > s.max_inline_file_bytes:
            raise ApiError(413, "too_large", "the exported file is too large")
        return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})

    @app.post("/api/tool")
    def run_tool(body: ToolBody, request: Request) -> dict:
        """Retry a file step that failed, without calling the model: same validation (with shape repair) and
        the same generators as the agent. Only the three file makers, which touch nothing but a temp folder."""
        guard_request(request)
        check_access(request)
        import shutil
        import tempfile as _tmp

        from birds.harness import Config, guard
        from birds.harness.config import Context
        from birds.harness.tools import TOOLS

        from .backends import file_preview, inline_file

        args, err = guard.validate_args(body.tool, body.arguments, (body.tool,))
        if err:
            return {"ok": False, "error": err}
        tmp = Path(_tmp.mkdtemp(prefix="bird-tool-"))
        try:
            ctx = Context(config=Config(workspace=tmp, audit_file=None), http=None)
            try:
                TOOLS[body.tool](args, ctx)
            except (guard.ToolError, guard.Blocked) as e:
                return {"ok": False, "error": str(e)}
            files = [
                inline_file(tmp / rel, file_preview(body.tool, args), s.max_inline_file_bytes) for rel in ctx.files
            ]
            return {"ok": True, "files": files}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @app.post("/api/chat")
    async def chat(body: ChatBody, request: Request) -> StreamingResponse:
        guard_request(request)
        mode = resolve_mode(request)
        if body.messages[-1].role != "user":
            raise ApiError(422, "invalid_request", "the last message must come from the user")
        if len(body.messages) > s.max_messages:
            raise ApiError(413, "too_many_messages", f"at most {s.max_messages} messages per conversation")
        if any(len(m.content) > s.max_message_chars for m in body.messages):
            raise ApiError(413, "message_too_long", f"a message is longer than {s.max_message_chars} characters")
        if len(body.attachments) > s.max_attachments:
            raise ApiError(413, "too_many_attachments", f"at most {s.max_attachments} attached documents")
        texts = [a for a in body.attachments if a.encoding == "text"]
        binaries = [a for a in body.attachments if a.encoding == "base64"]
        if any(len(a.content) > s.max_attachment_chars for a in texts):
            raise ApiError(
                413, "attachment_too_long", f"an attached document is longer than {s.max_attachment_chars} characters"
            )
        for a in binaries:
            if not a.name.lower().endswith(BINARY_ATTACHMENTS):
                raise ApiError(415, "attachment_type", "only PDF, DOCX, XLSX and PPTX files are sent as binary")
            if not re.fullmatch(r"[A-Za-z0-9+/=]*", a.content):
                raise ApiError(422, "attachment_invalid", "an attached file is not valid base64")
        if sum(len(a.content) for a in binaries) + sum(len(i.url) for i in body.images) > s.max_binary_chars:
            raise ApiError(413, "attachment_too_long", "the attached files and images are too large together")
        total = sum(len(m.content) for m in body.messages) + sum(len(a.content) for a in texts)
        if total > s.max_request_chars:
            raise ApiError(413, "request_too_large", "the conversation is too long: start a new one")
        if body.approved and body.denied:
            raise ApiError(422, "invalid_request", "approve or deny, not both")

        images = [{"name": sanitize_filename(i.name), "url": check_image(i.url)} for i in body.images]
        messages = [m.model_dump(exclude_none=True) for m in body.messages]
        attachments = [
            {"name": sanitize_filename(a.name), "content": a.content, "encoding": a.encoding} for a in body.attachments
        ]
        backend, binding = backend_for(mode, request)
        conv = tokens.digest(
            {
                "m": [{"role": m["role"], "content": m["content"]} for m in messages],
                "a": [[a["name"], tokens.digest(a["content"])] for a in attachments],
            }
        )
        resume, decision = None, None
        if body.approved or body.denied:
            try:
                resume = tokens.verify((body.approved or body.denied)[0], s.signing_secret)
            except tokens.TokenError as e:
                raise ApiError(400, "confirm_invalid", f"this confirmation cannot be used: {e}") from None
            if resume.get("conv") != conv or resume.get("bind") != binding:
                raise ApiError(400, "confirm_invalid", "this confirmation belongs to another conversation or model")
            decision = bool(body.approved)
        chat_request = ChatRequest(messages, body.thinking, body.lang, attachments, resume, decision, images)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        cancel = threading.Event()

        def emit(event: Event) -> None:
            if not cancel.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, event)

        def sign(payload: dict) -> str:
            return tokens.sign({**payload, "conv": conv, "bind": binding}, s.signing_secret, s.confirm_ttl)

        ctx = RunContext(emit, cancel, sign, time.monotonic() + s.max_seconds, s.max_inline_file_bytes)

        def worker() -> None:
            from birds.harness import guard
            from birds.harness.llm import EndpointError

            try:
                backend.run(chat_request, ctx)
            except Cancelled:
                pass
            except EndpointError as exc:  # the model endpoint, not the user: say it calmly, with a stable code
                emit({"type": "error", "code": exc.kind, "message": ep.explain(exc.kind, body.lang)})
            except Exception as exc:  # noqa: BLE001 - reported to the user as an error event
                emit(
                    {
                        "type": "error",
                        "code": "internal",
                        "message": guard.redact(str(exc))[:400] or exc.__class__.__name__,
                    }
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        async def stream():
            thread = threading.Thread(target=worker, name="bird-chat", daemon=True)
            thread.start()
            try:
                yield ": bird\n\n"  # first bytes at once, so proxies open the stream
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=s.heartbeat_seconds)
                    except TimeoutError:
                        yield ": keep-alive\n\n"  # SSE comment: keeps idle proxies from closing the connection
                        continue
                    if event is None:
                        break
                    yield _sse(apply_carbon(event, s.grid_intensity))
                yield _sse({"type": "done"})
            finally:
                cancel.set()  # client gone or run finished: unblock sleeps

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------ frontend

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "brand" / "favicon.svg", media_type="image/svg+xml")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": {"code": "not_found", "message": "not found"}}, status_code=404)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


IMAGE_MIN_PIXELS = 200_000  # below this, the live model hallucinated on a real test (400 x 220): refuse
IMAGE_MIN_SIDE = 300
IMAGE_MAX_SIDE = 2048  # the browser downsizes to 1568 px; anything larger did not come from our UI


def check_image(url: str) -> str:
    """Validate an image data URL: PNG, JPEG or WebP, decodable, within size bounds. Never stored."""
    import base64
    import io

    m = re.match(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$", url)
    if not m:
        raise ApiError(415, "image_type", "images must be PNG, JPEG or WebP data URLs")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            fmt, (w, h) = (im.format or "").lower(), im.size
    except Exception:
        raise ApiError(415, "image_invalid", "this image cannot be read") from None
    if fmt not in ("png", "jpeg", "webp"):
        raise ApiError(415, "image_type", "images must be PNG, JPEG or WebP")
    if w * h < IMAGE_MIN_PIXELS or min(w, h) < IMAGE_MIN_SIDE:
        raise ApiError(422, "image_too_small", f"image too small to be read reliably ({w}x{h})")
    if max(w, h) > IMAGE_MAX_SIDE:
        raise ApiError(413, "image_too_large", f"image too large ({w}x{h})")
    return url


def _sse(event: Event) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
