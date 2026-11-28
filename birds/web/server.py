"""FastAPI app for the Bird web chat: static frontend + a small stateless API (see docs/WEB.md).

Nothing is kept in memory between requests except a best-effort rate-limit window and the note queues of the Mode
Agent runs at work in this process (birds.harness.crew_plan.REGISTRY; a note that misses its run is carried by the
browser into the next slice): the app runs unchanged on a long-lived local server (scripts/serve.py) and on
serverless functions (app.py, Vercel).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import endpoint as ep
from . import tokens
from . import widgets as widgets_mod
from .backends import Backend, Cancelled, ChatRequest, DemoBackend, Event, HarnessBackend, RunContext, sanitize_filename
from .settings import ENERGY_SOURCES, Settings

STATIC_DIR = Path(__file__).parent / "static"
SITE_DIR = Path(__file__).resolve().parents[2] / "site"  # corporate site, served under /a-propos/

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; font-src 'self'; connect-src 'self'; "
    "frame-src 'self'; "  # only the canvas preview frame (/canvas/frame, sandboxed, no network: see canvas_web)
    
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
INTERNAL_ERROR = {"fr": "Une erreur interne est survenue.", "en": "Something went wrong on our side."}


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    memo: str | None = Field(default=None, max_length=4000)  # compact record of the tools of that turn
    interrupted: bool = False  # the answer was stopped or cut by max_tokens: marked as such in the history


class ImageIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=32, max_length=1_500_000)  # data:image/(png|jpeg|webp);base64,...


class Attachment(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: str
    encoding: Literal["text", "base64"] = "text"  # base64: an office file or PDF, read by read_file on the server
    # what an earlier turn of this conversation read on the scanned pages of this PDF ({"2": "text"}): sent back by
    # the browser so the pages are not read again. Untrusted like the file itself: capped and defanged on use.
    ocr: dict[str, str] | None = Field(default=None, max_length=50)
    # brought by THIS message (the app re-sends every attachment of the conversation each turn): a table of an
    # earlier message is computed on only when the turn asks for it (birds/harness/analysis/hooks.brought)
    fresh: bool | None = None


BINARY_ATTACHMENTS = (".pdf", ".docx", ".xlsx", ".pptx")


_Short = Annotated[str, Field(max_length=300)]


class PlanEditsIn(BaseModel):
    """The plan card's typed fields only (crew_plan.apply_edits re-validates each value: enums, 3–12 slides,
    headings and domains cleaned). Unknown keys are dropped; a value of the wrong type is a 422, never a 500."""

    model_config = ConfigDict(extra="ignore")

    audience: Literal["general", "decision", "experts"] | None = None
    length: Literal["short", "standard", "long"] | None = None
    n_slides: int | None = Field(default=None, ge=1, le=50)
    sections: list[_Short] | None = Field(default=None, max_length=16)
    prefer: list[_Short] | None = Field(default=None, max_length=12)
    exclude: list[_Short] | None = Field(default=None, max_length=12)
    focus: str | None = Field(default=None, max_length=400)


class AgentPlanIn(BaseModel):
    """« Lancer » on the plan card: the signed plan and the user's edits of its typed fields (crew_plan.apply_edits)."""

    token: str = Field(min_length=16, max_length=60_000)
    edits: PlanEditsIn = Field(default_factory=PlanEditsIn)


class AgentNoteIn(BaseModel):
    """A typed instruction added while the team works (crew_plan.parse_note validates the value for its kind)."""

    kind: Literal["exclude_site", "prefer_site", "audience", "length", "add_section", "focus"]
    value: str = Field(min_length=1, max_length=200)
    id: str = Field(default="", max_length=24)


