"""Optional frame failures stay quiet and do not conceal application bugs."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from news.integrations import pagebuilder
from pagebuilder.contracts.public import TenantMismatchError
from sqlalchemy import text
from sqlalchemy.exc import InvalidRequestError, OperationalError

pytestmark = pytest.mark.asyncio


async def test_database_fallback_logs_no_sensitive_details_or_warnings(db, monkeypatch, caplog):
    error = OperationalError(
        "SELECT :secret", {"secret": "private-marker"}, Exception("db failure")
    )
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
    assert "private-marker" not in caplog.text
    assert all(record.levelno < logging.WARNING and record.exc_info is None for record in records)


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
