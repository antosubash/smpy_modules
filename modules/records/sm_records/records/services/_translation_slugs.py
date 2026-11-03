"""records services _translation_slugs helpers."""

from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sm_records.core.constants import MAX_SLUG_LEN
from sm_records.models import RecordType, tables_for
from sm_records.records.services.errors import Conflict


_MAX_SLUG_ATTEMPTS = 20


async def _free_slug(db: AsyncSession, rtype: RecordType, base: str, locale: str) -> str:
    """``base`` if it is free in ``locale``, else ``base-2``, ``base-3``…

    Usually the first: slugs are unique per language (§4.1), so the source's
    own slug is available in the new one unless an unrelated record already
    took it there. One query for the whole candidate set rather than a
    create-and-catch loop, which would roll back anything the caller had
    already written in the same transaction.

    ``include_deleted``, because the trash keeps its claim per locale.
    """
    cls = tables_for(rtype).record
    stmt = (
        select(cls.slug)
        .where(
            cls.type_id == rtype.id,
            cls.locale == locale,
            cls.slug.startswith(base[: _stem(base)]),
        )
        .execution_options(include_deleted=True)
    )
    taken = {slug for slug in (await db.execute(stmt)).scalars().all() if slug}
    if base not in taken:
        return base
    for suffix in range(2, _MAX_SLUG_ATTEMPTS + 2):
        candidate = f"{base[: MAX_SLUG_LEN - len(str(suffix)) - 1]}-{suffix}"
        if candidate not in taken:
            return candidate
    raise Conflict(f"could not derive a free slug from {base!r} in {locale!r}; set one explicitly")


def _stem(base: str) -> int:
    """How much of ``base`` every candidate is guaranteed to share.

    A base already at the column's limit has to be cut to make room for the
    suffix, so its variants do not start with ``base`` — prefiltering on the
    full string would miss them and hand back a slug that is in fact taken.
    """
    longest = len(str(_MAX_SLUG_ATTEMPTS + 1))
    return min(len(base), MAX_SLUG_LEN - longest - 1)
