"""The tags step (R8, D8): once per import, before its first batch, under the fence.

Staging previewed each label's value; here the final one is decided against the list's
*current* choices (``tag_values``), written into ``tags_found`` and the missing choices added
to the list, all in the caller's transaction, which commits only if the fenced job ``UPDATE``
matched (D3). A list that gained records since staging and has no ``tags`` field cannot take
new choices (``TagsFieldMissing``): tags are turned off for this import and one
``tags_unavailable`` error is recorded.
"""

from __future__ import annotations

from typing import Any

from sm_records.contracts.newsletter_admin import FieldChoice
from sm_records.contracts.newsletter_import import (
    TagsFieldMissing,
    add_tag_choices,
    importable_fields,
)
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.imports.constants import KEEP_ERRORS
from sm_newsletter.imports.fence import fenced
from sm_newsletter.imports.tags import tag_values
from sm_newsletter.models import ImportJob

__all__ = ["needs_tags", "tags_once"]

UNAVAILABLE = {"file": None, "line": None, "code": "tags_unavailable", "field": "tags"}


def needs_tags(job: ImportJob) -> bool:
    return bool((job.mapping or {}).get("tags") and job.tags_found and not job.tags_added)


async def tags_once(
    session: AsyncSession, *, tenant_id: str, job: ImportJob, owner: str, records_settings: Any
) -> None:
    """Decide the final values, add the new choices, mark the step done; fenced."""
    targets = await importable_fields(session, tenant_id=tenant_id, type_key=job.list_type_key)
    existing = targets.tag_choices if targets is not None else []  # indexed or not (T6b)
    values = tag_values([t["label"] for t in job.tags_found], existing)
    found = [{**t, "value": values[t["label"]]} for t in job.tags_found]
    known = {c.value for c in existing}
    new: list[FieldChoice] = []
    for item in found:
        if item["value"] not in known:
            known.add(item["value"])
            new.append(FieldChoice(value=item["value"], label=item["label"]))
    try:
        async with session.begin_nested():
            if new:
                await add_tag_choices(
                    session,
                    tenant_id=tenant_id,
                    type_key=job.list_type_key,
                    choices=new,
                    settings=records_settings,
                    actor=job.created_by,
                )
    except TagsFieldMissing:
        errors = list(job.errors or [])
        if len(errors) < KEEP_ERRORS:
            errors.append(dict(UNAVAILABLE))
        update = {
            "mapping": {**(job.mapping or {}), "tags": False},
            "errors": errors,
            "errors_total": ImportJob.errors_total + 1,
        }
    else:
        update = {"tags_found": found, "tags_added": True}
    await fenced(session, tenant_id=tenant_id, import_id=job.id, owner=owner, values=update)  # ty: ignore[invalid-argument-type]
