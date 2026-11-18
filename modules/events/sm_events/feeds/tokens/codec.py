"""The token's shape and the one derivative of it that is stored."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from typing import Final

from sm_events.core import constants

__all__ = ["hash_token", "new_token", "well_formed"]

_SHAPE: Final = re.compile(constants.TOKEN_PATTERN)


def new_token() -> str:
    """A fresh token: the prefix and 32 random bytes, ``base64url`` without padding."""
    body = base64.urlsafe_b64encode(secrets.token_bytes(constants.TOKEN_BYTES)).rstrip(b"=")
    return constants.TOKEN_PREFIX + body.decode("ascii")


def hash_token(token: str) -> str:
    """The SHA-256 hex digest that is stored and looked up. The token is already 256 bits of
    entropy, so a plain digest is enough (nothing to brute-force, no salt to keep)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def well_formed(token: str) -> bool:
    """Whether ``token`` has the shape :func:`new_token` makes. A malformed one is refused
    before any database read: there is nothing it could name."""
    return isinstance(token, str) and _SHAPE.fullmatch(token) is not None
