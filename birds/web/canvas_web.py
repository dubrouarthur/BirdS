"""The canvas in the web app: chat-turn hooks, SSE events, the export / image / check endpoints and the sandboxed
preview frame (see docs/CANVAS.md).

Events sent on the chat stream:

* ``{"type": "canvas", "phase": "stream"|"final"|"abort", "aid", "base", "doc", "label", "open"}`` — a snapshot
  of the artifact ``aid`` (``base``: the version it was built from, None for a new artifact). The browser shows
  ``stream`` snapshots as a draft and commits ``final`` as a new version.
* ``{"type": "canvas_media", "aid", "media": [{"id", "data" (base64), "credit", "licence", "source", …}]}``.

Kept apart from backends.py and server.py (a few hooks there).
"""

from __future__ import annotations

import dataclasses
import re
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from birds.canvas import convert, dsl, images, patch, turn

MAX_DOC_CHARS = 400_000  # a document sent back by the browser, as JSON
MAX_MEDIA = 10
MAX_MEDIA_B64 = 700_000  # one picture (the canvas keeps them under 240 kB)
MAX_BODY = 4_400_000  # Vercel's request limit is 4.5 MB

# ------------------------------------------------------------------ the chat turn


def canvas_in(raw) -> dict | None:
    """The artifact the browser sent with the message, validated (None when absent or invalid: the turn then runs
    as an ordinary one, it never fails for it). The browser sends the document only while the panel is shown, or
    for the one turn after the artifact was made or changed (``open`` False then); otherwise only a reference
    ({'aid', 'version', 'kind', 'open': False}), returned with ``ref`` True and no document."""
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("doc"), dict):
        aid = raw.get("aid")
        if not (isinstance(aid, str) and re.fullmatch(r"a[0-9a-f]{12}|l[0-9a-f]{6,20}", aid)):
            return None
        kind = raw.get("kind") if raw.get("kind") in ("deck", "doc", "code", "sheet") else "deck"
        ver = raw.get("version") if isinstance(raw.get("version"), int) and 0 < raw["version"] < 10_000 else 1
        return {"ref": True, "aid": aid, "kind": kind, "version": ver, "open": False}
    try:
        doc = dsl.validate(raw["doc"])
    except dsl.Invalid:
        return None
    aid = raw.get("aid") if isinstance(raw.get("aid"), str) and re.fullmatch(r"a[0-9a-f]{12}", raw["aid"]) else None
    ver = raw.get("version") if isinstance(raw.get("version"), int) and 0 < raw["version"] < 10_000 else 1
    target = (
        raw.get("target") if isinstance(raw.get("target"), str) and re.fullmatch(r"b\d{1,4}", raw["target"]) else None
    )
    shown = raw.get("open") is not False  # an older page sent no flag: its panel was the one shown
    return {"doc": doc, "aid": aid or turn.new_aid(), "version": ver, "target": target if shown else None,
            "open": shown, "fresh": raw.get("fresh") is True}  # fmt: skip


def plan_for(request, words: str, lang: str, enabled: bool = True, attached: bool = False) -> turn.Plan | None:
    """The canvas plan of this turn (None: an ordinary turn). Never on a resumed confirmation."""
    if not enabled or getattr(request, "resume", None) is not None:
        return None
    try:
        return turn.plan(words, getattr(request, "canvas", None), lang, attached=attached)
    except Exception:  # noqa: BLE001 - the canvas must never break an ordinary turn
        return None


def ref(run) -> dict | None:
    """The answer's link to its artifact: {'aid', 'version'} (and the document itself when a trained file tool made
    it on an ordinary turn: it was not streamed)."""
    c = getattr(run, "canvas", None)
    if not c:
        return None
    out = {"aid": c["aid"], "version": c["version"]}
    if c.get("adopted"):
        out.update(doc=public(c["doc"]), kind=c["doc"].get("kind"), open=False)
    return out


def public(doc: dict) -> dict:
    """The document as sent to the browser (internal search hints dropped)."""
    out = dsl.clone(doc)
    for b in out.get("blocks") or []:
        for p in b.get("parts") or []:
            p.pop("exclude", None)
    return out


