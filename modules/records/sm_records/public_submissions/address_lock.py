"""One address's opt-out lock, tenant-wide (newsletter PR 7, Codex finding 1).

An import admits a confirmed row only if the address is unsubscribed on none of
the tenant's lists (D1), and an unsubscribe on list A must not land between
that read and the import's create on list B. Both therefore take this lock on
the address first: every unsubscribe (:func:`.opt_in.leave`) and the import's
batch (:func:`.campaign_import.lock_batch`), each before any type or row lock.

* Postgres: ``pg_advisory_xact_lock`` on :func:`address_key`, held to the end
  of the transaction; several addresses in ascending key order, so two batches
  sharing addresses never wait on each other in a cycle.
* SQLite: nothing. Its write lock is database-wide, and the import takes it
  (the type lock's ``UPDATE``) before it reads the opt-outs.

The key is a stable signed 64-bit value of the tenant and the address's
SHA-256: the same normalisation (:func:`.subscribe.normalise`) and digest as
newsletter's suppression hash, so either side can derive it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.public_submissions.subscribe import normalise

__all__ = ["address_key", "address_key_from_hash", "lock_addresses"]

_NAMESPACE = "sm_records.optout.v1"
_LOCK = text("SELECT pg_advisory_xact_lock(:k)")


def address_key_from_hash(tenant_id: str, digest: str) -> int:
    """The lock key of the address whose hex SHA-256 (of the normalised
    address) is ``digest``, in ``tenant_id``."""
    raw = hashlib.sha256(f"{_NAMESPACE}\0{tenant_id}\0{digest}".encode()).digest()
    return int.from_bytes(raw[:8], "big", signed=True)


def address_key(tenant_id: str, email: str) -> int:
    """The lock key of ``email`` (normalised) in ``tenant_id``."""
    digest = hashlib.sha256(normalise(email).encode()).hexdigest()
    return address_key_from_hash(tenant_id, digest)


async def lock_addresses(db: AsyncSession, tenant_id: str, emails: Iterable[str]) -> None:
    """Take every address's lock, ascending key order; a no-op on SQLite and
    for an empty address. Re-taking one this transaction holds never waits."""
    if db.get_bind().dialect.name == "sqlite":
        return
    keys = sorted({address_key(tenant_id, e) for e in emails if normalise(e)})
    for key in keys:
        await db.execute(_LOCK, {"k": key})
