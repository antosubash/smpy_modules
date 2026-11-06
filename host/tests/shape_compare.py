"""The comparison behind ``test_images_error_shape``: byte-exact but for the CSP nonce."""

from __future__ import annotations

import base64
import json
import re

import httpx
from itsdangerous import TimestampSigner

# Only the clock and server timings differ between two answers; nothing else is dropped.
IGNORED = {"date", "server-timing"}
SESSION_COOKIE = "session"
_POLICY_NONCE = re.compile(r"'nonce-([\w-]+)'")
_BODY_NONCE = re.compile(rb'\bnonce="([\w-]+)"')


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
    the decoded cookies. Content-Length is compared as sent, except on a compressed
    page, where the nonce makes it vary.

    One value is substituted. The framework stamps each response with a random
    CSP nonce, on the page's scripts and (outside development) in its policy, so
    two answers can never match on it. It is replaced literally, after checking
    that the response uses a single nonce throughout.
    """
    headers = {k: v for k, v in response.headers.items() if k not in IGNORED and k != "set-cookie"}
    content = response.content
    policy = headers.get("content-security-policy", "")
    nonces = set(_POLICY_NONCE.findall(policy))
    nonces.update(found.decode() for found in _BODY_NONCE.findall(content))
    assert len(nonces) <= 1, f"a response uses one CSP nonce, got {nonces}"
    for nonce in nonces:
        if "content-security-policy" in headers:
            headers["content-security-policy"] = policy.replace(nonce, "<nonce>")
        content = content.replace(nonce.encode(), b"<nonce>")
    # A page's random nonce moves its gzipped size by a few bytes, and a HEAD has no
    # body to find the nonce in. A GET's decoded bytes cover what that length described.
    if "content-encoding" in headers and "text/html" in headers.get("content-type", ""):
        headers.pop("content-length", None)
    return response.status_code, content, headers, cookies(response, secret)


def sign_session(secret: str, payload: dict, when: float | None = None) -> str:
    raw = base64.b64encode(json.dumps(payload).encode())
    signer = TimestampSigner(secret)
    return signer.sign(raw).decode()
