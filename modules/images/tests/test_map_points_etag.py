"""``…/points`` revalidates like the byte routes (S1): a strong ETag of the
answer, and a 304 only after the full access and redaction check."""

from __future__ import annotations

import pytest
from sm_images.models import Collection, Image, Visibility
from sqlalchemy import update

from tests.access_support import OWNER, STRANGER, headers
from tests.test_map_points import _public, _seed, _url


def _strong(tag: str) -> bool:
    return tag.startswith('"') and tag.endswith('"')


async def _set(client, model, where, **values) -> None:
    async with client.db_state.session_factory() as s:
        await s.execute(update(model).where(where).values(**values))
        await s.commit()


@pytest.mark.parametrize("surface", ["admin", "twin"])
async def test_points_carry_a_strong_etag_and_answer_304(client, surface):
    coll, _, _ = await _seed(client, Visibility.PUBLIC)
    url = (_url if surface == "admin" else _public)(coll)
    who = headers(STRANGER)
    got = await client.get(url, headers=who)
    assert got.status_code == 200
    tag = got.headers["etag"]
    assert _strong(tag)
    assert "no-cache" in got.headers["cache-control"]
    again = await client.get(url, headers={**who, "If-None-Match": tag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == tag
    assert again.headers["cache-control"] == got.headers["cache-control"]
    # The answer changes, and so does its tag.
    await _set(client, Image, Image.collection_id == coll.id, lat=10.0, lng=20.0)
    moved = await client.get(url, headers={**who, "If-None-Match": tag})
    assert moved.status_code == 200 and moved.headers["etag"] != tag


@pytest.mark.parametrize("surface", ["admin", "twin"])
async def test_a_conditional_points_request_is_refused_once_private(client, surface):
    coll, _, _ = await _seed(client, Visibility.PUBLIC)
    url = (_url if surface == "admin" else _public)(coll)
    who = headers(STRANGER)
    tag = (await client.get(url, headers=who)).headers["etag"]
    await _set(client, Collection, Collection.id == coll.id, visibility=Visibility.PRIVATE)
    gone = await client.get(url, headers={**who, "If-None-Match": tag})
    assert gone.status_code == 404
    assert "etag" not in gone.headers


async def test_the_owner_and_a_viewer_get_different_tags_for_different_answers(client):
    """The tag digests the answer itself, so a viewer's gated page never
    validates an editor's raw one."""
    coll, _, _ = await _seed(client, Visibility.PUBLIC)
    owner = await client.get(_url(coll), headers=headers(OWNER))
    viewer = await client.get(_url(coll), headers=headers(STRANGER))
    same = owner.json() == viewer.json()
    assert (owner.headers["etag"] == viewer.headers["etag"]) is same
