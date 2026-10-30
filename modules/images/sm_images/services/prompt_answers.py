"""The answers of an image's prompt steps, for the viewer's step cards.

``{"prompt:<id>": {"data": ..., "text": ...}}`` - the result's data (the
reviewed correction when there is one) and its free text. Someone who can edit
the collection always gets them; a viewer only for an image whose picture may
be shown (``redaction``: the display copy is trusted, or nothing is pending) -
the gate ``services.prompts.results_page`` applies to a viewer's results list.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from sm_images.access import redaction
from sm_images.models import Collection, Image, PromptResult
from sm_images.pipeline.registry import PROMPT_PREFIX

__all__ = ["answers"]


async def _may_show(db: Any, collection: Collection, image: Image) -> bool:
    if redaction.trusts_display(collection, image):
        return True
    return not await redaction.pending(db, collection, image)


async def answers(
    db: Any, collection: Collection, image: Image, *, editor: bool
) -> dict[str, dict[str, Any]]:
    if not editor and not await _may_show(db, collection, image):
        return {}
    stmt = select(
        PromptResult.prompt_id,
        PromptResult.result_data,
        PromptResult.reviewed_data,
        PromptResult.result_text,
    ).where(PromptResult.image_id == image.id)
    out: dict[str, dict[str, Any]] = {}
    for pid, data, reviewed, text in (await db.execute(stmt)).all():
        if data is None and reviewed is None and text is None:
            continue
        out[f"{PROMPT_PREFIX}{pid}"] = {
            "data": reviewed if reviewed is not None else data,
            "text": text,
        }
    return out
