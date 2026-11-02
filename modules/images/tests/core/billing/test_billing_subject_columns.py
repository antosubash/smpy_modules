"""The subject columns: ``NULL`` until a hold records one (#284)."""

from __future__ import annotations

from sm_images.models import BillingOp
from sqlalchemy import select


async def test_rows_default_to_null_subject(pipe):
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    assert (await pipe.row(img)).storage_subject is None
    async with pipe.db_state.session_factory() as s:
        s.add(BillingOp(op="release", image_id=img, hold_id="h", subject="user:x"))
        await s.commit()
        assert (await s.execute(select(BillingOp.subject))).scalar_one() == "user:x"
