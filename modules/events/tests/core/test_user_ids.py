"""One canonical user id for what a user owns, and every spelling a cleanup must match."""

from __future__ import annotations

import uuid

import pytest
from sm_events.core import user_ids
from sm_events.feeds.tokens import cleanup
from sm_events.models import Calendar, FeedToken
from sqlalchemy import select

ID = uuid.UUID("3f2504e0-4f89-11d3-9a0c-0305e82c3301")
SPELLINGS = [
    str(ID),
    str(ID).upper(),
    ID.hex,
    ID.hex.upper(),
    f"{{{ID}}}",
    f"urn:uuid:{ID}",
]


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_every_spelling_has_one_canonical_form(spelling):
    assert user_ids.canonical_user_id(spelling) == str(ID)


def test_other_ids_are_left_alone():
    for plain in ("u", "Alice", "auth0|abc123", "x" * 64, ""):
        assert user_ids.canonical_user_id(plain) == plain
    assert user_ids.canonical_user_id(ID) == str(
        ID
    )  # a UUID object, as the framework's events carry


@pytest.mark.parametrize("given", [*SPELLINGS, ID])
def test_spellings_cover_every_form_a_row_could_hold(given):
    found = set(user_ids.spellings(given))
    for form in SPELLINGS[:4]:  # the forms a column holds (braced and urn are only ever input)
        assert form.lower() in found, form
    assert str(ID) in found and ID.hex in found


def test_spellings_of_a_plain_id():
    assert set(user_ids.spellings("Alice")) == {"alice"}


@pytest.mark.parametrize("stored", [str(ID), str(ID).upper(), ID.hex, ID.hex.upper()])
@pytest.mark.parametrize("asked", [*SPELLINGS, ID])
async def test_the_feed_cleanup_matches_every_spelling(db, db_state, stored, asked):
    """Rows written in any spelling go when the user goes, whichever spelling the event carries."""
    cal = Calendar(slug="c", name="C", owner_id="o")
    db.add(cal)
    await db.flush()
    db.add(
        FeedToken(calendar_id=cal.id, user_id=stored, token_hash="a" * 64, label="L", locale="en")
    )
    db.add(
        FeedToken(
            calendar_id=cal.id, user_id="someone-else", token_hash="b" * 64, label="L", locale="en"
        )
    )
    await db.commit()
    assert await cleanup.delete_user_tokens(db_state.session_factory, asked) == 1
    left = (await db.execute(select(FeedToken.user_id))).scalars().all()
    assert left == ["someone-else"]
