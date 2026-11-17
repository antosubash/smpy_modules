"""Masking of email addresses the share picker returns."""

from __future__ import annotations

__all__ = ["mask_email", "visible_email"]

_MASK = "***"


def mask_email(address: str) -> str:
    """``alice@example.org`` becomes ``a***@example.org``; an address without
    ``@`` or with an empty local part becomes ``***``."""
    local, sep, domain = address.partition("@")
    if not sep or not local:
        return _MASK
    return f"{local[0]}{_MASK}@{domain}"


def visible_email(address: str, query: str) -> str:
    """The full address only when the stripped query is exactly that address
    (case-insensitive); otherwise the masked one. A 3-character query must not
    hand out members' addresses."""
    if query.strip().lower() == address.lower():
        return address
    return mask_email(address)
