"""A stand-in CAPTCHA ``siteverify`` and the ``provider`` fixture that installs it.

Imported by ``conftest.py``, so the website-submission CAPTCHA suites share one
copy (importing a fixture into a test module trips ruff's redefinition rule).
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest
from sm_records.public_submissions import captcha


def _streamed(status: int, body: bytes, headers: dict | None = None) -> httpx.Response:
    """A response read the way a real transport hands it over: as a stream,
    which ``verify`` reads raw and bounded."""
    return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers or {})


class Provider:
    """A stand-in ``siteverify``: answers ``success`` for the response
    ``"good"``, and records what it was asked."""

    def __init__(
        self, *, status: int = 200, body: object = None, headers: dict | None = None
    ) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.asked: list[tuple[str, dict[str, list[str]]]] = []
        self.encodings: list[str | None] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        self.asked.append((str(request.url), form))
        self.encodings.append(request.headers.get("accept-encoding"))
        if isinstance(self.body, bytes):
            return _streamed(self.status, self.body, self.headers)
        if self.body is not None:
            return _streamed(self.status, str(self.body).encode())
        verdict = {"success": form.get("response") == ["good"]}
        return _streamed(self.status, json.dumps(verdict).encode())


@pytest.fixture
def provider(monkeypatch) -> Provider:
    fake = Provider()
    monkeypatch.setattr(
        captcha,
        "client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
    )
    return fake
