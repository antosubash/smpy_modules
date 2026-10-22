"""The connection's ``return_base_url``: what is stored, and what is refused."""

from __future__ import annotations

import pytest
from api_helpers import arm_csrf
from sm_billing.admin import connection_changes
from sm_billing.errors import BillingError
from sm_billing.schemas import ConnectionIn

ADMIN = "/api/billing/admin"


@pytest.fixture
async def admin(authenticated_client):
    await arm_csrf(authenticated_client, "/admin/billing/plans")
    return authenticated_client


# ── return_base_url ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("", ""),
        ("   ", ""),
        ("https://app.example.com", "https://app.example.com"),
        ("https://app.example.com/", "https://app.example.com"),
        (" http://localhost:8000/ ", "http://localhost:8000"),
    ],
)
def test_return_url_accepted(raw, stored):
    assert connection_changes(ConnectionIn(return_base_url=raw))["return_base_url"] == stored


@pytest.mark.parametrize(
    "raw",
    [
        "not a url",
        "javascript:alert(1)",
        "ftp://example.com",
        "https://",
        "https://app.example.com/billing",
        "https://app.example.com/?x=1",
        "https://app.example.com/#top",
        "https://user:pw@app.example.com",
        "https://app example.com",
        "https://a.example.com/" + "x" * 300,
        "https://" + "a" * 250 + ".com",
        # urlsplit silently drops these, so they must be refused before parsing.
        "https://exa\nmple.com",
        "https://exa\tmple.com",
        "https://example.com\x00",
    ],
)
def test_return_url_rejected(raw):
    with pytest.raises(BillingError) as exc:
        connection_changes(ConnectionIn(return_base_url=raw))
    assert (exc.value.code, exc.value.status_code) == ("invalid_return_url", 400)
    assert "http" in exc.value.extra["message"]


@pytest.mark.parametrize("raw", ["not a url", "javascript:alert(1)", "https://x.io/" + "a" * 300])
async def test_return_url_rejected_over_http(app, admin, raw):
    response = await admin.put(f"{ADMIN}/connection", json={"return_base_url": raw})
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "invalid_return_url"
    assert response.json()["message"]
    assert app.state.sm_billing.settings.return_base_url == ""
