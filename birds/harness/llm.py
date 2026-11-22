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
    def _target(self):
        import httpx

        headers = {"Accept": "text/event-stream, application/json", **self._auth}
        if self.egress is None:
            return self.url, headers, {}
        from birds.harness import guard

        try:
            ips = guard.check_url(self.url, self.egress)
        except guard.Blocked as e:
            raise EndpointError("blocked", f"endpoint URL refused by the egress policy: {e}") from None
        u = httpx.URL(self.url)
        headers["Host"] = u.netloc.decode("ascii")
        ip = ips[0]
        return u.copy_with(host=f"[{ip}]" if ":" in ip else ip), headers, {"sni_hostname": u.host}

    def _post(self, body: dict, read_timeout: float, on_piece) -> tuple[int | None, int | None]:
        import httpx

        target, headers, ext = self._target()
        timeout = httpx.Timeout(read_timeout, connect=min(15.0, read_timeout))
        try:
            with self.http.stream("POST", target, json=body, headers=headers, extensions=ext, timeout=timeout) as r:
                if r.status_code >= 300:
                    detail = r.read()[:400].decode("utf-8", "replace")
                    raise _http_error(r.status_code, detail)
                if "text/event-stream" not in r.headers.get("content-type", ""):
                    data = json.loads(r.read() or b"{}")  # the server answered in one piece
                    on_piece(_piece(data))
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
                    a, b = _usage(obj)
                    tin, tout = (a if a is not None else tin), (b if b is not None else tout)
                    if on_piece(_piece(obj)) or obj.get("stop") is True:
                        break
                return tin, tout
        except httpx.TimeoutException:
            raise EndpointError("timeout", "the model endpoint did not answer in time") from None
        except httpx.HTTPError as e:
            raise EndpointError("unreachable", f"cannot reach the model endpoint ({type(e).__name__})") from None

    def generate(
        self, prompt: str, max_tokens: int, stop: list[str], *, on_token=None, on_status=None, deadline=None, **_
    ) -> dict:
        """``deadline`` is a ``time.monotonic()`` value: waiting for a waking endpoint and reading stop before it."""
        t0 = time.monotonic()
        body = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "stop": stop,
            "temperature": self.temperature,
            "stream": self.stream,
            **self.extra,
        }
        if self.stream:
            body.setdefault("stream_options", {"include_usage": True})
        attempt, conservative = 0, False
        while True:
            cutter = _StopCutter(stop, on_token)

            def on_piece(piece, cutter=cutter):
                cutter.feed(piece)
                return cutter.done

            left = self.timeout if deadline is None else deadline - time.monotonic()
            if left <= 1:
                raise EndpointError("timeout", "no time left to call the model endpoint")
            try:
                tin, tout = self._post(body, min(self.timeout, left), on_piece)
                break
            except EndpointError as e:
                if e.kind == "bad_request" and not conservative and not cutter.sent:
                    conservative = True  # some engines refuse stream_options, or more than 4 stop sequences
                    body.pop("stream_options", None)
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
                self.sleep(wait)
        text = cutter.finish()
        return {
            "text": text,
            "prompt_tokens": tin,
            "completion_tokens": tout,
            "prompt_chars": len(prompt),
            "completion_chars": len(text),
            "seconds": round(time.monotonic() - t0, 3),
            "wake_attempts": attempt,
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

    def generate(self, prompt: str, max_tokens: int, stop: list[str], *, on_token=None, **_) -> dict:
        self.prompts.append(prompt)
        raw = self.outputs.pop(0) if self.outputs else ""
        text = _cut(raw, stop)
        if on_token:
            for i in range(0, len(text), self.chunk):
                on_token(text[i : i + self.chunk])
        return {
            "text": text,
            "prompt_tokens": len(prompt) // 4,
            "completion_tokens": len(raw) // 4,
            "seconds": self.seconds,
        }