def emit_doc(ctx, p: turn.Plan, doc: dict | None, phase: str, lang: str, open_: bool = True, label: str = "") -> None:
    ev = {"type": "canvas", "phase": phase, "aid": p.aid, "base": p.version if p.mode != "create" else None,
          "kind": "code" if p.kind == "diagram" else p.kind, "label": label, "open": open_}  # fmt: skip
    if doc is not None:
        ev["doc"] = public(doc)
    ctx.emit(ev)


def _finder(mode: str, agent, doc: dict, lang: str):
    if mode == "demo":
        return images.finder("demo", theme=doc.get("theme"), lang=lang)
    from birds.harness import office_media as om

    return images.finder("server", fetch=om.Fetcher(agent.http, agent.cfg))


def illustrate(ctx, p: turn.Plan, doc: dict, mode: str, agent, lang: str) -> None:
    """Pictures for the image blocks still without one (bounded in number and time), sent as one event."""
    if doc.get("kind") not in ("deck", "doc"):
        return
    budget = min(turn.IMAGE_SECONDS, max(0.0, ctx.seconds_left() - 20))
    if budget <= 1:
        return
    found = images.resolve(doc, _finder(mode, agent, doc, lang), limit=turn.IMAGE_LIMIT,
                           deadline=time.monotonic() + budget)  # fmt: skip
    if found:
        ctx.emit({"type": "canvas_media", "aid": p.aid, "media": found})


def run_direct(p: turn.Plan, ctx, agent, lang: str, mode: str):
    """A change the user's words fully describe: applied without any model call."""
    from birds.harness import meter
    from birds.harness.agent import Run

    t0 = time.monotonic()
    doc, done, failed = patch.apply_all(p.base, p.ops or [])
    illustrate(ctx, p, doc, mode, agent, lang)
    emit_doc(ctx, p, doc, "final", lang, label=p.said)
    run = Run(lang=lang, answer=p.said if done else _t(lang, "Je n'ai rien pu changer : ", "Nothing changed: ")
              + "; ".join(failed), stop_reason="answer")  # fmt: skip
    if done and failed:
        run.answer += " " + _t(lang, "(en partie : ", "(partly: ") + "; ".join(failed) + ")"
    run.report = meter.report([], wall_seconds=time.monotonic() - t0, tool_calls=0, bytes_fetched=0,
                              measured_wh=None, **meter.energy_options(agent.cfg))  # fmt: skip
    run.canvas = {"aid": p.aid, "version": p.version + 1, "doc": doc}
    return run


def run_reopen(p: turn.Plan, ctx, agent, lang: str):
    """An edit asked of an artifact whose panel is closed (the browser sent only its reference): the panel opens
    again and the chat says so. No model call: the next message carries the document."""
    from birds.harness import meter
    from birds.harness.agent import Run

    t0 = time.monotonic()
    emit_reopen(ctx, p)
    run = Run(lang=lang, answer=p.said, stop_reason="answer")
    run.report = meter.report([], wall_seconds=time.monotonic() - t0, tool_calls=0, bytes_fetched=0,
                              measured_wh=None, **meter.energy_options(agent.cfg))  # fmt: skip
    return run


def emit_reopen(ctx, p: turn.Plan) -> None:
    ctx.emit({"type": "canvas", "phase": "reopen", "aid": p.aid, "kind": p.kind})


def _t(lang: str, fr: str, en: str) -> str:
    return en if lang == "en" else fr


