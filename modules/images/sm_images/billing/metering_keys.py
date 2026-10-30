"""Idempotency keys for billing's meters, bounded to billing's key length.

Billing accepts keys of 1-121 characters (``sm_billing.metering.validate.
KEY_MAX``: the 128-character column less the ``:refund`` suffix). A readable
composite of a tenant, three uuids and a version does not fit, so a key is a
short readable prefix plus the SHA-256 of the full composite: deterministic
for the same parts (a retry or a redelivery is charged once), distinct for
any other, and under 80 characters whatever the parts' lengths.
"""

from __future__ import annotations

import hashlib
from typing import Any

__all__ = ["KEY_MAX", "digest_key"]

KEY_MAX = 121  # billing's limit; tests/test_metering_keys.py keeps it in step


def digest_key(prefix: str, *parts: Any) -> str:
    """``<prefix>:<sha256 hex of the parts>``; ``prefix`` stays readable."""
    composite = "\x1f".join(str(p) for p in parts)
    key = f"{prefix}:{hashlib.sha256(composite.encode()).hexdigest()}"
    if len(key) > KEY_MAX:  # only a too-long prefix gets here: a programming error
        raise ValueError(f"metering key prefix {prefix!r} is too long")
    return key
