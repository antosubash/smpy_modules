#!/usr/bin/env python
"""Smoke-test images and newsletter through a real broker, worker and beat (#339).

Every e2e spec runs Celery eager (``tests/e2e/start-test-server.sh``), so the
path production uses - task arguments serialised onto Redis, queue routing, a
worker that never builds the app and reads its settings from the database,
beat's schedule - is otherwise covered by unit tests only. This drives it over
HTTP against a host started **non-eager**, with one worker serving the
``images``, ``newsletter`` and ``celery`` queues and one beat:

1. upload an image and wait until its pipeline (``exif``, ``renditions``)
   settles, every step ``completed`` or ``skipped`` and a thumbnail published;
2. import one subscriber (``newsletter.run_import`` on the worker), schedule a
   campaign to send now on the console transport, and wait until the
   ``newsletter.dispatch`` beat (every minute) has marked it ``sent``.

It sets nothing up itself beyond what an admin would through the API: the
host, worker and beat must already run, the newsletter settings (console
transport, sender, postal address) must have been written before the worker
started (it caches them), and the bootstrap admin must exist. CI's
``Background tasks (Redis + Celery worker)`` job does all of that.

    uv run python scripts/bg_tasks_smoke.py --base-url http://127.0.0.1:8000

Exits 0 when both settle, 1 with the last state seen otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "modules" / "images" / "tests" / "fixtures" / "rotated.jpg"
_PAGE_JSON = re.compile(r'<script data-page="app" type="application/json">([^<]*)</script>')
_SETTLED = {"completed", "skipped"}


class SmokeError(Exception):
    """A step did not reach the state it should; the message says what was seen."""


def _check(res: httpx.Response, *expected: int) -> Any:
    if res.status_code not in expected:
        raise SmokeError(
            f"{res.request.method} {res.request.url.path}: {res.status_code} {res.text}"
        )
    return res.json() if res.content else None


def _poll(what: str, fetch: Callable[[], Any], done: Callable[[Any], bool], timeout: float) -> Any:
    """``fetch()`` every 2 s until ``done`` holds for it; raise after ``timeout``."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = fetch()
        if done(last):
            return last
        time.sleep(2)
    raise SmokeError(
        f"{what}: not reached within {timeout:.0f} s; last seen {json.dumps(last, default=str)}"
    )


def wait_until_up(client: httpx.Client, timeout: float) -> None:
    def live() -> bool:
        try:
            return client.get("/health/live").status_code == 200
        except httpx.TransportError:
            return False

    _poll("host /health/live", live, bool, timeout)


