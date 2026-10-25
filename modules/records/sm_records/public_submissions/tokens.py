"""The signed form token, the keyed IP hash, and the two host values they need.

**Form token** — ``{digest}.{issued}.{nonce}.{mac}``, where ``mac`` is
HMAC-SHA256 under the host's ``secret_key`` over
``form|tenant|type_key|digest|issued|nonce``, base64url. Stateless: nothing
is stored. It proves the form was loaded from this host, for this type in
this tenant, at least ``min_fill`` seconds ago and at most ``max_age`` — and
``digest`` (:func:`~sm_records.public_submissions.definition.form_digest`)
says exactly what the visitor was shown, so a form loaded before an edit —
of a field or of the consent text — is a ``409 form_changed``. The digest is
in clear because the caller compares it; the MAC covers it.

**IP hash** — ``HMAC-SHA256(secret_key, f"{tenant}|{ip}")`` hex. Keyed, so
enumerating the IPv4 space does not reverse it; per tenant, so two
organisations' rows cannot be joined on it.

Rotating ``secret_key`` invalidates every outstanding form token, which costs
a visitor one automatic retry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any

__all__ = [
    "FormToken",
    "TokenError",
    "host_secret",
    "ip_hash",
    "public_base_url",
    "sign_form",
    "verify_form",
]


class TokenError(ValueError):
    """A token that does not verify, or is too young or too old."""


@dataclass(frozen=True)
class FormToken:
    digest: str
    issued: int


def host_secret(app: Any) -> str:
    """The host's ``secret_key``. There is always one in a real host (the
    framework generates and stores it); an app without one cannot sign."""
    secret = getattr(getattr(getattr(app.state, "sm", None), "settings", None), "secret_key", "")
    if not secret:
        raise RuntimeError("records: the host has no secret_key to sign submissions with")
    return str(secret)


def public_base_url(app: Any) -> str:
    """The host's ``public_base_url`` (an operator setting, never the request's
    ``Host``), or ``""`` while it is unset."""
    host = getattr(app.state, "host", None)
    return str(getattr(getattr(host, "settings", None), "public_base_url", "") or "").rstrip("/")


def _mac(secret: str, *parts: object) -> str:
    message = "|".join(str(part) for part in parts).encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign_form(
    secret: str, tenant: str, type_key: str, digest: str, *, now: float | None = None
) -> str:
    issued = int(time.time() if now is None else now)
    nonce = secrets.token_hex(8)
    mac = _mac(secret, "form", tenant, type_key, digest, issued, nonce)
    return f"{digest}.{issued}.{nonce}.{mac}"


def verify_form(
    secret: str,
    token: str,
    tenant: str,
    type_key: str,
    *,
    min_fill: int,
    max_age: int,
    now: float | None = None,
) -> FormToken:
    """The token's claims, once its MAC and its age check out."""
    # ASCII only: ``int()`` rejects what ``isdigit()`` accepts ("\u00b2"), and
    # ``hmac.compare_digest`` raises ``TypeError`` on a non-ASCII ``str`` -- either
    # would be a 500 for an anonymous caller instead of ``form_expired``.
    parts = token.split(".") if isinstance(token, str) and token.isascii() else []
    if len(parts) != 4 or not parts[0].isalnum() or not parts[1].isdigit():
        raise TokenError("malformed form token")
    digest, issued, nonce, mac = parts[0], int(parts[1]), parts[2], parts[3]
    expected = _mac(secret, "form", tenant, type_key, digest, issued, nonce)
    if not hmac.compare_digest(expected, mac):
        raise TokenError("form token does not verify")
    age = (time.time() if now is None else now) - issued
    if age < min_fill:
        raise TokenError("form sent too soon after it was loaded")
    if age > max_age:
        raise TokenError("form token has expired")
    return FormToken(digest=digest, issued=issued)


def ip_hash(secret: str, tenant: str, ip: str) -> str:
    return hmac.new(secret.encode(), f"{tenant}|{ip}".encode(), hashlib.sha256).hexdigest()