class AgentNoteBody(AgentNoteIn):
    run: str = Field(min_length=8, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")


class ChatBody(BaseModel):
    messages: list[Message] = Field(min_length=1)
    thinking: bool = False
    # Mode Réflexion (birds.harness.reflexion): « auto » or a bird; omitted, ``thinking`` alone decides (older clients)
    reflexion: Literal["auto", "colibri", "hirondelle", "faucon", "chouette", "albatros"] | None = None
    agent: Literal["auto", "on", "off"] = "auto"  # Mode Agent (birds.harness.crew): Auto, Activé, Désactivé
    # Mode Agent, wave 2: "plan" asks for the plan card first (the app); omitted, a decided team starts at once (API)
    agent_flow: Literal["plan", "run"] | None = None  # "run": the app, the team starts at once (no plan card first)
    agent_plan: AgentPlanIn | None = None  # « Lancer »: the signed plan, edited
    agent_slice: str | None = Field(default=None, max_length=600_000)  # the next slice of a long task (signed state)
    agent_notes: list[AgentNoteIn] = Field(default_factory=list, max_length=12)  # notes not delivered live
    lang: Literal["fr", "en"] = "fr"
    attachments: list[Attachment] = Field(default_factory=list)
    images: list[ImageIn] = Field(default_factory=list, max_length=3)  # for the last user message only
    approved: list[str] = Field(default_factory=list, max_length=1)  # confirm token the user approved
    denied: list[str] = Field(default_factory=list, max_length=1)  # confirm token the user refused
    conv_lang: Literal["fr", "en"] | None = None  # pinned at the first message of the conversation
    conversation_id: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    tz: str | None = Field(default=None, max_length=64)  # Intl.DateTimeFormat().resolvedOptions().timeZone
    canvas: dict | None = None  # the artifact open in the canvas ({aid, version, doc, target}): see canvas_web


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
        **s.energy_config,
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
        "widgets": s.geo,
        "geo_user_agent": s.geo_user_agent,
        "geo_cache_dir": s.geo_cache_dir,
        **{
            k: getattr(s, k)
            for k in ("nominatim_url", "photon_url", "ban_url", "company_url", "fx_url", "met_url")
            if getattr(s, k, None)
        },
    }


def build_server_backend(s: Settings) -> Backend | None:
    """The operator's model: an OpenAI-compatible endpoint, or a model loaded in this process (local use)."""
    if s.local_llm is not None:
        local = HarnessBackend(
            s.local_llm,
            s.local_tok,
            kind="local",
            model=s.model,
            workspace=s.workspace,
            config=harness_config(s),
            history_tokens=s.history_tokens,
            msg_cap_tokens=s.history_msg_tokens,
            cache_isolation=s.cache_isolation,
        )
        local.canvas = s.canvas
        return local
    if not s.base_url:
        return None
    from birds.harness import CompletionsClient

    tok = None
    if s.tokenizer:  # optional: the real tokenizer instead of the vendored chat template (needs transformers)
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(s.tokenizer)
    llm = CompletionsClient(s.base_url, s.model, s.api_key, timeout=s.max_seconds)
    backend = HarnessBackend(
        llm,
        tok,
        kind="completions",
        model=s.model,
        workspace=s.workspace,
        config=harness_config(s),
        http=fetch_client(s),
        history_tokens=s.history_tokens,
        msg_cap_tokens=s.history_msg_tokens,
        cache_isolation=s.cache_isolation,
    )
    backend.canvas = s.canvas
    return backend


def fetch_client(s: Settings):
    """read_page's HTTP client. Behind a filtering egress proxy (BIRD_PIN_DNS=0) it uses the proxy settings."""
    if s.pin_dns:
        return None  # the harness default: no proxy variables, connection pinned to the validated address
    import httpx

    return httpx.Client(follow_redirects=False)


def image_client(s: Settings):
    """A fresh client for one /api/img fetch: no proxy variables (unless behind a filtering proxy, like read_page),
    no redirects followed by httpx (guard.fetch_image checks each hop), and so no cookie jar shared between images."""
    import httpx

    return fetch_client(s) or httpx.Client(trust_env=False, follow_redirects=False)


class ImageCache:
    """Small in-process LRU of re-encoded images: 32 entries, 6 MB, 1 hour. Best effort, per instance."""

    def __init__(self, entries: int = 32, max_bytes: int = 6_000_000, ttl: float = 3600.0):
        from collections import OrderedDict

        self.entries, self.max_bytes, self.ttl = entries, max_bytes, ttl
        self._data: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> bytes | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None or time.monotonic() - hit[0] > self.ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return hit[1]

    def put(self, key: str, data: bytes) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), data)
            self._data.move_to_end(key)
            while len(self._data) > self.entries or sum(len(v[1]) for v in self._data.values()) > self.max_bytes:
                self._data.popitem(last=False)


