"""Fixtures for the test-send tests: the scripted aiosmtpd relay (the SMTP
path) and ``built``."""

import pytest_asyncio

from tests.sending.conftest import (  # noqa: F401 - re-exported fixtures
    client_tls,
    make_transport,
    relay,
    tls_files,
)
from tests.support.sending import make_app


@pytest_asyncio.fixture
async def built():
    app, state, cid = await make_app()
    yield app, state, cid
    await state.engine.dispose()