def run_canvas(agent, p: turn.Plan, request, ctx, *, user_sent: str, words: str, system, history, lang: str,
               mode: str, attached: bool = False):  # fmt: skip
    """A create or patch turn (see birds.canvas.turn). Returns the harness Run; ``run.canvas`` holds the result."""
    if p.mode == "direct":
        return run_direct(p, ctx, agent, lang, mode)
    if p.mode == "reopen":
        return run_reopen(p, ctx, agent, lang)
    captured: list[dict] = []
    compute = turn.compute_for(p, words, lang)
    stream = turn.Stream(compute, lambda d: emit_doc(ctx, p, d, "stream", lang))
    hooks = dataclasses.replace(agent.hooks, on_token=stream.feed, on_reset=stream.reset)
    # the turn's ordinary tools stay offered on a patch turn too (an edit that was not one still gets its weather);
    # a trained file tool called anyway is captured by the sink and its arguments become the new version
    kind = "code" if (p.base or {}).get("kind") == "code" else p.kind
    # read_file only with a file to read: without one a small model « reads » the deck's title and apologises
    hide = turn.FILE_TOOLS + (() if attached else ("read_file",))
    # draft_email only when the request also asks for a mail (« … et un mail pour l'annoncer »): else a compte rendu
    # naming Paul and Marie went out as a draft to invented addresses and the canvas was dropped
    from birds.harness import plan as taskplan

    if not any(i.kind == "mail" for i in taskplan.extract(words, lang)):
        hide += ("draft_email",)
    a2 = turn.derive_agent(agent, hooks, turn.sink_for(captured), hide=hide, kind=kind)
    from birds.harness.llm import EndpointError

    try:
        run = a2.run(turn.turn_message(p, user_sent, lang), history=history or None, system=system,
                     thinking=request.thinking, lang=lang, request_text=words, attached=attached, tz=request.tz)  # fmt: skip
    except EndpointError:
        if stream.doc is not None:
            emit_doc(ctx, p, None, "abort", lang)  # the snapshot streamed so far is not left as the result
        raise  # the backend answers from the cards already shown, or reports the error
    stream.flush()
    text = str(run.answer or "") if run.stop_reason in ("answer", "length", "repetition") else ""
    repairs: list[str] = []
    before = after = ""
    doc = None
    if captured:
        doc = convert.from_tool(captured[-1]["tool"], captured[-1]["args"], lang)
        if p.mode != "create" and doc is not None and doc.get("kind") == (p.base or {}).get("kind"):
            doc = patch.rewrite(p.base, doc)
        before = text
        repairs.append(f"model called {captured[-1]['tool']}: its arguments became the document")
    elif text:
        if p.kind in ("code", "diagram") or (p.base or {}).get("kind") == "code":
            found = dsl.parse_code(text, "mermaid" if p.kind == "diagram" else None)
            doc = turn.code_doc(found, lang, (p.base or {}).get("title") or convert.subject(words))
            if found:
                before, after = found["before"], found["after"]
        elif p.mode == "create":
            doc = convert.from_json_text(text, lang)  # the tool's arguments written as text (a 4B habit)
            if doc is not None:
                repairs.append("JSON arguments written in the answer became the document")
            else:
                before, content, after = dsl.split_answer(text)
                doc = dsl.parse(content, p.kind, lang, repairs)
            if not _enough(doc):
                doc = None
        else:
            ops, how = patch.parse_patch(text, p.base, words, p.target, repairs)
            doc = patch.apply_all(p.base, ops)[0] if ops else None
            repairs.append(f"patch mode: {how}")
    if doc is None:
        if stream.doc is not None:
            emit_doc(ctx, p, None, "abort", lang)
        if p.mode == "patch" and text and any(patch._is_op_line(ln) for ln in text.split("\n")):
            # operations, none of them asked for: say so plainly rather than show them
            name = turn.NAMES.get((p.base or {}).get("kind") or "doc", turn.NAMES["doc"])[turn._lang2(lang)]
            run.answer = _t(lang, f"Je n'ai pas modifié {name} : précisez le bloc à changer (« raccourcis la "
                                  "diapositive 3 ») ou cliquez sur un bloc, puis « Demander à Bird ».",
                            f"I left {name} as it was: say which block to change (\"shorten slide 3\") or click "
                            "a block, then \"Ask Bird\".")  # fmt: skip
        return run  # the chat shows the model's answer as is (no canvas this time)
    kind = doc.get("kind")
    if p.mode == "create" and kind in ("deck", "doc"):
        turn.finish_doc(doc, kind, words, lang)
    elif kind == "deck":
        from birds.canvas import convert as cv

        cv.enrich(doc)
    illustrate(ctx, p, doc, mode, agent, lang)
    emit_doc(ctx, p, doc, "final", lang, label=_t(lang, "Création", "Created") if p.mode == "create" else words[:80])
    run.answer = turn.chat_text("code" if p.kind == "diagram" else kind, doc, lang, before, after,
                                cut=run.stop_reason == "length", verb="create" if p.mode == "create" else "patch")  # fmt: skip
    run.stop_reason = "answer"
    run.canvas = {"aid": p.aid, "version": (p.version + 1) if p.mode != "create" else 1, "doc": doc,
                  "repairs": repairs, "raw": text[:8000]}  # fmt: skip  # raw: for evaluations, never sent
    return run


