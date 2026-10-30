"""Why an import row failed, on its job: ``{code, item, status, reason, where}``.

``code`` is the row's error code (``http_403``, ``unsupported_type``, ...);
``item`` its feature index; for an HTTP answer ``status`` and its standard
``reason`` phrase; ``where`` the source's host and path - never its query
string or user info, which may carry a token. Only the first
:data:`ITEM_ERRORS_MAX` rows are kept: the card lists them and counts the rest
from ``failed_count``.
"""

from __future__ import annotations

import contextlib
import http
import re
import uuid
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select, update

from sm_images.core.constants import NO_SYNC
from sm_images.imports import jobs
from sm_images.models import ImportItem, ImportJob

__all__ = ["ITEM_ERRORS_MAX", "append", "entry", "record"]

ITEM_ERRORS_MAX = 20
WHERE_MAX = 200
_HTTP = re.compile(r"^http_(\d{3})$")


def _where(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    place = f"{parts.hostname or ''}{parts.path}"
    return place[:WHERE_MAX] or None


def entry(code: str, item: int, url: str | None, at: str) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "item": item}
    found = _HTTP.match(code)
    if found:
        status = int(found.group(1))
        out["status"] = status
        with contextlib.suppress(ValueError):
            out["reason"] = http.HTTPStatus(status).phrase
    where = _where(url)
    if where:
        out["where"] = where
    out["at"] = at
    return out


async def append(
    db: Any, tenant: str, job_id: uuid.UUID, failed: list[tuple[str, int, str | None]]
) -> None:
    """Add ``(code, feature index, url)`` rows to the job's errors in ``db``'s
    transaction (after the job's row was taken: ``jobs.bump`` or the chunk's
    checkpoint), as far as :data:`ITEM_ERRORS_MAX` allows."""
    if not failed:
        return
    errors = (
        await db.execute(select(ImportJob.errors).where(*jobs.where(tenant, job_id)))
    ).scalar_one_or_none() or []
    room = ITEM_ERRORS_MAX - sum(1 for e in errors if "item" in e)
    if room <= 0:
        return
    at = jobs.now().isoformat()
    new = [entry(code, index, url, at) for code, index, url in failed[:room]]
    await db.execute(
        update(ImportJob)
        .where(*jobs.where(tenant, job_id))
        .values(errors=[*errors, *new])
        .execution_options(**NO_SYNC)
    )


async def record(db: Any, tenant: str, job_id: uuid.UUID, item_id: int, code: str) -> None:
    """Add the failed row ``item_id`` (a download that failed) to its job's errors."""
    found = (
        await db.execute(
            select(ImportItem.feature_index, ImportItem.url).where(
                ImportItem.id == item_id, ImportItem.tenant_id == tenant
            )
        )
    ).first()
    if found is not None:
        await append(db, tenant, job_id, [(code, found.feature_index, found.url)])
