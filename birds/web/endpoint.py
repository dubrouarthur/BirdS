"""User-supplied model endpoints: validation (this is an SSRF vector), plain-language diagnostics.

A visitor may point the app at their own OpenAI-compatible endpoint (typically a Hugging Face Inference
Endpoint). The URL is then fetched BY OUR SERVER, so it is restricted hard: https only, default port, host in an
allowlist (``*.endpoints.huggingface.cloud`` unless the operator extends it), public addresses only, connection
pinned to the validated address, no redirects. The address checks are the harness egress guard, reused as is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from birds.harness import guard
from birds.harness.llm import CompletionsClient, EndpointError, normalize_base_url

MAX_URL_CHARS, MAX_TOKEN_CHARS, MAX_MODEL_CHARS = 300, 400, 120
_PRINTABLE = re.compile(r"^[\x21-\x7e]+$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$")


class EndpointRejected(ValueError):
    """The endpoint parameters are not acceptable. ``code`` is stable, the message is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EgressPolicy:
    """What ``guard.check_url`` needs: here, https on the default port towards allowlisted hosts only."""

    allow_domains: tuple[str, ...]
    allowed_ports: tuple[int, ...] = (443,)
    deny_domains: tuple[str, ...] = ()


def validate_user_endpoint(url: str, allowed_hosts: tuple[str, ...]) -> tuple[str, EgressPolicy]:
    """Return (normalised base URL ending with /v1, egress policy) or raise EndpointRejected."""
    import httpx

    url = (url or "").strip()
    if not url or len(url) > MAX_URL_CHARS or not _PRINTABLE.match(url):
        raise EndpointRejected("invalid_url", "endpoint URL missing, too long or with unexpected characters")
    if not url.lower().startswith("https://"):
        raise EndpointRejected("https_only", "the endpoint URL must start with https://")
    try:
        u = httpx.URL(url)
        port = u.port
    except Exception:
        raise EndpointRejected("invalid_url", "the endpoint URL cannot be parsed") from None
    host = (u.host or "").lower().rstrip(".")
    if u.userinfo or u.query or u.fragment:
        raise EndpointRejected("invalid_url", "the endpoint URL must not contain credentials, a query or a fragment")
    if port not in (None, 443):
        raise EndpointRejected("port", "only the default https port is allowed")
    if not host or re.fullmatch(r"[\d.]+|\[.*\]", host) or ":" in host:
        raise EndpointRejected("host_not_allowed", "the endpoint must be a host name, not an IP address")
    if not any(host.endswith("." + d) for d in allowed_hosts):
        raise EndpointRejected("host_not_allowed", "this host is not in the list of allowed endpoint hosts")
    policy = EgressPolicy(allow_domains=tuple(allowed_hosts))
    base = normalize_base_url(str(u.copy_with(path=u.path.rstrip("/") or "/")))
    try:
        guard.check_url(base + "/completions", policy)  # resolves the name: public addresses only
    except guard.Blocked as e:
        raise EndpointRejected("address", f"endpoint address refused: {e}") from None
    return base, policy


def clean_token(token: str | None) -> str | None:
    token = (token or "").strip()
    if not token:
        return None
    if len(token) > MAX_TOKEN_CHARS or not _PRINTABLE.match(token):
        raise EndpointRejected("invalid_token", "the access token has an unexpected shape")
    return token


def clean_model(model: str | None, default: str = "bird") -> str:
    model = (model or "").strip() or default
    if len(model) > MAX_MODEL_CHARS or not _MODEL.match(model):
        raise EndpointRejected("invalid_model", "the model name has an unexpected shape")
    return model


