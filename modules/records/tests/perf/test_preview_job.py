"""``POST /schema/preview`` synchronous against deferred — F10.

The measurement that matters is not "how long does the scan take" (that is
``test_schema_ops.test_dry_run_restrictive``, and the answer must not change)
but **how long the caller waits**. In this harness the two are the same number
by construction: ``DeferredJobsMiddleware`` drains the job after the response
has been sent but before the ASGI call returns, so an HTTP client measuring
round-trip time would see the deferred path take exactly as long as the
synchronous one and learn nothing.

``_StartTimer`` is the fix: an ASGI wrapper *outside* the whole middleware
stack that stamps the moment ``http.response.start`` goes out. Time-to-that is
what a real client waits; time-to-return is the whole operation including the
scan. Both are recorded, and the pair is the finding.
"""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient
from sm_records.settings import RecordsSettings

from tests.app_harness import build_app
from tests.perf._bench import Results, Timing
from tests.perf._http import HEADERS
from tests.perf.conftest import load_type, type_counts

pytestmark = pytest.mark.perf

_API = "/api/records/types"


class _StartTimer:
    """Outermost ASGI wrapper: records when the response line was sent."""

    def __init__(self, app) -> None:
        self.app = app
        self.started_at: float | None = None

    async def __call__(self, scope, receive, send) -> None:
        self.started_at = None

        async def _send(message):
            if message["type"] == "http.response.start" and self.started_at is None:
                self.started_at = time.perf_counter()
            await send(message)

        await self.app(scope, receive, _send)


def _restrictive(rtype) -> list[dict]:
    """``order.gift`` becomes required — the change ``test_schema_ops`` uses,
    so the two files measure the same scan."""
    raw = [dict(field) for field in (rtype.fields or [])]
    for field in raw:
        if field["key"] == "gift":
            field["required"] = True
    return raw


async def _post_preview(client, timer, fields) -> tuple[int, float, float]:
    """``(status, ms to the response line, ms to the whole call)``."""
    began = time.perf_counter()
    response = await client.post(
        f"{_API}/order/schema/preview", json={"fields": fields}, headers=HEADERS
    )
    finished = time.perf_counter()
    assert timer.started_at is not None
    return (
        response.status_code,
        (timer.started_at - began) * 1000.0,
        (finished - began) * 1000.0,
    )


async def test_preview_sync_against_deferred(perf_db, perf_session, tmp_path):
    counts = await type_counts(perf_session)
    n = counts.get("order", 0)
    rtype = await load_type(perf_session, "order")
    fields = _restrictive(rtype)

    app, _ = await build_app(tmp_path, perf_db)
    timer = _StartTimer(app)
    async with AsyncClient(transport=ASGITransport(app=timer), base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]

        # Before: the whole scan inside the request, whatever the type holds.
        app.state.sm_records.settings = RecordsSettings(preview_sync_limit=10**9)
        status, to_line, whole = await _post_preview(client, timer, fields)
        assert status == 200
        Results.add("POST /schema/preview, synchronous (time to response)", n, Timing([to_line]))
        Results.add("POST /schema/preview, synchronous (total)", n, Timing([whole]))

        # After: a 202 and a job, on the same type and the same change.
        app.state.sm_records.settings = RecordsSettings(preview_sync_limit=max(n // 3, 0))
        status, to_line, whole = await _post_preview(client, timer, fields)
        assert status == 202
        Results.add("POST /schema/preview, deferred (time to 202)", n, Timing([to_line]))
        Results.add("POST /schema/preview, deferred (total incl. scan)", n, Timing([whole]))

    Results.note(
        "preview: the deferred total is the synchronous total plus the job registry; "
        "what changes is when the caller is answered, not what the scan costs"
    )
