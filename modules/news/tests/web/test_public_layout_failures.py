"""Optional frame failures stay observable and do not conceal application bugs."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from news.integrations import pagebuilder
from pagebuilder.contracts.public import TenantMismatchError
from sqlalchemy import text
from sqlalchemy.exc import InvalidRequestError, OperationalError, ProgrammingError

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_layout_warning():
    pagebuilder._warn_layout_unavailable.cache_clear()
    yield
    pagebuilder._warn_layout_unavailable.cache_clear()


@pytest.mark.parametrize("error_type", [OperationalError, ProgrammingError])
async def test_database_fallback_warns_once_without_sensitive_details(
    db, monkeypatch, caplog, error_type
):
    error = error_type("SELECT :secret", {"secret": "private-marker"}, Exception("db failure"))
    contract = SimpleNamespace(public=SimpleNamespace(layout_props=AsyncMock(side_effect=error)))
    monkeypatch.setattr(pagebuilder, "_contract", lambda: contract)
    with caplog.at_level(logging.DEBUG, logger=pagebuilder.__name__):
        for _ in range(2):
            assert (
                await pagebuilder.public_layout_props(None, db, locale="en", tenant_id="default")
                == {}
            )
    assert await db.scalar(text("SELECT 1")) == 1
    records = [record for record in caplog.records if record.name == pagebuilder.__name__]
    assert records
    assert len([record for record in records if record.levelno == logging.WARNING]) == 1
    assert "private-marker" not in caplog.text
    assert "SELECT" not in caplog.text
    assert "db failure" not in caplog.text
    assert all(record.exc_info is None for record in records)


async def test_invalidated_connection_propagates_instead_of_returning_a_frame(db, monkeypatch):
    error = OperationalError("SELECT 1", {}, Exception("disconnect"), connection_invalidated=True)

    async def disconnected(*args, **kwargs):
        connection = await db.connection()
        await connection.invalidate()
        raise error

    contract = SimpleNamespace(public=SimpleNamespace(layout_props=disconnected))
    monkeypatch.setattr(pagebuilder, "_contract", lambda: contract)
    with pytest.raises(OperationalError) as caught:
        await pagebuilder.public_layout_props(None, db, locale="en", tenant_id="default")
    assert caught.value is error


@pytest.mark.parametrize(
    "error",
    [
        AttributeError("bug"),
        TypeError("bug"),
        InvalidRequestError("bad session use"),
        TenantMismatchError("wrong tenant"),
        asyncio.CancelledError(),
    ],
)
async def test_non_database_failures_propagate(db, monkeypatch, error):
    contract = SimpleNamespace(public=SimpleNamespace(layout_props=AsyncMock(side_effect=error)))
    monkeypatch.setattr(pagebuilder, "_contract", lambda: contract)
    with pytest.raises(type(error)):
        await pagebuilder.public_layout_props(None, db, locale="en", tenant_id="default")
    assert await db.scalar(text("SELECT 1")) == 1
