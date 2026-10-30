"""Review round 1: abort on a failed open, keeper teardown, port 0, octet-stream."""

from __future__ import annotations

import asyncio
import contextlib
import types
import uuid

import pytest
from file_storage.contracts.service import NotSupportedError
from simple_module_db import tenant_context
from sm_images.errors import UnsupportedType
from sm_images.imports.url_safety import UnsafeURLError, check_url
from sm_images.ingest import multipart
from sm_images.ingest.ticket import declared_type
from sm_images.pipeline import keeper as keeper_mod


class _Backend:
    supports_direct_upload = True

    def __init__(self):
        self.aborted: list[tuple[str, str]] = []

    async def create_multipart(self, key, content_type):
        return "up-1"

    async def presign_part(self, *args):
        raise NotSupportedError("relay")

    async def abort_multipart(self, key, upload):
        self.aborted.append((key, upload))


class _FailingDb:
    def add(self, row):
        pass

    async def flush(self):
        raise RuntimeError("flush failed")

    async def rollback(self):
        pass


async def test_a_failed_flush_aborts_the_backend_upload(monkeypatch):
    backend = _Backend()

    @contextlib.asynccontextmanager
    async def no_intent(keys, session_factory=None):
        yield

    monkeypatch.setattr(multipart, "object_intent", no_intent)
    with tenant_context("t"), pytest.raises(RuntimeError, match="flush failed"):
        await multipart.open_upload(
            _FailingDb(),
            types.SimpleNamespace(backend=backend),
            types.SimpleNamespace(id=uuid.uuid4()),
            key="k/1.jpg",
            image_id=uuid.uuid4(),
            size=10,
            content_type="image/jpeg",
            filename="a.jpg",
            owner="o",
            secret="s",
        )
    assert backend.aborted == [("k/1.jpg", "up-1")]


async def test_stop_propagates_an_outer_cancellation():
    started = asyncio.Event()

    async def stubborn():
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)  # slow teardown: the outer cancel lands here
            raise

    async def outer():
        k = asyncio.ensure_future(stubborn())
        await started.wait()
        try:
            await asyncio.sleep(0)
        finally:
            await keeper_mod.stop(k)

    task = asyncio.ensure_future(outer())
    await started.wait()
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0.05)
    task.cancel()  # while the keeper is being torn down
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_stop_returns_normally_for_a_cancelled_keeper():
    k = asyncio.ensure_future(asyncio.sleep(60))
    await asyncio.sleep(0)
    await keeper_mod.stop(k)
    assert k.cancelled()


@pytest.mark.parametrize("url", ["http://example.com:0/a.jpg", "https://example.com:0/"])
def test_explicit_port_zero_is_an_invalid_url(url):
    with pytest.raises(UnsafeURLError, match="invalid_url"):
        check_url(url)


def test_octet_stream_with_an_image_extension_is_accepted():
    assert declared_type("a.heic", "application/octet-stream") == "image/heic"
    assert declared_type("a.jpg", "application/octet-stream") == "image/jpeg"


def test_octet_stream_without_an_image_extension_is_415():
    with pytest.raises(UnsupportedType):
        declared_type("a.exe", "application/octet-stream")
    with pytest.raises(UnsupportedType):
        declared_type("a.jpg", "text/plain")
