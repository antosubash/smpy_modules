"""Review fixes for auto-run on imports (Task 22, round 1)."""

from __future__ import annotations

import inspect

import pytest_asyncio
from sm_images.ingest.imports import jobs, settle
from sm_images.module import ImagesModule

from tests.ingest.imports.test_import_api import _start
from tests.support.imports import b64, feature, geojson
from tests.support.upload import make_collection


@pytest_asyncio.fixture
async def import_api(uploads):
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)
    uploads.cid = await make_collection(uploads)  # type: ignore[attr-defined]
    return uploads


async def test_an_import_runs_auto_run_prompts_by_default(import_api):
    """Ruling: on unless the import opts out."""
    got = await _start(import_api, file=geojson([feature({"img": b64("red")})]))
    assert got.status_code == 202, got.text
    assert got.json()["auto_run_prompts"] is True
    off = await _start(
        import_api, file=geojson([feature({"img": b64("blue")})]), auto_run_prompts="false"
    )
    assert off.json()["auto_run_prompts"] is False


def test_the_flag_travels_with_the_job_not_a_per_item_read():
    assert "auto_run_prompts" in jobs.JobSnap.__dataclass_fields__
    param = inspect.signature(settle.settle_bytes).parameters["auto_run"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is inspect.Parameter.empty


async def test_the_job_flag_reaches_ingest(imp, monkeypatch):
    seen = []
    real = settle.ingest_item

    async def spy(*a, **kw):
        seen.append(kw["auto_run"])
        return await real(*a, **kw)

    monkeypatch.setattr(settle, "ingest_item", spy)
    for flag in (True, False):
        job = await imp.job(
            [feature({"img": b64("red" if flag else "blue")})], auto_run_prompts=flag
        )
        assert await imp.run(job) == "completed"
    assert seen == [True, False]
