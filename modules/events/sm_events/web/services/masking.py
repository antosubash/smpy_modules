"""Masking of email addresses the share picker returns."""

from __future__ import annotations

__all__ = ["mask_email", "matches_query", "safe_display_name", "visible_email"]

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


def matches_query(label: str, address: str, query: str) -> bool:
    """Whether the share picker may offer a user for *query*.

    Only a display name containing the stripped query (a label that is the
    address itself does not count), or the query being the whole address. A
    partial address never matches: otherwise the picker would confirm an
    address piece by piece."""
    needle = query.strip().lower()
    if not needle:
        return False
    if needle == address.lower():
        return True
    return bool(label) and label.lower() != address.lower() and needle in label.lower()


def safe_display_name(label: str, address: str, query: str) -> str:
    """The name to show: the user's label, unless that is (or contains) an
    email address, which gets the same treatment as the address itself."""
    if label.lower() == address.lower() or "@" in label:
        return visible_email(address, query)
    return label
