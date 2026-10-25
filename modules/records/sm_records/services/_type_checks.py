"""Checks a type create makes that need no database — split from
:mod:`sm_records.services.types` for the 300-line cap."""

from __future__ import annotations

from sm_records.collections import collections
from sm_records.services.errors import ValidationFailed

__all__ = ["check_collection"]


def check_collection(collection: str | None) -> None:
    """A type may only be created in a collection this process declares
    (Phase 5 §6.2).

    422 and not 409: the name is a value in the request body that does not
    name anything, which is what 422 is for, and the message lists what *is*
    declared because the answer is a property of the host's code rather than of
    anything the caller can create. ``None`` — the global tables — is always
    valid and is what a host that declares none can ever use.
    """
    if collection is None:
        return
    declared = collections()
    if collection not in declared:
        named = ", ".join(declared) or "none — this host declares no collections"
        raise ValidationFailed(
            f"collection {collection!r} is not declared by this host (declared: {named}); "
            "a collection's tables come from declare_collection() at import time",
            [{"field": "collection", "message": f"{collection!r} is not a declared collection"}],
        )
