"""Image bytes, a collection to upload into, and what landed where.

``uploads`` is the fixture upload tests use: the harness client with a
filesystem backend installed and the intent session factory set, as
``on_startup`` leaves them in a host.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest_asyncio
from PIL import Image as PILImage
from sm_images.intents import use_session_factory
from sm_images.models import Image, ObjectIntent, StepRun
from sqlalchemy import select

from tests.support.stub_auth import as_user

BASE = "/api/images/collections"
WRITER = ("images.view", "images.create")
OLGA = as_user("olga", WRITER)


def picture(fmt: str = "JPEG", size: tuple[int, int] = (8, 6), color: str = "red") -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def jpeg(**kw: Any) -> bytes:
    return picture("JPEG", **kw)


def png(**kw: Any) -> bytes:
    return picture("PNG", **kw)


def heic(**kw: Any) -> bytes:
    from sm_images.processing.heif import register_heif

    register_heif()

    return picture("HEIF", **kw)


@pytest_asyncio.fixture
async def uploads(client, storage):
    use_session_factory(client.db_state.session_factory)
    client.storage = storage  # type: ignore[attr-defined]
    return client


async def make_collection(client, headers=OLGA, **body) -> str:
    body.setdefault("name", "Trees")
    made = await client.post(BASE, json=body, headers=headers)
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def post_files(client, cid: str, files: list[tuple[str, bytes, str]], headers=OLGA, **data):
    return await client.post(
        f"{BASE}/{cid}/images",
        files=[("files", f) for f in files],
        data=data,
        headers=headers,
    )


def stored(storage) -> list[str]:
    """Every object key in the filesystem backend, multipart staging excluded."""
    root = Path(storage.root)
    # The backend shards on the key's first two characters: ``<root>/<k[:2]>/<key>``.
    return sorted(
        str(p.relative_to(root)).split("/", 1)[1]
        for p in root.rglob("*")
        if p.is_file() and ".multipart" not in p.parts
    )


def object_bytes(storage, key: str) -> bytes:
    return storage._resolve(key).read_bytes()


async def all_rows(client, model=Image, *, include_deleted: bool = False) -> list[Any]:
    async with client.db_state.session_factory() as s:
        stmt = select(model).execution_options(include_deleted=include_deleted)
        return list((await s.execute(stmt)).scalars())


async def intents(client) -> list[str]:
    return [i.key for i in await all_rows(client, ObjectIntent)]


async def step_runs(client) -> list[tuple[str, str]]:
    return sorted((r.step, r.status.value) for r in await all_rows(client, StepRun))


def record_dispatch(monkeypatch) -> list[Any]:
    from sm_images import pipeline

    sent: list[Any] = []

    async def fake(image_id, tenant):
        sent.append(image_id)

    monkeypatch.setattr(pipeline, "_send", fake)
    return sent