IMG_MAX_BYTES = 2_000_000
# 16 Mpx is ample for a 640 px card. A small compressible file can still decode big (an 8000 x 5000 RGBA PNG of
# 165 KB is 160 MB of pixels), so decoding is also bounded in concurrency.
IMG_MAX_PIXELS = 16_000_000
IMG_DECODES = threading.BoundedSemaphore(3)
IMG_MAX_SIDE, IMG_MIN_SIDE, IMG_OUT_SIDE = 8000, 64, 640
_MAGIC = {
    "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "image/gif": lambda b: b[:6] in (b"GIF87a", b"GIF89a"),
    "image/webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}


def reencode_image(ctype: str, raw: bytes) -> bytes:
    """Check the bytes really are the declared type, then re-encode the first frame as WebP, long side <= 640 px.
    Re-encoding drops EXIF/GPS and any payload hidden in the file. Raises ApiError."""
    import io

    from PIL import Image, ImageOps

    if not _MAGIC.get(ctype, lambda b: False)(raw):
        raise ApiError(415, "image_type", "the file is not the image type it claims to be")
    import warnings

    try:
        with warnings.catch_warnings():  # the size check below refuses bombs before decoding: no warning needed
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(raw))
        with im:
            w, h = im.size
            if w * h > IMG_MAX_PIXELS or max(w, h) > IMG_MAX_SIDE:
                raise ApiError(422, "image_invalid", "image too large to decode")
            if min(w, h) < IMG_MIN_SIDE:
                raise ApiError(422, "image_too_small", "image too small to show")
            im.seek(0)
            # no full-size copy: JPEG decodes at a reduced scale (draft), the rest is reduced in place
            if im.format == "JPEG":
                im.draft("RGB", (2 * IMG_OUT_SIDE, 2 * IMG_OUT_SIDE))
            with IMG_DECODES:
                im.thumbnail((IMG_OUT_SIDE, IMG_OUT_SIDE), reducing_gap=2.0)
            frame = ImageOps.exif_transpose(im)  # on the small image: a small copy, detached from the file
            alpha = frame.mode in ("RGBA", "LA") or (frame.mode == "P" and "transparency" in frame.info)
            frame = frame.convert("RGBA" if alpha else "RGB")
    except ApiError:
        raise
    except Exception:  # noqa: BLE001 - truncated, corrupt or a decompression bomb
        raise ApiError(422, "image_invalid", "this image cannot be read") from None
    out = io.BytesIO()
    frame.save(out, "WEBP", quality=80, method=4)
    return out.getvalue()


TOOL_TEXT = {  # why a tool is on or off on this deployment, for the "available tools" panel
    "web_search": ("Recherche : {label}", "Search: {label}"),
    # no search backend label (the demo, or a backend that does not name itself): a whole sentence, never "Recherche :"
    "web_search_plain": ("Cherche sur le web et cite ses sources", "Searches the web and cites its sources"),
    "web_search_off": (
        "Désactivée par l'exploitant (BIRD_SEARCH_DEFAULT=none)",
        "Switched off (BIRD_SEARCH_DEFAULT=none)",
    ),
    "read_page": ("Lit une page publique (http/https, adresses publiques, 2 Mo au plus)", "Reads a public page"),
    "read_file": (
        "Actif quand vous joignez un document (texte, PDF, Word, Excel, PowerPoint) ou une image",
        "Active when you attach a document (text, PDF, Word, Excel, PowerPoint) or an image",
    ),
    "read_file_ws": ("Lit les fichiers du dossier de travail du serveur", "Reads files in the server workspace"),
    "draft_email": ("Prépare un brouillon ; rien n'est envoyé", "Prepares a draft; nothing is sent"),
    "make_slides": ("Crée un .pptx, téléchargeable ici", "Creates a .pptx, downloadable here"),
    "make_document": ("Crée un .docx, téléchargeable ici", "Creates a .docx, downloadable here"),
    "make_sheet": ("Crée un .xlsx, téléchargeable ici", "Creates a .xlsx, downloadable here"),
    "make_chart": (
        "Affiche un graphique dans la conversation (barres, courbe, camembert)",
        "Shows a chart in the chat (bar, line, pie)",
    ),
    "find_places": ("Cherche des lieux et adresses (OpenStreetMap)", "Finds places and addresses (OpenStreetMap)"),
    "find_company": ("Consulte l'annuaire officiel des entreprises", "Looks up the official French company register"),
    "convert_currency": ("Convertit une somme au taux BCE du jour", "Converts an amount at the ECB rate of the day"),
    "get_weather": ("Prévisions météo (MET Norway)", "Weather forecast (MET Norway)"),
    "run_python": (
        "Désactivé : exécuter du code demande un vrai bac à sable, absent de ce déploiement",
        "Off: running code needs a real sandbox, which this deployment does not have",
    ),
}
# --- open data (birds/opendata_schemas.py)
from birds.opendata_schemas import OPENDATA_TEXT  # noqa: E402

