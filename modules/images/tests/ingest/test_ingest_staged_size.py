"""A staged object over ``max_image_bytes`` is refused from its size alone.

``add_image(staged_key=...)`` loads the object into memory to inspect it, so
the cap is applied to the stored size (``ImageStore.head``) first: an
oversized direct upload must never be read whole.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sm_images.core.errors import FileTooLarge
from sm_images.ingest import IngestMeta, IngestService


class _Store:
    def __init__(self, size: int) -> None:
        self.size = size
        self.reads: list[str] = []

    async def head(self, key: str) -> tuple[int, str | None]:
        return self.size, None

    async def read(self, key: str) -> bytes:
        self.reads.append(key)
        return b"\0" * self.size


async def test_an_oversized_staged_object_is_refused_without_a_read():
    store = _Store(size=1001)
    ingest = IngestService(None, store, SimpleNamespace(max_image_bytes=1000))
    with pytest.raises(FileTooLarge):
        await ingest.add_image(
            SimpleNamespace(id=uuid.uuid4()),
            staged_key="staging/x.jpg",
            image_id=uuid.uuid4(),
            filename="x.jpg",
            meta=IngestMeta(),
            source="upload",
        )
    assert store.reads == []
