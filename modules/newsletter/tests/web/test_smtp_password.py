"""``PUT /api/newsletter/settings/smtp-password``: the one place the password is written.

The app is ``tests.support.app.build_app``: the module's own settings and
routes, the framework's settings store and the generic module-settings API,
with only auth and the host's ``app.state.sm`` stubbed.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from settings.service import SettingService
from settings.store import SettingsStore
from simple_module_hosting.csrf import CSRF_HEADER
from sm_newsletter.core import constants, crypto

from tests.support.app import build_app as _build

URL = f"{constants.ROUTE_PREFIX_API}/settings/smtp-password"
MANAGE = {"x-perms": f"{constants.PERM_MANAGE},{constants.PERM_SETTINGS_EDIT}"}


@pytest_asyncio.fixture
async def built():
    app, state = await _build()
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _stored(state) -> str | None:
    async with state.session_factory() as db:
        overrides = await SettingsStore(SettingService(db)).get_overrides(constants.PACKAGE)
    return overrides.get("smtp_password", (None,))[0]


async def test_put_stores_ciphertext(client, built):
    app, state = built
    res = await client.put(URL, json={"password": "s3cret"}, headers=MANAGE)
    assert res.status_code == 200, res.text
    assert res.json() == {"has_password": True}
    assert "s3cret" not in res.text
    stored = await _stored(state)
    assert stored is not None
    assert stored.startswith("enc:v1:")
    assert "s3cret" not in stored
    assert crypto.decrypt_value(stored, "smtp_password") == "s3cret"
    assert app.state.sm_newsletter.settings.smtp_password == stored


@pytest.mark.parametrize("secret", ["  pa ss  ", "\tpw\n", "x" * 1024])
async def test_password_is_stored_exactly_as_submitted(client, built, secret):
    """Leading and trailing whitespace is part of a password, not padding."""
    _, state = built
    res = await client.put(URL, json={"password": secret}, headers=MANAGE)
    assert res.status_code == 200, res.text
    assert crypto.decrypt_value(await _stored(state), "smtp_password") == secret


async def test_put_requires_manage(client, built):
    _, state = built
    res = await client.put(URL, json={"password": "s3cret"}, headers={"x-perms": "newsletter.view"})
    assert res.status_code == 403
    assert await _stored(state) is None


async def test_manage_without_settings_edit_is_403(client, built):
    _, state = built
    res = await client.put(
        URL, json={"password": "s3cret"}, headers={"x-perms": constants.PERM_MANAGE}
    )
    assert res.status_code == 403
    assert await _stored(state) is None


async def test_settings_edit_without_manage_is_403(client, built):
    _, state = built
    res = await client.put(
        URL, json={"password": "s3cret"}, headers={"x-perms": constants.PERM_SETTINGS_EDIT}
    )
    assert res.status_code == 403
    assert await _stored(state) is None


def test_settings_edit_constant_matches_the_framework():
    from settings.constants import PERM_EDIT

    assert constants.PERM_SETTINGS_EDIT == PERM_EDIT


@pytest.mark.parametrize(
    "body", [{"password": ""}, {"password": "   "}, {}, {"password": "x" * 1025}]
)
async def test_put_invalid_is_422(client, built, body):
    _, state = built
    res = await client.put(URL, json=body, headers=MANAGE)
    assert res.status_code == 422
    assert await _stored(state) is None


async def test_put_lone_surrogate_is_422_not_a_500(client, built):
    _, state = built
    res = await client.put(
        URL,
        content=b'{"password": "ab\\ud800"}',
        headers={**MANAGE, "content-type": "application/json"},
    )
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_password"
    assert await _stored(state) is None


@pytest.mark.parametrize("secret", ["   \n ", "x" * 1025, "p" * 2000])
async def test_put_invalid_never_echoes_the_value(client, built, secret):
    res = await client.put(URL, json={"password": secret}, headers=MANAGE)
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_password"
    assert secret not in res.text
    assert secret.strip() not in res.text or not secret.strip()


async def test_generic_settings_screen_refuses_writes(client, built):
    _, state = built
    res = await client.put(
        f"/api/settings/modules/{constants.PACKAGE}",
        json={"smtp_password": "plain"},
        headers={"x-perms": "settings.edit"},
    )
    assert res.status_code == 409, res.text
    assert await _stored(state) is None


async def test_csrf_is_required_when_a_session_exists():
    app, state = await _build(session=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            token = (await c.get("/token")).json()["token"]
            assert token
            refused = await c.put(URL, json={"password": "pw"}, headers=MANAGE)
            assert refused.status_code == 403
            assert "CSRF" in refused.json()["detail"]
            assert await _stored(state) is None
            ok = await c.put(URL, json={"password": "pw"}, headers={**MANAGE, CSRF_HEADER: token})
            assert ok.status_code == 200, ok.text
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_multi_tenant_without_a_tenant_is_403_even_with_both_permissions():
    """Both permissions do not stand in for a tenant: nothing resolved, nothing stored."""
    both = {"x-perms": f"{constants.PERM_MANAGE},{constants.PERM_SETTINGS_EDIT}"}
    app, state = await _build(multi=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            res = await c.put(URL, json={"password": "pw"}, headers=both)
        assert res.status_code == 403
        assert res.json()["code"] == "tenant_required"
        assert await _stored(state) is None
    finally:
        await state.engine.dispose()
