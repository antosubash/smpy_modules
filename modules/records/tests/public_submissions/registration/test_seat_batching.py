"""A bulk turn releases its seats with one contract call, and a refused turn keeps its seat."""

from __future__ import annotations

import pytest
from sm_records.public_submissions.registration import mail as reg_mail

from tests.support.app_harness import ADMIN, roles
from tests.support.registration_http import (
    TYPE,
    register_confirmed,
    regs,
    seat_counts,
)

pytestmark = pytest.mark.usefixtures("reg_site")
A = {"headers": roles(ADMIN)}


@pytest.fixture(autouse=True)
def _quiet_mail(monkeypatch):
    async def quiet(*_a, **_k):
        return None

    monkeypatch.setattr(reg_mail, "queue_registration_mail", quiet)


async def test_a_bulk_trash_releases_with_one_contract_call(reg_site, monkeypatch):
    """V2: one release per bulk turn (one ascending lock acquisition), not one per record."""
    from sm_events.contracts import registration as contract

    for n in range(4):
        await register_confirmed(reg_site, f"b{n}@example.org")
    uuids = [r["uuid"] for r in await regs(reg_site)]
    real = contract.release
    calls: list[int] = []

    async def counting(db, **kw):
        calls.append(len(kw["holders"]))
        return await real(db, **kw)

    monkeypatch.setattr(contract, "release", counting)
    got = await reg_site.post(
        f"/api/records/types/{TYPE}/records/bulk", json={"action": "trash", "uuids": uuids}, **A
    )
    assert got.status_code == 200, got.text
    assert calls == [4] and await seat_counts(reg_site) == (0, 0)


async def test_a_refused_bulk_turn_keeps_its_seat(reg_site):
    """A turn whose savepoint rolled back must not release the seat of a record that stays."""
    await register_confirmed(reg_site, "keep@example.org")
    (record,) = await regs(reg_site)
    got = await reg_site.post(
        f"/api/records/types/{TYPE}/records/bulk",
        json={"action": "trash", "uuids": [record["uuid"], "f" * 32]},  # the second is unknown
        **A,
    )
    assert got.status_code in (404, 409, 422)
    assert await seat_counts(reg_site) == (1, 1)