def _enough(doc: dict) -> bool:
    """A real deck or document: two blocks, or one block with two parts (else the answer stays in the chat)."""
    blocks = doc.get("blocks") or []
    return len(blocks) >= 2 or bool(blocks and len(blocks[0].get("parts") or []) >= 2)


def adopt_files(run, ctx, lang: str) -> None:
    """A deck, document or sheet made by a trained tool on an ordinary turn (or by the Mode Agent's team) is also
    offered in the canvas: the browser keeps it, and the file card gets « Ouvrir dans le canevas »."""
    try:
        _adopt(run, ctx, lang)
    except Exception:  # noqa: BLE001 - never lose the answer for the canvas
        return


def _adopt(run, ctx, lang: str) -> None:
    if getattr(run, "canvas", None):
        return
    for s in getattr(run, "steps", []) or []:
        if s.tool not in turn.FILE_TOOLS or s.error or not isinstance(s.arguments, dict):
            continue
        doc = convert.from_tool(s.tool, s.arguments, lang)
        if doc is None:
            continue
        kind = doc["kind"]
        if kind in ("deck", "doc"):
            turn.finish_doc(doc, kind, doc.get("title") or "", lang)
        p = turn.Plan("create", kind, turn.new_aid())
        # no event of its own: the document travels with the answer (« Ouvrir dans le canevas » on the file card)
        run.canvas = {"aid": p.aid, "version": 1, "doc": doc, "adopted": True}
        return


def memo_with_canvas(memo: str, run, lang: str) -> str:
    line = turn.memo_line(getattr(run, "canvas", None), lang)
    return (memo + "\n" + line).strip() if line else memo


# ------------------------------------------------------------------ endpoints


class ExportIn(BaseModel):
    doc: dict
    format: Literal["pptx", "docx", "xlsx"]
    media: dict[str, str] = Field(default_factory=dict, max_length=MAX_MEDIA)


