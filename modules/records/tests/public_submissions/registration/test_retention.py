"""Retention of registrations: a pending hold that expires, and the occurrence-based window."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_records.core import constants
from sm_records.public_submissions import retention

from tests.support.public_submissions_support import update as update_type
from tests.support.registration_http import (
    TYPE,
    follow,
    reg_config,
    reg_links,
    register,
    regs,
    seat_counts,
    single_opt_in,
)

pytestmark = pytest.mark.usefixtures("reg_site")
START = datetime(2099, 7, 1, 8, tzinfo=UTC)


async def sweep(site, at):
    settings = getattr(site.app.state, constants.PACKAGE).settings
    return await retention.sweep(site.db_state.session_factory, settings, now=at)


async def test_pending_expires_and_its_seat_goes(reg_site):
    await register(reg_site, "a@example.org")
    await register(reg_site, "b@example.org")
    mine = next(m for m in reg_site.outbox.sent if m.to == "b@example.org")
    assert (await follow(reg_site, "confirm", reg_links(mine)["confirm"]["t"])).status_code == 200
    assert await seat_counts(reg_site) == (2, 2)
    soon = datetime.now(UTC) + timedelta(minutes=30)
    assert (await sweep(reg_site, soon)).purged == 0, "inside the hold nothing is due"
    later = datetime.now(UTC) + timedelta(hours=2)
    done = await sweep(reg_site, later)
    assert done is not None and done.purged == 1
    left = await regs(reg_site)
    assert [r["data"]["sm_email"] for r in left] == ["b@example.org"]  # confirmed: kept
    assert left[0]["data"]["sm_status"] == "registered"
    assert await seat_counts(reg_site) == (1, 1)
    assert await regs(reg_site, trashed=True) == []


async def test_the_hold_is_the_types_own(reg_site):
    await update_type(reg_site, TYPE, public_submissions=reg_config(pending_hold_hours=2))
    await register(reg_site)
    assert (await sweep(reg_site, datetime.now(UTC) + timedelta(hours=1))).purged == 0
    assert (await sweep(reg_site, datetime.now(UTC) + timedelta(hours=3))).purged == 1


async def test_retention_runs_from_the_occurrence(reg_site):
    await update_type(
        reg_site,
        TYPE,
        public_submissions=reg_config(
            double_opt_in=False,
            consent={"required": True, "text": {"en": "ok"}},
            retention_days=30,
        ),
    )
    await register(reg_site, consent=True)
    assert (await sweep(reg_site, START + timedelta(days=29))).purged == 0
    assert len(await regs(reg_site)) == 1 and await seat_counts(reg_site) == (1, 1)
    assert (await sweep(reg_site, START + timedelta(days=31))).purged == 1
    assert await regs(reg_site) == [] and await seat_counts(reg_site) == (0, 0)


async def test_zero_keeps_what_is_confirmed_but_not_what_is_pending(reg_site):
    await update_type(
        reg_site,
        TYPE,
        public_submissions=reg_config(
            double_opt_in=False, consent={"required": True, "text": {"en": "ok"}}, retention_days=0
        ),
    )
    await register(reg_site, consent=True)
    assert (await sweep(reg_site, START + timedelta(days=4000))).purged == 0
    assert len(await regs(reg_site)) == 1


async def test_a_cancelled_registration_is_purged_with_the_rest(reg_site):
    await single_opt_in(reg_site)
    await update_type(
        reg_site,
        TYPE,
        public_submissions=reg_config(
            double_opt_in=False, consent={"required": True, "text": {"en": "ok"}}, retention_days=10
        ),
    )
    await register(reg_site, consent=True)
    (record,) = await regs(reg_site)
    from tests.support.app_harness import ADMIN, roles
    from tests.support.registration_http import record_url

    await reg_site.post(record_url(record["uuid"], "/submission/cancel"), headers=roles(ADMIN))
    assert (await sweep(reg_site, START + timedelta(days=11))).purged == 1
    assert await regs(reg_site) == [] and await seat_counts(reg_site) == (0, 0)
