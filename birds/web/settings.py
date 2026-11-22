"""Deployment settings, read once from environment variables (Vercel) or built by scripts/serve.py."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_ENDPOINT_HOSTS = ("endpoints.huggingface.cloud",)  # i.e. *.endpoints.huggingface.cloud

# Energy estimate of the remote GPU (power x time). Default: the NVIDIA L4 of the Inference Endpoint, whose rated
# maximum board power (TDP) is 72 W: https://www.nvidia.com/en-us/data-center/l4/ (specifications table).
DEFAULT_GPU_WATTS = 72.0
DEFAULT_GPU_LABEL = "NVIDIA L4 (72 W TDP)"
GPU_SOURCE = "https://www.nvidia.com/en-us/data-center/l4/"
# Energy comparison: a published, sourced per-query figure. Default: Google's median Gemini Apps text prompt,
# 0.24 Wh, full serving boundary (active chips, idle capacity, host CPU/RAM, data-centre PUE), 21 Aug 2025.
DEFAULT_REFERENCE = {
    "wh": 0.24,
    "label_fr": "une requête texte médiane d'un grand assistant généraliste (chiffre publié par son fournisseur, août 2025)",
    "label_en": "a median text prompt to a large general-purpose assistant (figure published by its provider, Aug 2025)",
    "source": "https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference",
}
# Theoretical compute per generated token (~2 x active parameters FLOPs): classes of large models, no brand names.
DEFAULT_COMPARE = (
    ("grand modèle dense", "large dense model", 400.0),
    ("grand modèle à experts", "large mixture-of-experts model", 40.0),
)


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
    brave_api_key: str | None = field(default=None, repr=False)
    tavily_api_key: str | None = field(default=None, repr=False)
    search_default: str = "wikipedia"  # "wikipedia" (no key) or "none"
    search_contact: str | None = None  # contact in the User-Agent sent to Wikipedia
    pin_dns: bool = True  # read_page connects to the validated IP; set False only behind a filtering egress proxy
    # user-supplied endpoints ("Mon endpoint" in the settings of the app)
    allow_user_endpoint: bool = False
    endpoint_allowed_hosts: tuple[str, ...] = DEFAULT_ENDPOINT_HOSTS
    # resources
    grid_intensity: float | None = None  # g CO2e / kWh, shown only when set
    wh_per_1k_tokens: float | None = None  # operator calibration -> "estimated" energy
    calibration_source: str | None = None
    measure_gpu: bool = False
    equivalent: dict | None = None  # {"label", "wh", "source"}: an everyday comparison, only if configured and cited
    gpu_watts: float | None = DEFAULT_GPU_WATTS  # None/0: no power x time estimate
    gpu_label: str = DEFAULT_GPU_LABEL
    gpu_source: str | None = GPU_SOURCE
    pue: float = 1.0
    reference: dict | None = field(default_factory=lambda: dict(DEFAULT_REFERENCE))  # None: comparison hidden
    active_params_b: float = 4.0  # Bird S 4B, dense
    compare_classes: tuple = DEFAULT_COMPARE  # ((label_fr, label_en, active params in billions), ...)
    # protection of a public URL
    access_code: str | None = None
    rate_limit: int = 20  # requests per minute and per IP, per instance (best effort)
    img_rate_limit: int = 60  # /api/img requests per minute and per IP (a separate window: an answer shows 3)
    image_ttl: float = 7 * 86400.0  # how long a signed web image URL stays valid (conversations reloaded later)
    max_messages: int = 60
    max_message_chars: int = 24_000
    max_request_chars: int = 400_000
    max_attachments: int = 4
    max_attachment_chars: int = 60_000
    max_binary_chars: int = 3_400_000  # base64 of PDF/Office files + images per request (Vercel caps bodies at 4.5 MB)
    max_steps: int = 6
    max_calls_per_step: int = 3
    cache_isolation: bool = True  # cache_salt per conversation (privacy) vs a prefix shared by all (energy)
    history_msg_tokens: int = 3168  # cap of one history message (head 2/3 + tail 1/3)
    history_tokens: int = 6000  # estimated tokens of earlier turns sent with each request (history.window)
    max_tokens: int = 1536  # per generation: a full make_slides call needs room
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
            # VERCEL_URL is public (it is the deployment's address): never a seed for a signing key
            seed = api_key or access or get("VERCEL_DEPLOYMENT_ID")
            signing = "derived" if seed else "ephemeral"
            key = hashlib.sha256(("bird-signing:" + seed).encode("utf-8")).digest() if seed else secrets.token_bytes(32)
        equivalent = None
        eq_wh = _num(get("BIRD_EQUIVALENT_WH"), None, float, 0.0)
        if get("BIRD_EQUIVALENT_LABEL") and get("BIRD_EQUIVALENT_SOURCE") and eq_wh:
            equivalent = {"label": get("BIRD_EQUIVALENT_LABEL"), "wh": eq_wh, "source": get("BIRD_EQUIVALENT_SOURCE")}
        gpu_watts = _num(get("BIRD_GPU_WATTS"), DEFAULT_GPU_WATTS, float, 0.0) or None
        gpu_label = get("BIRD_GPU_LABEL") or (
            DEFAULT_GPU_LABEL if gpu_watts == DEFAULT_GPU_WATTS else f"GPU {gpu_watts:g} W" if gpu_watts else ""
        )
        reference = dict(DEFAULT_REFERENCE)
        ref_wh = get("BIRD_REFERENCE_WH_PER_QUERY")
        if ref_wh is not None:
            if ref_wh.lower() in ("0", "off", "none", "non"):
                reference = None
            else:
                wh = _num(ref_wh, None, float, 0.0)
                label, source = get("BIRD_REFERENCE_LABEL"), get("BIRD_REFERENCE_SOURCE")
                # a custom figure is shown only with its label and its source
                reference = (
                    {"wh": wh, "label_fr": label, "label_en": label, "source": source}
                    if wh and label and source
                    else None
                )
        classes = DEFAULT_COMPARE
        if get("BIRD_COMPARE_CLASSES"):  # "grand modèle dense:400, grand modèle à experts:40"
            parsed = []
            for part in get("BIRD_COMPARE_CLASSES").split(","):
                name, _, num = part.rpartition(":")
                n = _num(num, None, float, 0.1)
                if name.strip() and n:
                    parsed.append((name.strip(), name.strip(), n))
            classes = tuple(parsed) or DEFAULT_COMPARE
        contact = get("BIRD_CONTACT") or (
            "https://" + get("VERCEL_PROJECT_PRODUCTION_URL") if get("VERCEL_PROJECT_PRODUCTION_URL") else None
        )
        return cls(
            brave_api_key=get("BIRD_BRAVE_API_KEY"),
            tavily_api_key=get("BIRD_TAVILY_API_KEY"),
            search_default="none"
            if (get("BIRD_SEARCH_DEFAULT") or "").lower() in ("none", "off", "0")
            else "wikipedia",
            search_contact=contact,
            pin_dns=_flag(get("BIRD_PIN_DNS"), default=True),
            gpu_watts=gpu_watts,
            gpu_label=gpu_label,
            pue=max(1.0, _num(get("BIRD_PUE"), 1.0, float, 1.0)),
            reference=reference,
            active_params_b=_num(get("BIRD_ACTIVE_PARAMS_B"), 4.0, float, 0.1),
            compare_classes=classes,
            max_tokens=_num(get("BIRD_MAX_TOKENS"), 1536, int, 256),
            history_tokens=_num(get("BIRD_HISTORY_TOKENS"), 6000, int, 1056),
            cache_isolation=(get("BIRD_CACHE_SALT") or "conversation").lower() not in ("off", "0", "none"),
            history_msg_tokens=_num(get("BIRD_HISTORY_MSG_TOKENS"), 3168, int, 528),
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
            img_rate_limit=_num(get("BIRD_IMG_RATE_LIMIT"), 60, int, 0),
            image_ttl=_num(get("BIRD_IMAGE_TTL"), 7 * 86400.0, float, 60.0),
            max_seconds=_num(get("BIRD_MAX_SECONDS"), 240.0, float, 5.0),
            signing_secret=key,
            signing=signing,
            demo_delay=_num(get("BIRD_DEMO_DELAY"), 1.0, float, 0.0),
        )