TOOL_TEXT.update(OPENDATA_TEXT)
# --- end open data


def tools_info(s: Settings, backend) -> dict:
    """Which tools the model may use here, which are off, and why. Also which search backend answers."""
    from birds.tools import PRODUCT_TOOL_NAMES

    offered = set(getattr(backend, "tools", []) or [])
    search = getattr(backend, "search_info", None) or {}
    out = []
    for name in PRODUCT_TOOL_NAMES:
        state = "on" if name in offered else "off"
        key = name
        if name == "read_file" and s.workspace is None and getattr(backend, "kind", "") != "demo":
            state, key = "attach", "read_file"
        elif name == "read_file":
            key = "read_file_ws"
        elif name == "web_search" and state == "off":
            key = "web_search_off"
        label = search.get("label") or ""
        if key == "web_search" and not label.strip():
            key = "web_search_plain"
        fr, en = TOOL_TEXT.get(key, ("", ""))
        out.append({"name": name, "state": state, "fr": fr.format(label=label), "en": en.format(label=label)})
    return {"tools": out, "search": search}


def peer_ip(request, trusted_proxies: int = 0) -> str:
    """The client address for the rate limiters. X-Forwarded-For is written by the client and is only read when the
    operator says how many proxies of their own sit in front (``BIRD_TRUSTED_PROXIES``, 1 on Vercel): each proxy
    appends the address it saw, so the client is the N-th entry from the right, never the first one."""
    peer = request.client.host if request.client else "?"
    if trusted_proxies <= 0:
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return hops[-min(trusted_proxies, len(hops))] if hops else peer


