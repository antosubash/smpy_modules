"""Domain events other modules can subscribe to.

The framework's bus is :mod:`simple_module_core.events`: :class:`Event` is a
plain dataclass base, a module subscribes in ``register_event_handlers(bus,
app=...)``, and the bus itself lives at ``request.app.state.sm.event_bus``.
These are dataclasses and not SQLModel DTOs for that reason alone — the base
class is a dataclass, and the repo's SQLModel rule is about models and wire
DTOs, not about what the framework's own base dictates.

**They carry identifiers and the few fields a subscriber can act on without a
second query, and nothing else.** Not the payload: it is the largest thing a
record has, it is the thing most likely to be stale by the time an async
handler reads it, and a subscriber that needs it can read the record — except
after :class:`RecordPurged`, which is the one event whose subject is gone, and
which is therefore the one that has to be complete in itself.

**They are published after the commit, from the endpoint layer.** The service
layer never imports FastAPI (``docs/architecture.md`` rule 1) and the bus
arrives on ``app.state``, so the seam is the one ``menu.mark_dirty`` already
uses; and :mod:`sm_records.deferred` is what makes it *after the commit*, so
no subscriber ever sees an event for a write that rolled back. See
:mod:`sm_records.events`.

Field order is ``type_key`` first everywhere, because every subscriber that
filters filters on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from simple_module_core.events import Event

__all__ = [
    "RecordCreated",
    "RecordPurged",
    "RecordRestored",
    "RecordTrashed",
    "RecordTypeChanged",
    "RecordTypeDeleted",
    "RecordUpdated",
]


@dataclass
class RecordCreated(Event):
    """A record exists that did not before — from the API, a translation, or
    a row of an import (one event per row, not one per file).

    ``translation_group`` rather than "is a translation": a record alone in a
    group carries a group named after its own uuid (§4.3), so a subscriber
    that groups by it needs no special case for the first record of a set.
    """

    type_key: str
    uuid: str
    locale: str
    translation_group: str
    status: str


@dataclass
class RecordUpdated(Event):
    """A record was written — content, status, or both.

    **One event with the status pair, not a separate ``RecordPublished``.**
    Publishing is a status transition on an ordinary write, so a second event
    would either double-fire on a create-as-published or have to be suppressed
    there; ``status_before != status_after`` is the same information and is
    true exactly when it happened. A create is a :class:`RecordCreated` and
    never also this.

    ``version`` is the version this write produced, so a subscriber that reads
    the record back can tell whether it is looking at this write or a later
    one.
    """

    type_key: str
    uuid: str
    version: int
    status_before: str
    status_after: str


@dataclass
class RecordTrashed(Event):
    """A record was soft-deleted. Reversible — see :class:`RecordRestored`.

    ``cascaded_from`` is the uuid of the record whose delete this one followed
    from, and ``None`` when the caller asked for this record by name.
    ``services._lifecycle.soft_delete_record`` trashes records of types the URL
    never mentions (design §9's ``cascade``), and a search indexer or a cache
    purger has to be able to tell that apart from an explicit trash — not
    least because the cascaded record's own referrers were never shown to
    anybody.
    """

    type_key: str
    uuid: str
    cascaded_from: str | None = None


@dataclass
class RecordRestored(Event):
    """A trashed record came back, with its index rows rebuilt against the
    schema as it is now rather than as it was when it was trashed (§8.3)."""

    type_key: str
    uuid: str


@dataclass
class RecordPurged(Event):
    """A record was really deleted, with its revisions. Not reversible.

    The only event a subscriber cannot recover from by re-reading, so it is
    the only one that has to say everything: after it there is no row to ask.
    ``locale`` and ``translation_group`` are here for that reason and not on
    the other delete events.
    """

    type_key: str
    uuid: str
    locale: str
    translation_group: str


@dataclass
class RecordTypeChanged(Event):
    """A type's schema was written — ``PUT /types/{key}``, including a
    rollback, which is an apply of an earlier revision.

    This is the event that makes ``index.providers.register_reduce_provider``'s
    "run the CLI afterwards" caveat automatable: a host's own index or reduce
    provider projects from field values, and ``index_affecting_keys`` names the
    fields whose stored shape just moved, so a subscriber knows its projection
    is stale without diffing anything itself.

    ``schema_version`` is the version after the write. It does **not** move for
    a change that touched only pointers or labels, so a subscriber keying a
    cache on it sees no invalidation for a change that invalidates nothing.
    ``kind`` is the diff's own class — ``additive``, ``index_affecting``,
    ``restrictive`` or ``destructive``.
    """

    type_key: str
    schema_version: int
    kind: str
    index_affecting_keys: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class RecordTypeDeleted(Event):
    """A type and every record of it are gone.

    ``purged`` is how many records went with it, trash included — the number
    the operator confirmed (§8.9). The records also arrive as individual
    :class:`RecordPurged` events, and this is what tells a subscriber the
    *type* is gone, which no number of record events would.
    """

    type_key: str
    purged: int
