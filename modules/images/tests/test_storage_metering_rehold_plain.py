"""The settlement outbox's rehold and release ordering without injected hooks
(these interleavings need no concurrency): a replacement that lapses before
its commit, and a release that must wait for the image's current hold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images import billing_ops
from sm_images.pipeline.orchestrate import rerun_image
from sm_images.tenancy import DEFAULT_TENANT

from tests.billing_support import lapsed_image, ops
from tests.pipeline_support import Blur, use_steps

T = DEFAULT_TENANT
LATER = timedelta(hours=2)


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


def _settle(pipe, at: timedelta = LATER):
    return billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + at)


async def test_p1b_a_lapsed_replacement_never_wedges_the_rehold(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)
    gauge.next_seconds = [0]  # the first replacement lapses before its commit
    await _settle(pipe)
    await _settle(pipe, LATER * 4)  # a retry must not replay the spent key
    row = await pipe.row(img)
    assert [h.id for h in gauge.live()] == [row.storage_hold_id]
    assert gauge.holds[row.storage_hold_id].status == "committed"
    assert gauge.holds[seed].status == "released"
    assert all(o.done_at for o in await ops(pipe.db_state))


async def test_p1d_the_old_hold_waits_for_the_current_hold_to_be_committed(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, lapsed = await lapsed_image(pipe, gauge, coll)
    gauge.fail_commit = 1
    await rerun_image(pipe.runtime, T, img, "force")  # a newer hold C, not committed yet
    current = (await pipe.row(img)).storage_hold_id
    assert current not in (seed, lapsed)
    gauge.refuse_commit = {current}
    await _settle(pipe)
    # The rehold found the image naming C and installed nothing. The seed's
    # release must not run while C is uncommitted: the image would count nothing.
    assert gauge.holds[seed].status == "committed"
    assert gauge.holds[current].status == "held"
    gauge.refuse_commit = set()
    await _settle(pipe, LATER * 4)
    assert gauge.holds[current].status == "committed"
    assert gauge.holds[seed].status == "released"
    assert [h.id for h in gauge.live()] == [current]
    assert all(o.done_at for o in await ops(pipe.db_state))
