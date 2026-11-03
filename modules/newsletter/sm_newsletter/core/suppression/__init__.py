"""Who the module must not mail, per tenant, keyed by a hash of the address.

**Hashing.** A row stores ``sha256(address.strip().lower())`` (records'
normalisation), never the address: :func:`email_hash`. Spelling variants of
one address are one key.

**Tenant-wide suppression.** :func:`suppressed` answers per tenant, whatever
the list: an address with *any* row in the tenant - any reason, any
``list_type_key`` - gets nothing from any of the tenant's lists.

**The list is provenance.** An ``unsubscribed`` row names the list the address
left (non-empty, at most ``MAX_TYPE_KEY_LEN``), one row per list; every other
reason is address-wide and carries ``""``. A disagreeing pair is a
``ValueError``. The list is in the unique key ``(tenant_id, email_hash,
reason, list_type_key)`` so that a confirmation on one list clears only that
list's opt-out and another list's, which records still holds and the
reconcile would re-add, stays.

**Refresh on repeat.** :func:`suppress` / :func:`suppress_many` insert, and by
default move an existing row's ``created_at`` up to ``now`` (and take the new
``source``): a repeated opt-out or bounce must be newer than an earlier
confirmation. They return what they *inserted*. ``refresh=False`` is a pure
insert-ignore, for the reconcile: idempotent counts, and it never makes a row
look newer than it is.

**Cutoff on clear.** :func:`clear_for_confirmation` - called only for a
double-opt-in confirmation (records' confirm link, see ``mirror``) - takes the
confirmation's (aware) time and deletes that list's ``unsubscribed`` row and
the ``hard_bounce`` / ``imported_cleaned`` rows only where ``created_at <=
confirmed_at``: a bounce recorded after the confirmation survives a delayed
confirm handler. A complaint is never cleared, nor another list's opt-out.

Every function validates and binds ``tenant_id`` and pins it in its SQL; none
commits.
"""

from __future__ import annotations

from sm_newsletter.core.suppression.hashing import email_hash, normalise_email
from sm_newsletter.core.suppression.store import (
    clear_for_confirmation,
    suppress,
    suppress_many,
    suppressed,
)

__all__ = [
    "clear_for_confirmation",
    "email_hash",
    "normalise_email",
    "suppress",
    "suppress_many",
    "suppressed",
]
