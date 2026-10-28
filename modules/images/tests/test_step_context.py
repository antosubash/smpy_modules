from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sm_images.contracts import DisplayNotAllowed, ImageRead, StepContext, StepOutcome
from sm_images.models import LocationSource
from sm_images.pipeline.step import DisplayWriterMissing

from tests.step_support import _P, FakeStep


def _image() -> ImageRead:
    return ImageRead(
        id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        filename="a.jpg",
        content_type="image/jpeg",
        size_bytes=3,
    )


def _ctx(step, written, progress=None):
    async def rd():
        return b"d"

    async def ro():
        return b"o"

    async def wr(data, ct):
        written.append((data, ct))

    return StepContext(
        step=step,
        image=_image(),
        params=_P(),
        tenant_id="default",
        read_display=rd,
        read_original=ro,
        write_display=wr,
        on_progress=progress,
    )


def test_image_read_is_frozen():
    img = _image()
    with pytest.raises(ValidationError):
        img.filename = "b.jpg"


async def test_reads():
    ctx = _ctx(FakeStep("acme.x"), [])
    assert await ctx.read_display() == b"d"
    assert await ctx.read_original() == b"o"


async def test_write_display_only_for_mutators():
    written: list = []
    with pytest.raises(DisplayNotAllowed):
        await _ctx(FakeStep("acme.x"), written).write_display(b"x", "image/jpeg")
    assert written == []
    await _ctx(FakeStep("acme.x", mutates_display=True), written).write_display(b"x", "image/jpeg")
    assert written == [(b"x", "image/jpeg")]


async def test_write_display_without_a_writer_is_an_executor_error():
    """A mutator handed no writer is the executor's bug, not the step's: the
    error must not claim the step lacks ``mutates_display``."""
    step = FakeStep("acme.x", mutates_display=True)
    ctx = StepContext(
        step=step,
        image=_image(),
        params=_P(),
        tenant_id="default",
        read_display=lambda: None,
        read_original=lambda: None,
    )
    with pytest.raises(DisplayWriterMissing) as exc:
        await ctx.write_display(b"x", "image/jpeg")
    assert "mutates_display" not in str(exc.value)


def test_image_read_from_row():
    row = SimpleNamespace(
        id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        filename="a.jpg",
        content_type="image/jpeg",
        size_bytes=3,
        width=4,
        height=5,
        sha256="ab",
        lat=1.0,
        lng=2.0,
        altitude=None,
        heading=None,
        location_source=LocationSource.MANUAL,
        captured_at=None,
        camera_make="Acme",
        camera_model=None,
        orientation=6,
        external_source=None,
        external_id=None,
        properties={"k": 1},
        group_id=None,
        group_role=None,
        display_generation=2,
        storage_key="secret/original.jpg",
    )
    read = ImageRead.from_row(row)
    assert read.location_source == 3 and type(read.location_source) is int
    assert (read.width, read.display_generation, read.properties) == (4, 2, {"k": 1})
    assert "storage_key" not in read.model_dump()
    row.location_source = None
    assert ImageRead.from_row(row).location_source is None


async def test_progress_calls_callback_and_heartbeat(monkeypatch):
    seen: list = []
    beats: list = []
    import background_tasks

    monkeypatch.setattr(background_tasks, "heartbeat", lambda **kw: beats.append(kw))

    async def cb(pct):
        seen.append(pct)

    await _ctx(FakeStep("acme.x"), [], cb).progress(40)
    await _ctx(FakeStep("acme.x"), [], cb).progress(250)
    assert seen == [40, 100]
    assert beats == [{"progress": (40, 100)}, {"progress": (100, 100)}]


async def test_progress_without_callback_outside_task_is_noop():
    await _ctx(FakeStep("acme.x"), []).progress(10)


def test_outcomes():
    assert StepOutcome.completed({"a": 1}).output == {"a": 1}
    assert StepOutcome.skipped("no gps").reason == "no gps"
    f = StepOutcome.failed("bad", "boom")
    assert (f.status, f.code, f.message) == ("failed", "bad", "boom")