def sign_in(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    """A session cookie, then the session's CSRF token from a console page's props."""
    # A native client (no Origin, Referer or CSRF header) signs in without a token.
    _check(
        client.post("/api/users/auth/login", data={"username": email, "password": password}), 204
    )
    page = client.get("/admin/newsletter/")
    match = _PAGE_JSON.search(page.text)
    if page.status_code != 200 or not match:
        raise SmokeError(f"no Inertia page on /admin/newsletter/ ({page.status_code})")
    token = json.loads(match.group(1)).get("props", {}).get("csrfToken")
    if not token:
        raise SmokeError("no csrfToken prop on /admin/newsletter/")
    return {"X-CSRF-Token": token}


def image_settles(client: httpx.Client, csrf: dict[str, str], timeout: float) -> dict[str, Any]:
    collection = _check(
        client.post(
            "/api/images/collections",
            headers=csrf,
            json={"name": f"bg smoke {uuid.uuid4().hex[:8]}", "visibility": "private"},
        ),
        201,
    )
    with FIXTURE.open("rb") as fh:
        batch = _check(
            client.post(
                f"/api/images/collections/{collection['id']}/images",
                headers=csrf,
                files={"files": (FIXTURE.name, fh, "image/jpeg")},
            ),
            200,
        )
    (uploaded,) = batch["results"]
    if uploaded["status"] != "created":
        raise SmokeError(f"upload refused: {uploaded}")

    def fetch() -> dict[str, Any]:
        return _check(client.get(f"/api/images/images/{uploaded['id']}"), 200)

    def settled(image: dict[str, Any]) -> bool:
        runs = image.get("step_runs") or []
        failed = [r for r in runs if r["status"] == "failed"]
        if failed:
            raise SmokeError(f"pipeline step failed: {failed}")
        return (
            bool(runs) and all(r["status"] in _SETTLED for r in runs) and bool(image["thumb_url"])
        )

    image = _poll("image pipeline settled", fetch, settled, timeout)
    return {"id": image["id"], "steps": {r["step"]: r["status"] for r in image["step_runs"]}}


def _mailchimp_csv(email: str) -> bytes:
    return f'"Email Address","First Name","Last Name","TAGS"\n"{email}","Smoke","",""\n'.encode()


def campaign_sends(client: httpx.Client, csrf: dict[str, str], timeout: float) -> dict[str, Any]:
    api = "/api/newsletter"
    settings = _check(client.get(f"{api}/settings"), 200)
    if settings.get("transport") != "console":
        raise SmokeError(f"newsletter transport is {settings.get('transport')!r}, not 'console'")

    rand = uuid.uuid4().hex[:8]
    key = _check(
        client.post(
            f"{api}/lists",
            headers=csrf,
            json={"key": f"bg_smoke_{rand}", "label": f"BG smoke {rand}"},
        ),
        201,
    )["key"]
    staged = _check(
        client.post(
            f"{api}/imports",
            headers=csrf,
            data={"list": key},
            files={
                "files": (
                    "subscribed_members_export_smoke.csv",
                    _mailchimp_csv(f"smoke-{rand}@example.org"),
                    "text/csv",
                )
            },
        ),
        201,
    )
    _check(client.post(f"{api}/imports/{staged['id']}/apply", headers=csrf), 202)
    job = _poll(
        "subscriber import (newsletter.run_import) done",
        lambda: _check(client.get(f"{api}/imports/{staged['id']}"), 200),
        lambda j: j["status"] in {"done", "failed"},
        120,
    )
    if job["status"] != "done" or job["created"] != 1:
        raise SmokeError(f"import did not create the subscriber: {job}")

    draft = _check(
        client.post(
            f"{api}/campaigns",
            headers=csrf,
            json={"name": f"BG smoke {rand}", "list_type_key": key, "subject": f"BG smoke {rand}"},
        ),
        201,
    )
    body = [{"type": "Divider", "props": {"id": "a"}}]
    draft = _check(
        client.patch(
            f"{api}/campaigns/{draft['id']}",
            headers=csrf,
            json={"expected_revision": draft["revision"], "body": body},
        ),
        200,
    )
    scheduled = _check(
        client.post(
            f"{api}/campaigns/{draft['id']}/send",
            headers=csrf,
            json={"expected_revision": draft["revision"]},
        ),
        200,
    )
    if scheduled["status"] != "scheduled":
        raise SmokeError(f"campaign not scheduled: {scheduled['status']}")

    def fetch() -> dict[str, Any]:
        return _check(client.get(f"{api}/campaigns/{draft['id']}/progress"), 200)

    def sent(p: dict[str, Any]) -> bool:
        if p["status"] in {"paused", "cancelled"}:
            raise SmokeError(f"campaign stopped: {p}")
        return p["status"] == "sent"

    final = _poll("campaign sent by the newsletter.dispatch beat", fetch, sent, timeout)
    if final["sent"] != 1 or final["queued"] != 0:
        raise SmokeError(f"campaign sent, but not to its one subscriber: {final}")
    return {"id": draft["id"], "progress": final}


def _timed(label: str, run: Callable[[], dict[str, Any]]) -> None:
    started = time.monotonic()
    result = run()
    print(
        f"ok  {label} in {time.monotonic() - started:.1f} s: {json.dumps(result, default=str)}",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--password", default="changeme1")
    parser.add_argument("--image-timeout", type=float, default=180)
    parser.add_argument("--campaign-timeout", type=float, default=240)
    args = parser.parse_args(argv)

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        try:
            wait_until_up(client, 120)
            csrf = sign_in(client, args.email, args.password)
            _timed(
                "image pipeline settled", lambda: image_settles(client, csrf, args.image_timeout)
            )
            _timed("campaign sent", lambda: campaign_sends(client, csrf, args.campaign_timeout))
        except SmokeError as exc:
            print(f"FAIL {exc}", file=sys.stderr, flush=True)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
