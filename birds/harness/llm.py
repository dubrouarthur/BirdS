"""Model clients behind one small interface.

    generate(prompt, max_tokens, stop) -> {"text", "prompt_tokens", "completion_tokens", "seconds"}

The prompt is the RAW text rendered with the model's own chat template (birds.render.prompt). We deliberately do
not use the server's chat template or tool-call parser: the model is trained on one exact format and we parse it
ourselves (birds.parse).
"""

from __future__ import annotations

import json
import re
import time

STOP = ["<|im_end|>"]


def _cut(text: str, stop: list[str]) -> str:
    for s in stop or []:
        text = text.split(s, 1)[0]
    return text


class Cancelled(Exception):
    """The user pressed stop or went away (``cancel`` was set): the stream is closed and no retry is made."""


def accepts(fn, name: str) -> bool:
    """``fn`` takes the keyword ``name`` (or **kwargs): test doubles and older clients may not."""
    import inspect

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is p.VAR_KEYWORD for p in params.values())


class EndpointError(Exception):
    """The model endpoint could not serve the request. ``kind`` is stable; the message never contains credentials.

    kinds: unauthorized, waking (scaled to zero / still loading), unknown_model, wrong_route, bad_request, server, unreachable,
    timeout, blocked (egress policy).
    """

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind, self.status = kind, status


