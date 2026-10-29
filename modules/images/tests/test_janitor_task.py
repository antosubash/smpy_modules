"""The janitor beyond the purge: the platform intent pass, the per-tenant loop
and its beat entry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from simple_module_db import all_tenants
from simple_module_db.tenancy import current_tenant_id, is_all_tenants
from sm_images import janitor, task_config
from sm_images.janitor import janitor_async, reap_intents
from sm_images.models import Image, ObjectIntent
from sm_images.purge import PurgeReport
from sqlalchemy import select

from tests.pipeline_support import use_steps

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=8)


async def _intent(pipe, key: str, at: datetime, *, data: bytes | None = b"x") -> None:
    if data is not None:
        await pipe.store.put(key, data, content_type="image/jpeg", size=len(data))
    async with pipe.db_state.session_factory() as s:
        s.add(ObjectIntent(key=key, created_at=at))
        await s.commit()


async def _intents(pipe) -> list[str]:
    async with pipe.db_state.session_factory() as s:
        return sorted((await s.execute(select(ObjectIntent.key))).scalars())


async def _reap(pipe, **kw):
    with all_tenants():
        async with pipe.db_state.session_factory() as db:
            report = await reap_intents(
                db, pipe.store, now=kw.pop("now", NOW), grace_days=kw.pop("grace", 7), **kw
            )
            await db.commit()
    return report


async def test_orphan_intent_reaped(pipe):
    use_steps()
    coll = await pipe.collection({})
    owned = (await pipe.row(await pipe.image(coll))).storage_key
    orphan = f"images/default/{coll.id}/0000/display.1.dead.jpg"
    fresh = f"images/default/{coll.id}/0001/display.1.beef.jpg"
    await _intent(pipe, orphan, OLD)
    await _intent(pipe, owned, OLD, data=None)  # the row committed; the intent lingered
    await _intent(pipe, fresh, NOW - timedelta(hours=1))

    dry = await _reap(pipe, dry_run=True)
    assert (dry.reaped, dry.referenced) == ([orphan], [owned])
    assert await pipe.store.exists(orphan) and len(await _intents(pipe)) == 3

    report = await _reap(pipe)
    assert (report.reaped, report.referenced) == ([orphan], [owned])
    assert not await pipe.store.exists(orphan)
    assert await pipe.store.exists(owned) and await pipe.store.exists(fresh)
    assert await _intents(pipe) == [fresh]


async def test_a_young_intent_is_never_reaped_even_with_no_grace(pipe):
    use_steps()
    key = "images/default/c/i/display.1.young.jpg"
    await _intent(pipe, key, NOW - timedelta(hours=2))
    assert (await _reap(pipe, grace=0)).reaped == []
    assert await pipe.store.exists(key)


async def test_janitor_scopes_each_tenant_then_one_platform_pass(pipe, monkeypatch):
    calls: list[tuple[str, object]] = []

    async def uploads(db, store, now, cap):
        calls.append(("uploads", current_tenant_id.get()))
        return 1

    async def purge(db, store, **kw):
        calls.append(("purge", current_tenant_id.get()))
        return PurgeReport(kw["dry_run"])

    async def intents(db, store, **kw):
        calls.append(("intents", is_all_tenants()))
        return janitor.IntentReport(kw["dry_run"])

    async def two(runtime):
        return ["acme", "beta"]

    monkeypatch.setattr(janitor, "tenants", two)
    monkeypatch.setattr(janitor, "reap_expired_uploads", uploads)
    monkeypatch.setattr(janitor, "purge_expired", purge)
    monkeypatch.setattr(janitor, "reap_intents", intents)
    summary = await janitor_async(pipe.runtime, NOW)
    assert calls == [
        ("uploads", "acme"),
        ("purge", "acme"),
        ("uploads", "beta"),
        ("purge", "beta"),
        ("intents", True),
    ]
    assert summary["uploads_reaped"] == 2


async def test_janitor_purges_past_the_settings_grace(pipe):
    use_steps()
    coll = await pipe.collection({})
    old, recent = await pipe.image(coll), await pipe.image(coll)
    await pipe.trash(Image, old, NOW - timedelta(days=pipe.settings.janitor_grace_days + 1))
    await pipe.trash(Image, recent, NOW - timedelta(days=1))

    summary = await janitor_async(pipe.runtime, NOW)
    assert summary["images_purged"] == 1 and summary["objects_deleted"] == 1
    async with pipe.db_state.session_factory() as s:
        left = select(Image.id).execution_options(include_deleted=True)
        assert list((await s.execute(left)).scalars()) == [recent]


def _refusing(monkeypatch, bad: set[str]) -> list[str]:
    """Deletes of ``bad`` keys fail; returns every key a delete was tried on."""
    from sm_images.storage import ImageStore

    real, tried = ImageStore.delete_keys, []

    async def delete_keys(self, keys):
        keys = list(keys)
        tried.extend(keys)
        if bad & set(keys):
            raise RuntimeError("storage refused")
        return await real(self, keys)

    monkeypatch.setattr(ImageStore, "delete_keys", delete_keys)
    return tried


async def test_a_failing_intent_does_not_starve_newer_ones(pipe, monkeypatch):
    use_steps()
    stuck, fresh = "images/default/c/i/display.1.stuck.jpg", "images/default/c/i/display.1.ok.jpg"
    await _intent(pipe, stuck, OLD - timedelta(days=1))
    await _intent(pipe, fresh, OLD)
    _refusing(monkeypatch, {stuck})

    assert (await _reap(pipe, cap=1)).reaped == []  # tried the stuck one, recorded it
    assert (await _reap(pipe, cap=1)).reaped == [fresh]  # then the newer one's turn
    assert await _intents(pipe) == [stuck]
    async with pipe.db_state.session_factory() as s:
        (row,) = (await s.execute(select(ObjectIntent))).scalars()
        assert row.attempted_at is not None


async def test_an_intent_pass_stops_trying_after_repeated_failures(pipe, monkeypatch):
    use_steps()
    keys = [f"images/default/c/i/display.1.k{n}.jpg" for n in range(5)]
    for n, key in enumerate(keys):
        await _intent(pipe, key, OLD - timedelta(minutes=n))
    monkeypatch.setattr(janitor, "FAILURE_LIMIT", 2)
    tried = _refusing(monkeypatch, set(keys))

    report = await _reap(pipe)
    assert report.reaped == [] and len(tried) == 2  # storage is down: stop early
    assert await _intents(pipe) == sorted(keys)


async def test_purge_dry_run_leaves_intents_and_billing_alone(pipe, monkeypatch):
    from sm_images import billing_ops, storage_keys
    from sm_images.purge import purge_expired

    use_steps()
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    old = storage_keys.image_prefix("default", str(coll.id), str(img)) + "display.1.x.jpg"
    await _intent(pipe, old, OLD)
    await pipe.trash(Image, img, OLD)
    released: list = []

    async def record(db, holds):
        released.append(holds)

    monkeypatch.setattr(billing_ops, "release_storage", record)
    async with pipe.db_state.session_factory() as db:
        report = await purge_expired(db, pipe.store, now=NOW, grace_days=7, dry_run=True)
        await db.commit()
    assert report.images == [img] and old in report.keys
    assert await _intents(pipe) == [old] and await pipe.store.exists(old)
    assert released == []


async def test_janitor_dry_run_end_to_end_changes_nothing(pipe, monkeypatch):
    from sm_images import billing_ops

    use_steps()
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    orphan = f"images/default/{coll.id}/0000/display.1.dead.jpg"
    await _intent(pipe, orphan, OLD)
    await pipe.trash(Image, img, OLD)
    before = pipe.keys()
    released: list = []

    async def record(db, holds):
        released.append(holds)

    monkeypatch.setattr(billing_ops, "release_storage", record)
    summary = await janitor_async(pipe.runtime, NOW, dry_run=True)
    assert summary["images_purged"] == 1 and summary["intents_reaped"] == 1  # would be
    assert pipe.keys() == before and await _intents(pipe) == [orphan]
    async with pipe.db_state.session_factory() as s:
        left = select(Image.id).execution_options(include_deleted=True)
        assert list((await s.execute(left)).scalars()) == [img]
    assert released == []


def test_janitor_is_a_daily_beat_next_to_reconcile():
    entry = task_config.BEAT_SCHEDULE["images-janitor"]
    assert entry["task"] == task_config.JANITOR == "images.janitor"
    assert entry["schedule"] == 24 * 3600.0
    assert task_config.TASK_ROUTES[task_config.JANITOR] == {"queue": task_config.QUEUE_DEFAULT}
    assert "images-reconcile" in task_config.BEAT_SCHEDULE


def test_janitor_task_is_registered():
    from sm_images import tasks

    assert tasks.janitor.name == "images.janitor"
