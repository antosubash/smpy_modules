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


def test_janitor_is_a_daily_beat_next_to_reconcile():
    entry = task_config.BEAT_SCHEDULE["images-janitor"]
    assert entry["task"] == task_config.JANITOR == "images.janitor"
    assert entry["schedule"] == 24 * 3600.0
    assert task_config.TASK_ROUTES[task_config.JANITOR] == {"queue": task_config.QUEUE_DEFAULT}
    assert "images-reconcile" in task_config.BEAT_SCHEDULE


def test_janitor_task_is_registered():
    from sm_images import tasks

    assert tasks.janitor.name == "images.janitor"
