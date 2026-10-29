"""Per-phase isolation in the platform beats: one recovery or clean-up phase
that raises is logged and counted, and the phases after it still run - in
``images.reconcile`` (its image dispatches too) and in ``images.janitor``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sm_images import janitor, reconcile, reconcile_dispatch
from sm_images.tenancy import DEFAULT_TENANT

T = DEFAULT_TENANT
LATER = datetime.now(UTC) + timedelta(minutes=10)


def _boom(*_args, **_kwargs):
    raise RuntimeError("poison row")


async def _aboom(*_args, **_kwargs):
    _boom()


async def test_a_failing_dispatch_is_counted_and_the_others_still_go(pipe, monkeypatch):
    bad, good = uuid.uuid4(), uuid.uuid4()
    sent: list[uuid.UUID] = []

    async def reopenable(runtime, tenant, ids):
        return [bad, good]

    async def dispatch(runtime, tenant, image_id):
        if image_id == bad:
            raise RuntimeError("broker down for this one")
        sent.append(image_id)

    monkeypatch.setattr(reconcile_dispatch, "reopenable_images", reopenable)
    monkeypatch.setattr(reconcile_dispatch, "submit_dispatch", dispatch)
    done = await reconcile.reconcile_tenant(pipe.runtime, T, LATER)
    assert sent == [good]
    assert (done["dispatched"], done["failed_dispatches"]) == (1, 1)


async def test_a_failing_reconcile_phase_does_not_starve_the_later_ones(pipe, monkeypatch):
    ran: list[str] = []

    async def maps(runtime, tenant, now):
        ran.append("maps")
        return 3

    monkeypatch.setattr(reconcile, "recover_imports", _aboom)
    monkeypatch.setattr(reconcile, "reconcile_maps", maps)
    done = await reconcile.reconcile_tenant(pipe.runtime, T, LATER)
    assert ran == ["maps"] and done["maps"] == 3
    assert done["failed_phases"] == 1
    assert "import_jobs" not in done


async def test_a_failing_janitor_phase_does_not_stop_the_rest(pipe, monkeypatch):
    ran: list[str] = []

    async def staging(runtime, tenant, now, grace):
        ran.append("staging")
        return 2

    async def sweep(factory, tenant, older_than):
        ran.append("sweep")
        return 5

    monkeypatch.setattr(janitor, "purge_expired", _aboom)
    monkeypatch.setattr(janitor, "reap_staging", staging)
    monkeypatch.setattr(janitor.billing_ops, "sweep", sweep)
    done = await janitor.janitor_tenant(pipe.runtime, T, LATER)
    assert ran == ["staging", "sweep"]
    assert (done["import_staging_reaped"], done["billing_ops_swept"]) == (2, 5)
    assert done["failed_phases"] == 1
    assert "images_purged" not in done


async def test_each_janitor_phase_is_isolated_from_the_next(pipe, monkeypatch):
    ran: list[str] = []

    async def purge(db, store, **kw):
        ran.append("purge")
        return janitor.PurgeReport(dry_run=False)

    async def sweep(factory, tenant, older_than):
        ran.append("sweep")
        return 0

    monkeypatch.setattr(janitor, "reap_expired_uploads", _aboom)
    monkeypatch.setattr(janitor, "purge_expired", purge)
    monkeypatch.setattr(janitor, "reap_staging", _aboom)
    monkeypatch.setattr(janitor.billing_ops, "sweep", sweep)
    done = await janitor.janitor_tenant(pipe.runtime, T, LATER)
    assert ran == ["purge", "sweep"]
    assert done["failed_phases"] == 2
