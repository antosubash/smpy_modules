"""What newsletter's Mailchimp import needs from records (newsletter PR 7).

Beside :mod:`sm_records.contracts.newsletter` and ``newsletter_admin``, and on
the same tenant rule: the caller names the tenant, it is validated, bound with
``tenant_scope`` (another one while a tenant is bound raises
``TenantIsolationError``) and pinned in every query. Nothing here commits; the
caller finishes its transaction with ``simple_module_db.finalize_session``.

Part 1: :func:`create_list`, :func:`importable_fields`, :func:`add_tag_choices`
(and its pure value rule, :func:`tag_choice_values`).
Part 2: :func:`import_subscribers` (R3-R5, D5) and :func:`opted_out_anywhere` (D1),
both after :func:`lock_import_batch` (Codex finding 1).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from sm_records.contracts._newsletter_args import _checked_tenant
from sm_records.contracts.newsletter_admin import FieldChoice, _field
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.public_submissions import campaign_import, campaign_lists, campaign_reads
from sm_records.public_submissions.address_lock import address_key as address_lock_key
from sm_records.public_submissions.address_lock import (
    address_key_from_hash as address_lock_key_from_hash,
)
from sm_records.public_submissions.campaign_import import (
    CONSENT_TEMPLATE,
    MAX_IMPORT_BATCH,
    ImportOutcome,
    ImportResult,
    ImportRow,
    ImportStatus,
)
from sm_records.public_submissions.campaign_lists import (
    MAPPABLE_TYPES,
    MAX_CHOICE_LEN,
    MAX_NEW_CHOICES,
    TAGS_FIELD,
    InvalidListKey,
    ListExists,
    TagsFieldMissing,
)
from sm_records.public_submissions.campaign_reads import SubscriberFilterError
from sm_records.public_submissions.tag_values import tag_values

__all__ = [
    "CONSENT_TEMPLATE",
    "MAPPABLE_TYPES",
    "MAX_CHOICE_LEN",
    "MAX_IMPORT_BATCH",
    "MAX_NEW_CHOICES",
    "RECORDS_PACKAGE",
    "TAGS_FIELD",
    "FieldChoice",
    "ImportField",
    "ImportOutcome",
    "ImportResult",
    "ImportRow",
    "ImportStatus",
    "ImportTargets",
    "InvalidListKey",
    "ListExists",
    "RecordsSettings",
    "SubscriberFilterError",
    "TagsFieldMissing",
    "add_tag_choices",
    "address_lock_key",
    "address_lock_key_from_hash",
    "create_list",
    "import_subscribers",
    "importable_fields",
    "lock_import_batch",
    "opted_out_anywhere",
    "tag_choice_values",
]

RECORDS_PACKAGE = "sm_records"  # the `settings_for` key (R13)


class ImportField(SQLModel):
    key: str
    label: str
    type: str
    choices: list[FieldChoice] = []


class ImportTargets(SQLModel):
    fields: list[ImportField]
    tags: Literal["present", "creatable", "missing"]
    tag_choices: list[FieldChoice] = []
    """The ``tags`` multiselect's current choices, whether or not the field is
    indexed (``list_fields`` shows indexed fields only); ``[]`` without one."""


async def create_list(
    session: AsyncSession,
    *,
    tenant_id: str,
    key: str,
    label: str,
    settings: RecordsSettings,
    actor: str | None = None,
) -> str:
    """A new subscription list (``first_name``, ``last_name``; double opt-in,
    not yet enabled for public signup) in the tenant; its key.

    ``ListExists`` when the key is taken, ``InvalidListKey`` when records
    refuses the key or label."""
    tenant = _checked_tenant(tenant_id)
    with tenant_scope(tenant):
        return await campaign_lists.create(
            session, key=key, label=label, settings=settings, actor=actor
        )


async def importable_fields(
    session: AsyncSession, *, tenant_id: str, type_key: str
) -> ImportTargets | None:
    """The fields an import can fill and the state of ``tags``; ``None`` for no
    such list in the tenant, ``SubscriberFilterError("not_a_list")`` for a
    type that is not one."""
    tenant = _checked_tenant(tenant_id)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return None
        fields = []
        for raw in campaign_lists.mappable_fields(rtype):
            shaped = _field(raw)
            fields.append(
                ImportField(
                    key=shaped.key, label=shaped.label, type=shaped.type, choices=shaped.choices
                )
            )
        raw_tags = campaign_lists.tags_field(rtype)
        tag_choices = (
            _field(raw_tags).choices
            if raw_tags is not None and raw_tags.get("type") == "multiselect"
            else []
        )
        return ImportTargets(
            fields=fields,
            tags=await campaign_lists.tags_state(session, rtype),
            tag_choices=tag_choices,
        )


async def add_tag_choices(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    labels: Sequence[str],
    settings: RecordsSettings,
    actor: str | None = None,
) -> dict[str, str]:
    """Each label's ``tags`` choice value (:func:`tag_choice_values`), decided
    under the list's type lock against its choices as they are then, the
    missing ones appended (creating the multiselect on a list with no
    records): the authoritative label -> value mapping. Existing values and
    their labels are kept; a label a choice already carries reuses its value.

    ``ValueError`` for more than ``MAX_NEW_CHOICES`` labels, a label that is
    not 1-``MAX_CHOICE_LEN`` characters without control characters, or a
    duplicate label; ``TagsFieldMissing`` when ``tags`` is absent on a list
    with records, or is not a multiselect. No such list raises
    ``TagsFieldMissing`` too."""
    tenant = _checked_tenant(tenant_id)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            raise TagsFieldMissing(type_key)
        return await campaign_lists.add_choices(
            session, rtype, labels, settings=settings, actor=actor
        )


def tag_choice_values(labels: Sequence[str], existing: Sequence[FieldChoice]) -> dict[str, str]:
    """The value rule :func:`add_tag_choices` applies (D8), for a preview: a
    label a choice carries reuses its value, else the label itself (no comma,
    not taken), else its slug plus a hash, ``-2``, ``-3``… while taken. Pure."""
    return tag_values(labels, [(c.value, c.label) for c in existing])


async def import_subscribers(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    rows: Sequence[ImportRow],
    settings: RecordsSettings,
    now: datetime,
    source: str = "Mailchimp",
) -> list[ImportResult]:
    """Apply one batch of imported subscribers to the list; one result per
    row, in input order (R3's records column, R4's system values).

    Never confirms a ``pending`` signup, never resubscribes an ``unsubscribed``
    or trashed record, and writes into a confirmed one only through a
    validating ``update_record`` under the row lock (D5). Publishes nothing:
    the batch runs inside ``events.muted`` (R5). Writes no suppression: that is
    the caller's.

    **The caller must skip every confirmed row whose address
    :func:`opted_out_anywhere` reports** (D1): this call decides only from the
    record on *this* list, so someone unsubscribed on another list of the
    tenant would otherwise be created confirmed here.

    ``ValueError`` before any query for more than ``MAX_IMPORT_BATCH`` rows, an
    address twice (after normalising), a naive datetime or an unknown status;
    ``SubscriberFilterError("not_a_list")`` for a type that is not a list,
    ``LookupError`` for no such list in the tenant."""
    tenant = _checked_tenant(tenant_id)
    checked = campaign_import.checked_rows(rows, now, source)
    with tenant_scope(tenant):
        return await campaign_import.run(
            session, tenant, type_key, checked, settings=settings, now=now, source=source
        )


async def opted_out_anywhere(
    session: AsyncSession, *, tenant_id: str, emails: Sequence[str]
) -> set[str]:
    """The normalised addresses among ``emails`` that are ``unsubscribed`` on
    any of the tenant's lists, trash included (D1). At most
    ``MAX_IMPORT_BATCH`` addresses (``ValueError``)."""
    tenant = _checked_tenant(tenant_id)
    wanted = campaign_import.checked_emails(emails)
    with tenant_scope(tenant):
        return await campaign_import.opted_out(session, tenant, wanted)


async def lock_import_batch(
    session: AsyncSession, *, tenant_id: str, type_key: str, emails: Sequence[str]
) -> None:
    """Hold, to the end of the caller's transaction, the opt-out lock of every
    address in ``emails`` (``pg_advisory_xact_lock`` on
    :func:`address_lock_key`, ascending; nothing on SQLite), then the list's
    type lock. Every unsubscribe takes the address lock first too, so the
    caller's :func:`opted_out_anywhere` and suppression reads made after this
    stay true until it commits.

    Call it first in the batch's transaction, before any read the admission
    decides from, and before newsletter's own row locks. ``ValueError`` for
    ``emails`` not a sequence of ``str``; ``LookupError`` for no such list."""
    tenant = _checked_tenant(tenant_id)
    wanted = campaign_import.checked_emails(emails, cap=None)
    with tenant_scope(tenant):
        await campaign_import.lock_batch(session, tenant, type_key, wanted)