def normalize_base_url(url: str) -> str:
    """Accept the endpoint URL with or without ``/v1`` (or a full ``/v1/completions``) and return ``…/v1``."""
    u = (url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if u.endswith(suffix):
            u = u[: -len(suffix)]
    return u if u.endswith("/v1") else u + "/v1"


def _piece(obj: dict) -> str:
    """Text carried by one stream chunk, across engines (OpenAI completions, chat-style delta, llama.cpp, TGI)."""
    choices = obj.get("choices") or []
    if choices:
        c = choices[0] or {}
        if isinstance(c.get("text"), str):
            return c["text"]
        delta = c.get("delta") or {}
        if isinstance(delta.get("content"), str):
            return delta["content"]
        return ""
    if isinstance(obj.get("content"), str):  # llama.cpp native /completion
        return obj["content"]
    token = obj.get("token")
    if isinstance(token, dict) and isinstance(token.get("text"), str) and not token.get("special"):
        return token["text"]  # TGI native /generate_stream
    return ""


def _usage(obj: dict) -> tuple[int | None, int | None]:
    """(prompt_tokens, completion_tokens) when the engine reports them, in any of the shapes we know."""
    u = obj.get("usage")
    if isinstance(u, dict) and (u.get("prompt_tokens") is not None or u.get("completion_tokens") is not None):
        return u.get("prompt_tokens"), u.get("completion_tokens")
    t = obj.get("timings")
    if isinstance(t, dict) and (t.get("prompt_n") is not None or t.get("predicted_n") is not None):
        return t.get("prompt_n"), t.get("predicted_n")  # llama.cpp
    if obj.get("tokens_evaluated") is not None or obj.get("tokens_predicted") is not None:
        return obj.get("tokens_evaluated"), obj.get("tokens_predicted")  # llama.cpp native
    d = obj.get("details")
    if isinstance(d, dict) and d.get("generated_tokens") is not None:
        return d.get("prefill_tokens") or d.get("prompt_tokens"), d.get("generated_tokens")  # TGI native
    return None, None


def _meta(obj: dict, meta: dict | None) -> None:
    """finish_reason (stop | length | ...) and prompt tokens served from the prefix cache, when reported."""
    if meta is None:
        return
    choices = obj.get("choices") or []
    if choices and isinstance(choices[0], dict) and choices[0].get("finish_reason"):
        meta["finish_reason"] = choices[0]["finish_reason"]
    u = obj.get("usage")
    details = u.get("prompt_tokens_details") if isinstance(u, dict) else None
    if isinstance(details, dict) and details.get("cached_tokens") is not None:
        meta["cached_tokens"] = details["cached_tokens"]


_ESCAPES = re.compile(r"\\[nrt\"\\/]|\\u[0-9a-fA-F]{4}")  # JSON escapes are not letters


def find_loop(
    text: str, *, min_span: int = 400, min_copies: int = 3, probe: int = 40, window: int = 12000
) -> int | None:
    """Where to cut ``text`` if it ends in a degenerate loop, else ``None``.

    A loop is the end of the text repeating one exact unit (a word, a line, a paragraph) back to back, at least
    ``min_copies`` times and over at least ``min_span`` characters. The unit's length is found from the previous
    occurrences of the last ``probe`` characters. The returned index keeps the first copy and drops the repeats.
    Real prose, tables and code almost never repeat 400 identical characters in a row; a small model stuck in
    greedy decoding does, until ``max_tokens``. A unit without any letter or digit (spaces, dashes, empty table
    rows) must run eight times longer. Measured on 264k training answers: only degenerate samples are flagged.
    """
    if len(text) < min_span:
        return None
    tail = text[-window:]
    n, key = len(tail), tail[-probe:]
    end = n - 1
    for _ in range(4):  # the nearest few occurrences of the closing characters: candidate periods
        i = tail.rfind(key, 0, end)
        if i < 0:
            return None
        period = n - probe - i
        end = i + probe - 1
        if period * min_copies > n:
            return None
        unit, copies = tail[-period:], 1
        while (copies + 1) * period <= n and tail[n - (copies + 1) * period : n - copies * period] == unit:
            copies += 1
        # blank or ruled lines (table padding, separators) repeat legitimately: they need a far longer run
        need = min_span if any(c.isalnum() for c in _ESCAPES.sub("", unit)) else min_span * 8
        if copies >= min_copies and copies * period >= need:
            # the repeated run may start before a whole number of copies: walk back to where it really begins,
            # then keep exactly one unit from there (the text can end mid-copy while streaming)
            start = n - copies * period
            while start > 0 and tail[start - 1] == tail[start - 1 + period]:
                start -= 1
            return len(text) - n + start + period
    return None


class _LoopGuard:
    """Checks the growing text for a loop every ``every`` new characters (the check is cheap but not free)."""

    def __init__(self, every: int = 48):
        self.every, self.next, self.cut = every, every, None

    def check(self, text: str) -> int | None:
        if self.cut is None and len(text) >= self.next:
            self.next = len(text) + self.every
            self.cut = find_loop(text)
        return self.cut


class _StopCutter:
    """Forwards text but never a stop string, even when the server streams it split across chunks."""

    def __init__(self, stop: list[str], emit):
        self.stop, self.emit, self.text, self.sent, self.done = [s for s in stop or [] if s], emit, "", 0, False
        self.hold = max((len(s) for s in self.stop), default=1) - 1

    def feed(self, piece: str) -> None:
        if self.done or not piece:
            return
        self.text += piece
        cut = min((i for i in (self.text.find(s) for s in self.stop) if i >= 0), default=-1)
        if cut >= 0:
            self.text, self.done = self.text[:cut], True
        end = len(self.text) if self.done else max(self.sent, len(self.text) - self.hold)
        if end > self.sent and self.emit:
            self.emit(self.text[self.sent : end])
        self.sent = max(self.sent, end)

    def finish(self) -> str:
        if not self.done and len(self.text) > self.sent and self.emit:
            self.emit(self.text[self.sent :])
        self.sent = len(self.text)
        return self.text


class CompletionsClient:
    """OpenAI-compatible ``/v1/completions`` with a raw prompt (vLLM, llama.cpp server, TGI, Ollama).

    Tolerant of engine differences: streamed or plain JSON answers, ``usage`` present or not, servers that refuse
    ``stream_options`` or more than four stop sequences. A 503 while a scaled-to-zero endpoint wakes up is retried
    with backoff until ``deadline``. With ``egress`` (an object with ``allowed_ports``, ``allow_domains``,
    ``deny_domains``) the URL is checked by the harness egress guard before every request, the connection goes
    to the validated address (DNS pinning) and redirects are refused: use it for URLs typed by a user.
    """

    WAKE_STATUS = (503,)
    WAKE_BACKOFF = (3.0, 5.0, 8.0, 12.0, 15.0)

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        *,
        temperature: float = 0.0,
        timeout: float = 300.0,
        extra: dict | None = None,
        transport=None,
        stream: bool = True,
        egress=None,
        sleep=time.sleep,
    ):
        import httpx

        self.url = normalize_base_url(base_url) + "/completions"
        self.model, self.temperature, self.extra = model, temperature, extra or {}
        self.stream, self.egress, self.sleep, self.timeout = stream, egress, sleep, timeout
        self._auth = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # trust_env=False with an egress policy: a proxy variable must not reroute a pinned connection
        self.http = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False, trust_env=egress is None)

    # -- one HTTP attempt
    def _target(self, url: str | None = None):
        import httpx

        url = url or self.url
        headers = {"Accept": "text/event-stream, application/json", **self._auth}
        if self.egress is None:
            return url, headers, {}
        from birds.harness import guard

        try:
            ips = guard.check_url(url, self.egress)
        except guard.Blocked as e:
            raise EndpointError("blocked", f"endpoint URL refused by the egress policy: {e}") from None
        u = httpx.URL(url)
        headers["Host"] = u.netloc.decode("ascii")
        ip = ips[0]
        return u.copy_with(host=f"[{ip}]" if ":" in ip else ip), headers, {"sni_hostname": u.host}

    def _post(
        self, body: dict, read_timeout: float, on_piece, url: str | None = None, meta: dict | None = None
    ) -> tuple[int | None, int | None]:
        import httpx

        target, headers, ext = self._target(url)
        timeout = httpx.Timeout(read_timeout, connect=min(15.0, read_timeout))
        try:
            with self.http.stream("POST", target, json=body, headers=headers, extensions=ext, timeout=timeout) as r:
                if r.status_code >= 300:
                    detail = r.read()[:400].decode("utf-8", "replace")
                    raise _http_error(r.status_code, detail)
                if "text/event-stream" not in r.headers.get("content-type", ""):
                    data = json.loads(r.read() or b"{}")  # the server answered in one piece
                    on_piece(_piece(data))
                    _meta(data, meta)
                    return _usage(data)
                tin = tout = None
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    if obj.get("error"):
                        err = obj["error"]
                        raise EndpointError("server", _safe(err.get("message") if isinstance(err, dict) else err))
                    _meta(obj, meta)
                    a, b = _usage(obj)
                    tin, tout = (a if a is not None else tin), (b if b is not None else tout)
                    if on_piece(_piece(obj)) or obj.get("stop") is True:
                        break
                return tin, tout
        except httpx.TimeoutException:
            raise EndpointError("timeout", "the model endpoint did not answer in time") from None
        except httpx.HTTPError as e:
            raise EndpointError("unreachable", f"cannot reach the model endpoint ({type(e).__name__})") from None

    def chat(
        self,
        messages: list[dict],
        max_tokens: int,
        *,
        on_token=None,
        on_status=None,
        deadline=None,
        thinking=False,
        extra=None,
        cancel=None,
    ) -> dict:
        """``/v1/chat/completions`` with the server's chat template: the only route that carries images (OpenAI
        content lists with ``image_url`` data URLs). No tools are sent: vLLM refuses them without a tool parser."""
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "stream": self.stream,
            "chat_template_kwargs": {"enable_thinking": bool(thinking)},
        }
        return self.generate(
            "",
            max_tokens,
            STOP,
            on_token=on_token,
            on_status=on_status,
            deadline=deadline,
            _body=body,
            _url=self.url[: -len("/completions")] + "/chat/completions",
            _chars=sum(len(json.dumps(m.get("content"), ensure_ascii=False)) for m in messages),
            extra=extra,
            cancel=cancel,
        )

    def generate(
        self,
        prompt: str,
        max_tokens: int,
        stop: list[str],
        *,
        on_token=None,
        on_status=None,
        deadline=None,
        _body=None,
        _url=None,
        _chars=None,
        extra=None,
        cancel=None,
        **_,
    ) -> dict:
        """``deadline`` is a ``time.monotonic()`` value: waiting for a waking endpoint and reading stop before it.
        ``cancel`` (a ``threading.Event``) set by the caller closes the stream at the next piece (the server then
        aborts the request: the GPU stops) and ends any wait for a waking endpoint: ``Cancelled`` is raised."""
        t0 = time.monotonic()
        body = _body or {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "stop": stop,
            "temperature": self.temperature,
            "stream": self.stream,
            **self.extra,
        }
        if extra:  # per-call fields, e.g. cache_salt (one per conversation: never on the shared client)
            body = {**body, **extra}
        if self.stream:
            body.setdefault("stream_options", {"include_usage": True})
        attempt, conservative = 0, False
        while True:
            cutter = _StopCutter(stop, on_token)
            mark = {"start": time.monotonic(), "first": None}
            meta: dict = {}
            loop = _LoopGuard()

            def on_piece(piece, cutter=cutter, mark=mark, loop=loop):
                if cancel is not None and cancel.is_set():
                    return True  # nobody is reading any more: close the stream now
                if piece and mark["first"] is None:
                    mark["first"] = time.monotonic()
                cutter.feed(piece)
                if not cutter.done and loop.check(cutter.text) is not None:
                    cutter.done = True  # closing the stream makes the server abort the request: the GPU stops
                return cutter.done

            if cancel is not None and cancel.is_set():
                raise Cancelled
            left = self.timeout if deadline is None else deadline - time.monotonic()
            if left <= 1:
                raise EndpointError("timeout", "no time left to call the model endpoint")
            try:
                tin, tout = self._post(body, min(self.timeout, left), on_piece, _url, meta)
                if cancel is not None and cancel.is_set():
                    raise Cancelled
                break
            except EndpointError as e:
                if e.kind == "bad_request" and not conservative and not cutter.sent:
                    conservative = True  # some engines refuse stream_options, or more than 4 stop sequences
                    body.pop("stream_options", None)
                    if "stop" in body:
                        body["stop"] = list(stop or [])[:4]
                    continue
                if e.kind != "waking" or cutter.sent:
                    raise
                wait = self.WAKE_BACKOFF[min(attempt, len(self.WAKE_BACKOFF) - 1)]
                attempt += 1
                if deadline is not None and time.monotonic() + wait + 5 > deadline:
                    raise
                if deadline is None and attempt > 40:
                    raise
                if on_status:
                    on_status("waking", {"attempt": attempt, "retry_in": wait})
                if cancel is None:
                    self.sleep(wait)
                elif cancel.wait(wait):
                    raise Cancelled from None  # stopped while waiting for the endpoint to wake up: no more attempts
        text = cutter.finish()
        if loop.cut is not None:
            text, meta["finish_reason"] = text[: loop.cut].rstrip(), "repetition"
        end = time.monotonic()
        return {
            "text": text,
            "prompt_tokens": tin,
            "completion_tokens": tout,
            "prompt_chars": _chars if _chars is not None else len(prompt),
            "completion_chars": len(text),
            "seconds": round(end - t0, 3),
            # the successful attempt only (waiting for a waking endpoint excluded): time the GPU worked for us,
            # plus network latency, so an upper bound of the busy time
            "busy_seconds": round(end - mark["start"], 3),
            "first_token_seconds": round(mark["first"] - mark["start"], 3) if mark["first"] else None,
            "wake_attempts": attempt,
            "finish_reason": meta.get("finish_reason"),
            "cached_tokens": meta.get("cached_tokens"),
        }

    def probe(self) -> dict:
        """One-token completion, to check that the endpoint is reachable and speaks /v1/completions."""
        t0 = time.monotonic()
        body = {"model": self.model, "prompt": "Bonjour", "max_tokens": 1, "temperature": 0.0, "stream": False}
        tin, tout = self._post(body, min(self.timeout, 20.0), lambda piece: False)
        return {"seconds": round(time.monotonic() - t0, 3), "usage_reported": tin is not None or tout is not None}


