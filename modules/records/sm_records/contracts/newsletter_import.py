"""What newsletter's Mailchimp import needs from records (newsletter PR 7).

Beside :mod:`sm_records.contracts.newsletter` and ``newsletter_admin``, and on
the same tenant rule: the caller names the tenant, it is validated, bound with
``tenant_scope`` (another one while a tenant is bound raises
``TenantIsolationError``) and pinned in every query. Nothing here commits; the
caller finishes its transaction with ``simple_module_db.finalize_session``.

Part 1: :func:`create_list`, :func:`importable_fields`, :func:`add_tag_choices`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from sm_records.contracts._newsletter_args import _checked_tenant
from sm_records.contracts.newsletter_admin import FieldChoice, _field
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.public_submissions import campaign_lists, campaign_reads
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

__all__ = [
    "MAPPABLE_TYPES",
    "MAX_CHOICE_LEN",
    "MAX_NEW_CHOICES",
    "RECORDS_PACKAGE",
    "TAGS_FIELD",
    "FieldChoice",
    "ImportField",
    "ImportTargets",
    "InvalidListKey",
    "ListExists",
    "RecordsSettings",
    "SubscriberFilterError",
    "TagsFieldMissing",
    "add_tag_choices",
    "create_list",
    "importable_fields",
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
        return ImportTargets(fields=fields, tags=await campaign_lists.tags_state(session, rtype))


async def add_tag_choices(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    choices: Sequence[FieldChoice],
    settings: RecordsSettings,
    actor: str | None = None,
) -> list[str]:
    """Append the missing ``choices`` to the list's ``tags`` multiselect,
    creating the field on a list with no records; the values actually added,
    in the given order (existing values and their labels are kept).

    ``ValueError`` for more than ``MAX_NEW_CHOICES``, a value or label that is
    not 1-``MAX_CHOICE_LEN`` characters without control characters, or a
    duplicate value; ``TagsFieldMissing`` when ``tags`` is absent on a list
    with records, or is not a multiselect. ``None`` for no such list raises
    ``TagsFieldMissing`` too."""
    tenant = _checked_tenant(tenant_id)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            raise TagsFieldMissing(type_key)
        return await campaign_lists.add_choices(
            session, rtype, choices, settings=settings, actor=actor
        )
