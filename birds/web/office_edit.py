"""``POST /api/office``: the in-app editor rebuilds a deck or a document from its edited plan, without the model.

The browser sends the plan it was given in the preview (titles, bullets or sections, the picture chosen for each
slide or section, cover, theme), the file it already holds (the pictures are taken back from it, by their
``bird-media:<id>`` names, and re-encoded) and the pictures the user added in the editor (data URLs). Same
generators as the agent; nothing is stored; same-origin, rate-limited and access-coded like ``/api/tool``.
"""

from __future__ import annotations

import base64
import binascii
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

MAX_FILE_B64 = 4_200_000
MAX_UPLOADS = 6
MAX_UPLOAD_B64 = 2_800_000
MAX_SLIDES, MAX_SECTIONS, MAX_TEXT = 60, 40, 200_000


class Upload(BaseModel):
    id: str = Field(pattern=r"^n\d{1,2}$")
    url: str = Field(max_length=MAX_UPLOAD_B64)
    alt: str = Field(default="", max_length=160)


class OfficeBody(BaseModel):
    tool: Literal["make_slides", "make_document"]
    args: dict
    theme: Literal["corporate", "modern", "warm"] | None = None
    cover: str | None = Field(default=None, max_length=12)
    media: list[dict] = Field(default_factory=list, max_length=20)  # the plan's media (ids, alt, credit, chart spec)
    sources: list[dict] = Field(default_factory=list, max_length=30)
    file: str | None = Field(default=None, max_length=MAX_FILE_B64)
    uploads: list[Upload] = Field(default_factory=list, max_length=MAX_UPLOADS)
    lang: Literal["fr", "en"] = "fr"


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _text(v, n: int) -> str:
    return str(v if v is not None else "")[:n]


def clean_args(tool: str, args: dict) -> dict:
    """The edited plan, reduced to what the generators read, with types and sizes checked."""
    title = _text(args.get("title"), 200).strip() or "Bird"
    out: dict = {"title": title, "subtitle": _text(args.get("subtitle"), 200)}
    if tool == "make_slides":
        slides = args.get("slides")
        if not isinstance(slides, list) or not 1 <= len(slides) <= MAX_SLIDES:
            raise _err(422, "invalid_plan", f"a deck needs 1 to {MAX_SLIDES} slides")
        out["slides"] = []
        for s in slides:
            if not isinstance(s, dict):
                raise _err(422, "invalid_plan", "each slide is an object")
            bullets = s.get("bullets") or []
            if not isinstance(bullets, list):
                raise _err(422, "invalid_plan", "bullets must be a list")
            slide = {"title": _text(s.get("title"), 300), "bullets": [_text(b, 1200) for b in bullets[:30]]}
            for k in ("image", "layout"):
                if isinstance(s.get(k), str) and len(s[k]) <= 16:
                    slide[k] = s[k]
            if s.get("notes"):
                slide["notes"] = _text(s["notes"], 4000)
            out["slides"].append(slide)
    else:
        sections = args.get("sections")
        if not isinstance(sections, list) or not 1 <= len(sections) <= MAX_SECTIONS:
            raise _err(422, "invalid_plan", f"a document needs 1 to {MAX_SECTIONS} sections")
        out["sections"] = []
        for s in sections:
            if not isinstance(s, dict):
                raise _err(422, "invalid_plan", "each section is an object")
            sec = {"heading": _text(s.get("heading"), 300), "content": _text(s.get("content"), 20_000)}
            figs = s.get("figures")
            if isinstance(figs, list):
                sec["figures"] = [f for f in figs[:6] if isinstance(f, str) and len(f) <= 12]
            out["sections"].append(sec)
    if sum(len(str(v)) for v in out.values()) > MAX_TEXT:
        raise _err(413, "too_large", "the plan is too long")
    return out


def rebuild_media(body: OfficeBody, workdir: Path) -> list:
    """The pictures for the rebuild: those of the previous file (by id), the charts of the plan, the new uploads."""
    from birds.harness import office_media as om
    from birds.harness.office_deck import media_in
    from birds.harness.tools.files import _check_zip

    known = {str(m.get("id")): m for m in body.media if isinstance(m, dict) and m.get("id")}
    media: list = []
    blobs: dict[str, bytes] = {}
    if body.file:
        try:
            raw = base64.b64decode(body.file, validate=True)
        except (binascii.Error, ValueError):
            raise _err(422, "bad_file", "the file is not valid base64") from None
        p = workdir / ("old.pptx" if body.tool == "make_slides" else "old.docx")
        p.write_bytes(raw)
        try:
            _check_zip(p)
            blobs = media_in(p)
        except Exception:  # noqa: BLE001 - a damaged file: rebuilt without its pictures
            blobs = {}
    for mid, meta in known.items():
        kind = meta.get("kind")
        if kind == "chart":
            if om.chart_spec_ok(meta.get("spec")):
                media.append(om.chart_media(meta["spec"], mid))
            continue
        if mid not in blobs or kind not in ("user", "web", "map"):
            continue
        try:
            m = om.prepare(blobs[mid], mid, kind, alt=_text(meta.get("alt"), 160), title=_text(meta.get("title"), 120))
        except om.ImageError:
            continue
        m.credit, m.licence, m.source = (_text(meta.get(k), 300) for k in ("credit", "licence", "source"))
        m.logo = bool(meta.get("logo"))
        if kind == "web" and not (m.credit and m.licence):
            continue  # a web picture never goes in without its credit
        media.append(m)
    for up in body.uploads:
        try:
            media.append(om.from_data_url(up.url, up.id, up.alt))
        except (om.ImageError, ValueError):
            raise _err(415, "image_invalid", "a picture added in the editor cannot be read") from None
    return om.budget(media)


def make_router(settings, guard_request, check_access) -> APIRouter:
    router = APIRouter()

    @router.post("/api/office")
    def office_edit(body: OfficeBody, request: Request) -> dict:
        guard_request(request)
        check_access(request)
        from birds.harness import Config, guard
        from birds.harness.config import Context
        from birds.harness.tools import TOOLS

        from .backends import inline_file, written_preview

        args = clean_args(body.tool, body.args)
        tmp = Path(tempfile.mkdtemp(prefix="bird-office-"))
        try:
            media = rebuild_media(body, tmp)
            args.update(_media=media, theme=body.theme, sources=[s for s in body.sources if isinstance(s, dict)])
            if body.cover:
                args["cover"] = body.cover
            ctx = Context(config=Config(workspace=tmp, audit_file=None), http=None, lang=body.lang)
            try:
                TOOLS[body.tool](args, ctx)
            except (guard.ToolError, guard.Blocked) as e:
                return {"ok": False, "error": str(e)}
            files = [inline_file(tmp / rel, written_preview(body.tool, args, ctx.step_info),
                                 settings.max_inline_file_bytes) for rel in ctx.files]  # fmt: skip
            return {"ok": True, "files": files}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return router
