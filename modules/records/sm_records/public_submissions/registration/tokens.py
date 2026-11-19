"""The registration token: the form token, bound to one event and one occurrence (PR 9).

``{digest}.{issued}.{nonce}.{event_id}.{occurrence_key}.{mac}``, with ``mac`` the same
HMAC-SHA256 as the form token's, over ``registration|tenant|type_key|digest|issued|nonce|event_id|
occurrence_key``. It proves what the form token proves (loaded from this host, for this type in
this tenant, between ``min_fill`` and ``max_age`` ago, showing exactly ``digest``) **and** which
event and which occurrence the visitor is registering for. The submit route takes the event *only*
from here: no body field names it, and the type, not the page, says everything else.

A different purpose label from the form token's ``"form"`` and six parts against four mean
neither can be turned into the other. ``event_id`` and ``occurrence_key`` are checked for their one
canonical spelling (ASCII, lower case, the key beginning with the event's own id) before the MAC is
computed, so no separator can be smuggled in and two spellings never name one occurrence. The
format matches events' (``sm_events.registration.args``): events refuses anything else, and
records does not import events to share it.
"""

from __future__ import annotations

import hmac
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sm_records.public_submissions.tokens import TokenError, _mac

__all__ = [
    "RegistrationToken",
    "canonical_event_id",
    "canonical_key",
    "sign_registration",
    "verify_registration",
]

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_EVENT = re.compile(rf"{_UUID}\Z", re.ASCII)
_KEY = re.compile(rf"(?P<id>{_UUID})(?::(?P<stamp>[0-9]{{8}}T[0-9]{{6}}Z))?\Z", re.ASCII)
_STAMP = "%Y%m%dT%H%M%SZ"
MAX_TOKEN = 300


@dataclass(frozen=True)
class RegistrationToken:
    digest: str
    issued: int
    event_id: str
    occurrence_key: str


def canonical_event_id(value: object) -> str:
    if not isinstance(value, str) or _EVENT.fullmatch(value) is None:
        raise ValueError("not an event id")
    return value


def canonical_key(event_id: str, value: object) -> str:
    """``value`` if it is ``event_id``'s own occurrence key in its one spelling."""
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("not an occurrence key")
    found = _KEY.fullmatch(value)
    if found is None or found["id"] != event_id:
        raise ValueError("not an occurrence key of this event")
    if found["stamp"] is not None:
        parsed = datetime.strptime(found["stamp"], _STAMP).replace(tzinfo=UTC)
        if parsed.strftime(_STAMP) != found["stamp"]:
            raise ValueError("not the canonical spelling of an instant")
    return value


def sign_registration(
    secret: str,
    tenant: str,
    type_key: str,
    digest: str,
    event_id: str,
    occurrence_key: str,
    *,
    now: float | None = None,
) -> str:
    event = canonical_event_id(event_id)
    key = canonical_key(event, occurrence_key)
    issued = int(time.time() if now is None else now)
    nonce = secrets.token_hex(8)
    mac = _mac(secret, "registration", tenant, type_key, digest, issued, nonce, event, key)
    return f"{digest}.{issued}.{nonce}.{event}.{key}.{mac}"


def verify_registration(
    secret: str,
    token: str,
    tenant: str,
    type_key: str,
    *,
    min_fill: int,
    max_age: int,
    now: float | None = None,
) -> RegistrationToken:
    """The token's claims, once its shape, MAC and age check out (``TokenError`` otherwise)."""
    parts = (
        token.split(".")
        if isinstance(token, str) and token.isascii() and len(token) <= MAX_TOKEN
        else []
    )
    if len(parts) != 6 or not parts[0].isalnum() or not parts[1].isdigit():
        raise TokenError("malformed registration token")
    digest, issued, nonce, event_id, key, mac = parts
    try:
        event = canonical_event_id(event_id)
        canonical_key(event, key)
    except ValueError:
        raise TokenError("malformed registration token") from None
    expected = _mac(
        secret, "registration", tenant, type_key, digest, int(issued), nonce, event, key
    )
    if not hmac.compare_digest(expected, mac):
        raise TokenError("registration token does not verify")
    age = (time.time() if now is None else now) - int(issued)
    if age < min_fill:
        raise TokenError("form sent too soon after it was loaded")
    if age > max_age:
        raise TokenError("form token has expired")
    return RegistrationToken(digest, int(issued), event, key)