MESSAGES = {
    "ok": (
        "Connexion réussie : le serveur du modèle répond sur /v1/completions.",
        "Connected: the model server answers on /v1/completions.",
    ),
    "ok_no_usage": (
        "Connexion réussie. Le serveur du modèle ne renvoie pas le nombre de tokens : il sera estimé, et étiqueté comme tel.",
        "Connected. The model server does not report token counts: they will be estimated, and labelled as such.",
    ),
    "unauthorized": (
        "Le serveur du modèle refuse le jeton d'accès. Vérifiez qu'il est valide et qu'il a le droit d'appeler ce serveur.",
        "The model server refuses the access token. Check that it is valid and allowed to call this server.",
    ),
    "waking": (
        "Le modèle se réveille (serveur en veille ou en cours de démarrage). Cela peut prendre quelques minutes : réessayez dans un instant.",
        "The model is waking up (server scaled to zero or still starting). This can take a few minutes: try again shortly.",
    ),
    "endpoint_down": (
        "Le serveur du modèle est en erreur et ne peut pas démarrer pour le moment. Son administrateur doit le relancer depuis la console Hugging Face (Inference Endpoints).",
        "The model server is in error and cannot start right now. Its administrator must restart it from the Hugging Face console (Inference Endpoints).",
    ),
    "unknown_model": (
        "Le serveur du modèle répond, mais ne connaît pas ce nom de modèle. Mettez dans « Nom du modèle » (ou BIRD_MODEL) le nom indiqué par le serveur du modèle après « Valid aliases ».",
        'The model server answers but does not know this model name. Set the model name (or BIRD_MODEL) to the name the model server lists after "Valid aliases".',
    ),
    "wrong_route": (
        "L'adresse répond, mais pas sur /v1/completions. Vérifiez l'URL et que le moteur expose l'API compatible OpenAI.",
        "The address answers, but not on /v1/completions. Check the URL and that the engine exposes the OpenAI-compatible API.",
    ),
    "bad_request": (
        "Le serveur du modèle a rejeté la requête. Le nom du modèle est peut-être incorrect pour ce moteur.",
        "The model server rejected the request. The model name may be wrong for this engine.",
    ),
    "server": (
        "Le serveur du modèle a répondu par une erreur. Consultez ses journaux.",
        "The model server answered with an error. Check its logs.",
    ),
    "unreachable": (
        "Impossible de joindre le serveur du modèle. Vérifiez l'adresse et qu'il est bien démarré.",
        "Cannot reach the model server. Check the address and that it is running.",
    ),
    "timeout": ("Le serveur du modèle n'a pas répondu à temps.", "The model server did not answer in time."),
    "blocked": ("Cette adresse n'est pas autorisée pour un serveur de modèle.", "This address is not allowed for a model server."),
    "https_only": ("L'adresse doit commencer par https://.", "The address must start with https://."),
    "invalid_url": ("L'adresse du serveur du modèle n'est pas valide.", "The model server address is not valid."),
    "port": ("Seul le port https par défaut est accepté.", "Only the default https port is accepted."),
    "host_not_allowed": (
        "Cet hôte n'est pas dans la liste autorisée (par défaut : *.endpoints.huggingface.cloud).",
        "This host is not in the allowed list (default: *.endpoints.huggingface.cloud).",
    ),
    "address": (
        "Cette adresse n'est pas autorisée (adresse privée ou introuvable).",
        "This address is not allowed (private or not found).",
    ),
    "invalid_token": ("Le jeton d'accès a une forme inattendue.", "The access token has an unexpected shape."),
    "invalid_model": ("Le nom du modèle a une forme inattendue.", "The model name has an unexpected shape."),
    "disabled": (
        "Cette instance n'accepte pas d'endpoint personnel : le modèle est configuré par l'administrateur.",
        "This instance does not accept personal endpoints: the model is configured by the administrator.",
    ),
    "not_configured": ("Aucun modèle n'est configuré sur ce serveur.", "No model is configured on this server."),
    "demo": ("Mode démo : aucun modèle à joindre.", "Demo mode: there is no model to reach."),
}


def explain(code: str, lang: str) -> str:
    fr, en = MESSAGES.get(code, MESSAGES["server"])
    return en if lang == "en" else fr


def probe(client: CompletionsClient, lang: str) -> dict:
    """One-token completion; never raises, never returns anything the caller typed."""
    try:
        info = client.probe()
    except EndpointError as e:
        return {"ok": False, "status": e.kind, "message": explain(e.kind, lang), "http_status": e.status}
    code = "ok" if info.get("usage_reported") else "ok_no_usage"
    images = False
    try:  # images go through /v1/chat/completions: one more 1-token call says whether that route exists
        client.chat([{"role": "user", "content": "Bonjour"}], 1)
        images = True
    except Exception:  # noqa: BLE001 - only a capability check
        images = False
    return {"ok": True, "status": code, "message": explain(code, lang), "seconds": info.get("seconds"), "images": images}
