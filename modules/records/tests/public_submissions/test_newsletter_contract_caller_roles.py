"""``sm_records.contracts.newsletter.caller_roles`` (newsletter PR 3, ruling R13):
the request's roles plus its ``records.type.<key>`` grants, as ``can_read_list``
takes them. Kept apart from ``test_newsletter_contract_lists.py`` for its size cap.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sm_records.contracts.newsletter import CallerRoles, caller_roles, can_read_list

from tests.support.newsletter_contract import TENANT, session
from tests.support.newsletter_http import LIST
from tests.support.public_submissions_support import update


def _request(user_roles: list[str] | None, held: set[str]) -> Any:
    user = SimpleNamespace(roles=user_roles) if user_roles is not None else None
    return SimpleNamespace(
        state=SimpleNamespace(user=user, resolved_permissions=held),
        app=SimpleNamespace(state=SimpleNamespace()),
    )


async def _can_read(client, caller: CallerRoles) -> bool:
    async with session(client) as db:
        return await can_read_list(db, tenant_id=TENANT, type_key=LIST, roles=caller)


async def test_caller_roles_from_request(audience):
    narrowed = await update(audience, LIST, allowed_roles=["x"])
    assert narrowed.status_code == 200, narrowed.text
    granted = caller_roles(_request(["editor"], {"records.type.news_list"}))
    assert list(granted) == ["editor"]
    assert granted.granted_types == {"news_list"}
    assert await _can_read(audience, caller_roles(_request(["editor"], {"records.type.news"})))
    assert not await _can_read(audience, caller_roles(_request(["editor"], set())))


async def test_caller_roles_wildcard_role_has_no_type_grants(audience):
    narrowed = await update(audience, LIST, allowed_roles=["x"])
    assert narrowed.status_code == 200, narrowed.text
    admin = caller_roles(_request(["admin"], {"*", "records.type.news"}))
    assert admin.granted_types == frozenset()
    assert not await _can_read(audience, admin)


def test_caller_roles_anonymous_is_empty():
    anon = caller_roles(_request(None, set()))
    assert list(anon) == [] and anon.granted_types == frozenset()
