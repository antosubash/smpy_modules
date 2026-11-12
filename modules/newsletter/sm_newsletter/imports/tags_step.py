"""The tags step (R8, D8): once per import, before its first batch, under the fence.

Staging previewed each label's value; here records decides the final ones, reading the
list's choices, resolving each label (the same rule) and appending the missing ones under
one type lock (``add_tag_choices``, Codex finding 4), and its mapping is written into
``tags_found``, all in the caller's transaction, which commits only if the fenced job
``UPDATE`` matched (D3). A list that gained records since staging and has no ``tags``
field cannot take new choices (``TagsFieldMissing``): tags are turned off for this import
and one ``tags_unavailable`` error is recorded.
"""

from __future__ import annotations

from typing import Any, cast

from sm_records.contracts.newsletter_import import TagsFieldMissing, add_tag_choices
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.imports.constants import KEEP_ERRORS
from sm_newsletter.imports.fence import fenced
from sm_newsletter.models import ImportJob

__all__ = ["needs_tags", "tags_once"]

UNAVAILABLE = {"file": None, "line": None, "code": "tags_unavailable", "field": "tags"}


def needs_tags(job: ImportJob) -> bool:
    return bool((job.mapping or {}).get("tags") and job.tags_found and not job.tags_added)


async def tags_once(
    session: AsyncSession, *, tenant_id: str, job: ImportJob, owner: str, app: Any | None
) -> None:
    """Decide the final values, add the new choices, mark the step done; fenced."""
    try:
        async with session.begin_nested():
            values = await add_tag_choices(
                session,
                tenant_id=tenant_id,
                type_key=job.list_type_key,
                labels=[t["label"] for t in job.tags_found],
                app=app,
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
        found = [{**t, "value": values[t["label"]]} for t in job.tags_found]
        update = {"tags_found": found, "tags_added": True}
    job_id = cast(int, job.id)  # a stored job always has its id
    await fenced(session, tenant_id=tenant_id, import_id=job_id, owner=owner, values=update)
