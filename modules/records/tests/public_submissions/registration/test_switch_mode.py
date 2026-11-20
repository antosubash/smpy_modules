"""A form switched between double and single opt-in: a resubmit decides from the stored status, so
a pending registration never takes a seat on resubmit and the counts never drift."""

from __future__ import annotations

import pytest

from tests.support.public_submissions_support import update
from tests.support.registration_http import (
    TYPE,
    load_registration,
    reg_config,
    register,
    regs,
    seat_counts,
    single_opt_in,
)

pytestmark = pytest.mark.usefixtures("reg_site")


async def double_opt_in(site):
    resp = await update(site, TYPE, public_submissions=reg_config(double_opt_in=True))
    assert resp.status_code == 200, resp.text


async def submit(site, **kw):
    await load_registration(site, site.event)
    got = await register(site, "ada@example.org", consent=True, **kw)
    assert got.status_code == 202, got.text


async def test_double_to_single_a_pending_resubmit_takes_no_seat(reg_site):
    await submit(reg_site)
    assert [r["data"]["sm_status"] for r in await regs(reg_site)] == ["pending"]
    await single_opt_in(reg_site)
    await submit(reg_site)  # the same address again, now on a single opt-in form
    assert [r["data"]["sm_status"] for r in await regs(reg_site)] == ["pending"]
    assert await seat_counts(reg_site) == (0, 0)  # only its confirmation takes the seat


async def test_single_to_double_a_registered_resubmit_changes_nothing(reg_site):
    await single_opt_in(reg_site)
    await submit(reg_site)
    assert await seat_counts(reg_site) == (1, 1)
    await double_opt_in(reg_site)
    await submit(reg_site)
    assert [r["data"]["sm_status"] for r in await regs(reg_site)] == ["registered"]
    assert await seat_counts(reg_site) == (1, 1)
