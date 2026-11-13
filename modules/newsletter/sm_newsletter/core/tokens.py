"""The per-send tokens every tracked link carries (S10, T17).

``{tenant}.{campaign_id}.{send_id}.{mac}``: HMAC-SHA256 under the host's
current ``secret_key``, base64url, truncated to 128 bits, compared in constant
time. Verification also accepts keys retained in ``SM_SECRET_KEY_PREVIOUS``;
removing a key revokes its links. Signing always uses the supplied current key.
The MAC covers a purpose (``u`` unsubscribe, ``o`` open, ``c`` click) that is
never in the token: each route implies it, so a token minted for one purpose
fails ``parse`` for the others and a leaked click URL cannot unsubscribe anyone.
Minted when the mail is built and never stored. The tenant may itself contain
dots, so the token is split from the right. ``parse`` never raises and runs no
statement: a forged token is refused before the database is touched.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sm_newsletter.core import crypto
from sm_newsletter.core.constants import CLICK_PREFIX, OPEN_PREFIX, UNSUBSCRIBE_PREFIX
from sm_newsletter.core.tenancy import valid_tenant

__all__ = [
    "MAX_TOKEN",
    "PURPOSES",
    "Purpose",
    "SendToken",
    "click_url",
    "host_secret",
    "open_url",
    "parse",
    "sign",
    "unsubscribe_url",
    "verify",
]

logger = logging.getLogger(__name__)

Purpose = Literal["u", "o", "c"]
PURPOSES: Final = ("u", "o", "c")

MAX_TOKEN: Final = 200
_MAC_BYTES: Final = 16
_MAX_DIGITS: Final = 18


@dataclass(frozen=True)
class SendToken:
    tenant_id: str
    campaign_id: int
    send_id: int


def _mac(secret: str, purpose: str, tenant_id: str, campaign_id: int, send_id: int) -> str:
    message = f"newsletter|{purpose}|{tenant_id}|{campaign_id}|{send_id}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()[:_MAC_BYTES]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign(secret: str, *, purpose: Purpose, tenant_id: str, campaign_id: int, send_id: int) -> str:
    if not secret:
        raise ValueError("a send token needs a secret")
    if purpose not in PURPOSES:
        raise ValueError("unknown token purpose")
    if not valid_tenant(tenant_id):
        raise ValueError("invalid tenant")
    mac = _mac(secret, purpose, tenant_id, campaign_id, send_id)
    return f"{tenant_id}.{campaign_id}.{send_id}.{mac}"


def parse(secret: str, token: object, *, purpose: Purpose) -> SendToken | None:
    """Claims under the current or a retained key, else ``None``. Never raises.

    Read retired keys only after the current MAC fails. Malformed retired-key
    configuration refuses fallback without revealing its value.
    """
    if not secret or purpose not in PURPOSES or not isinstance(token, str):
        return None
    if not token.isascii() or len(token) > MAX_TOKEN:
        return None
    parts = token.rsplit(".", 3)
    if len(parts) != 4:
        return None
    tenant_id, campaign_raw, send_raw, mac = parts
    if not (campaign_raw.isdigit() and send_raw.isdigit()):
        return None
    if len(campaign_raw) > _MAX_DIGITS or len(send_raw) > _MAX_DIGITS:
        return None
    if not valid_tenant(tenant_id):
        return None
    campaign_id, send_id = int(campaign_raw), int(send_raw)
    if f"{campaign_id}.{send_id}" != f"{campaign_raw}.{send_raw}":
        return None  # a leading zero: one send has exactly one token
    if not hmac.compare_digest(_mac(secret, purpose, tenant_id, campaign_id, send_id), mac):
        try:
            matched = any(
                hmac.compare_digest(_mac(key, purpose, tenant_id, campaign_id, send_id), mac)
                for key in crypto.previous_secrets()
            )
        except (RuntimeError, UnicodeEncodeError):
            logger.error("newsletter: invalid SM_SECRET_KEY_PREVIOUS; token refused")
            return None
        if not matched:
            return None
    return SendToken(tenant_id, campaign_id, send_id)


def unsubscribe_url(public_base: str, token: str) -> str:
    return f"{public_base.rstrip('/')}{UNSUBSCRIBE_PREFIX}{token}"


def open_url(public_base: str, token: str) -> str:
    return f"{public_base.rstrip('/')}{OPEN_PREFIX}{token}.gif"


def click_url(public_base: str, token: str, position: int) -> str:
    return f"{public_base.rstrip('/')}{CLICK_PREFIX}{token}/{position}"


def host_secret(app: Any) -> str:
    """The web process's secret; ``""`` means "cannot verify"."""
    try:
        return str(app.state.sm.settings.secret_key or "")
    except AttributeError:
        return ""


_warned: set[str] = set()


def verify(
    app: Any, token: str, *, purpose: Purpose, resolved_tenant: str | None, refused: str
) -> SendToken | None:
    """The claims of a public link's token, or ``None``: no host secret (one
    ERROR per ``refused`` text, saying what is refused), a bad MAC, or a host
    that resolved another tenant than the token's (``resolved_tenant`` is only
    ever host-derived). Runs no statement."""
    secret = host_secret(app)
    if not secret:
        if refused not in _warned:
            _warned.add(refused)
            logger.error("newsletter: no host secret_key; %s", refused)
        return None
    claims = parse(secret, token, purpose=purpose)
    if claims is None:
        return None
    if resolved_tenant is not None and resolved_tenant != claims.tenant_id:
        return None
    return claims
