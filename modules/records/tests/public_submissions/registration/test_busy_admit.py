"""``SeatsBusy`` from events' ``admit`` answers in records' own envelope on every path that admits:
a 409 ``seats_busy`` with nothing half-done, never events' envelope and never a 500."""

from __future__ import annotations

import pytest
from sm_events.contracts import registration as contract
from sm_events.core.errors_registration import SeatsBusy
from sm_records.public_submissions.registration import mail as reg_mail

from tests.support.app_harness import ADMIN, roles
from tests.support.registration_http import (
    TYPE,
    confirm_record,
    load_registration,
    record_url,
    register,
    register_confirmed,
    regs,
    seat_counts,
    single_opt_in,
)

pytestmark = pytest.mark.usefixtures("reg_site")
A = {"headers": roles(ADMIN)}


@pytest.fixture(autouse=True)
def _quiet_mail(monkeypatch):
    async def quiet(*_a, **_k):
        return None

    monkeypatch.setattr(reg_mail, "queue_registration_mail", quiet)


def busy_admit(monkeypatch):
    async def busy(*_a, **_k):
        raise SeatsBusy

    monkeypatch.setattr(contract, "admit", busy)


def records_envelope(got):
    body = got.json()
    assert got.status_code == 409, got.text
    assert body == {"detail": "the seats are busy; try again"}  # records' envelope, not events'
    assert "events" not in str(body)


async def test_a_single_opt_in_submit_is_try_again(reg_site, monkeypatch):
    await single_opt_in(reg_site)
    await load_registration(reg_site, reg_site.event)
    busy_admit(monkeypatch)
    records_envelope(await register(reg_site, "a@example.org", consent=True))
    assert await regs(reg_site) == [] and await seat_counts(reg_site) == (0, 0)


async def test_a_confirmation_is_try_again_and_stays_pending(reg_site, monkeypatch):
    await register(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    busy_admit(monkeypatch)
    records_envelope(await confirm_record(reg_site, record))
    (still,) = await regs(reg_site)
    assert still["data"]["sm_status"] == "pending" and await seat_counts(reg_site) == (0, 0)


async def test_a_restore_is_try_again_and_stays_trashed(reg_site, monkeypatch):
    await register_confirmed(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    assert (await reg_site.delete(record_url(record["uuid"]), **A)).status_code == 204
    busy_admit(monkeypatch)
    records_envelope(await reg_site.post(record_url(record["uuid"], "/restore"), **A))
    assert await regs(reg_site) == [] and await seat_counts(reg_site) == (0, 0)
    assert TYPE  # the type is the registration form under test
