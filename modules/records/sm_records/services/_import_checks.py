"""Whether a row may become — or rewrite — a record at all.

Split from :mod:`sm_records.services._import_plan` for the 300-line cap, along
a seam that names itself: that module decides *what would happen* to each row
(create, update, skip) and this one answers the prior question — is this row
admissible. Three rules, none of them about the payload
(``_payload.validate`` owns that) and all of them about the row's relationship
to what already exists: two rows claiming one identity, a row moving a record
between languages or groups, and a row naming a translation group it has no
business joining. Its two siblings are
:func:`sm_records.services._uuids.uuids_claimed_elsewhere` (a uuid another
table set holds) and
:func:`sm_records.services._import_rows.version_required`, which sit where
they do because other callers need them.

They are asked from the planning pass rather than from the writer because a
**dry run has to predict them**. The module's bargain is that a dry run is the
real run with the writing switched off (:mod:`sm_records.services.import_`),
which a check reachable only from ``write_row`` quietly breaks.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType, tables_for
from sm_records.services._import_parse import ImportRow
from sm_records.services._import_rows import Envelope

__all__ = [
    "duplicates",
    "forged_group",
    "group_claims",
    "groups_in_type",
    "immutable",
]


def duplicates(pairs: Sequence[tuple[ImportRow, Envelope]]) -> dict[int, str]:
    """Rows whose identity another row in the same file already claimed.
    Caught here rather than at the unique index, where the second write is a
    raw ``IntegrityError`` — a 500 about a constraint, on a file whose real
    problem is that two exports were concatenated."""
    seen: dict[str, int] = {}
    out: dict[int, str] = {}
    for row, _ in pairs:
        if not row.uuid:
            continue
        first = seen.setdefault(row.uuid, row.number)
        if first != row.number:
            out[row.number] = f"uuid {row.uuid} appears twice in this file (first at row {first})"
    return out


def group_claims(pairs: Sequence[tuple[ImportRow, Envelope]]) -> dict[str, int]:
    """How many rows of this file carry each ``translation_group`` value."""
    counts: dict[str, int] = {}
    for _, envelope in pairs:
        group = envelope.translation_group
        if group:
            counts[group] = counts.get(group, 0) + 1
    return counts


async def groups_in_type(db: AsyncSession, rtype: RecordType, groups: set[str]) -> set[str]:
    """Which of ``groups`` already exist among this type's records, trash
    included — a trashed sibling is still a sibling and still exempt.

    One statement for the whole file, and none at all unless some row carries a
    group that :func:`forged_group` has not already excused.
    """
    if not groups:
        return set()
    cls = tables_for(rtype).record
    stmt = (
        select(cls.translation_group)
        .where(cls.type_id == rtype.id, cls.translation_group.in_(groups))
        .execution_options(include_deleted=True)
    )
    return {str(found) for found in (await db.execute(stmt)).scalars().all()}


def forged_group(
    rtype: RecordType, row: ImportRow, envelope: Envelope, claims: dict[str, int], taken: set[str]
) -> str | None:
    """Whether this *new* record may join the group its row names (§4.3).

    A ``translation_group`` is not data, it is a **capability**: records
    sharing one are siblings, and siblings are exempt from each other's
    ``unique`` claims (``_claims.ensure_unique``'s ``exclude_group``). §2 has
    the importer carry the value verbatim, so a hand-written file naming the
    group of a record it has nothing to do with used to buy that exemption —
    two records holding one ``unique`` value, for the price of ``records.edit``
    and a second content locale. ``RecordCreate`` has no ``translation_group``
    for exactly this reason; the importer was the same hole one door along.

    Two values are legitimate, and they are the two an *export* produces:

    * the row's **own uuid** — a record alone in a group named after itself,
      which is what ``create_record`` writes; and
    * a group **another row of this file also carries** — a translated pair
      travelling together, because an export of a group contains the whole
      group (a record's siblings are records of the same type, and the export
      streams the type).

    A group that exists nowhere in **this type** is allowed too: an exemption
    from nobody is not an exemption, and a file inventing its own group keys is
    what a migration between installs looks like. The rule bites exactly where
    the capability is — a group this type already holds — and ``taken`` is that
    set (:func:`groups_in_type`). Joining one is
    ``POST /api/records/types/{key}/records/{uuid}/translations``, which checks
    the language is free and copies the source's payload; the message says so,
    because the answer is never "edit the file".

    Note what this does **not** refuse: another *type*'s group. Groups are
    scoped by type everywhere that reads one, and since migration
    ``fe3ea2dfe0fb`` the unique index agrees, so a ``memo`` row carrying an
    ``art`` group is simply a group ``memo`` does not have.
    """
    group = envelope.translation_group
    if not group or group == row.uuid or claims.get(group, 0) > 1 or group not in taken:
        return None
    return (
        f"translation_group {group} names a group not in this file; create translations "
        f"through POST /api/records/types/{rtype.key}/records/{{uuid}}/translations"
    )


def immutable(record: Record, row: ImportRow, envelope: Envelope) -> str | None:
    """What this row asks to change about an existing record that cannot change.

    A record's language is fixed for its lifetime and its translation group is
    the relationship it is *in*, so a file asking to move either is refused
    rather than silently ignored — the same answer ``PUT /records/{uuid}``
    gives a body carrying a ``locale`` (§4.3). Ignoring it would make an import
    the one write path where a language change appears to succeed.

    A round trip never trips this: the export writes each record's own values
    back, so the comparison is between a value and itself.
    """
    if row.locale is not None and row.locale != record.locale:
        return (
            f"record {record.uuid} is in {record.locale!r} and a record's locale is fixed "
            f"for its lifetime; create a translation instead of importing it as "
            f"{row.locale!r}"
        )
    if (
        envelope.translation_group is not None
        and envelope.translation_group != record.translation_group
    ):
        return (
            f"record {record.uuid} is already in translation group "
            f"{record.translation_group}; an import cannot move a record between groups"
        )
    return None
