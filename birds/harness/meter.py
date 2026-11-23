"""Per-run resource report.

Energy, in order of preference:
1. measured: GPU power read with nvidia-smi on this machine, integrated over the generations;
2. estimated from an explicit calibration (Wh per 1 000 tokens, with its source);
3. estimated from tokens (default): input and output tokens x Wh per 1 000 tokens drawn from published measurements
   of vLLM serving (output tokens cost ~17 x more than input tokens; prefix-cached prompt tokens skip prefill);
4. opt-in only: power x time, rated board power x the time our HTTP streams lasted x PUE. A loose UPPER bound (the
   card rarely draws its rated power, network time counts, and a batching server shares the card between requests).
Nothing is shown when none of these applies.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time


def gpu_watts() -> float | None:
    """Total power draw of the visible GPUs, or None when there is no nvidia-smi / no GPU."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return sum(float(x) for x in out.split()) if out.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class GpuMeter:
    """Integrates GPU power into watt-hours over the `with` blocks it wraps (one per generation).

    It measures the whole GPU (idle draw and other processes included), on THIS machine only.
    """

    def __init__(self, period: float = 0.5, read=gpu_watts, enabled: bool = True):
        self.period, self.read, self.joules, self.samples = period, read, 0.0, 0
        self.enabled = enabled and read() is not None
        self._stop = threading.Event()
        self._thread = None

    def _sample(self):
        watts, now = self.read(), time.monotonic()
        if watts is not None:
            self.joules += watts * (now - self._last)
            self.samples += 1
        self._last = now

    def _run(self):
        while not self._stop.wait(self.period):
            self._sample()

    def __enter__(self):
        if self.enabled:
            self._stop.clear()
            self._last = time.monotonic()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        if self.enabled:
            self._stop.set()
            self._thread.join(timeout=self.period + 6)
            self._sample()  # close the interval, so even a short generation gets one reading

    @property
    def wh(self) -> float | None:
        return self.joules / 3600 if self.samples else None


CHARS_PER_TOKEN = 4  # rough, for the labelled fallback only


def _tokens(u: dict, side: str) -> int:
    n = u.get(f"{side}_tokens")
    if n is not None:
        return int(n)
    return -(-int(u.get(f"{side}_chars") or 0) // CHARS_PER_TOKEN)


def _cached(u: dict) -> int:
    """Prompt tokens of one generation served from the prefix cache, never more than its prompt."""
    try:
        n = int(u.get("cached_tokens") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, _tokens(u, "prompt")))


def energy_options(cfg) -> dict:
    """The energy arguments of ``report`` taken from a harness Config (or anything with the same attributes)."""
    keys = ("wh_per_1k_tokens", "calibration_source", "energy_method", "wh_per_1k_out", "wh_per_1k_in",
            "wh_per_1k_out_range", "wh_per_1k_in_range", "cached_input_share", "serving_overhead",
            "gpu_watts", "gpu_label", "pue")  # fmt: skip
    opts = {k: getattr(cfg, k, None) for k in keys}
    opts["energy_method"] = opts["energy_method"] or "tokens"
    opts["cached_input_share"] = opts["cached_input_share"] or 0.0
    opts["pue"] = opts["pue"] or 1.0
    return opts


def report(
    usage: list[dict],
    *,
    wall_seconds: float,
    tool_calls: int,
    bytes_fetched: int,
    measured_wh: float | None,
    wh_per_1k_tokens: float | None = None,
    calibration_source: str | None = None,
    energy_method: str = "tokens",
    wh_per_1k_out: float | None = None,
    wh_per_1k_in: float | None = None,
    wh_per_1k_out_range: tuple | None = None,
    wh_per_1k_in_range: tuple | None = None,
    cached_input_share: float = 0.0,
    serving_overhead: float | None = None,
    gpu_watts: float | None = None,
    gpu_label: str | None = None,
    pue: float = 1.0,
    busy_seconds_override: float | None = None,
) -> dict:
    """Resource report for the UI. ``energy_wh`` is None unless it was measured, calibrated or estimated.

    Energy, first that applies: measured (nvidia-smi) > explicit calibration > ``energy_method``: "tokens" (default,
    Wh per 1 000 input / output tokens; off while both values are None), "power_time" (opt-in upper bound: rated
    power x busy time) or "off". ``busy_seconds_override``: GPU time measured another way (Mode Agent: the union of
    parallel call intervals, which share one GPU batch); only "power_time" uses it, tokens are simply summed."""
    # Token counts come from the model server. When it reports none, fall back to characters / 4 and say so.
    busy = round(sum(float(u.get("busy_seconds") or 0) for u in usage), 3)
    if busy_seconds_override is not None:
        busy = round(float(busy_seconds_override), 3)
    exact = all(u.get("prompt_tokens") is not None and u.get("completion_tokens") is not None for u in usage)
    tin = sum(_tokens(u, "prompt") for u in usage)
    tout = sum(_tokens(u, "completion") for u in usage)
    cached = sum(_cached(u) for u in usage)
    out = {
        "prompt_tokens": tin,
        "completion_tokens": tout,
        "cached_tokens": cached,
        "generations": len(usage),
        "tokens_exact": exact,
        "tokens_source": "model server" if exact else "estimated: characters / 4",
        "generation_seconds": round(sum(u.get("seconds") or 0 for u in usage), 3),
        "busy_seconds": busy,
        "first_token_seconds": next((u["first_token_seconds"] for u in usage if u.get("first_token_seconds")), None),
        "wall_seconds": round(wall_seconds, 3),
        "tool_calls": tool_calls,
        "bytes_fetched": bytes_fetched,
        "energy_wh": None,
        "energy_kind": None,
        "energy_source": None,
        "energy_method": None,
        "energy_basis": None,
    }
    if measured_wh is not None:
        out.update(
            energy_wh=round(measured_wh, 4),
            energy_kind="measured",
            energy_source="nvidia-smi (GPU only)",
            energy_method="nvidia_smi",
        )
    elif wh_per_1k_tokens is not None:
        out.update(
            energy_wh=round((tin + tout) / 1000 * wh_per_1k_tokens, 6),
            energy_kind="estimated",
            energy_method="calibration",
            energy_source=calibration_source or f"configured calibration: {wh_per_1k_tokens} Wh per 1k tokens",
        )
    elif energy_method == "power_time":
        if gpu_watts and busy > 0:
            out.update(estimate_power_time(gpu_watts, busy, pue=pue, label=gpu_label))
    elif energy_method == "tokens" and (wh_per_1k_out is not None or wh_per_1k_in is not None) and tin + tout > 0:
        out.update(
            estimate_tokens(
                tin,
                tout,
                cached=cached,
                wh_per_1k_in=wh_per_1k_in or 0.0,
                wh_per_1k_out=wh_per_1k_out or 0.0,
                in_range=wh_per_1k_in_range,
                out_range=wh_per_1k_out_range,
                cached_share=cached_input_share,
                serving_overhead=serving_overhead,
                exact=exact,
            )  # fmt: skip
        )
    return out


