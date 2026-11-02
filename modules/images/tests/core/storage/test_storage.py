"""ImageStore over the framework's storage backend (filesystem on tmp_path)."""

from __future__ import annotations

import pytest
from file_storage.contracts.service import StorageNotFoundError
from sm_images.core.storage import ImageStore, reset_worker_store, store_for, worker_store

KEY = "images/default/c/i/original.jpg"


async def _agen(*chunks: bytes):
    for c in chunks:
        yield c


async def test_round_trip_bytes_and_iterator(images_app, storage):
    app, _ = images_app
    store = store_for(app)
    await store.put(KEY, b"hello world", content_type="image/jpeg", size=11)
    assert await store.read(KEY) == b"hello world"
    assert await store.exists(KEY)
    assert await store.head(KEY) == (11, None)

    k2 = "images/default/c/i/display.1.jpg"
    await store.put(k2, _agen(b"abc", b"def"), content_type="image/jpeg", size=6)
    assert b"".join([c async for c in await store.stream(k2)]) == b"abcdef"
    assert await store.head("images/nope") is None


async def test_range_read_is_inclusive(images_app, storage):
    store = store_for(images_app[0])
    await store.put(KEY, b"0123456789", content_type="image/jpeg", size=10)
    got = b"".join([c async for c in await store.stream_range(KEY, 2, 4)])
    assert got == b"234"


async def test_range_falls_back_to_slicing_without_get_range(images_app, storage):
    class NoRange:
        async def get(self, key):
            return await storage.get(key)

    store = ImageStore(NoRange())
    await store_for(images_app[0]).put(KEY, b"0123456789", content_type="x", size=10)
    got = b"".join([c async for c in await store.stream_range(KEY, 2, 4)])
    assert got == b"234"


async def test_head_without_head_support_counts_bytes(images_app, storage):
    class Bare:
        async def exists(self, key):
            return await storage.exists(key)

        async def get(self, key):
            return await storage.get(key)

    await store_for(images_app[0]).put(KEY, b"0123456789", content_type="x", size=10)
    assert await ImageStore(Bare()).head(KEY) == (10, None)


async def test_delete_keys_ignores_missing(images_app, storage):
    store = store_for(images_app[0])
    await store.put(KEY, b"x", content_type="image/jpeg", size=1)
    assert await store.delete_keys([KEY, "images/never/was"]) == 2
    assert not await store.exists(KEY)
    assert await store.delete_keys([]) == 0


async def test_read_missing_raises(images_app, storage):
    with pytest.raises(StorageNotFoundError):
        await store_for(images_app[0]).read("images/none")


# -- worker_store: cached per process, rebuilt when the backend settings change --


@pytest.fixture
def worker_settings(monkeypatch):
    import background_tasks
    from file_storage import backends
    from file_storage.settings import FileStorageSettings

    current = {"value": FileStorageSettings(backend="filesystem", fs_root_path="/tmp/a")}
    built: list[str] = []

    def fake_settings_for(cls, package, **kw):
        assert (cls, package) == (FileStorageSettings, "file_storage")
        return current["value"].model_copy(deep=True)

    def fake_build(settings):
        built.append(settings.fs_root_path)
        return object()

    monkeypatch.setattr(background_tasks, "settings_for", fake_settings_for, raising=False)
    monkeypatch.setattr(backends, "build_backend", fake_build)
    reset_worker_store()
    yield current, built
    reset_worker_store()


def test_worker_store_is_cached_while_settings_are_unchanged(worker_settings):
    _, built = worker_settings
    assert worker_store() is worker_store()
    assert built == ["/tmp/a"]


def test_worker_store_rebuilds_when_backend_settings_change(worker_settings):
    from file_storage.settings import FileStorageSettings

    current, built = worker_settings
    first = worker_store()
    current["value"] = FileStorageSettings(backend="filesystem", fs_root_path="/tmp/b")
    second = worker_store()
    assert second is not first
    assert built == ["/tmp/a", "/tmp/b"]
    assert worker_store() is second


def test_worker_store_rebuilds_in_a_forked_child(worker_settings, monkeypatch):
    import os

    _, built = worker_settings
    first = worker_store()
    pid = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: pid + 1)
    assert worker_store() is not first
    assert len(built) == 2
