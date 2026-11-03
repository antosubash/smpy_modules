"""Shared setup for test_collections_crud."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.support.app_harness import seed_type

API = "/api/records/types/gig/records"


@pytest.fixture
async def gig(client, field_def):
    return await seed_type(
        client.db_state,
        "gig",
        [
            field_def("name", "text"),
            field_def("capacity", "integer"),
        ],
        collection="events",
        display_field="name",
        slug_field="name",
    )


async def _count(db_state, cls) -> int:
    async with db_state.session_factory() as session:
        return int((await session.execute(select(func.count(cls.id)))).scalar_one())


@pytest.fixture
async def note(client, field_def):
    """A *global* type, so both revision tables hand out ids 1 and 2."""
    return await seed_type(
        client.db_state,
        "note",
        [field_def("name", "text")],
        display_field="name",
    )
