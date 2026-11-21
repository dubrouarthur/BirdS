"""FastAPI app for the Bird web chat: static frontend, SSE chat API, generated files."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .backends import SAFE_NAME, Backend, Cancelled, ChatRequest, ConfirmRegistry, Event, RunContext

STATIC_DIR = Path(__file__).parent / "static"

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
    "manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=200_000)


class ChatBody(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=200)
    thinking: bool = False
    lang: Literal["fr", "en"] = "fr"


class ConfirmBody(BaseModel):
    id: str = Field(max_length=64)
    allow: bool


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


def create_app(
    backend: Backend,
    workspace: Path | str | None = None,
    grid_intensity: float | None = None,
    confirm_timeout: float = 300.0,
) -> FastAPI:
    """Build the app. ``grid_intensity`` is in g CO2e/kWh; without it no CO2 figure is ever shown."""
    if grid_intensity is not None and grid_intensity < 0:
        raise ValueError("grid_intensity must be >= 0")
    root = Path(workspace) if workspace else Path(tempfile.mkdtemp(prefix="bird-workspace-"))
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()

    app = FastAPI(title="Bird", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.backend = backend
    app.state.workspace = root
    app.state.confirms = ConfirmRegistry()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {
            "model": backend.model,
            "backend": backend.kind,
            "tools": list(backend.tools),
            "thinking_default": False,
            # Extra, optional: lets the meter explain how CO2 is derived.
            "grid_intensity_g_per_kwh": grid_intensity,
        }

    @app.post("/api/chat")
    async def chat(body: ChatBody) -> StreamingResponse:
        if body.messages[-1].role != "user":
            raise HTTPException(422, "the last message must come from the user")
        request = ChatRequest([m.model_dump() for m in body.messages], body.thinking, body.lang)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        cancel = threading.Event()

        def emit(event: Event) -> None:
            if not cancel.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, event)

        ctx = RunContext(emit, app.state.confirms, cancel, root, confirm_timeout)

        def worker() -> None:
            try:
                backend.run(request, ctx)
            except Cancelled:
                pass
            except Exception as exc:  # noqa: BLE001 - reported to the user as an error event
                emit({"type": "error", "message": str(exc) or exc.__class__.__name__})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        async def stream():
            thread = threading.Thread(target=worker, name="bird-chat", daemon=True)
            thread.start()
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if event is None:
                        break
                    yield _sse(apply_carbon(event, grid_intensity))
                yield _sse({"type": "done"})
            finally:
                cancel.set()  # client gone or run finished: unblock sleeps and pending confirmations

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/confirm")
    def confirm(body: ConfirmBody) -> dict:
        if not app.state.confirms.resolve(body.id, body.allow):
            raise HTTPException(404, "unknown or expired confirmation")
        return {"ok": True}

    @app.get("/files/{name}")
    def files(name: str) -> FileResponse:
        if not SAFE_NAME.match(name) or ".." in name:
            raise HTTPException(404, "not found")
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path, filename=name, headers={"Cache-Control": "no-store"})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "bird.svg", media_type="image/svg+xml")

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "not found"}, status_code=404)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _sse(event: Event) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
