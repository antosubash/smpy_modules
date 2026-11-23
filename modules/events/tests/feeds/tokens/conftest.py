"""A token world for the resolver's tests: one private calendar shared with ``sv``."""

from __future__ import annotations

import pytest
from sm_events.models import Calendar  # noqa: F401

from tests.feeds.tokens.resolve_support import mint
from tests.support.access import seed_calendars
from tests.support.calendars import seed_event
from tests.support.tokens import token_app


@pytest.fixture
async def world():
    """Calendar ``P`` shared with ``sv`` (view), one published and one draft event, a link."""
    app, state = await token_app()
    async with state.session_factory() as db:
        cals = await seed_calendars(db)
        pub = await seed_event(db, cals["P"], title="Public", status="published", slug="pub")
        draft = await seed_event(db, cals["P"], title="Draft", status="draft", slug="draft")
        await db.commit()
    created = await mint(app, state, cals["P"], "sv")
    yield app, state, cals, created, (pub, draft)
    await state.engine.dispose()
