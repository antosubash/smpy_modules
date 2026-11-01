"""The admin Subscriptions list can be searched, so a long list stays reachable (#274)."""

from __future__ import annotations

import uuid

from api_helpers import page_props
from conftest import make_user
from helpers import make_tenant
from sm_billing import constants as c
from sm_billing.subjects import subject_for_user
from users.models import User

ADMIN = "/api/billing/admin/subscriptions"


async def _ids(admin, q: str) -> list[str]:
    response = await admin.get(ADMIN, params={"q": q})
    assert response.status_code == 200, response.text
    return [r["tenant_id"] for r in response.json()]


async def test_user_mode_searches_by_email(user_mode_app, admin):
    app = user_mode_app
    alice = subject_for_user(await make_user(app, "alice@x.io"))
    await make_user(app, "bob@x.io")
    assert await _ids(admin, "ALICE") == [alice]
    assert await _ids(admin, "%") == []  # a wildcard is matched literally
    assert await _ids(admin, "_lice") == []
    props = await page_props(admin, "/admin/billing/subscriptions?q=alice")
    assert [r["tenant_id"] for r in props["subscriptions"]["items"]] == [alice]
    assert props["search"] == "alice"
    assert props["subscriptions"]["total"] == 1


async def test_user_mode_matches_a_subject_or_uuid_exactly(user_mode_app, admin):
    app = user_mode_app
    user_id = await make_user(app, "carol@x.io")
    await make_user(app, "dave@x.io")
    subject = subject_for_user(user_id)
    assert await _ids(admin, subject) == [subject]
    assert await _ids(admin, user_id) == [subject]
    assert await _ids(admin, str(uuid.uuid4())) == []


async def test_tenant_mode_searches_by_name_or_slug(app, admin):
    async with app.state.sm.db.session_factory() as session:
        acme = await make_tenant(session, "acme")
        globex = await make_tenant(session, "globex-corp")
        await session.commit()
        acme_id, globex_id = acme.id, globex.id
    assert await _ids(admin, "Globex") == [globex_id]
    assert await _ids(admin, "acme") == [acme_id]
    assert await _ids(admin, "x-c") == [globex_id]  # the slug
    assert await _ids(admin, "%") == []


async def test_user_list_stops_at_the_row_limit_and_pages_on(user_mode_app, admin):
    async with user_mode_app.state.sm.db.session_factory() as session:
        for i in range(c.ADMIN_ROW_LIMIT + 1):
            session.add(User(id=uuid.uuid4(), email=f"u{i:03}@x.io", hashed_password="x"))
        await session.commit()
    first = [r["tenant_id"] for r in (await admin.get(ADMIN)).json()]
    assert len(first) == c.ADMIN_ROW_LIMIT  # users past the limit are cut ...
    rest = await admin.get(ADMIN, params={"offset": c.ADMIN_ROW_LIMIT})
    after = [r["tenant_id"] for r in rest.json()]
    assert after and not set(first) & set(after)  # ... and the next page has them