def create_app(
    settings: Settings | None = None, *, server_backend: Backend | None = None, demo: Backend | None = None
) -> FastAPI:
    """Build the app. ``server_backend`` / ``demo`` override what the settings would build (tests)."""
    s = settings or Settings()
    if s.grid_intensity is not None and s.grid_intensity < 0:
        raise ValueError("grid_intensity must be >= 0")
    demo = demo or DemoBackend(delay=s.demo_delay, energy=s.energy_config if s.demo_energy else None)
    server = server_backend if server_backend is not None else build_server_backend(s)
    limiter = RateLimiter(s.rate_limit)
    img_limiter = RateLimiter(s.img_rate_limit)
    img_cache = ImageCache()

    app = FastAPI(title="Bird", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.demo, app.state.server_backend = s, demo, server
    # upstream client for /api/img: a fresh one per image (no cookie jar survives); tests swap in a mock transport
    app.state.image_client = lambda: image_client(s)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        from .canvas_web import frame_request_refused

        if frame_request_refused(request):  # only /canvas/frame may load in a frame (the sandboxed preview)
            response = PlainTextResponse("frame refused", status_code=403)
        else:
            response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        path = request.url.path
        if path.startswith("/static/"):
            # browsers revalidate; a CDN in front may keep a copy until the next deployment
            response.headers["Cache-Control"] = "public, max-age=0, s-maxage=86400, must-revalidate"
        elif path == "/" or path == "/manifest.webmanifest":
            response.headers["Cache-Control"] = "no-cache"
        elif path == "/api/img" and response.status_code == 200:
            pass  # a re-encoded public image, signed URL: cacheable (set by the route)
        elif path in ("/api/map", "/api/icon") and response.status_code == 200:
            pass  # same-origin images: "private, max-age=86400" set by birds.web.mapimg
        elif path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if path == "/canvas/frame":
            from .canvas_web import frame_headers

            frame_headers(response)  # the sandboxed preview frame has its own, stricter-on-network policy
        return response

    # ------------------------------------------------------------------ request guards

    def client_ip(request: Request) -> str:
        return peer_ip(request, settings.trusted_proxies)

    def same_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
            if origin.split("://", 1)[-1].rstrip("/").lower() != host.lower():
                raise ApiError(403, "cross_origin", "cross-origin requests are not accepted")
        if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            raise ApiError(403, "cross_origin", "cross-origin requests are not accepted")

    def guard_request(request: Request) -> None:
        """Same-origin only (no CORS headers are ever sent), then the best-effort rate limit."""
        same_origin(request)
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
            llm,
            kind="completions",
            model=model,
            config=cfg,
            http=fetch_client(s),
            history_tokens=s.history_tokens,
            msg_cap_tokens=s.history_msg_tokens,
            cache_isolation=s.cache_isolation,
        )
        backend.canvas = s.canvas
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
                "method": s.energy_method,
                "tokens": {
                    "wh_per_1k_out": s.wh_per_1k_out,
                    "wh_per_1k_in": s.wh_per_1k_in,
                    "wh_per_1k_out_range": s.energy_config["wh_per_1k_out_range"],
                    "wh_per_1k_in_range": s.energy_config["wh_per_1k_in_range"],
                    "serving_overhead": s.energy_config["serving_overhead"],
                    "sources": [dict(x) for x in ENERGY_SOURCES],
                },
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
            "thinking_default": True,
            "reflexion_default": "auto",
            "default_mode": default_mode(),
            "modes": {"demo": True, "server": server is not None, "user": bool(s.allow_user_endpoint)},
            "demo_model": demo.model,
            "access_required": bool(s.access_code),
            "images": bool(getattr(shown, "images", False)),
            "site_url": "/a-propos/" if (SITE_DIR / "index.html").is_file() else None,
            "images_modes": {
                "demo": bool(getattr(demo, "images", False)),
                "server": bool(getattr(server, "images", False)) if server is not None else False,
                "user": bool(s.allow_user_endpoint),  # confirmed per endpoint by "Tester la connexion"
            },
            "image_limits": {"min_pixels": IMAGE_MIN_PIXELS, "min_side": IMAGE_MIN_SIDE, "max_side": 1568, "max": 3},
            "history_tokens": s.history_tokens,
            "history_msg_tokens": s.history_msg_tokens,
            "cache_isolation": "salted" if s.cache_isolation else "off",
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

    @app.post("/api/agent/note")
    def agent_note(body: AgentNoteBody, request: Request) -> dict:
        """« Ajouter une consigne »: a typed instruction for a team at work in this process. Not here (another
        instance, or between two slices): ``delivered`` is false and the browser sends it with the next slice."""
        guard_request(request)
        from birds.harness import crew_plan

        note = crew_plan.parse_note(body.kind, body.value, body.id)
        if note is None:
            raise ApiError(422, "note_invalid", "this instruction is not valid for its kind")
        return {"ok": True, "delivered": crew_plan.REGISTRY.deliver(body.run, note), "id": note.id,
                "kind": note.kind, "value": note.value}  # fmt: skip

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

        from .backends import inline_file, written_preview

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
                inline_file(tmp / rel, written_preview(body.tool, args, ctx.step_info), s.max_inline_file_bytes)
                for rel in ctx.files
            ]
            return {"ok": True, "files": files}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---- data analysis hook (birds/web/data_api.py): the data card's full table and one-click analyses
    from .data_api import register as _data_routes

    _data_routes(app, guard_request, check_access, ApiError)

    @app.get("/api/img")
    def web_image(request: Request):
        """A web image Bird credited in an answer, fetched by the server and re-encoded, so the browser never
        contacts a third-party host. Only URLs this server signed are served (not an open proxy)."""
        from fastapi.responses import Response

        from birds.harness import Config, guard

        same_origin(request)
        if not img_limiter.allow(client_ip(request)):
            raise ApiError(429, "rate_limited", "too many requests, wait a minute")
        q = request.query_params
        u, e, sig = q.get("u") or "", q.get("e") or "", q.get("s") or ""
        if (
            not u
            or len(u) > 2048
            or not re.fullmatch(r"https?://\S+", u)
            or not re.fullmatch(r"\d{1,12}", e)
            or not re.fullmatch(r"[0-9a-f]{32}", sig)
        ):
            raise ApiError(400, "bad_request", "missing or invalid image parameters")
        try:
            tokens.check_image_sig(u, e, sig, s.signing_secret)
        except tokens.TokenError as err:
            if str(err) == "expired":
                raise ApiError(410, "expired", "this image link has expired") from None
            raise ApiError(403, "bad_signature", "this image link was not issued here") from None
        host = (urlsplit(u).hostname or "?").lower()
        headers = {
            "Cache-Control": "public, max-age=3600, s-maxage=86400",
            "Content-Disposition": 'inline; filename="image.webp"',
        }
        cached = img_cache.get(u)
        if cached is not None:
            return Response(cached, media_type="image/webp", headers=headers)
        status, size = 200, 0
        try:
            cfg = Config(workspace=Path("."), audit_file=None, pin_dns=s.pin_dns)
            client = app.state.image_client()
            try:
                ctype, raw = guard.fetch_image(client, cfg, u, max_bytes=IMG_MAX_BYTES, timeout=8.0)
            finally:
                client.close()
            size = len(raw)
            data = reencode_image(ctype, raw)
        except guard.Blocked:
            status = 403
            raise ApiError(403, "blocked", "this address is not allowed") from None
        except guard.FetchError as err:
            status, code = {"image_type": (415, "image_type"), "too_large": (413, "too_large")}.get(
                err.code, (502, "upstream")
            )
            raise ApiError(status, code, "the image could not be fetched") from None
        except ApiError as err:
            status = err.status_code
            raise
        finally:
            print(json.dumps({"event": "img", "host": host, "status": status, "bytes": size}), flush=True)
        img_cache.put(u, data)
        return Response(data, media_type="image/webp", headers=headers)

    @app.post("/api/chat")
    async def chat(body: ChatBody, request: Request) -> StreamingResponse:
        guard_request(request)
        mode = resolve_mode(request)
        if body.messages[-1].role != "user":
            raise ApiError(422, "invalid_request", "the last message must come from the user")
        if len(body.messages) > s.max_messages:
            raise ApiError(413, "too_many_messages", f"at most {s.max_messages} messages per conversation")
        # earlier user turns come back as the exact text the model received (image transcriptions and attachment
        # notes included), so they may exceed the raw limit by USER_SENT_EXTRA, derived from the code's own caps
        extra = user_sent_extra(s)
        if any(len(m.content) > s.max_message_chars + (extra if m.role == "user" else 0) for m in body.messages):
            raise ApiError(413, "message_too_long", f"a message is longer than {s.max_message_chars} characters")
        if (body.images or body.attachments) and len(body.messages[-1].content) > s.max_message_chars:
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
        total += sum(len(k) + len(v) for a in body.attachments for k, v in (a.ocr or {}).items())
        if total > s.max_request_chars:
            raise ApiError(413, "request_too_large", "the conversation is too long: start a new one")
        if body.approved and body.denied:
            raise ApiError(422, "invalid_request", "approve or deny, not both")

        canvas_in = None
        if body.canvas is not None:
            from . import canvas_web

            if len(json.dumps(body.canvas, ensure_ascii=False)) > canvas_web.MAX_DOC_CHARS:
                raise ApiError(413, "canvas_too_large", "the document open in the canvas is too large")
            canvas_in = canvas_web.canvas_in(body.canvas)  # invalid: the turn runs without it
        images = [{"name": sanitize_filename(i.name), "url": check_image(i.url)} for i in body.images]
        messages = [m.model_dump(exclude_none=True) for m in body.messages]
        attachments = [
            {
                "name": sanitize_filename(a.name),
                "content": a.content,
                "encoding": a.encoding,
                **({"ocr": a.ocr} if a.ocr and a.encoding == "base64" else {}),
                **({"fresh": a.fresh} if a.fresh is not None else {}),
            }
            for a in body.attachments
        ]
        backend, binding = backend_for(mode, request)
        conv = tokens.digest(
            {
                "m": [{k: m.get(k) for k in ("role", "content", "memo", "interrupted")} for m in messages],
                "a": [[a["name"], tokens.digest(a["content"])] for a in attachments],
                "cid": body.conversation_id,
                "lang": body.conv_lang,
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
        agent_plan = agent_slice = None
        try:  # the plan card's « Lancer » and the next slice of a long task carry state signed by this server
            if body.agent_plan is not None:
                agent_plan = {"payload": tokens.verify(body.agent_plan.token, s.signing_secret),
                              "edits": body.agent_plan.edits.model_dump(exclude_none=True)}  # fmt: skip
                if agent_plan["payload"].get("k") != "crew_plan":
                    raise tokens.TokenError("not a plan")
            if body.agent_slice:
                agent_slice = tokens.verify(body.agent_slice, s.signing_secret)
                if agent_slice.get("k") != "crew_slice":
                    raise tokens.TokenError("not a slice")
        except tokens.TokenError as e:
            raise ApiError(400, "agent_state_invalid", f"this agent state cannot be used: {e}") from None
        for got in (agent_plan and agent_plan["payload"], agent_slice):
            if got is not None and (got.get("conv") != conv or got.get("bind") != binding):
                raise ApiError(400, "agent_state_invalid", "this agent state belongs to another conversation or model")
        once = ticket = None  # a signed agent state runs once at a time, and not again once its run ended normally
        if agent_slice is not None:
            once = f"slice:{agent_slice.get('run')}:{agent_slice.get('slice')}"
        elif agent_plan is not None:
            once = "plan:" + tokens.digest(body.agent_plan.token)
        if once is not None:
            from birds.harness import crew_plan

            ticket = crew_plan.ONCE.claim(once)
            if ticket is None:
                raise ApiError(409, "agent_state_used", "this agent step is already running or done")

        def release(finished: bool) -> None:
            if once is not None:  # cut or failed: the same state can be used again (« Reprendre »)
                from birds.harness import crew_plan

                crew_plan.ONCE.release(once, ticket, finished)
        from birds.harness import reflexion as reflexion_mod

        # a chosen bird sets the reasoning switch the rest of the app reads; « auto » reasons unless Bird picks
        # Colibri (decided in the run, reflexion.decide)
        thinking = body.thinking if body.reflexion is None else body.reflexion == "auto" or (
            reflexion_mod.level(body.reflexion).thinking)  # fmt: skip
        chat_request = ChatRequest(
            messages,
            thinking,
            body.lang,
            attachments,
            resume,
            decision,
            images,
            conv_lang=body.conv_lang,
            conversation_id=body.conversation_id,
            tz=str(widgets_mod.tz_or_default(body.tz)),
            agent=body.agent,
            agent_flow=body.agent_flow,
            agent_plan=agent_plan,
            agent_slice=agent_slice,
            agent_notes=[n.model_dump() for n in body.agent_notes],
            reflexion=body.reflexion,
            canvas=canvas_in,
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        cancel = threading.Event()

        def emit(event: Event) -> None:
            if not cancel.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, event)

        def sign(payload: dict) -> str:
            return tokens.sign({**payload, "conv": conv, "bind": binding}, s.signing_secret, s.confirm_ttl)

        ctx = RunContext(
            emit,
            cancel,
            sign,
            time.monotonic() + s.max_seconds,
            s.max_inline_file_bytes,
            sign_image=lambda u: tokens.sign_image_url(u, s.signing_secret, s.image_ttl),
            secret=s.signing_secret,
            geo={
                "on": s.geo,
                "layer": s.tile_layer,
                "holiday_url": s.holiday_url if s.geo else None,
                "holiday_zone": s.holiday_zone,
            },
        )

        def worker() -> None:
            from birds.harness import guard
            from birds.harness.llm import EndpointError

            finished = False
            try:
                backend.run(chat_request, ctx)
                finished = not cancel.is_set()
            except Cancelled:
                pass
            except EndpointError as exc:  # the model endpoint, not the user: say it calmly, with a stable code
                emit({"type": "error", "code": exc.kind, "message": ep.explain(exc.kind, body.lang)})
            except Exception as exc:  # noqa: BLE001 - reported to the user as an error event
                # a plain sentence for the user; the redacted exception text only as a technical detail
                emit(
                    {
                        "type": "error",
                        "code": "internal",
                        "message": INTERNAL_ERROR["en" if body.lang == "en" else "fr"],
                        "detail": guard.redact(str(exc))[:400] or exc.__class__.__name__,
                    }
                )
            finally:
                release(finished)
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
                if not cancel.is_set():  # the client left first: its state is free at once for « Reprendre »
                    release(False)
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

    @app.exception_handler(RequestValidationError)
    async def invalid_body(request: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI's 422, without echoing the input back: a value such as Infinity (valid for Python's json)
        cannot be written as JSON, and a body is not to be repeated in an error anyway."""
        errs = [{"loc": list(e.get("loc") or ()), "msg": str(e.get("msg") or "")[:200], "type": str(e.get("type") or "")}
                for e in exc.errors()][:20]  # fmt: skip
        return JSONResponse({"detail": errs}, status_code=422)

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": {"code": "not_found", "message": "not found"}}, status_code=404)

    from . import mapimg, office_edit

    def _geo_cfg():
        from birds.harness import Config

        return Config(workspace=Path(tempfile.gettempdir()), audit_file=None, **harness_config(s))

    app.include_router(mapimg.make_router(s, _geo_cfg))
    app.include_router(office_edit.make_router(s, guard_request, check_access))  # the deck/document editor
    from . import canvas_web

    app.include_router(canvas_web.make_router(s, guard_request, check_access, resolve_mode, image_client))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    if SITE_DIR.is_dir():
        import mimetypes
        import re as _re

        from fastapi.responses import RedirectResponse, Response

        site_root = SITE_DIR.resolve()
        # the site is written for its own domain (links like "/demarche", "/assets/site.css"): under /a-propos/
        # those root-relative links are rewritten on the fly, and clean URLs map to their .html file
        root_link = _re.compile(r'((?:href|src|srcset|action|content)=")/(?!/)')
        # only what a page needs: README.md, COPY.md, vercel.json and other internal files stay private
        site_types = {".html", ".css", ".js", ".webp", ".png", ".svg", ".ico", ".woff2"}

        def site_file(path: str) -> Path | None:
            target = (site_root / path).resolve()
            if site_root not in target.parents and target != site_root:
                return None
            for cand in (target, target.with_suffix(".html") if not target.suffix else None, target / "index.html"):
                if cand is not None and cand.is_file():
                    return cand if cand.suffix.lower() in site_types else None
            return None

        @app.get("/a-propos", include_in_schema=False)
        def about_site() -> RedirectResponse:
            return RedirectResponse("/a-propos/", status_code=308)

        @app.get("/a-propos/{path:path}", include_in_schema=False)
        def about_page(path: str = ""):
            f = site_file(path.strip("/"))
            if f is None:
                raise HTTPException(status_code=404)
            if f.suffix == ".html":
                html = root_link.sub(r"\1/a-propos/", f.read_text(encoding="utf-8"))
                return Response(html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
            kind = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            return FileResponse(f, media_type=kind, headers={"Cache-Control": "public, max-age=3600"})

    return app


IMAGE_MIN_PIXELS = 200_000  # below this, the live model hallucinated on a real test (400 x 220): refuse
IMAGE_MIN_SIDE = 300
IMAGE_MAX_SIDE = 2048  # the browser downsizes to 1568 px; anything larger did not come from our UI


def user_sent_extra(s: Settings) -> int:
    """Largest growth of a user message between what the user typed and what the model received (3.3.1)."""
    from birds.harness import guard

    from .backends import _ATTACH_NOTE, _IMAGE_NOTE, ATTACH_DIR, IMAGE_TEXT_CHARS

    note = 2 + max(map(len, _IMAGE_NOTE.values())) + 4 + 160 + 1 + max(map(len, guard.UNTRUSTED_NOTE.values())) + 1
    attach = 1 + max(map(len, _ATTACH_NOTE.values())) + 4 + len(ATTACH_DIR) + 1 + 160 + 1
    return 3 * (IMAGE_TEXT_CHARS + note) + s.max_attachments * attach


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
