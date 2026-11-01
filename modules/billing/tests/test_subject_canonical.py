"""A user subject is valid only as ``subject_for_user`` spells it (#274).

An uppercase or dashless spelling parses as the same UUID, but requests, the
admin list and checkout all key on the canonical string: a row stored under
another spelling would bill nobody. So such a subject names no user anywhere.
"""

from __future__ import annotations

import uuid

from conftest import make_user
from helpers import make_plan
from sm_billing import subjects
from sm_billing.lifecycle import tenant_gone
from sm_billing.models import Subscription
from sqlalchemy import func, select
from usage_api_helpers import ADMIN as USAGE
from usage_api_helpers import COUNTER, define_meters

ADMIN = "/api/billing/admin"


def _spellings(user_id: str) -> list[str]:
    return [f"user:{user_id.upper()}", f"user:{uuid.UUID(user_id).hex}"]


async def test_only_the_canonical_spelling_names_a_user(user_mode_app):
    app = user_mode_app
    user_id = await make_user(app, "a@x.io")
    canonical = subjects.subject_for_user(user_id)
    assert subjects.user_uuid(canonical) == uuid.UUID(user_id)
    async with app.state.sm.db.session_factory() as db:
        assert await subjects.exists(db, canonical)
        for spelling in _spellings(user_id):
            assert subjects.user_uuid(spelling) is None
            assert not await subjects.exists(db, spelling)
            assert (await subjects.names(db, [spelling]))[spelling] == (spelling, "")
        # A missing user under another spelling is not "gone" either: it never
        # named anyone, so reconcile must not tear anything down for it.
        missing = "abcdefab-cdef-4abc-8def-abcdefabcdef"  # letters, so upper() differs
        assert await tenant_gone(db, app, subjects.subject_for_user(missing))
        for spelling in _spellings(missing):
            assert not await tenant_gone(db, app, spelling)


async def _subscriptions(app) -> int:
    async with app.state.sm.db.session_factory() as db:
        return (await db.execute(select(func.count()).select_from(Subscription))).scalar_one()


async def test_admin_refuses_a_non_canonical_user_subject(user_mode_app, admin):
    app = user_mode_app
    define_meters(app)
    user_id = await make_user(app, "a@x.io")
    async with app.state.sm.db.session_factory() as session:
        team = (await make_plan(session, "team")).id
        await session.commit()
    before = await _subscriptions(app)
    for spelling in _spellings(user_id):
        assigned = await admin.post(
            f"{ADMIN}/subscriptions/{spelling}/assign", json={"plan_id": team}
        )
        assert (assigned.status_code, assigned.json()["detail"]) == (404, "tenant_not_found")
        adjusted = await admin.post(
            f"{USAGE}/{spelling}/adjust", json={"meter": COUNTER, "quantity": 1, "reason": "r"}
        )
        assert (adjusted.status_code, adjusted.json()["detail"]) == (404, "tenant_not_found")
    assert await _subscriptions(app) == before

    canonical = subjects.subject_for_user(user_id)
    ok = await admin.post(f"{ADMIN}/subscriptions/{canonical}/assign", json={"plan_id": team})
    assert (ok.status_code, ok.json()["plan_key"]) == (200, "team")
    adjusted = await admin.post(
        f"{USAGE}/{canonical}/adjust", json={"meter": COUNTER, "quantity": 1, "reason": "r"}
    )
    assert adjusted.status_code == 200, adjusted.text
