"""The optional CAPTCHA on website submissions (#101, design §5 step 6).

Off by default (``public_submissions_captcha_provider = "none"``): the
honeypot, the signed form token, its minimum fill time and the rate limits
already stop the bulk of form spam, and a CAPTCHA costs every visitor. An
operator under a targeted flood turns on Cloudflare Turnstile or hCaptcha on
the Settings screen; both are verified the same way, by a form ``POST`` of
the secret and the widget's response to the provider's ``siteverify``
endpoint, which answers ``{"success": true|false}``.

It runs after the token and before anything is written, and it **fails
closed**: a response the provider rejects is ``400 captcha_failed``, and a
provider that cannot be reached (timeout, 5xx, an answer that is not JSON) is
``503 captcha_unavailable`` — never a submission let through unverified. A
provider that is configured without both keys is treated as unreachable for
the same reason, and the definition leaves the widget out
(:func:`public_config`), so a half-configured CAPTCHA refuses rather than
silently protects nothing.

The widget's script comes from the provider's host, so the public pages'
``Content-Security-Policy`` (pagebuilder's ``public_csp``) has to allow it;
:func:`csp_warning` says so once at startup when it does not.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Final

import httpx

from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.settings import RecordsSettings

__all__ = [
    "PROVIDERS",
    "TIMEOUT_SECONDS",
    "csp_warning",
    "public_config",
    "verify",
]

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS: Final = 5.0

PROVIDERS: Final[dict[str, dict[str, str]]] = {
    "turnstile": {
        "verify": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        "host": "challenges.cloudflare.com",
    },
    "hcaptcha": {
        "verify": "https://api.hcaptcha.com/siteverify",
        "host": "hcaptcha.com",
    },
}
"""Each provider's verify endpoint, and the host its widget loads from (what
``public_csp`` has to name)."""

MAX_RESPONSE_LEN: Final = 8192
"""A Turnstile response is at most 2048 characters and an hCaptcha one a few
thousand; far longer is not one (the body cap bounds it anyway)."""

MAX_ANSWER_BYTES: Final = 64 * 1024
"""The most of a provider's answer that is read: a verdict is a few hundred
bytes, so a larger one is refused (fails closed) rather than buffered."""

client_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(  # noqa: E731
    timeout=TIMEOUT_SECONDS
)
"""How a verification client is made — a seam for tests, which swap in an
``httpx.MockTransport`` rather than reaching a provider."""


def _provider(settings: RecordsSettings) -> str | None:
    name = settings.public_submissions_captcha_provider
    return name if name in PROVIDERS else None


def public_config(settings: RecordsSettings) -> dict[str, str] | None:
    """What the form needs to render the widget — the provider and its public
    site key — or ``None`` when no CAPTCHA is in use. The secret never leaves
    the server."""
    provider = _provider(settings)
    site_key = settings.public_submissions_captcha_site_key.strip()
    if provider is None or not site_key:
        return None
    return {"provider": provider, "site_key": site_key}


async def verify(settings: RecordsSettings, response: str | None, remote_ip: str) -> None:
    """Refuse the submission unless the provider vouches for ``response``.
    A no-op while no provider is configured."""
    provider = _provider(settings)
    if provider is None:
        return
    secret = settings.public_submissions_captcha_secret.strip()
    if not secret or not settings.public_submissions_captcha_site_key.strip():
        logger.error("records: the %s CAPTCHA has no site key or secret; refusing", provider)
        raise SubmissionRefused("captcha_unavailable", "the CAPTCHA could not be checked")
    if not response or len(response) > MAX_RESPONSE_LEN:
        raise SubmissionRefused("captcha_failed", "complete the CAPTCHA and send the form again")
    form: dict[str, Any] = {"secret": secret, "response": response}
    if remote_ip and remote_ip != "unknown":  # ``abuse.client_ip``'s "no client" placeholder
        form["remoteip"] = remote_ip
    try:
        async with (
            client_factory() as client,
            client.stream(
                "POST",
                PROVIDERS[provider]["verify"],
                data=form,
                headers={"Accept-Encoding": "identity"},
            ) as answer,
        ):
            answer.raise_for_status()
            # Raw bytes, unencoded as asked: a decoded stream could expand a
            # small compressed answer far past the bound before it is counted.
            encoding = answer.headers.get("content-encoding", "identity").strip().lower()
            if encoding not in ("", "identity"):
                raise ValueError(f"the provider answered with {encoding!r}, not identity")
            body = bytearray()
            async for piece in answer.aiter_raw():
                # Checked before appending: the buffer never holds more than
                # the bound, however large one chunk is.
                if len(body) + len(piece) > MAX_ANSWER_BYTES:
                    raise ValueError("the provider's answer is too large")
                body += piece
        success = json.loads(bytes(body)).get("success") is True
    except (httpx.HTTPError, httpx.StreamError, ValueError, AttributeError) as exc:
        logger.warning("records: the %s CAPTCHA could not be verified: %s", provider, exc)
        raise SubmissionRefused(
            "captcha_unavailable", "the CAPTCHA could not be checked; try again shortly"
        ) from exc
    if not success:
        raise SubmissionRefused("captcha_failed", "complete the CAPTCHA and send the form again")


def csp_warning(app: Any, settings: RecordsSettings) -> str | None:
    """A warning when a CAPTCHA is on and pagebuilder's public CSP does not
    name the provider's host — the widget would be blocked on every page.
    Read through ``app.state.pagebuilder`` with ``getattr``: records never
    imports pagebuilder, and without it there is no CSP of its to check."""
    provider = _provider(settings)
    if provider is None:
        return None
    services = getattr(getattr(app, "state", None), "pagebuilder", None)
    csp = getattr(getattr(services, "settings", None), "public_csp", None)
    if not isinstance(csp, str) or not csp.strip():
        return None
    host = PROVIDERS[provider]["host"]
    if host in csp:
        return None
    return (
        f"records: the {provider} CAPTCHA is on, but pagebuilder's public_csp does not "
        f"allow {host}; add it to script-src and frame-src or the widget cannot load"
    )
