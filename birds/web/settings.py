"""Deployment settings, read once from environment variables (Vercel) or built by scripts/serve.py."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_ENDPOINT_HOSTS = ("endpoints.huggingface.cloud",)  # i.e. *.endpoints.huggingface.cloud


def _flag(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "oui")


def _num(value: str | None, default, cast=float, minimum=None):
    try:
        n = cast(value) if value is not None and value.strip() else default
    except (TypeError, ValueError):
        return default
    return default if n is not None and minimum is not None and n < minimum else n


@dataclass
class Settings:
    # the model endpoint configured by the operator (None: demo only, unless a user endpoint is allowed)
    base_url: str | None = None
    model: str = "adubrou/Bird-S-4B"  # vLLM serves a repo under its own name unless --served-model-name is set
    model_label: str = "Bird S 4B"  # the product name shown in the interface
    api_key: str | None = None
    searxng_url: str | None = None
    # user-supplied endpoints ("Mon endpoint" in the settings of the app)
    allow_user_endpoint: bool = False
    endpoint_allowed_hosts: tuple[str, ...] = DEFAULT_ENDPOINT_HOSTS
    # resources
    grid_intensity: float | None = None  # g CO2e / kWh, shown only when set
    wh_per_1k_tokens: float | None = None  # operator calibration -> "estimated" energy
    calibration_source: str | None = None
    measure_gpu: bool = False
    equivalent: dict | None = None  # {"label", "wh", "source"}: an everyday comparison, only if configured and cited
    # protection of a public URL
    access_code: str | None = None
    rate_limit: int = 20  # requests per minute and per IP, per instance (best effort)
    max_messages: int = 60
    max_message_chars: int = 24_000
    max_request_chars: int = 400_000
    max_attachments: int = 4
    max_attachment_chars: int = 60_000
    max_steps: int = 6
    max_calls_per_step: int = 3
    max_tokens: int = 1024
    max_inline_file_bytes: int = 3_000_000
    # time
    max_seconds: float = 240.0  # agent budget for one request; keep it below the function's maxDuration
    heartbeat_seconds: float = 10.0
    confirm_ttl: float = 900.0
    # stateless confirm
    signing_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)
    signing: str = "ephemeral"  # "configured" | "derived" | "ephemeral"
    # workspace: None = a fresh temporary folder per request, deleted afterwards (serverless)
    workspace: str | None = None
    demo_delay: float = 1.0
    local_llm: object | None = None  # scripts/serve.py --local
    local_tok: object | None = None
    tokenizer: str | None = None  # scripts/serve.py --tokenizer: real tokenizer instead of the vendored template

    @property
    def server_configured(self) -> bool:
        return bool(self.base_url) or self.local_llm is not None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        get = lambda k: (e.get(k) or "").strip() or None  # noqa: E731
        base_url, api_key, access = get("BIRD_BASE_URL"), get("BIRD_API_KEY"), get("BIRD_ACCESS_CODE")
        # Safe default: visitors may type their own endpoint only when the operator configured none. A shared
        # deployment with a server endpoint should not also invite people to paste tokens in a browser.
        allow_user = _flag(get("BIRD_ALLOW_USER_ENDPOINT"), default=not base_url)
        hosts = tuple(
            h.strip().lower().lstrip("*.") for h in (get("BIRD_ENDPOINT_ALLOWED_HOSTS") or "").split(",") if h.strip()
        )
        secret, signing = get("BIRD_SIGNING_SECRET"), "configured"
        if secret:
            key = secret.encode("utf-8")
        else:
            # No secret configured. A random per-process key would break the confirm flow as soon as two requests
            # land on two instances, so derive a stable one from what only this deployment knows, when possible.
            seed = api_key or access or get("VERCEL_DEPLOYMENT_ID") or get("VERCEL_URL")
            signing = "derived" if seed else "ephemeral"
            key = hashlib.sha256(("bird-signing:" + seed).encode("utf-8")).digest() if seed else secrets.token_bytes(32)
        equivalent = None
        eq_wh = _num(get("BIRD_EQUIVALENT_WH"), None, float, 0.0)
        if get("BIRD_EQUIVALENT_LABEL") and get("BIRD_EQUIVALENT_SOURCE") and eq_wh:
            equivalent = {"label": get("BIRD_EQUIVALENT_LABEL"), "wh": eq_wh, "source": get("BIRD_EQUIVALENT_SOURCE")}
        return cls(
            base_url=base_url,
            model=get("BIRD_MODEL") or "adubrou/Bird-S-4B",
            model_label=get("BIRD_MODEL_LABEL") or "Bird S 4B",
            api_key=api_key,
            searxng_url=get("BIRD_SEARXNG_URL"),
            allow_user_endpoint=allow_user,
            endpoint_allowed_hosts=DEFAULT_ENDPOINT_HOSTS + tuple(h for h in hosts if h not in DEFAULT_ENDPOINT_HOSTS),
            grid_intensity=_num(get("BIRD_GRID_INTENSITY"), None, float, 0.0),
            wh_per_1k_tokens=_num(get("BIRD_WH_PER_1K_TOKENS"), None, float, 0.0),
            calibration_source=get("BIRD_CALIBRATION_SOURCE"),
            equivalent=equivalent,
            access_code=access,
            rate_limit=_num(get("BIRD_RATE_LIMIT"), 20, int, 0),
            max_seconds=_num(get("BIRD_MAX_SECONDS"), 240.0, float, 5.0),
            signing_secret=key,
            signing=signing,
            demo_delay=_num(get("BIRD_DEMO_DELAY"), 1.0, float, 0.0),
        )
