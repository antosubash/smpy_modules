"""The subscription address as a secret: sealed at rest, masked everywhere else."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from simple_module_core.module_settings import ModuleSettingsRegistry
from sm_events.core import crypto
from sm_events.core.clock import utcnow
from sm_events.feeds.subscriptions import urls
from sm_events.models import Calendar, Subscription
from sm_events.module import EventsModule
from sqlalchemy import text

URL = "https://calendar.google.com/calendar/ical/x%40group/private-abc123/basic.ics"


def test_seal_round_trip():
    stored = urls.seal(URL)
    assert stored.startswith("enc:v2:")
    assert URL not in stored
    assert urls.unseal(stored) == URL


async def test_url_column_is_ciphertext(db):
    cal = Calendar(slug="t", name="T", owner_id="o")
    db.add(cal)
    await db.flush()
    db.add(
        Subscription(
            calendar_id=cal.id,
            created_by="o",
            url_enc=urls.seal(URL),
            url_display=urls.display_of(URL),
            label="Work",
            next_fetch_at=utcnow(),
        )
    )
    await db.flush()
    raw = (await db.execute(text("SELECT url_enc, url_display FROM events_subscription"))).one()
    assert raw[0].startswith("enc:v2:")
    for piece in ("private-abc123", "basic.ics", "x%40group", "ical"):
        assert piece not in raw[0]
        assert piece not in raw[1]
    assert raw[1] == "https://calendar.google.com/…"


def test_unseal_with_previous_key(monkeypatch):
    monkeypatch.setattr(crypto, "_secret_provider", lambda: "the-old-key")
    stored = urls.seal(URL)
    monkeypatch.setattr(crypto, "_secret_provider", lambda: "the-new-key")
    with pytest.raises(urls.UrlUnreadable):
        urls.unseal(stored)  # no previous key configured: closed
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "the-old-key")
    assert urls.unseal(stored) == URL
    # a list of keys, the old one among them
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", '["unrelated", "the-old-key"]')
    assert urls.unseal(stored) == URL


@pytest.mark.parametrize(
    "stored",
    [
        "enc:v9:abcdef",
        "enc:v2:not-a-token",
        "",
        "https://calendar.example/plain-text-is-never-a-sealed-value",
        "plaintext",
    ],
)
def test_unseal_unreadable(stored):
    with pytest.raises(urls.UrlUnreadable) as caught:
        urls.unseal(stored)
    assert "calendar.example" not in str(caught.value) + repr(caught.value)


def test_unseal_wrong_key(monkeypatch):
    stored = urls.seal(URL)
    monkeypatch.setattr(crypto, "_secret_provider", lambda: "another-secret")
    with pytest.raises(urls.UrlUnreadable) as caught:
        urls.unseal(stored)
    assert URL not in str(caught.value)


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        (URL, "https://calendar.google.com/…"),
        ("http://10.0.0.5:8080/a?token=t", "http://10.0.0.5:8080/…"),
        ("https://xn--bcher-kva.example/feed.ics", "https://xn--bcher-kva.example/…"),
        ("https://bücher.example/feed.ics?k=secret", "https://xn--bcher-kva.example/…"),
        ("https://cal.example:443/x", "https://cal.example/…"),
        ("http://cal.example:80/x", "http://cal.example/…"),
        ("https://cal.example:8443/x#frag", "https://cal.example:8443/…"),
        ("https://[2001:db8::1]:8443/secret", "https://[2001:db8::1]:8443/…"),
        ("https://u:p@cal.example/secret", "https://cal.example/…"),
        ("https://CAL.Example/Path", "https://cal.example/…"),
    ],
)
def test_display_of(url, shown):
    assert urls.display_of(url) == shown


def test_display_of_never_carries_path_query_or_credentials():
    shown = urls.display_of("https://user:pw@cal.example/p/SECRET?token=SECRET2#SECRET3")
    for secret in ("SECRET", "pw", "user", "token"):
        assert secret not in shown


def test_worker_fallback_reads_env_secret(monkeypatch):
    """A Celery worker builds no app: the secret comes from the environment."""
    monkeypatch.setattr(crypto, "_secret_provider", None)
    monkeypatch.setenv("SM_SECRET_KEY", "worker-secret")
    stored = urls.seal(URL)
    monkeypatch.setattr(crypto, "_secret_provider", lambda: "worker-secret")
    assert urls.unseal(stored) == URL


def test_no_secret_anywhere_refuses_with_a_message_that_names_no_value(monkeypatch):
    monkeypatch.setattr(crypto, "_secret_provider", None)
    monkeypatch.delenv("SM_SECRET_KEY", raising=False)
    monkeypatch.setattr(crypto, "_dotenv_secret", lambda: "")
    with pytest.raises(RuntimeError, match="SM_SECRET_KEY"):
        urls.seal(URL)


def test_the_module_installs_the_apps_secret():
    module = EventsModule()
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module.register_settings(app)
    app.state.sm = SimpleNamespace(settings=SimpleNamespace(secret_key="the-live-secret"))
    assert crypto._secret_provider is not None
    assert crypto._secret_provider() == "the-live-secret"
