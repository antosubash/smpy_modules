"""The comparison behind ``test_images_error_shape``: byte-exact, nothing substituted."""

from __future__ import annotations

import base64
import json

import httpx
from itsdangerous import TimestampSigner

# Only the clock and server timings differ between two answers; nothing else is dropped.
IGNORED = {"date", "server-timing"}
SESSION_COOKIE = "session"


def session_payload(value: str, secret: str) -> dict:
    """The signed session cookie's contents. The signature is verified with the
    app's own secret (Starlette's itsdangerous signer), so a forged or truncated
    value fails here. Nothing is normalised: the framework stamps ``expires_at``
    at sign-in and keeps it, so identical snapshots carry the same deadline."""
    raw = TimestampSigner(secret).unsign(value.encode(), max_age=14 * 24 * 3600)
    return json.loads(base64.b64decode(raw))


def cookies(response: httpx.Response, secret: str) -> list[tuple]:
    """Every Set-Cookie as (name, attributes, value); the session cookie's value
    is its decoded, signature-verified payload."""
    out = []
    for raw in response.headers.get_list("set-cookie"):
        first, _, attrs = raw.partition(";")
        name, _, value = first.partition("=")
        name = name.strip()
        shown = (
            json.dumps(session_payload(value, secret), sort_keys=True)
            if name == SESSION_COOKIE
            else value
        )
        out.append((name, attrs.strip(), shown))
    return sorted(out)


def shape(response: httpx.Response, secret: str):
    """Everything observable, nothing normalised by pattern: status, the raw body
    bytes (httpx undoes gzip only), every header but the clock and timings, and
    the decoded cookies. Content-Length is compared as sent."""
    headers = {k: v for k, v in response.headers.items() if k not in IGNORED and k != "set-cookie"}
    return response.status_code, response.content, headers, cookies(response, secret)


def sign_session(secret: str, payload: dict, when: float | None = None) -> str:
    raw = base64.b64encode(json.dumps(payload).encode())
    signer = TimestampSigner(secret)
    return signer.sign(raw).decode()
