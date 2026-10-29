#!/usr/bin/env python
"""Test-only: seed AI results for the review queue spec, with no AI call.

    python tests/e2e/seed_images_review.py <collection_id>

Adds one prompt (a small output schema) to the collection and a completed,
unreviewed result for each of its first two images, written straight to the
database the way a finished run leaves them. ``images-review.spec.ts`` runs it
after it has uploaded the images; it prints the prompt id and the result ids as
JSON. Not part of the product, and not under ``pages/``.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from headless_settings import headless_settings  # noqa: E402
from simple_module_hosting.app_builder import create_app  # noqa: E402
from sm_images.models import Image, Prompt, PromptResult  # noqa: E402
from sm_images.models.enums import StepStatus  # noqa: E402
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope  # noqa: E402
from sqlalchemy import select  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {
        "count": {"type": "integer", "description": "Trees in the picture"},
        "species": {"type": "string", "enum": ["oak", "pine"]},
    },
    "required": ["count"],
}
OUTPUTS = [{"count": 3, "species": "oak"}, {"count": 5, "species": "pine"}]


async def _seed(collection_id: uuid.UUID) -> dict[str, object]:
    app = create_app(headless_settings())
    factory = app.state.sm.db.session_factory
    with tenant_scope(DEFAULT_TENANT):
        async with factory() as db:
            prompt = Prompt(
                collection_id=collection_id,
                name="Tree count",
                instruction="Count the trees.",
                output_schema=SCHEMA,
            )
            db.add(prompt)
            await db.flush()
            stmt = (
                select(Image).where(Image.collection_id == collection_id).order_by(Image.filename)
            )
            images = list((await db.execute(stmt)).scalars())[: len(OUTPUTS)]
            rows = [
                PromptResult(
                    prompt_id=prompt.id,
                    image_id=image.id,
                    status=StepStatus.COMPLETED,
                    result_data=data,
                    model_name="seeded",
                    prompt_revision=prompt.revision,
                )
                for image, data in zip(images, OUTPUTS, strict=False)
            ]
            db.add_all(rows)
            await db.commit()
            out = {"prompt": str(prompt.id), "results": [r.id for r in rows]}
    await app.state.sm.db.engine.dispose()
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: seed_images_review.py <collection_id>", file=sys.stderr)
        return 2
    print(json.dumps(asyncio.run(_seed(uuid.UUID(argv[0])))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
