"""The freeze claim carries the audience it claimed (Codex C2): the list and
audience come from the same read as the generation the claim pins, so a list
change committed between an earlier read and the claim cannot freeze the old
list's subscribers under the new generation."""

from __future__ import annotations

from sm_newsletter.sending import freeze as freezing

from tests.support.campaign_world import campaign_row, send_rows, set_columns
from tests.support.freeze_world import (
    due_campaign,
    emails,
    run_freeze,
    schedule,
    subscribers,
    unschedule,
    world,
)
from tests.support.records_seed import seed_list
from tests.support.sending import T


async def test_list_swapped_before_the_claim_freezes_only_the_new_list(tmp_path, monkeypatch):
    app, state, _ = await world(tmp_path)
    try:
        await seed_list(state, T, "other")
        await subscribers(state, 3)
        others = await subscribers(state, 2, key="other", prefix="o")
        cid = await due_campaign(state)
        real = freezing.claim_freeze

        async def swap_then_claim(session, **kw):
            await unschedule(state, cid)
            await set_columns(state, T, cid, list_type_key="other")
            await schedule(app, state, cid)
            return await real(session, **kw)

        monkeypatch.setattr(freezing, "claim_freeze", swap_then_claim)
        assert await run_freeze(state, cid) == freezing.FreezeResult(True, 2, 0)

        campaign = await campaign_row(state, T, cid)
        assert (campaign.status, campaign.list_type_key, campaign.recipient_count) == (
            "sending",
            "other",
            2,
        )
        assert await emails(state, cid) == sorted(others)
        assert {row.freeze_gen for row in await send_rows(state, T, cid)} == {campaign.freeze_gen}
    finally:
        await state.engine.dispose()
