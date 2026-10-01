"""Relation DTOs — what a resolved reference and a referrer look like on the
wire (design doc §9, Phase 4).

Two questions, two shapes. *Forward*: "what does this relation point at?" is
:class:`ExpandedRef`, filled only under an explicit ``?expand=`` and only to
depth one. *Reverse*: "what points at this record?" is :class:`ReferrerRead`,
a single indexed query over ``records_index_ref`` that the delete dialog and
the editor's "Referenced by" panel both read.
"""

from __future__ import annotations

from sqlmodel import SQLModel

from sm_records.models import Record, RecordType

__all__ = ["ExpandedRef", "ReferrerRead", "ReferrersResponse", "expanded_ref", "referrer_read"]


class ExpandedRef(SQLModel):
    """One stored reference, resolved.

    Exactly one of the three states holds:

    - **resolved** — ``display_title`` is set, ``dangling`` and ``restricted``
      are both ``False``;
    - **dangling** — the target is trashed or purged (§9: a restorable delete
      must not break what references it), ``display_title`` is ``None``;
    - **restricted** — the target's type narrows ``allowed_roles`` to roles
      the caller lacks; ``display_title`` is ``None`` and nothing about the
      row leaks but the uuid the caller already holds in ``data``.

    ``type_key`` and ``uuid`` are always present: they are the stored value,
    echoed so a client can render a list without re-reading ``data``.
    """

    type_key: str
    uuid: str
    display_title: str | None
    slug: str | None = None
    status: str | None = None
    dangling: bool = False
    restricted: bool = False


class ReferrerRead(SQLModel):
    """A record that points at the one being read, and what deleting the
    target would do to it — the field's ``on_delete``, so the dialog can say
    "3 orders reference this and will block the delete" rather than "3"."""

    type_key: str
    type_label: str
    uuid: str
    display_title: str
    field_key: str
    field_label: str
    on_delete: str
    is_deleted: bool


class ReferrersResponse(SQLModel):
    items: list[ReferrerRead]
    """The referrers this caller may see, one page of them. A record pointing
    at the target from two relation fields is two entries — the panel names
    the field — and one referrer as far as :attr:`total` is concerned."""

    total: int
    """Every referring *record*, live and trashed, visible to this caller or
    not. It is the number a ``restrict`` refusal and the delete dialog speak,
    so it cannot shrink per caller."""

    hidden: int = 0
    """How many of :attr:`total` this caller may not view, because their type
    narrows ``allowed_roles`` past them (design §10).

    Stated rather than left to be inferred: the count was always derivable by
    subtraction, and a panel that showed four of seven with no explanation
    reads as a bug. *Which* records they are does not leak — ``items`` is
    paginated over the visible set alone, so paging cannot locate them."""


def expanded_ref(
    type_key: str,
    uuid: str,
    target: Record | None,
    *,
    restricted: bool = False,
) -> ExpandedRef:
    """Build one :class:`ExpandedRef`. ``target`` is ``None`` when the row is
    trashed or gone; ``restricted`` wins over a found row, so a caller who may
    not see the type learns nothing but the uuid they sent."""
    if restricted:
        return ExpandedRef(type_key=type_key, uuid=uuid, display_title=None, restricted=True)
    if target is None:
        return ExpandedRef(type_key=type_key, uuid=uuid, display_title=None, dangling=True)
    return ExpandedRef(
        type_key=type_key,
        uuid=uuid,
        display_title=target.display_title,
        slug=target.slug,
        status=target.status.value,
    )


def referrer_read(
    record: Record, rtype: RecordType, field_key: str, field_label: str, on_delete: str
) -> ReferrerRead:
    return ReferrerRead(
        type_key=rtype.key,
        type_label=rtype.label,
        uuid=record.uuid,
        display_title=record.display_title,
        field_key=field_key,
        field_label=field_label,
        on_delete=on_delete,
        is_deleted=record.is_deleted,
    )