class ImageIn(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    exclude: list[str] = Field(default_factory=list, max_length=8)
    theme: Literal["corporate", "modern", "warm"] | None = None
    lang: Literal["fr", "en"] = "fr"
    mid: str | None = Field(default=None, pattern=r"^[a-z]{1,2}\d{1,4}$")


class CheckIn(BaseModel):
    lang: Literal["python", "json"]
    code: str = Field(max_length=60_000)


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _body_size(request: Request) -> None:
    try:
        n = int(request.headers.get("content-length") or 0)
    except ValueError:
        n = 0
    if n > MAX_BODY:
        raise _err(413, "too_large", "the request is too large")


FRAME_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src data: blob:; "
    "font-src data:; media-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'self'; sandbox allow-scripts"
)
# The preview frame: loaded with sandbox="allow-scripts" (no allow-same-origin: an opaque origin, no access to the
# app, its storage or its cookies), its own CSP (no network at all: connect-src, img-src and font-src allow only
# data:/blob:), and the app's CSP allows only same-origin frames, so a navigation of the frame elsewhere is
# blocked too. The code arrives by postMessage; console errors go back the same way.
FRAME_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,
initial-scale=1"><title>Aperçu</title></head><body><script>
(function () {
  var CAP = "<scr" + "ipt>(function(){var P=parent;function s(k,a){try{P.postMessage({bird:'console',level:k,"
    + "text:String(a).slice(0,600)},'*')}catch(e){}}"
    + "addEventListener('error',function(e){s('error',(e.message||'Error')+(e.lineno?' (l. '+e.lineno+')':''))});"
    + "addEventListener('unhandledrejection',function(e){var r=e.reason;s('error','Promise: '+(r&&r.message||r))});"
    + "['error','warn','log'].forEach(function(k){var o=console[k];console[k]=function(){s(k,[].map.call(arguments,"
    + "function(x){try{return typeof x==='object'?JSON.stringify(x):String(x)}catch(e){return String(x)}}).join(' '));"
    + "if(o)o.apply(console,arguments)}});"
    + "document.addEventListener('click',function(e){var a=e.target&&e.target.closest&&e.target.closest('a[href]');"
    + "if(a&&a.getAttribute('href').charAt(0)!=='#'){e.preventDefault();s('info','link: '+a.getAttribute('href'))}},true);"
    + "addEventListener('load',function(){s('ready','')});"
    + "})();</scr" + "ipt>";
  addEventListener("message", function (e) {
    if (e.source !== parent || !e.data || e.data.bird !== "render" || typeof e.data.html !== "string") return;
    document.open();
    document.write(CAP + e.data.html);
    document.close();
  });
  parent.postMessage({ bird: "frame" }, "*");
})();
</script></body></html>"""


def make_router(settings, guard_request, check_access, resolve_mode, fetch_client) -> APIRouter:
    router = APIRouter()

    @router.post("/api/canvas/export")
    def canvas_export(body: ExportIn, request: Request):
        """The canvas document as .pptx / .docx / .xlsx (office engine, same themes). No model call, nothing kept."""
        _body_size(request)
        guard_request(request)
        check_access(request)
        from birds.canvas import export as ex

        for mid, data in body.media.items():
            if not re.fullmatch(r"[a-z]{1,2}\d{1,4}", mid) or len(data) > MAX_MEDIA_B64:
                raise _err(413, "too_large", "a picture is too large")
            if not re.fullmatch(r"[A-Za-z0-9+/=]*", data):
                raise _err(422, "bad_media", "a picture is not valid base64")
        try:
            doc = ex.validated(body.doc)
            data, mime, name = ex.export(doc, body.format, body.media)
        except ex.ExportError as e:
            raise _err(422, "invalid_document", str(e)[:200]) from None
        if len(data) > settings.max_inline_file_bytes:
            raise _err(413, "too_large", "the exported file is too large")
        from urllib.parse import quote

        ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        return Response(
            data,
            media_type=mime,
            headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"},
        )

    @router.post("/api/canvas/image")
    def canvas_image(body: ImageIn, request: Request) -> dict:
        """One picture for a query typed in the canvas (or « une autre image »): Commons with a checked licence in
        server mode, a drawn illustration in demo mode. Never a URL the client gives."""
        guard_request(request)
        mode = resolve_mode(request)
        mid = body.mid or "w1"
        if mode == "demo":
            m = images.generated(body.query + "|" + "|".join(body.exclude), mid.replace("w", "g", 1), body.theme,
                                 body.lang)  # fmt: skip
        else:
            from birds.harness import Config
            from birds.harness import office_media as om

            client = fetch_client(settings)  # a fresh client per call (server.image_client: never None)
            try:
                cfg = Config(workspace=__import__("pathlib").Path("."), audit_file=None, pin_dns=settings.pin_dns)
                m = images.search_commons(body.query, om.Fetcher(client, cfg), body.exclude, mid,
                                          deadline=time.monotonic() + 12)  # fmt: skip
            finally:
                if client is not None:
                    client.close()
        if m is None:
            return {"ok": False, "reason": "none"}
        return {"ok": True, "media": images.to_entry(m, body.query)}

    @router.post("/api/canvas/check")
    def canvas_check(body: CheckIn, request: Request) -> dict:
        """Syntax of a Python or JSON file of the canvas (never executed)."""
        guard_request(request)
        from birds.web.tidy import _check_json, _check_python

        return _check_python(body.code) if body.lang == "python" else _check_json(body.code)

    @router.get("/canvas/frame")
    def canvas_frame() -> HTMLResponse:
        return HTMLResponse(FRAME_HTML, headers={"Cache-Control": "no-store"})

    return router


def frame_headers(response) -> None:
    """The preview frame's own headers (set by the app's security middleware after the common ones)."""
    response.headers["Content-Security-Policy"] = FRAME_CSP
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
