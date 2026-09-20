"""Matching an incoming row to a record, and writing it.

Split from :mod:`sm_records.services.import_` for the file cap, along the seam
that was already there: that module owns the *run* (parse, validate
everything, then write in one transaction and report), and this one owns what
happens to **one** row.

Two rules are enforced here rather than there, because both are about a single
row and its counterpart in the database:

* **A row that says nothing new writes nothing.** Re-importing a file you
  exported must converge, not bump ``version`` on every record in the type —
  and "converge" cannot mean "write the same bytes again", because a write
  appends a revision, rewrites six index tables and invalidates every
  optimistic-concurrency token a client is holding. :func:`unchanged` is what
  makes the second run a no-op, and it is also where ``skipped`` in the report
  comes from. It compares two normalised payloads directly rather than
  rendering the stored one through the schema, which is S4 and most of what a
  no-op import used to cost.
* **An update never last-write-wins.** :func:`version_required` is the rule;
  it lives here with the write it guards, and the **planning pass** asks it so
  a dry run predicts the same refusal (``_import_plan.plan_rows``).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import ORPHANED_KEY
from sm_records.contracts.io import ImportMode
from sm_records.models import Record, RecordStatus, RecordType
from sm_records.services._import_parse import ImportRow
from sm_records.services._payload import slug_for
from sm_records.services.errors import ValidationFailed
from sm_records.services.records import create_record, update_record
from sm_records.settings import RecordsSettings

__all__ = ["Envelope", "envelope_for", "unchanged", "version_required", "write_row"]


class Envelope:
    """The non-payload half of a row, coerced once. A named object rather
    than a tuple because most of its members are optional in different ways,
    and a positional unpack is how ``position`` lands in ``status``.

    ``locale`` arrives raw and is replaced by the *resolved* content locale in
    ``import_._validate`` — where the settings are in reach and where a bad one
    becomes this row's error rather than the whole file's. ``translation_group``
    is carried verbatim: the importer never rewrites it, because that would
    rewrite the relationships the file is describing. It does **check** it —
    a group is a uniqueness exemption, not data (``_import_plan._forged_group``)
    — and a row naming a group this file does not describe is refused.
    """

    __slots__ = ("has_slug", "locale", "position", "slug", "status", "translation_group")

    def __init__(
        self,
        status: RecordStatus | None,
        slug: str | None,
        has_slug: bool,
        position: int | None,
        locale: str | None = None,
        translation_group: str | None = None,
    ) -> None:
        self.status = status
        self.slug = slug
        self.has_slug = has_slug
        self.position = position
        self.locale = locale
        self.translation_group = translation_group


def envelope_for(row: ImportRow) -> Envelope:
    """Coerce ``status``/``slug``/``position``, or raise the row's error.

    CSV hands every cell over as a string (``position`` arrives as ``"3"``),
    JSON hands it over typed. One coercion for both is the only reason having
    two formats is not two features that drift.
    """
    raw_status = row.envelope.get("status")
    status: RecordStatus | None = None
    if raw_status not in (None, ""):
        try:
            status = RecordStatus(str(raw_status))
        except ValueError as exc:
            raise ValidationFailed(
                f"unknown status {raw_status!r}",
                [{"field": "status", "message": "status must be 'draft' or 'published'"}],
            ) from exc
    raw_position = row.envelope.get("position")
    position: int | None = None
    if raw_position not in (None, ""):
        try:
            position = int(raw_position)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(
                f"position {raw_position!r} is not a whole number",
                [{"field": "position", "message": "position must be a whole number"}],
            ) from exc
    slug = row.envelope.get("slug")
    locale = row.envelope.get("locale")
    group = row.envelope.get("translation_group")
    return Envelope(
        status,
        None if slug is None else str(slug),
        "slug" in row.envelope,
        position,
        None if locale in (None, "") else str(locale),
        None if group in (None, "") else str(group),
    )


def unchanged(
    rtype: RecordType,
    record: Record,
    row: ImportRow,
    envelope: Envelope,
) -> bool:
    """Would writing this row change anything at all?

    **The envelope first, then one stored payload against the other.** The
    stored payload and the incoming one are both in *stored* form —
    ``record.data`` is what ``_payload.validate`` produced the last time this
    row was written, and ``row.stored`` is what it produced for this file's row
    a moment ago — so the comparison is between two normalised dictionaries
    (``to_jsonable`` has already turned every ``Decimal`` into a string and
    every date into an ISO string) and needs no schema pass at all. A plain
    ``==`` is that comparison: dict equality is key-order-blind, walks the
    payload once and allocates nothing, where serialising and hashing both
    sides would cost two ``json.dumps`` per row to learn the same answer.

    This used to render the record through ``read_view`` on every row and
    compare the result field by field, which is a lenient coercion of the whole
    payload to the current schema plus a ``to_jsonable`` walk back: the bulk of
    the 11 seconds a 9,000-row no-op import cost (S4), paid to learn that
    nothing had changed.

    Dropping it is sound *because of the first line*. ``schema_version``
    counting as a difference is not an optimisation, it is the rule — a write
    restamps the row at the type's current version (§8.3), and that restamp is
    the lazy migration. So by the time the payloads are compared the record has
    already been written under this exact schema, and the two questions
    ``read_view`` answered for a stale row — a key the payload predates, a
    deleted field's value still sitting at the top level — cannot arise. A
    record behind the schema returns ``False`` above and is rewritten, which is
    what it was always going to do.

    ``_orphaned`` is dropped from the stored side and never present on the
    incoming one (``_payload.validate`` refuses a payload carrying it), so an
    undo buffer for a field deleted three schema versions ago does not make
    every later import rewrite the type.
    """
    if record.schema_version != rtype.schema_version:
        return False
    if envelope.status is not None and envelope.status is not record.status:
        return False
    if envelope.position is not None and envelope.position != record.position:
        return False
    # ``locale`` and ``translation_group`` are not compared: neither can be
    # written by an update (a record's language is fixed for its lifetime), and
    # ``import_._plan`` refuses a row that asks to change one rather than
    # letting it read as "changed" and rewrite the record every import.
    if slug_for(rtype, row.values or {}, envelope.slug) != record.slug:
        return False
    stored = dict(record.data or {})
    stored.pop(ORPHANED_KEY, None)
    return stored == (row.stored or {})


def version_required(record: Record, row: ImportRow) -> str | None:
    """Why this row may not update ``record``, if the file left the version out.

    The export carries no ``version`` (design §5 says what travels: ``uuid``
    and content), so a file that wants to *change* a record has to say which
    version it is changing — or say ``force`` and mean it. Silently overwriting
    whatever is there is what §5.1 added the column to prevent, and a bulk path
    is the worst place to make an exception for it.

    A function rather than a branch inside :func:`write_row` because the
    **planning pass** has to be able to ask it: a dry run skips the write, so a
    refusal that only existed there made the preview promise an update the
    apply then failed (``_import_plan.plan_rows``). ``write_row`` keeps the
    same call as a guard for anything that reaches it without planning.
    """
    if row.version is not None:
        return None
    return (
        f"record {record.uuid} already exists and the file carries no 'version'; "
        "re-export it, add a version column, or import with force=true"
    )


async def write_row(
    db: AsyncSession,
    rtype: RecordType,
    row: ImportRow,
    record: Record | None,
    *,
    mode: ImportMode,
    envelope: Envelope,
    settings: RecordsSettings,
    actor: str | None,
    force: bool,
) -> str:
    """Write one row and say what it did: ``"created"`` or ``"updated"``.

    Through ``create_record``/``update_record`` and never a bulk insert.
    Everything those do is load-bearing for a *file* too, and more so: the
    revision that makes a bad import undoable, the index tables without which
    the imported rows match no filter, the ``unique`` and slug claims a file
    is likelier to violate than a human typing one form, and ``lock_type``.
    """
    if record is None:
        created = await create_record(
            db,
            rtype,
            data=row.data,
            settings=settings,
            status=envelope.status or RecordStatus.DRAFT,
            slug=envelope.slug,
            position=envelope.position or 0,
            actor=actor,
            locale=envelope.locale,
            translation_group=envelope.translation_group,
        )
        if row.uuid:
            # The file's own identity, kept: a round trip that renumbered
            # every record would break every relation pointing into it (§9)
            # and make a second import create duplicates instead of matching.
            created.uuid = row.uuid
            if envelope.translation_group is None:
                # A file with no ``translation_group`` column describes records
                # that are each alone in a group named after their own uuid —
                # the rule ``create_record`` applies, restated here because the
                # uuid it generated has just been replaced by the file's.
                created.translation_group = row.uuid
            db.add(created)
            await db.flush()
        return "created"

    expected = row.version
    if expected is None:
        missing = None if force else version_required(record, row)
        if missing is not None:
            raise ValidationFailed(
                missing,
                [{"field": "version", "message": "a version is required to update a record"}],
            )
        expected = record.version
    await update_record(
        db,
        rtype,
        record,
        expected_version=expected,
        data=row.data,
        settings=settings,
        status=envelope.status,
        slug=envelope.slug if envelope.has_slug else None,
        position=envelope.position,
        actor=actor,
    )
    return "updated"


def mode_error(mode: ImportMode, record: Record | None) -> str | None:
    """What ``mode`` forbids about this row, if anything."""
    if mode is ImportMode.CREATE and record is not None:
        return "a record already matches this row, and mode=create never updates"
    if mode is ImportMode.UPDATE and record is None:
        return "no record matches this row, and mode=update never creates"
    return None