def _safe(text) -> str:
    from birds.harness import guard

    return guard.redact(str(text or ""))[:300]


def _http_error(status: int, detail: str) -> EndpointError:
    detail = _safe(" ".join(detail.split()))
    if status in (401, 403):
        return EndpointError("unauthorized", f"the endpoint refused the access token (HTTP {status})", status)
    if status in CompletionsClient.WAKE_STATUS:
        return EndpointError("waking", f"the endpoint is starting or scaled to zero (HTTP {status})", status)
    if status == 404 and re.search(r"model .{0,80}(does not exist|not found)|valid aliases", detail, re.I):
        # vLLM answers 404 "The model `x` does not exist. Valid aliases: y." for a wrong `model` name
        return EndpointError("unknown_model", f"the endpoint does not serve this model name: {detail}", status)
    if status in (404, 405) or 300 <= status < 400:
        return EndpointError("wrong_route", f"no /v1/completions route at this address (HTTP {status})", status)
    if status in (400, 422):
        return EndpointError("bad_request", f"the endpoint rejected the request (HTTP {status}): {detail}", status)
    if status == 429:
        return EndpointError("server", "the endpoint is rate limiting requests (HTTP 429)", status)
    return EndpointError("server", f"the endpoint failed (HTTP {status}): {detail}", status)


