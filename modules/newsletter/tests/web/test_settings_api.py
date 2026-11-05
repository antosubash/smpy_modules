"""``GET`` / ``PUT /api/newsletter/settings``: the password is never returned,
and moving the relay clears it (R10)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from settings.service import SettingService
from settings.store import SettingsStore
from sm_newsletter.core import constants, crypto
from sm_newsletter.core.settings import NewsletterSettings

from tests.support.app import build_app as _build

URL = f"{constants.ROUTE_PREFIX_API}/settings"
PW_URL = f"{URL}/smtp-password"
BOTH = {"x-perms": f"{constants.PERM_MANAGE},{constants.PERM_SETTINGS_EDIT}"}
MANAGE_ONLY = {"x-perms": constants.PERM_MANAGE}


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


async def _overrides(state) -> dict:
    async with state.session_factory() as db:
        return await SettingsStore(SettingService(db)).get_overrides(constants.PACKAGE)


async def test_get_never_returns_password(client):
    await client.put(PW_URL, json={"password": "s3cret-pw"}, headers=BOTH)
    res = await client.get(URL, headers=MANAGE_ONLY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_password"] is True
    assert "smtp_password" not in body
    assert "s3cret-pw" not in res.text
    assert "enc:v1" not in res.text


async def test_get_requires_manage(client):
    assert (await client.get(URL, headers={"x-perms": "newsletter.view"})).status_code == 403


@pytest.mark.parametrize(
    "perms",
    [constants.PERM_MANAGE, constants.PERM_SETTINGS_EDIT, "newsletter.view", ""],
)
async def test_put_requires_both_perms(client, built, perms):
    _, state = built
    res = await client.put(URL, json={"daily_limit": 5}, headers={"x-perms": perms})
    assert res.status_code == 403
    assert await _overrides(state) == {}


async def test_host_change_clears_password(client, built):
    app, state = built
    await client.put(PW_URL, json={"password": "s3cret-pw"}, headers=BOTH)
    assert "smtp_password" in await _overrides(state)
    res = await client.put(URL, json={"smtp_host": "evil.example.net"}, headers=BOTH)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["password_cleared"] is True
    assert body["has_password"] is False
    assert body["smtp_host"] == "evil.example.net"
    assert "smtp_password" not in await _overrides(state)
    assert app.state.sm_newsletter.settings.smtp_password == ""


@pytest.mark.parametrize(
    "change",
    [{"smtp_port": 2525}, {"smtp_security": "tls"}, {"smtp_username": "other"}],
)
async def test_each_server_field_clears_password(client, change):
    await client.put(PW_URL, json={"password": "pw"}, headers=BOTH)
    res = await client.put(URL, json=change, headers=BOTH)
    assert res.json()["password_cleared"] is True


async def test_unrelated_change_keeps_password(client, built):
    _, state = built
    await client.put(PW_URL, json={"password": "s3cret-pw"}, headers=BOTH)
    res = await client.put(
        URL, json={"from_name": "Acme", "daily_limit": 100, "tracking_opens": False}, headers=BOTH
    )
    assert res.status_code == 200, res.text
    assert res.json()["password_cleared"] is False
    assert res.json()["has_password"] is True
    stored = (await _overrides(state))["smtp_password"][0]
    assert crypto.decrypt_value(stored, "smtp_password") == "s3cret-pw"


async def test_resending_the_same_server_keeps_password(client):
    await client.put(PW_URL, json={"password": "pw"}, headers=BOTH)
    host = (await client.get(URL, headers=MANAGE_ONLY)).json()["smtp_host"]
    res = await client.put(URL, json={"smtp_host": host}, headers=BOTH)
    assert res.json()["password_cleared"] is False
    assert res.json()["has_password"] is True


@pytest.mark.parametrize("port", [0, 70000, "x"])
async def test_invalid_port_422(client, built, port):
    _, state = built
    res = await client.put(URL, json={"smtp_port": port}, headers=BOTH)
    assert res.status_code == 422
    assert await _overrides(state) == {}


async def test_values_persist_and_hot_swap(client, built):
    app, state = built
    res = await client.put(
        URL,
        json={
            "transport": "console",
            "from_address": "news@example.org",
            "reply_to": "",
            "per_minute_limit": 7,
        },
        headers=BOTH,
    )
    assert res.status_code == 200, res.text
    live = app.state.sm_newsletter.settings
    assert live.transport == "console"
    assert live.from_address == "news@example.org"
    assert live.per_minute_limit == 7
    assert (await client.get(URL, headers=MANAGE_ONLY)).json()["per_minute_limit"] == 7
    assert (await _overrides(state))["per_minute_limit"][0] in (7, "7")


@pytest.mark.parametrize("extra", [{"smtp_password": "pw"}, {"nope": 1}])
async def test_unknown_and_password_keys_refused_without_echo(client, extra):
    res = await client.put(URL, json=extra, headers=BOTH)
    assert res.status_code == 422
    assert "pw" not in res.text.replace("smtp_password", "")


@pytest.mark.parametrize("field", ["from_name", "from_address", "reply_to"])
@pytest.mark.parametrize(
    "bad", ["a\r\nBcc: x@evil.test", "a\nb", "a\tb", "a\x00b", "a\u2028b", "a\x85b"]
)
async def test_put_refuses_control_chars_without_echo(client, built, field, bad):
    _, state = built
    res = await client.put(URL, json={field: bad}, headers=BOTH)
    assert res.status_code == 422
    assert "evil.test" not in res.text
    assert await _overrides(state) == {}


@pytest.mark.parametrize("field", ["from_name", "from_address", "reply_to"])
@pytest.mark.parametrize("bad", ["x\r\ny", "x\u2028y", "x\u2029y", "x\x85y"])
def test_model_refuses_control_chars(field, bad):
    with pytest.raises(ValueError, match=field):
        NewsletterSettings(**{field: bad})


async def test_password_write_cannot_slip_in_between_relay_read_and_write(
    client, built, monkeypatch
):
    """A password PUT racing a relay change must not commit inside the relay
    write's read-decide-write window, or the old password reaches the new host."""
    import asyncio

    import settings.reload as reload_mod

    app, state = built
    seen: dict = {}
    real = reload_mod.apply_changes_and_reload

    async def _racing(*args, **kwargs):
        # Called by the relay write after it decided from what it read.
        if "task" not in seen:
            seen["task"] = asyncio.ensure_future(
                client.put(PW_URL, json={"password": "raced-pw"}, headers=BOTH)
            )
            await asyncio.wait({seen["task"]}, timeout=0.5)
            seen["slipped"] = seen["task"].done()
        return await real(*args, **kwargs)

    monkeypatch.setattr(reload_mod, "apply_changes_and_reload", _racing)
    res = await client.put(URL, json={"smtp_host": "new.example.net"}, headers=BOTH)
    assert res.status_code == 200, res.text
    assert (await seen["task"]).status_code == 200
    assert seen["slipped"] is False
    assert app.state.sm_newsletter.settings.smtp_host == "new.example.net"
    # The password was written after the relay moved, for the new relay.
    assert "smtp_password" in await _overrides(state)


async def test_relay_change_clears_a_password_the_live_copy_lacks(client, built):
    """The decision reads the stored settings: a password the live copy does not
    show (written by another worker) is cleared too."""
    app, state = built
    await client.put(PW_URL, json={"password": "s3cret-pw"}, headers=BOTH)
    app.state.sm_newsletter.settings.smtp_password = ""  # a stale live copy
    res = await client.put(URL, json={"smtp_host": "other.example.net"}, headers=BOTH)
    assert res.status_code == 200, res.text
    assert res.json()["password_cleared"] is True
    assert "smtp_password" not in await _overrides(state)
