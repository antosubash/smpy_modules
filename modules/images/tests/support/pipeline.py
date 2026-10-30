"""A pipeline to test against: registry, store, runtime and seeded images.

``pipe`` is the fixture: an in-memory database (Postgres when the suite runs
there), a filesystem store on ``tmp_path``, the built-in steps plus whatever
fakes a test registers, and an **eager** runtime - so ``await pipe.run(img)``
drains the whole chain on the test's loop, the way an eager host does.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest_asyncio
from file_storage.backends.filesystem import FilesystemBackend
from PIL import Image as PILImage
from pydantic import BaseModel
from simple_module_core.events import EventBus
from sm_images.contracts import StepOutcome
from sm_images.models import Collection, Image, Rendition, StepRun
from sm_images.pipeline import registry
from sm_images.pipeline.builtin_steps import register_builtins
from sm_images.pipeline.orchestrate import submit_dispatch
from sm_images.pipeline.runtime import Runtime
from sm_images.settings import ImagesSettings
from sm_images.storage import ImageStore
from sm_images.storage import keys as storage_keys
from sm_images.tenancy import DEFAULT_TENANT, install_guard
from sqlalchemy import select, update

FIX = Path(__file__).parent.parent / "fixtures"


def jpeg(size: tuple[int, int] = (64, 48), color: str = "red") -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


class _P(BaseModel):
    pass


class Blur:
    """A display mutator: writes a smaller, green display copy."""

    id = "acme.blur"
    version = 1
    requires: tuple[str, ...] = ()
    mutates_display = True
    queue = "images_gpu"

    def __init__(self) -> None:
        self.calls = 0

    def params_schema(self):
        return _P

    def applies(self, image, params) -> bool:
        return True

    async def run(self, ctx):
        self.calls += 1
        await ctx.read_original()
        await ctx.write_display(jpeg((32, 24), "green"), "image/jpeg")
        return StepOutcome.completed({"blurred": 1})


class Scripted:
    """A plugin step whose behaviour a test sets (``outcome`` or ``fn``)."""

    def __init__(self, sid: str, *, requires=(), version: int = 1, queue: str = "images") -> None:
        self.id, self.version, self.requires, self.queue = sid, version, tuple(requires), queue
        self.mutates_display = False
        self.calls = 0
        self.outcome = StepOutcome.completed({"ok": True})
        self.fn: Any = None

    def params_schema(self):
        return _P

    def applies(self, image, params) -> bool:
        return True

    async def run(self, ctx):
        self.calls += 1
        if self.fn is not None:
            return await self.fn(ctx)
        return self.outcome


@dataclass
class Pipe:
    db_state: Any
    store: ImageStore
    settings: ImagesSettings
    bus: EventBus
    runtime: Runtime
    backend: FilesystemBackend
    images: dict[str, uuid.UUID] = field(default_factory=dict)

    async def collection(self, steps: dict[str, dict], **kw: Any) -> Collection:
        async with self.db_state.session_factory() as s:
            row = Collection(
                slug=kw.pop("slug", f"c-{uuid.uuid4().hex[:8]}"),
                name="C",
                owner_id="olga",
                pipeline_config={"steps": steps},
                **kw,
            )
            s.add(row)
            await s.commit()
            return row

    async def image(self, coll: Collection, data: bytes | None = None, **kw: Any) -> uuid.UUID:
        data = data if data is not None else jpeg()
        image_id = uuid.uuid4()
        key = storage_keys.original_key(DEFAULT_TENANT, str(coll.id), str(image_id), "jpg")
        await self.store.put(key, data, content_type="image/jpeg", size=len(data))
        async with self.db_state.session_factory() as s:
            s.add(
                Image(
                    id=image_id,
                    collection_id=coll.id,
                    storage_key=key,
                    filename="a.jpg",
                    content_type="image/jpeg",
                    size_bytes=len(data),
                    **kw,
                )
            )
            await s.commit()
        return image_id

    async def run(self, image_id: uuid.UUID, tenant: str = DEFAULT_TENANT) -> None:
        await submit_dispatch(self.runtime, tenant, image_id)

    async def runs(self, image_id: uuid.UUID) -> dict[str, StepRun]:
        async with self.db_state.session_factory() as s:
            rows = (await s.execute(select(StepRun).where(StepRun.image_id == image_id))).scalars()
            return {r.step: r for r in rows}

    async def status(self, image_id: uuid.UUID) -> dict[str, str]:
        return {k: v.status.value for k, v in (await self.runs(image_id)).items()}

    async def row(self, image_id: uuid.UUID) -> Image:
        async with self.db_state.session_factory() as s:
            return (await s.execute(select(Image).where(Image.id == image_id))).scalar_one()

    async def renditions(self, image_id: uuid.UUID) -> dict[str, Rendition]:
        async with self.db_state.session_factory() as s:
            stmt = select(Rendition).where(Rendition.image_id == image_id)
            return {r.size: r for r in (await s.execute(stmt)).scalars()}

    async def trash(self, model: Any, row_id: uuid.UUID, at: Any = None) -> None:
        """Soft-delete a row as the API would, ``deleted_at`` = ``at`` (default now)."""
        from datetime import UTC, datetime

        async with self.db_state.session_factory() as s:
            await s.execute(
                update(model)
                .where(model.id == row_id)
                .values(is_deleted=True, deleted_at=at or datetime.now(UTC))
                .execution_options(synchronize_session=False)
            )
            await s.commit()

    def keys(self) -> list[str]:
        root = Path(self.backend.root)
        return sorted(
            str(p.relative_to(root)).split("/", 1)[1] for p in root.rglob("*") if p.is_file()
        )


def use_steps(*steps: Any) -> None:
    """The registry as a host would have it: built-ins, then these, frozen."""
    registry.reset_registry()
    register_builtins()
    for step in steps:
        registry.register_step(step)
    registry.freeze()


async def make_pipe(tmp_path: Path, db_state: Any = None, **settings: Any) -> Pipe:
    from tests.pg_support import make_db_state

    state = db_state or await make_db_state()
    install_guard(state.sync_session_class)
    backend = FilesystemBackend(tmp_path / "storage")
    store = ImageStore(backend)
    cfg = ImagesSettings(**({"thumbnail_sizes": {"small": 16, "medium": 40}} | settings))
    bus = EventBus()
    runtime = Runtime(
        session_factory=state.session_factory,
        store=lambda: store,
        settings=lambda: cfg,
        bus=lambda: bus,
        eager=True,
        multi_tenant=lambda: False,  # the harness is a single-tenant host
        maps=False,  # map tests turn it on (``dataclasses.replace``)
    )
    return Pipe(state, store, cfg, bus, runtime, backend)


@pytest_asyncio.fixture
async def pipe(tmp_path):
    use_steps()
    p = await make_pipe(tmp_path)
    yield p
    await p.db_state.engine.dispose()
    registry.reset_registry()
