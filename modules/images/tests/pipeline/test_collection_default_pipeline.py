"""A new collection runs the core steps without any setup."""

from __future__ import annotations

from sm_images.models import Collection, StepRun
from sm_images.pipeline.config import validate_pipeline_config

from tests.support.upload import OLGA, all_rows, jpeg, make_collection, post_files


async def test_new_collection_enables_exif_and_renditions(uploads):
    await make_collection(uploads)
    (row,) = await all_rows(uploads, Collection)
    assert row.pipeline_config == {
        "steps": {"exif": {"enabled": True}, "renditions": {"enabled": True}}
    }
    assert validate_pipeline_config(row.pipeline_config).enabled() == ["exif", "renditions"]


async def test_an_upload_into_a_new_collection_is_queued_for_both_steps(uploads):
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")], headers=OLGA)
    assert got.status_code == 200, got.text
    steps = {r.step for r in await all_rows(uploads, StepRun)}
    assert {"exif", "renditions"} <= steps
