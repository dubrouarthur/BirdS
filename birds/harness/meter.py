"""Per-run resource report. Energy is measured (GPU power via nvidia-smi) or explicitly calibrated, never guessed."""

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


def report(
    usage: list[dict],
    *,
    wall_seconds: float,
    tool_calls: int,
    bytes_fetched: int,
    measured_wh: float | None,
    wh_per_1k_tokens: float | None = None,
    calibration_source: str | None = None,
) -> dict:
    """Resource report for the UI. `energy_wh` is None unless it was measured or an explicit calibration is set."""
    # Token counts come from the model server. When it reports none, fall back to characters / 4 and say so.
    exact = all(u.get("prompt_tokens") is not None and u.get("completion_tokens") is not None for u in usage)
    tin = sum(_tokens(u, "prompt") for u in usage)
    tout = sum(_tokens(u, "completion") for u in usage)
    out = {
        "prompt_tokens": tin,
        "completion_tokens": tout,
        "generations": len(usage),
        "tokens_exact": exact,
        "tokens_source": "model server" if exact else "estimated: characters / 4",
        "generation_seconds": round(sum(u.get("seconds") or 0 for u in usage), 3),
        "wall_seconds": round(wall_seconds, 3),
        "tool_calls": tool_calls,
        "bytes_fetched": bytes_fetched,
        "energy_wh": None,
        "energy_kind": None,
        "energy_source": None,
    }
    if measured_wh is not None:
        out.update(energy_wh=round(measured_wh, 4), energy_kind="measured", energy_source="nvidia-smi (GPU only)")
    elif wh_per_1k_tokens is not None:
        out.update(
            energy_wh=round((tin + tout) / 1000 * wh_per_1k_tokens, 4),
            energy_kind="estimated",
            energy_source=calibration_source or f"configured calibration: {wh_per_1k_tokens} Wh per 1k tokens",
        )
    return out
