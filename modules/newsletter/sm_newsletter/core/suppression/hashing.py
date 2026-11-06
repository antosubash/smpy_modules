"""How an address becomes a suppression key: records' normalisation, then SHA-256."""

from __future__ import annotations

import hashlib

__all__ = ["email_hash", "normalise_email"]


def normalise_email(address: object) -> str:
    """``address`` stripped and lower-cased; ``ValueError`` for an empty or non-string one."""
    if not isinstance(address, str):
        raise ValueError(f"not an email address: {address!r}")
    normalised = address.strip().lower()
    if not normalised:
        raise ValueError("empty email address")
    return normalised


def email_hash(address: object) -> str:
    """The hex SHA-256 of the normalised address: what a suppression row stores."""
    return hashlib.sha256(normalise_email(address).encode()).hexdigest()
