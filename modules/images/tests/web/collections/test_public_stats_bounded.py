"""Where ``/api/images/public/stats`` stops counting (#88).

The route is anonymous and any cache miss is a stranger's to cause, so no
answer may cost work proportional to the tenant's data: a count reads at most
``MAX_COUNT + 1`` images and answers ``{value: MAX_COUNT, capped: true}`` past
it (the records stats' shape), and the all-collections total considers at most
``MAX_COLLECTIONS`` public collections and is ``{value: null, capped: true}``
past that - a partial sum is not the total. The total is one count however
many collections it spans, not one per collection.
"""

from __future__ import annotations

import pytest
from sm_images.models import Visibility
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.support.pipeline import Blur, use_steps
from tests.support.public_stats import seed, stat

_SERVICE = "sm_images.web.services.public_stats"


@pytest.fixture(autouse=True)
def _blur_installed():
    use_steps(Blur())
    yield
    use_steps()


async def test_image_count_stops_at_the_cap(client, monkeypatch):
    monkeypatch.setattr(f"{_SERVICE}.MAX_COUNT", 3)
    specs = [(Visibility.PUBLIC, False, 2, 2, 1), (Visibility.PUBLIC, False, 1, 1, 0)]
    one, _ = await seed(client.db_state.session_factory, specs)
    assert await stat(client, "images") == {"value": 3, "capped": False}
    assert await stat(client, "located") == {"value": 3, "capped": False}
    await seed(client.db_state.session_factory, [(Visibility.PUBLIC, False, 1, 1, 0)])
    assert await stat(client, "images") == {"value": 3, "capped": True}
    assert await stat(client, "located") == {"value": 3, "capped": True}
    # One collection is bounded the same way, and below the cap is exact.
    assert await stat(client, "images", one.slug) == {"value": 2, "capped": False}
    monkeypatch.setattr(f"{_SERVICE}.MAX_COUNT", 1)
    assert await stat(client, "images", one.slug) == {"value": 1, "capped": True}


async def test_collection_count_stops_at_the_cap(client, monkeypatch):
    monkeypatch.setattr(f"{_SERVICE}.MAX_COUNT", 2)
    specs = [(Visibility.PUBLIC, False, 0, 0, 0)] * 3
    await seed(client.db_state.session_factory, specs)
    assert await stat(client, "collections") == {"value": 2, "capped": True}


async def test_too_many_collections_is_no_total(client, monkeypatch):
    """Past ``MAX_COLLECTIONS`` the total is unavailable, not a partial sum;
    one named collection still answers."""
    monkeypatch.setattr(f"{_SERVICE}.MAX_COLLECTIONS", 2)
    specs = [(Visibility.PUBLIC, False, 1, 1, 0)] * 2
    first, _ = await seed(client.db_state.session_factory, specs)
    assert await stat(client, "images") == {"value": 2, "capped": False}
    # Private ones are not considered, so they do not use up the allowance.
    await seed(client.db_state.session_factory, [(Visibility.PRIVATE, False, 1, 1, 0)])
    assert await stat(client, "images") == {"value": 2, "capped": False}
    await seed(client.db_state.session_factory, [(Visibility.PUBLIC, False, 1, 1, 0)])
    assert await stat(client, "images") == {"value": None, "capped": True}
    assert await stat(client, "located") == {"value": None, "capped": True}
    assert await stat(client, "images", first.slug) == {"value": 1, "capped": False}


async def test_total_is_one_count_however_many_collections(client):
    async def statements() -> int:
        seen: list[str] = []

        def spy(conn, cursor, statement, *a):
            seen.append(statement)

        event.listen(Engine, "before_cursor_execute", spy)
        try:
            assert (await stat(client, "images"))["capped"] is False
        finally:
            event.remove(Engine, "before_cursor_execute", spy)
        return len(seen)

    factory = client.db_state.session_factory
    await seed(factory, [(Visibility.PUBLIC, False, 1, 0, 1)])
    few = await statements()
    await seed(
        factory,
        [(Visibility.PUBLIC, False, 1, 0, 0)] * 2 + [(Visibility.PUBLIC, False, 1, 0, 1)] * 3,
    )
    many = await statements()
    assert many == few, (few, many)
