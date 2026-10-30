"""``auto_run`` prompts run on new images, through the one ingest entry point.

An upload always asks for them; an import only when its job says
``auto_run_prompts`` (GeoJSON base64 here; URL and ZIP imports settle through
the same ``settle_bytes``). They run behind the display mutator like every AI
step, and a prompt without ``auto_run`` is not requested.
"""

from __future__ import annotations

from simple_module_db import finalize_session
from sm_images import constants
from sm_images.ingest import IngestMeta, IngestService
from sm_images.models import Collection

from tests.support.ai import add_prompt, results, use_ai_steps
from tests.support.imports import b64, feature
from tests.support.pipeline import jpeg


async def test_an_upload_runs_the_auto_run_prompts(pipe, ai):
    use_ai_steps()
    coll = await pipe.collection({"exif": {}})
    auto = await add_prompt(pipe, coll, auto_run=True)
    manual = await add_prompt(pipe, coll)
    ai.answer = "seen"
    async with pipe.db_state.session_factory() as db:
        row = await db.get(Collection, coll.id)
        ingest = IngestService(
            db, pipe.store, pipe.settings, intent_factory=pipe.db_state.session_factory
        )
        added = await ingest.add_image(
            row, data=jpeg(), filename="a.jpg", meta=IngestMeta(), source=constants.SOURCE_UPLOAD
        )
        await finalize_session(db)
    await pipe.run(added.id)
    status = await pipe.status(added.id)
    assert status == {"exif": "completed", f"prompt:{auto.id}": "completed"}
    (row,) = await results(pipe, auto.id)
    assert row.result_text == "seen"
    assert await results(pipe, manual.id) == []


async def test_an_import_runs_them_only_when_asked(imp, ai):
    use_ai_steps()
    ai.answer = "seen"
    asked = await imp.pipe.collection({}, slug="asked")
    quiet = await imp.pipe.collection({}, slug="quiet")
    prompts = {c.slug: await add_prompt(imp.pipe, c, auto_run=True) for c in (asked, quiet)}
    for coll, flag in ((asked, True), (quiet, False)):
        job = await imp.job([feature({"img": b64("red")})], coll=coll, auto_run_prompts=flag)
        assert await imp.run(job) == "completed"
    (image,) = await imp.images(asked)
    assert f"prompt:{prompts['asked'].id}" in await imp.pipe.status(image.id)
    assert len(await results(imp.pipe, prompts["asked"].id)) == 1
    (image,) = await imp.images(quiet)
    assert f"prompt:{prompts['quiet'].id}" not in await imp.pipe.status(image.id)
    assert await results(imp.pipe, prompts["quiet"].id) == []
