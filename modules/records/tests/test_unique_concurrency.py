"""``unique`` under concurrency, on a database that can actually race.

Every other test in this directory runs against ``:memory:`` on a
``StaticPool``, where every session shares one connection and is therefore one
transaction — a harness in which check-then-act cannot be caught, because the
second writer reads the first writer's uncommitted row. That is why eight
concurrent creates with the same ``email`` returned eight ``201``s on a real
server and nothing here noticed.

So this module insists on the two things ``tests/test_reindex_runner_locking``
insists on for the same reason: a **file-backed** database and the **default
pool**, one connection per session, exactly as a server has.

What it pins is design §7.8's mitigation actually holding: writes to a type
are serialised, so of N concurrent creates carrying one unique value exactly
one is stored. And §5's slug claim, whose partial unique index is a real
constraint, refusing as the module's 409 rather than as an unhandled
``IntegrityError``.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.deps import require_edit, require_manage_types, require_view
from sm_records.models import Base, Record
from sm_records.services import _claims
from sqlalchemy import func, select

from tests.app_harness import build_app, seed_type

API = "/api/records/types"

#: Eight, because that is the width the perf study's probe raced at and the
#: number the finding quotes. Enough that a lost race is certain without the
#: lock, small enough that SQLite's write queue drains in well under a second.
WRITERS = 8


def _field(key: str, **overrides: Any) -> dict[str, Any]:
    definition = {"key": key, "type": "text", "label": key.title(), "indexed": True}
    definition.update(overrides)
    return definition


@pytest_asyncio.fixture
async def file_db(tmp_path):
    """A real SQLite *file* on the default pool — see the module docstring."""
    state = init_db(f"sqlite+aiosqlite:///{tmp_path / 'unique.db'}")
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def file_client(tmp_path, file_db):
    app, _ = await build_app(tmp_path, file_db)
    for dependency in (require_view, require_edit, require_manage_types):
        app.dependency_overrides[dependency.dependency] = lambda: None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _stored(file_db, type_id: int) -> int:
    async with file_db.session_factory() as session:
        total = await session.execute(
            select(func.count(Record.id))
            .where(Record.type_id == type_id)
            .execution_options(include_deleted=True)
        )
        return int(total.scalar_one())


async def _race(client: AsyncClient, key: str, payload: dict[str, Any]) -> Counter:
    """``WRITERS`` identical creates at once; the status codes they came back
    with, counted."""
    responses = await asyncio.gather(
        *(client.post(f"{API}/{key}/records", json={"data": payload}) for _ in range(WRITERS))
    )
    return Counter(response.status_code for response in responses)


async def test_concurrent_creates_of_one_unique_value_store_exactly_one(file_client, file_db):
    """The finding, directly: eight at once, one winner, seven 409s.

    ``email`` is unique and is *not* the type's ``slug_field``, so no database
    constraint covers it — the only thing standing between these eight writers
    and eight rows is :func:`sm_records.services._claims.lock_type` taking a
    real write lock before the check rather than a ``FOR UPDATE`` that compiles
    to nothing here.
    """
    rtype = await seed_type(
        file_db,
        "contact",
        [_field("name"), _field("email", unique=True)],
        display_field="name",
    )

    codes = await _race(file_client, "contact", {"name": "Ada", "email": "ada@example.com"})

    assert codes[201] == 1, f"expected one winner, got {dict(codes)}"
    assert codes[409] == WRITERS - 1, f"expected {WRITERS - 1} refusals, got {dict(codes)}"
    assert sum(codes.values()) == WRITERS
    assert await _stored(file_db, rtype.id) == 1


async def test_the_race_is_lost_as_a_409_and_never_as_a_500(file_client, file_db):
    """The same race where the unique field is *also* the ``slug_field``.

    That is the case the partial unique index does catch — and used to catch as
    an unhandled ``IntegrityError``, i.e. HTTP 500. Whatever refuses it, the
    caller must see the module's 409: a lost race is an ordinary outcome, not a
    server fault.
    """
    rtype = await seed_type(
        file_db,
        "product",
        [_field("name"), _field("sku", unique=True)],
        display_field="name",
        slug_field="sku",
    )

    codes = await _race(file_client, "product", {"name": "Widget", "sku": "W-1"})

    assert set(codes) <= {201, 409}, f"a lost race surfaced as {dict(codes)}"
    assert codes[201] == 1, dict(codes)
    assert await _stored(file_db, rtype.id) == 1


async def test_writes_to_a_type_without_a_collision_all_succeed(file_client, file_db):
    """The serialisation must cost throughput, not correctness: eight
    *different* unique values under the same lock are eight rows."""
    rtype = await seed_type(
        file_db,
        "contact",
        [_field("name"), _field("email", unique=True)],
        display_field="name",
    )

    responses = await asyncio.gather(
        *(
            file_client.post(
                f"{API}/contact/records",
                json={"data": {"name": f"n{i}", "email": f"n{i}@example.com"}},
            )
            for i in range(WRITERS)
        )
    )

    assert [response.status_code for response in responses] == [201] * WRITERS
    assert await _stored(file_db, rtype.id) == WRITERS


async def test_the_slug_index_itself_refuses_as_a_409(file_client, file_db, monkeypatch):
    """The database-level half of the slug claim, on its own.

    :func:`~sm_records.services._claims.ensure_slug_free` is the check and
    normally gets there first, so the constraint only ever fires when a writer
    slipped between the check and the flush. Neutralising the check is how that
    window is reproduced on demand — and what must come back is the *same* 409
    the check raises, not the ``IntegrityError`` that used to escape.
    """
    await seed_type(
        file_db,
        "product",
        [_field("name"), _field("sku", unique=False)],
        display_field="name",
        slug_field="sku",
    )

    first = await file_client.post(
        f"{API}/product/records", json={"data": {"name": "One", "sku": "dup"}}
    )
    assert first.status_code == 201, first.text

    async def blind(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(_claims, "ensure_slug_free", blind)
    second = await file_client.post(
        f"{API}/product/records", json={"data": {"name": "Two", "sku": "dup"}}
    )

    assert second.status_code == 409, second.text
    assert "dup" in second.json()["detail"]


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_lock_type_is_a_write_on_sqlite_and_a_row_lock_elsewhere(dialect):
    """The dialect split is the whole fix, so it is pinned rather than read.

    ``FOR UPDATE`` is a row lock on Postgres and nothing at all on SQLite;
    ``UPDATE … SET version = version`` is SQLite's ``RESERVED`` lock and is a
    pointless round trip where a real row lock exists.
    """
    import inspect

    source = inspect.getsource(_claims.lock_type)
    assert 'dialect.name == "sqlite"' in source
    assert "with_for_update" in source
    if dialect == "sqlite":
        assert "version=RecordType.version" in source
        # …and the no-op write must name ``updated_at`` too. ``AuditMixin``
        # declares it ``onupdate=func.now()``, so an UPDATE that leaves it out
        # turns a lock into an edit *and* leaves the attribute expired on the
        # in-memory type row — which a synchronous ``type_read`` then reads off
        # the async greenlet. See ``_common.guarded_bump``'s docstring.
        assert "updated_at=RecordType.updated_at" in source
