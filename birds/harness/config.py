"""Deployment configuration and the per-run context handed to every tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from birds.tools import PRODUCT_TOOL_NAMES


@dataclass
class Config:
    workspace: Path
    allowed_tools: tuple[str, ...] = tuple(PRODUCT_TOOL_NAMES)  # per-deployment allowlist
    allow_python: bool = False  # run_python is NOT a sandbox: enable only inside a disposable container
    cache_salt: str | None = None  # vLLM prefix-cache isolation, one value per conversation (backends.cache_salt)
    route_tools: bool = True  # hide web tools for a plain "make me a file" request (agent.route)
    # loop limits
    max_steps: int = 6  # model generations per run
    max_calls_per_step: int = 3
    max_result_chars: int = 6000  # per tool result
    max_context_chars: int = 24000  # all tool results of a run together
    max_tokens: int = 1024  # per generation
    timeout_s: float = 180.0  # wall clock for the whole run
    max_side_effects: int = 5  # draft_email / make_* / run_python calls per run
    # network
    # web_search backend, first configured wins: SearXNG, Brave, Tavily, then the no-key default (tools/search.py)
    searxng_url: str | None = None  # operator-configured, so not subject to the egress policy
    brave_api_key: str | None = field(default=None, repr=False)
    tavily_api_key: str | None = field(default=None, repr=False)
    search_default: str = "wikipedia"  # "wikipedia" (no key, always available) or "none" (web_search hidden)
    search_contact: str | None = None  # contact put in the User-Agent sent to Wikipedia (URL or e-mail)
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
    # power x time estimate for a remote GPU we cannot read (None: off). Reported as "estimated", upper bound.
    gpu_watts: float | None = None
    gpu_label: str | None = None  # e.g. "NVIDIA L4, 72 W TDP"
    pue: float = 1.0  # 1.0 = GPU only
    audit_file: str | None = "bird_audit.jsonl"  # None: audit lines go to stdout (serverless logs)
    # rich results (places, company register, ECB rates): BIRD_GEO=off withdraws the three tools
    widgets: bool = True
    geo_user_agent: str = "BirdHarness/0.1 (+geo)"  # generic: never a person's name or e-mail
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    photon_url: str = "https://photon.komoot.io/api"
    ban_url: str = "https://data.geopf.fr/geocodage/search"
    company_url: str = "https://recherche-entreprises.api.gouv.fr/search"
    fx_url: str = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    geo_cache_dir: str | None = None  # optional disk cache (file names are hashes, never the query)


@dataclass
class Context:
    """What a tool may touch: the workspace, the config, an HTTP client, and the run's collected outputs."""

    config: Config
    http: Any  # httpx.Client
    search: Any = None  # search backend with .search(query, n) -> [{"title", "url", "snippet"}]
    sources: list[str] = field(default_factory=list)  # URLs actually read
    found: list[str] = field(default_factory=list)  # URLs the search backend returned (trusted for read_page)
    drafts: list[dict] = field(default_factory=list)  # email drafts for the UI (never sent)
    files: list[str] = field(default_factory=list)  # generated files
    bytes_fetched: int = 0
    step_info: dict | None = None  # set by a tool for the UI (e.g. which search backend answered); moved to the step
    lang: str = "fr"  # language of the conversation (search backends that care, e.g. Wikipedia)
    request: str = ""  # the user's own words for this run (make_slides checks that their figures made it in)
    geo_calls: int = 0  # upstream geocoder requests of this run (cap: geo.MAX_LOOKUPS_PER_RUN)
    place_calls: int = 0  # successful find_places calls of this run

    @property
    def workspace(self) -> Path:
        return Path(self.config.workspace)
