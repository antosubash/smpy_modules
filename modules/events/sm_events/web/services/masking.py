"""Masking of email addresses the share picker returns."""

from __future__ import annotations

import unicodedata

__all__ = ["mask_email", "matches_query", "safe_display_name", "visible_email"]

_MASK = "***"
# Every at-sign a label can spell an address with (commercial at, small and
# full-width variants). A label holding one carries an address.
AT_SIGNS = "@\ufe6b\uff20"


def _fold(text: str) -> str:
    """Canonically composed, then case-insensitive: ``e`` + combining acute and
    ``\u00e9`` are the same letter to the person typing."""
    return unicodedata.normalize("NFC", text).lower()


def label_carries_address(label: str, address: str = "") -> bool:
    """Whether the display label holds an at-sign (any variant) or is the
    address itself. A plain linear check: labels are never parsed."""
    folded = _fold(label)
    return any(a in folded for a in AT_SIGNS) or (bool(address) and folded == _fold(address))


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
    if _fold(query.strip()) == _fold(address):
        return address
    return mask_email(address)


def matches_query(label: str, address: str, query: str) -> bool:
    """Whether the share picker may offer a user for *query*.

    A user whose label carries an address is found only by their whole address.
    Any other user is found by a part of the label, or by the whole address. A
    partial address never matches: otherwise the picker would confirm an
    address piece by piece."""
    needle = _fold(query.strip())
    if not needle:
        return False
    if needle == _fold(address):
        return True
    if label_carries_address(label, address):
        return False
    return needle in _fold(label)


def safe_display_name(label: str, address: str, query: str) -> str:
    """The name to show: the user's label, unless it carries an address, which
    gets the same treatment as the address itself."""
    if label_carries_address(label, address):
        return visible_email(address, query)
    return label
