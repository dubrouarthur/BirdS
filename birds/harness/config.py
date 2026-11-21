"""Deployment configuration and the per-run context handed to every tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from birds.tools import BIRD_TOOL_NAMES


@dataclass
class Config:
    workspace: Path
    allowed_tools: tuple[str, ...] = tuple(BIRD_TOOL_NAMES)  # per-deployment allowlist
    allow_python: bool = False  # run_python is NOT a sandbox: enable only inside a disposable container
    # loop limits
    max_steps: int = 6  # model generations per run
    max_calls_per_step: int = 3
    max_result_chars: int = 6000  # per tool result
    max_context_chars: int = 24000  # all tool results of a run together
    max_tokens: int = 1024  # per generation
    timeout_s: float = 180.0  # wall clock for the whole run
    max_side_effects: int = 5  # draft_email / make_* / run_python calls per run
    # network
    searxng_url: str | None = None  # operator-configured, so not subject to the egress policy
    http_timeout: float = 15.0
    max_bytes: int = 2_000_000
    max_redirects: int = 4
    allowed_ports: tuple[int, ...] = (80, 443)
    allow_domains: tuple[str, ...] = ()  # when set, only these domains (and their subdomains)
    deny_domains: tuple[str, ...] = ()
    pin_dns: bool = True  # connect to the IP we validated (set False only behind an egress proxy that filters itself)
    # files and code
    max_file_bytes: int = 10_000_000
    python_wall_s: float = 10.0
    python_cpu_s: int = 5
    # energy
    measure_gpu: bool = (
        False  # sample nvidia-smi around generation (only meaningful when the model runs on this machine)
    )
    wh_per_1k_tokens: float | None = None  # explicit calibration; reported as "estimated"
    calibration_source: str | None = None
    audit_file: str = "bird_audit.jsonl"


@dataclass
class Context:
    """What a tool may touch: the workspace, the config, an HTTP client, and the run's collected outputs."""

    config: Config
    http: Any  # httpx.Client
    search: Any = None  # search backend with .search(query, n) -> [{"title", "url", "snippet"}]
    sources: list[str] = field(default_factory=list)  # URLs actually read
    drafts: list[dict] = field(default_factory=list)  # email drafts for the UI (never sent)
    files: list[str] = field(default_factory=list)  # generated files
    bytes_fetched: int = 0

    @property
    def workspace(self) -> Path:
        return Path(self.config.workspace)