class LocalClient:
    """transformers in-process, greedy decoding. For a GPU box; imports are lazy so the harness stays light."""

    local = True  # the model runs on this machine: GPU power sampling is meaningful

    def __init__(self, model_id_or_path: str, adapter: str | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(adapter or model_id_or_path)
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(model_id_or_path, torch_dtype=dtype, device_map="auto")
        if adapter:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter)
        self.model.eval()

    def generate(self, prompt: str, max_tokens: int, stop: list[str], **_) -> dict:
        t0 = time.monotonic()
        enc = self.tok(prompt, add_special_tokens=False, return_tensors="pt").to(self.model.device)
        eos = [i for i in (self.tok.convert_tokens_to_ids(s) for s in stop or STOP) if isinstance(i, int) and i >= 0]
        with self.torch.no_grad():
            out = self.model.generate(
                **enc,
                do_sample=False,
                max_new_tokens=max_tokens,
                eos_token_id=eos or None,
                pad_token_id=self.tok.pad_token_id,
            )
        new = out[0, enc["input_ids"].shape[1] :]
        return {
            "text": _cut(self.tok.decode(new, skip_special_tokens=False), stop),
            "prompt_tokens": int(enc["input_ids"].shape[1]),
            "completion_tokens": int(new.shape[0]),
            "seconds": round(time.monotonic() - t0, 3),
        }


