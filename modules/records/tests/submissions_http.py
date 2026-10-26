"""An app that accepts website submissions, and the calls a form makes (#101).

``site`` is the ordinary harness plus what a real host supplies and the
harness does not: a ``secret_key`` to sign with, a ``public_base_url`` for
mail links, and a mail sender that delivers — :class:`Outbox`, which keeps
every message. Settings drop the minimum fill time so a test can load and
send in one breath; the tests of that rule set it back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_core.mail import MailMessage, install_mail_sender
from sm_records import _pattern_worker, constants
from sm_records.public_submissions import mail_runner
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, build_app, roles
from tests.public_submissions_support import create, form_config

SUBMISSIONS = constants.PUBLIC_SUBMISSIONS_API_PREFIX.rstrip("/")
ORIGIN = "http://test"
BASE_URL = "https://site.example"
JSON = {"Origin": ORIGIN, "Content-Type": "application/json"}


class Outbox:
    """A sender that delivers — into a list."""

    delivers_email = True

    def __init__(self) -> None:
        self.sent: list[MailMessage] = []
        self.fail = False
        self.fail_for: set[str] = set()

    async def send(self, message: MailMessage) -> None:
        if self.fail or message.to in self.fail_for:
            raise OSError("smtp is down")
        self.sent.append(message)


def configure(client: AsyncClient, **overrides: Any) -> RecordsSettings:
    """Replace the app's settings (what a Settings-screen save does)."""
    settings = RecordsSettings(**{"public_submissions_min_fill_seconds": 0, **overrides})
    getattr(client.app.state, constants.PACKAGE).settings = settings  # type: ignore[attr-defined]
    return settings


def host_parts(app: Any, *, base_url: str = BASE_URL) -> None:
    app.state.sm.settings = SimpleNamespace(secret_key="submissions-test-secret")
    app.state.host = SimpleNamespace(
        settings=SimpleNamespace(public_base_url=base_url, i18n_default_locale="en")
    )


async def _settle_mail(_response: Any) -> None:
    """Finish the mail a request spawned before the test sends the next one.

    The after-commit send (``mail_runner._spawn``) opens its own session, and
    in production that is its own pooled connection. Here every session shares
    the one ``StaticPool`` connection to ``:memory:``, so a send still running
    while the next request commits interleaves two transactions on one sqlite3
    handle: "cannot commit transaction - SQL statements in progress" (#262).
    """
    await mail_runner.drain()


@pytest_asyncio.fixture
async def site(tmp_path) -> AsyncIterator[AsyncClient]:
    app, db_state = await build_app(tmp_path)
    host_parts(app)
    outbox = Outbox()
    install_mail_sender(outbox)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=ORIGIN,
            event_hooks={"response": [_settle_mail]},
        ) as client:
            client.app = app  # type: ignore[attr-defined]
            client.db_state = db_state  # type: ignore[attr-defined]
            client.outbox = outbox  # type: ignore[attr-defined]
            configure(client)
            yield client
            await mail_runner.drain()
    finally:
        install_mail_sender(None)
        await _pattern_worker.close()
        await db_state.engine.dispose()


async def contact_type(client: AsyncClient, key: str = "contact", **config: Any) -> dict:
    """A contact-form type that accepts submissions and notifies one address."""
    body = form_config(**{"enabled": True, "notify_to": ["ops@example.org"], **config})
    resp = await create(client, key, config=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def load(client: AsyncClient, key: str = "contact", **headers: str) -> dict:
    resp = await client.get(f"{SUBMISSIONS}/{key}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def send(
    client: AsyncClient,
    key: str = "contact",
    data: dict[str, Any] | None = None,
    *,
    token: str | None = None,
    headers: dict[str, str] | None = None,
    **body: Any,
):
    """``POST …/submit`` as a form would, loading a token first if none given."""
    if token is None:
        token = (await load(client, key))["token"]
    payload = {
        "data": {"name": "Ada", "email": "Ada@Example.org ", "message": "Hello"}
        if data is None
        else data,
        "token": token,
        **body,
    }
    response = await client.post(
        f"{SUBMISSIONS}/{key}/submit", json=payload, headers={**JSON, **(headers or {})}
    )
    await mail_runner.drain()
    return response


async def records_of(
    client: AsyncClient, key: str = "contact", *, trashed: bool = False, as_: str = ADMIN
) -> list:
    query = "?trashed=true" if trashed else ""
    resp = await client.get(f"/api/records/types/{key}/records{query}", headers=roles(as_))
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]
