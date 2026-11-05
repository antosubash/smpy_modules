"""The per-send token every tracked link carries (S10).

``{tenant}.{campaign_id}.{send_id}.{mac}``: HMAC-SHA256 under the host's
``secret_key``, base64url, truncated to 128 bits, compared in constant time.
Minted when the mail is built and never stored. The tenant may itself contain
dots, so the token is split from the right. ``parse`` never raises and runs no
statement: a forged token is refused before the database is touched.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Final

from sm_newsletter.core.constants import UNSUBSCRIBE_PREFIX
from sm_newsletter.core.tenancy import valid_tenant

__all__ = ["MAX_TOKEN", "SendToken", "host_secret", "parse", "sign", "unsubscribe_url"]

MAX_TOKEN: Final = 200
_MAC_BYTES: Final = 16
_MAX_DIGITS: Final = 18


@dataclass(frozen=True)
class SendToken:
    tenant_id: str
    campaign_id: int
    send_id: int


def _mac(secret: str, tenant_id: str, campaign_id: int, send_id: int) -> str:
    message = f"newsletter|send|{tenant_id}|{campaign_id}|{send_id}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()[:_MAC_BYTES]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign(secret: str, *, tenant_id: str, campaign_id: int, send_id: int) -> str:
    if not secret:
        raise ValueError("a send token needs a secret")
    if not valid_tenant(tenant_id):
        raise ValueError("invalid tenant")
    return f"{tenant_id}.{campaign_id}.{send_id}.{_mac(secret, tenant_id, campaign_id, send_id)}"


def parse(secret: str, token: object) -> SendToken | None:
    """The claims when the MAC verifies, else ``None``. Never raises."""
    if not secret or not isinstance(token, str):
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
    if not hmac.compare_digest(_mac(secret, tenant_id, campaign_id, send_id), mac):
        return None
    return SendToken(tenant_id, campaign_id, send_id)


def unsubscribe_url(public_base: str, token: str) -> str:
    return f"{public_base.rstrip('/')}{UNSUBSCRIBE_PREFIX}{token}"


def host_secret(app: Any) -> str:
    """The web process's secret; ``""`` means "cannot verify"."""
    try:
        return str(app.state.sm.settings.secret_key or "")
    except AttributeError:
        return ""