class FakeClient:
    """Scripted outputs for tests and demos. Records the prompts it was given; streams in small chunks."""

    def __init__(self, outputs: list[str], seconds: float = 0.01, chunk: int = 7):
        self.outputs, self.prompts, self.seconds, self.chunk = list(outputs), [], seconds, chunk

    def chat(self, messages: list[dict], max_tokens: int, *, on_token=None, **_) -> dict:
        self.chats = getattr(self, "chats", []) + [messages]
        return self.generate("<chat>", max_tokens, STOP, on_token=on_token)

    def generate(self, prompt: str, max_tokens: int, stop: list[str], *, on_token=None, **_) -> dict:
        self.prompts.append(prompt)
        raw = self.outputs.pop(0) if self.outputs else ""
        text, reason, loop = _cut(raw, stop), None, _LoopGuard()
        for i in range(0, len(text), self.chunk):
            if on_token:
                on_token(text[i : i + self.chunk])
            cut = loop.check(text[: i + self.chunk])
            if cut is not None:
                text, reason = text[:cut].rstrip(), "repetition"
                break
        if reason is None and find_loop(text) is not None:
            text, reason = text[: find_loop(text)].rstrip(), "repetition"
        return {
            "text": text,
            "prompt_tokens": len(prompt) // 4,
            "completion_tokens": len(raw) // 4,
            "seconds": self.seconds,
            **({"finish_reason": reason} if reason else {}),
        }
