"""The events step of ``bg_tasks_smoke.py``: a reminder mailed by the real beat.

Follow an event that starts in 16 minutes with the 15-minute lead and wait until the
``events.reminders`` beat has mailed it exactly once (the Delivery card's counts: one more
``sent``, nothing failed or unfinished). It needs a mail sender that really delivers (CI points
the mail module's SMTP backend at a local ``aiosmtpd`` sink) and the host's public address
**stored in the database** (``host.public_base_url``): the smoke refuses to run with
``SM_PUBLIC_BASE_URL`` in its environment, because the variable would make a worker that never
reads the database pass.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from bg_tasks_smoke_support import SmokeError, check, poll


def require_database_only(environ: Mapping[str, str] = os.environ) -> None:
    """The smoke proves the database-only configuration; the env var would mask a worker that
    cannot read the stored address."""
    if environ.get("SM_PUBLIC_BASE_URL"):
        raise SmokeError(
            "SM_PUBLIC_BASE_URL is set: store host.public_base_url in the database instead"
        )


def reminder_sent(client: httpx.Client, csrf: dict[str, str], timeout: float) -> dict[str, Any]:
    require_database_only()
    api = "/api/events"
    rand = uuid.uuid4().hex[:8]
    status = check(client.get(f"{api}/reminders/status"), 200)
    if not status["available"]:
        why = check(client.get(f"{api}/reminders/delivery"), 200)["reason"]
        raise SmokeError(f"reminders are not available: {why}")
    calendar = check(
        client.post(
            f"{api}/calendars",
            headers=csrf,
            json={"name": f"BG smoke {rand}", "visibility": "internal"},
        ),
        201,
    )
    start = datetime.now(UTC) + timedelta(minutes=16)
    stamp = "%Y-%m-%dT%H:%M"
    event = check(
        client.post(
            f"{api}/events",
            headers=csrf,
            json={
                "calendar_id": calendar["id"],
                "times": {
                    "timezone": "UTC",
                    "start": start.strftime(stamp),
                    "end": (start + timedelta(hours=1)).strftime(stamp),
                },
                "texts": {"en": {"title": f"BG smoke {rand}"}},
            },
        ),
        201,
    )
    published = check(
        client.post(
            f"{api}/events/{event['id']}/approve",
            headers=csrf,
            json={"expected_revision": event["revision"]},
        ),
        200,
    )
    if published["status"] != "published":
        raise SmokeError(f"event not published: {published['status']}")
    follow = check(
        client.put(f"{api}/events/{event['id']}/follow", headers=csrf, json={"leads": [15]}), 200
    )
    if not follow["deliverable"]:
        raise SmokeError(f"the worker could not remind this account: {follow}")

    def counts() -> dict[str, Any]:
        return check(client.get(f"{api}/reminders/delivery"), 200)["counts"]

    before = counts()["sent"]  # a re-run on the same database starts from what is already there

    def done(c: dict[str, Any]) -> bool:
        if c["failed"]:
            raise SmokeError(f"a reminder failed: {c}")
        return c["sent"] > before

    final = poll("reminder mailed by the events.reminders beat", counts, done, timeout)
    if final["sent"] != before + 1 or final["unfinished"]:
        raise SmokeError(f"expected exactly one new reminder, sent cleanly: {final}")
    return {"event": event["id"], "counts": final}