def _wh(n_in: float, n_out: float, wh_in: float, wh_out: float) -> float:
    return n_in / 1000 * wh_in + n_out / 1000 * wh_out


def estimate_tokens(
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cached: int = 0,
    wh_per_1k_in: float,
    wh_per_1k_out: float,
    in_range: tuple | None = None,
    out_range: tuple | None = None,
    cached_share: float = 0.0,
    serving_overhead: float | None = None,
    exact: bool = True,
) -> dict:
    """Energy from token counts. Output tokens (decode) cost far more than input tokens (prefill), and prompt tokens
    served from the prefix cache skip prefill (each counts ``cached_share`` of an input token). The per-token values
    come from published measurements of vLLM serving (see birds/web/settings.py). Always labelled "estimated"."""
    cached = max(0, min(int(cached or 0), int(prompt_tokens)))
    share = max(0.0, min(1.0, float(cached_share or 0.0)))
    billed_in = int(prompt_tokens) - cached + cached * share
    tout = int(completion_tokens)
    wh = _wh(billed_in, tout, wh_per_1k_in, wh_per_1k_out)
    basis = {
        "input_tokens": int(prompt_tokens),
        "cached_tokens": cached,
        "output_tokens": tout,
        "wh_per_1k_in": float(wh_per_1k_in),
        "wh_per_1k_out": float(wh_per_1k_out),
        "cached_share": share,
        "low_wh": None,
        "high_wh": None,
        "serving_overhead": serving_overhead,
        "boundary": "serving" if serving_overhead else "unspecified",
    }
    if in_range and out_range:
        basis["low_wh"] = round(_wh(billed_in, tout, in_range[0], out_range[0]), 6)
        basis["high_wh"] = round(_wh(billed_in, tout, in_range[1], out_range[1]), 6)
    scope = f"whole service, GPU x {serving_overhead:g}" if serving_overhead else "boundary not stated"
    if cached and share == 0:
        cache_note = f"; {cached} prompt tokens from the prefix cache not counted"
    elif cached:
        cache_note = f"; {cached} prompt tokens from the prefix cache at {share:g} x"
    else:
        cache_note = ""
    source = (
        f"estimated from tokens: {tout} output x {wh_per_1k_out:g} Wh/1k + {round(billed_in)} input x "
        f"{wh_per_1k_in:g} Wh/1k{cache_note} (published vLLM measurements, {scope})"
        + ("" if exact else "; token counts themselves estimated (characters / 4)")
    )
    return {
        "energy_wh": round(wh, 6),
        "energy_kind": "estimated",
        "energy_method": "tokens",
        "energy_source": source,
        "energy_basis": basis,
    }


def estimate_power_time(watts: float, busy_seconds: float, *, pue: float = 1.0, label: str | None = None) -> dict:
    """Upper-bound energy of a remote GPU: rated power x busy time x PUE. Always labelled "estimated".

    Opt-in only (energy_method="power_time"): the busy time is the HTTP stream's wall time (network and queueing
    included) and the whole card is charged to one request although vLLM batches requests, so it runs 5-15 x high."""
    pue = pue if pue and pue >= 1.0 else 1.0
    wh = float(watts) * float(busy_seconds) * pue / 3600.0
    scope = "GPU only" if pue == 1.0 else f"PUE {pue:g}"
    gpu = label or f"{watts:g} W GPU"
    return {
        "energy_wh": round(wh, 4),
        "energy_kind": "estimated",
        "energy_method": "power_time",
        "energy_source": f"upper bound: {gpu} x {busy_seconds:.1f} s of generation ({scope})",
        "energy_basis": {"watts": float(watts), "busy_seconds": round(float(busy_seconds), 3), "pue": pue, "gpu": gpu},
    }
