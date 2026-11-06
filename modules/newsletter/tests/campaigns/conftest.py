"""Fixtures for the test-send tests: the scripted aiosmtpd relay (the SMTP
path), an empty console outbox around every test, and ``built``."""

import pytest
import pytest_asyncio
from sm_newsletter.sending.transport import console

from tests.sending.conftest import (  # noqa: F401 - re-exported fixtures
    client_tls,
    make_transport,
    relay,
    tls_files,
)
from tests.support.sending import make_app


@pytest.fixture(autouse=True)
def _empty_outbox():
    console._outbox.clear()
    yield
    console._outbox.clear()


@pytest_asyncio.fixture
async def built():
    app, state, cid = await make_app()
    yield app, state, cid
    await state.engine.dispose()
