"""The newsletter's confirm and unsubscribe links (#101).

Both are HMAC-SHA256 under the host's ``secret_key``, base64url, compared in
constant time, and **minted when the mail is built** from the subscriber's
current state — nothing secret is stored, and nothing secret is ever in the
outbox.

* **Confirm** — ``{tenant}.{type}.{uuid}.{exp}.{gate}.{mac}``, ``exp`` the
  expiry in epoch seconds (``public_submissions_confirm_ttl_hours`` after the
  send).
* **Unsubscribe** — ``{tenant}.{type}.{uuid}.{gate}.{mac}``: no expiry, so it
  stays stable and a future campaign sender can build the same one.

Two MACs, each 128 bits, so the order the design asks for holds: ``gate``
covers ``action|tenant|type|uuid[|exp]`` and is checked **before any
statement runs** — a forged tenant, type or uuid is refused without touching
the database, and so learns nothing. ``mac`` covers the same plus the
record's ``sm_nonce``, and is checked once the record is loaded. Rotating the
nonce (a re-subscribe, an unsubscribe) kills every link minted before it;
rotating ``secret_key`` kills all of them.

The tenant is the leftmost part and the only one that may itself contain a
dot (``TENANT_RE``); type keys, uuids, digits and base64url never do, so the
token is split from the right.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlencode

from sm_records import constants
from sm_records.constants import TYPE_KEY_PATTERN
from sm_records.tenancy import valid_tenant

__all__ = [
    "CONFIRM",
    "UNSUBSCRIBE",
    "Link",
    "LinkInvalid",
    "matches",
    "parse",
    "sign",
    "url",
]

CONFIRM: Final = "confirm"
UNSUBSCRIBE: Final = "unsubscribe"
Action = Literal["confirm", "unsubscribe"]

MAX_LINK_TOKEN: Final = 300
_TYPE_KEY_RE: Final = re.compile(TYPE_KEY_PATTERN)
_MAC_BYTES: Final = 16


class LinkInvalid(ValueError):  # noqa: N818 - reads as the condition it is
    """A link that does not verify, names nothing, or has expired."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.expired = reason == "expired"


@dataclass(frozen=True)
class Link:
    action: str
    tenant: str
    type_key: str
    uuid: str
    exp: int | None
    mac: str


def _mac(secret: str, *parts: object) -> str:
    message = "|".join(str(part) for part in parts).encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()[:_MAC_BYTES]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _claims(link: Link) -> tuple[object, ...]:
    head = (link.action, link.tenant, link.type_key, link.uuid)
    return head if link.exp is None else (*head, link.exp)


def sign(
    secret: str,
    action: Action,
    *,
    tenant: str,
    type_key: str,
    uuid: str,
    nonce: str,
    exp: int | None = None,
) -> str:
    """A link token for ``action`` on one subscriber, bound to ``nonce``."""
    link = Link(action, tenant, type_key, uuid, exp if action == CONFIRM else None, "")
    claims = _claims(link)
    gate = _mac(secret, "gate", *claims)
    mac = _mac(secret, "state", *claims, nonce)
    middle = [tenant, type_key, uuid] + ([str(exp)] if link.exp is not None else [])
    return ".".join([*middle, gate, mac])


def _well_formed(link: Link) -> bool:
    return (
        valid_tenant(link.tenant)
        and _TYPE_KEY_RE.fullmatch(link.type_key) is not None
        and link.uuid.isascii()
        and link.uuid.isalnum()
        and len(link.uuid) <= 64
    )


def parse(secret: str, action: Action, token: object, *, now: float | None = None) -> Link:
    """The link's claims once its ``gate`` verifies and, for a confirm link,
    it has not expired. Runs no statement: what it refuses never reached the
    database."""
    if not isinstance(token, str) or not token.isascii() or len(token) > MAX_LINK_TOKEN:
        raise LinkInvalid("malformed")
    count = 5 if action == CONFIRM else 4
    parts = token.rsplit(".", count)
    if len(parts) != count + 1:
        raise LinkInvalid("malformed")
    if action == CONFIRM:
        tenant, type_key, uuid, exp_raw, gate, mac = parts
        if not exp_raw.isdigit() or len(exp_raw) > 12:
            raise LinkInvalid("malformed")
        exp: int | None = int(exp_raw)
    else:
        tenant, type_key, uuid, gate, mac = parts
        exp = None
    link = Link(action, tenant, type_key, uuid, exp, mac)
    if not _well_formed(link):
        raise LinkInvalid("malformed")
    if not hmac.compare_digest(_mac(secret, "gate", *_claims(link)), gate):
        raise LinkInvalid("does not verify")
    if exp is not None and (time.time() if now is None else now) > exp:
        raise LinkInvalid("expired")
    return link


def matches(secret: str, link: Link, nonce: object) -> bool:
    """Whether ``link`` was minted for the subscriber's current ``sm_nonce``."""
    if not isinstance(nonce, str) or not nonce:
        return False
    return hmac.compare_digest(_mac(secret, "state", *_claims(link), nonce), link.mac)


def url(base_url: str, action: Action, token: str, locale: str | None) -> str:
    """The absolute landing-page address the mail links to. ``l`` is only the
    page's language — presentation, not a claim, so it is not signed."""
    query = {"t": token, **({"l": locale} if locale else {})}
    return f"{base_url}{constants.PUBLIC_SUBMISSIONS_VIEW_PREFIX}{action}?{urlencode(query)}"
