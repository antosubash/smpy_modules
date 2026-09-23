"""The stored ``invalid_since`` mark: who writes it, who clears it, who counts.

Design §8.3 says a record a restrictive change leaves behind is **marked, not
hidden** — still returned, still editable, still saying which fields are
wrong. That marking has always been *derived*:
:func:`sm_records.services._payload.read_view` runs the compiled validator on
read and returns the errors as ``invalid``. It stays the authority for the
record being edited, and it is the wrong shape for every other question a
person asks about it — "which records", "how many", "show me only those" —
because answering those from a validator means one pass per row, which is why
a list passes ``with_invalid=False`` in the first place.

``Record.invalid_since`` is the same fact as a column. Three rules:

* **It is written only by a scan of the schema records are actually stored
  against** — the inline pass of a forced :func:`schema_change.apply`, and the
  ``rescan`` behind "Check records". A draft preview scans a *proposed* field
  list that may never be saved, and marking from it would flag records against
  a schema nobody applied.
* **It is cleared by the record's next successful write** — create, update,
  import — because that write validated against the current schema and is
  precisely the fix §8.3 promises. A scan that finds a record clean clears it
  too, which is how a record fixed outside the module (a payload edited in
  ``psql``, a field's constraint relaxed) stops being marked. A **restore** is
  not one of them: it writes the row without looking at the payload, so it
  fixes nothing and leaves the mark where it was.
* **The timestamp is not moved by a later scan.** A record that was already
  marked and still fails keeps the instant it first did, which is the only
  thing "since" can honestly mean.

**Duplicates are out of scope for the column, deliberately.** A record sharing
a value with another after a field was forced ``unique`` fails no per-record
rule — its payload validates perfectly — and the pair is found by
:mod:`sm_records.services._duplicates`' ``GROUP BY``, which yields counts and a
sample rather than the full set of ids. It is surfaced the way it always was,
by ``_duplicates.conflicts_for`` topping up ``invalid`` on the single-record
read, and the refusal text still says that class cannot be fixed by editing
the record.

**The writes are core ``UPDATE``s, not ORM assignments.** The framework's
audit listener stamps ``updated_at``/``updated_by`` on any row the session
considers modified, and a mark is not an edit of the record: restamping it
would reorder the default ``-updated_at`` listing and claim an author for a
change no person made. Core DML also costs one statement per batch instead of
one per record — and because it never fires ``after_flush``,
:func:`~sm_records.services._common.mark_written` is what tells the framework
the request wrote something. ``set_committed_value`` then puts the new value
on the instances the scan is holding, so the identity map agrees with the
database without any of them becoming dirty.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from sm_records.models import Record, RecordType, tables_for
from sm_records.services._common import mark_written, utcnow
from sm_records.tenancy import bound_tenant

__all__ = ["Marker", "clear_on_write", "count_for_type", "write_marks"]

_COLUMN = "invalid_since"


def clear_on_write(record: Record) -> None:
    """A record that was just written validly is not invalid any more.

    Called from the ORM write path that validated (``records.update_record``),
    where the row is being updated anyway — so this is a column in an
    ``UPDATE`` that was already happening rather than a statement of its own.
    Unconditional: assigning ``None`` to an attribute that already holds it is
    not a change SQLAlchemy emits.

    A create needs nothing — a new row's column defaults to ``NULL``. A trash
    does not clear, because a trashed record still holds the payload the
    schema refuses; and neither does a **restore**, because bringing that same
    payload back is not a check of it (``_lifecycle.restore_record``).
    """
    record.invalid_since = None


async def write_marks(
    db: AsyncSession,
    rtype: RecordType,
    *,
    mark: Sequence[Record] = (),
    clear: Sequence[Record] = (),
    now: datetime | None = None,
) -> int:
    """Set the mark on ``mark`` and remove it from ``clear``. Rows touched.

    Two statements at most, whatever the batch size, against whichever table
    set the type lives in (Phase 5 §6.3). See the module docstring for why
    they are core statements and what ``set_committed_value`` is doing here.
    """
    cls = tables_for(rtype).record
    at = now or utcnow()
    touched = 0
    for records, value in ((mark, at), (clear, None)):
        ids = [record.id for record in records if record.id is not None]
        if not ids:
            continue
        # The tenant explicitly: an ``UPDATE`` gets no tenant filter (tenancy §E).
        owned = cls.id.in_(ids), cls.tenant_id == bound_tenant()
        await db.execute(sa_update(cls).where(*owned).values(invalid_since=value))
        for record in records:
            attributes.set_committed_value(record, _COLUMN, value)
        touched += len(ids)
    if touched:
        mark_written(db)
    return touched


class Marker:
    """The mark-writing half of a dry run, so the scan itself stays a scan.

    :func:`sm_records.services._dry_run.dry_run` walks every record of a type
    in batches and already knows, per record, whether it satisfies the model
    being checked. This rides along on that answer: three lines in the scan,
    the judging and the batched writes here.

    ``enabled`` is ``False`` for a draft preview — the common case — and then
    every method is a no-op that touches nothing, which is what keeps "preview
    writes nothing" true for the button that says so.
    """

    def __init__(self, db: AsyncSession, rtype: RecordType, *, enabled: bool) -> None:
        self._db = db
        self._rtype = rtype
        self.enabled = enabled
        self._now = utcnow()
        self._mark: list[Record] = []
        self._clear: list[Record] = []
        self.marked = 0
        self.cleared = 0

    def judge(self, record: Record, *, failed: bool) -> None:
        """Queue this record's mark, if the scan changes what it holds.

        A record that already carries a mark and still fails is left alone —
        the instant it first failed is the one worth keeping — and a record
        that passes and carries none costs nothing.
        """
        if not self.enabled:
            return
        if failed and record.invalid_since is None:
            self._mark.append(record)
        elif not failed and record.invalid_since is not None:
            self._clear.append(record)

    async def flush(self) -> None:
        """Write this batch's marks. Called once per batch by the scan."""
        if not self.enabled or not (self._mark or self._clear):
            return
        self.marked += len(self._mark)
        self.cleared += len(self._clear)
        await write_marks(self._db, self._rtype, mark=self._mark, clear=self._clear, now=self._now)
        self._mark, self._clear = [], []


async def count_for_type(db: AsyncSession, rtype: RecordType) -> int:
    """How many **live** records of one type are marked.

    Live only, and that is the point: the number is what the hub row shows and
    what the ``filter=invalid:eq:true`` link behind it lists, and a listing
    does not show the trash. ``func.count(record.id)`` rather than a bare
    ``count()`` for the reason :func:`~sm_records.services._common.record_count`
    gives — naming the mapper is what the framework's soft-delete filter
    attaches to, and without it this would count trashed rows too.
    """
    record = tables_for(rtype).record
    stmt = select(func.count(record.id)).where(
        record.type_id == rtype.id, record.invalid_since.isnot(None)
    )
    return int((await db.execute(stmt)).scalar_one())
