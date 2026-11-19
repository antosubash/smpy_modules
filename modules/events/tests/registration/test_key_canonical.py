"""An occurrence key has exactly one spelling: anything else is refused, never normalised."""

from __future__ import annotations

import pytest
from sm_events.registration import args, guards
from sm_events.registration.availability import describe

from tests.registration.seat_helpers import take
from tests.registration.support import NOW, consistent, one_off, series
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

ID = "0b1d3f6e-5c1a-4f0e-9d3a-2b7c8e9f1a42"
GOOD = f"{ID}:20260708T080000Z"
ARABIC = "".join(chr(0x660 + int(c)) for c in "20260708") + "T080000Z"
FULL = "".join(chr(0xFF10 + int(c)) for c in "20260708") + "T080000Z"

BAD = [
    f"{ID}:{ARABIC}",
    f"{ID}:{FULL}",
    f"{ID}:20260708T" + "".join(chr(0x660 + int(c)) for c in "080000") + "Z",
    GOOD + "\n",
    ID + "\n",
    f"{ID.upper()}:20260708T080000Z",
    ID.upper(),
    "{" + ID + "}",
    "urn:uuid:" + ID,
    ID.replace("-", ""),
    f"{ID}:20260708t080000z",
    f"{ID}:20260708T080000z",
    f"{ID}:20261308T080000Z",
    f"{ID}:20260230T080000Z",
    f"{ID}:20260708T240000Z",
    f"{ID}:20260708T086000Z",
    f"{ID}:20260708T080060Z",
    f"{ID}: 20260708T080000Z",
    f"{ID}:20260708T080000Z ",
    f"{ID}:+0260708T080000Z",
    ID.replace("a", chr(0xFF41)),
]


@pytest.mark.parametrize("key", BAD)
def test_one_spelling_only(key):
    with pytest.raises(ValueError):
        args.occurrence_key(key)


@pytest.mark.parametrize("key", [ID, GOOD])
def test_the_canonical_key_is_returned_as_given(key):
    assert args.occurrence_key(key) == key


@pytest.mark.parametrize(
    "value", [ID.upper(), ID + "\n", ID.replace("a", chr(0xFF41)), "{" + ID + "}"]
)
def test_event_id_one_spelling(value):
    with pytest.raises(ValueError):
        args.event_id(value)


def test_the_guards_parse_ascii_only():
    import uuid

    event_id = uuid.UUID(ID)
    from sm_events.content.schedule import Schedule  # noqa: F401  (shape only)

    assert guards._STAMPED.fullmatch(GOOD) is not None
    assert guards._STAMPED.fullmatch(f"{ID}:{ARABIC}") is None
    assert guards._STAMPED.fullmatch(GOOD + "\n") is None
    assert event_id


@pytest.mark.parametrize("key", BAD[:8])
async def test_describe_and_admit_refuse_a_lookalike(db, cal, key):
    event = await one_off(db, cal)
    with pytest.raises(ValueError):
        await describe(
            db,
            tenant_id="default",
            event_id=event.id,
            occurrence_key=key,
            provider=PROVIDER_ID,
            target=KNOWN_TARGET,
            locale="en",
        )
    with pytest.raises(ValueError):
        await take(db, event, "h1", key)
    assert await consistent(db) == {}


async def test_a_well_formed_key_for_a_non_occurrence_admits_nothing(db, cal):
    event = await series(db, cal, registration_capacity=5)
    for stamp in ("20260709T080000Z", "20260708T080001Z", "20990709T080000Z", "20000101T000000Z"):
        got = await take(db, event, "h1", f"{event.id}:{stamp}")
        assert (got.admitted, got.code) == (False, "event_unavailable"), stamp
    got = await take(db, event, "h1", str(event.id))  # a one-off's key on a series
    assert got.code == "event_unavailable"
    assert await consistent(db) == {}
    assert NOW
