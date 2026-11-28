"""Signed, short-lived tokens that carry a paused run between two independent requests (stateless confirm).

    token = base64url(zlib(json(payload))) + "." + base64url(HMAC-SHA256(secret, body))

The payload is readable by its holder (it only contains what that user's own run already saw); what the signature
guarantees is that it was issued by this deployment, has not been altered and has not expired.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import zlib

MAX_TOKEN_CHARS = 600_000


class TokenError(ValueError):
    """The token is malformed, forged, expired or does not belong to this request."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def digest(value) -> str:
    """Stable SHA-256 of a JSON-serialisable value (used to bind a token to a conversation or an action)."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sign(payload: dict, secret: bytes, ttl: float, now: float | None = None) -> str:
    body = dict(payload, exp=int((now if now is not None else time.time()) + ttl))
    raw = _b64(
        zlib.compress(json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"), 6)
    )
    return raw + "." + _b64(hmac.new(secret, raw.encode("ascii"), hashlib.sha256).digest())


def verify(token: str, secret: bytes, now: float | None = None) -> dict:
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
        raise TokenError("malformed token")
    raw, sig = token.split(".")
    try:
        given = _unb64(sig)
    except (ValueError, TypeError):
        raise TokenError("malformed token") from None
    if not hmac.compare_digest(given, hmac.new(secret, raw.encode("ascii", "ignore"), hashlib.sha256).digest()):
        raise TokenError("invalid signature")
    try:
        payload = json.loads(zlib.decompress(_unb64(raw)))
    except (ValueError, zlib.error):
        raise TokenError("malformed token") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("exp"), int):
        raise TokenError("malformed token")
    if (now if now is not None else time.time()) > payload["exp"]:
        raise TokenError("expired token")
    return payload


def expiry(token: str) -> int | None:
    """The ``exp`` of a token this server just signed, read WITHOUT checking the signature: only to tell its holder
    until when it can be used (never to trust its content)."""
    try:
        exp = json.loads(zlib.decompress(_unb64(token.split(".")[0]))).get("exp")
    except (ValueError, TypeError, AttributeError, zlib.error):
        return None
    return exp if isinstance(exp, int) else None


# ---------------------------------------------------------------- web image URLs (/api/img)


def _image_sig(u: str, e: int, secret: bytes) -> str:
    return hmac.new(secret, f"img|{e}|{u}".encode(), hashlib.sha256).hexdigest()[:32]


def sign_image_url(u: str, secret: bytes, ttl: float, now: float | None = None) -> str:
    """Same-origin path that serves image ``u`` through the server. Only URLs signed here are served, so /api/img
    is not an open proxy: it shows what Bird surfaced in an answer, for ``ttl`` seconds."""
    from urllib.parse import urlencode

    e = int((now if now is not None else time.time()) + ttl)
    return "/api/img?" + urlencode({"u": u, "e": e, "s": _image_sig(u, e, secret)})


def check_image_sig(u: str, e: str, s: str, secret: bytes, now: float | None = None) -> None:
    """Raise TokenError('invalid signature' | 'expired') unless (u, e, s) was issued by sign_image_url."""
    try:
        exp = int(e)
    except (TypeError, ValueError):
        raise TokenError("invalid signature") from None
    given = (s or "").encode("ascii", "ignore") if isinstance(s, str) else b""
    if not hmac.compare_digest(given, _image_sig(u, exp, secret).encode()):
        raise TokenError("invalid signature")
    if (now if now is not None else time.time()) > exp:
        raise TokenError("expired")
