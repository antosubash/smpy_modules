"""Deleting map archives nothing references any more (a superseded build's own
upload, the archive a publish or a withdrawal just replaced).

Its own module so both :mod:`~sm_images.map.build` and
:mod:`~sm_images.map.revoke` import it at the top, with no cycle between them.
"""

from __future__ import annotations

import logging

from simple_module_db.independent import independent_session
from sqlalchemy import delete

from sm_images.models import ObjectIntent
from sm_images.pipeline.runtime import Runtime

__all__ = ["drop_objects"]

logger = logging.getLogger(__name__)


async def drop_objects(runtime: Runtime, keys: list[str]) -> None:
    """Delete objects nothing references, then their intents. Best effort: one
    whose delete fails keeps its intent, and the janitor retries."""
    if not keys:
        return
    try:
        await runtime.store().delete_keys(keys)
        async with independent_session(runtime.session_factory) as s:
            await s.execute(delete(ObjectIntent).where(ObjectIntent.key.in_(keys)))
    except Exception:
        logger.warning("images.map.object_cleanup_failed keys=%s", keys, exc_info=True)
