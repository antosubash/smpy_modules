"""Helpers the background-tasks smoke scripts share (``bg_tasks_smoke.py`` and the per-module
steps such as ``bg_tasks_smoke_events.py``), so neither imports the other."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

__all__ = ["SmokeError", "check", "poll"]


class SmokeError(Exception):
    """A step did not reach the state it should; the message says what was seen."""


def check(res: httpx.Response, *expected: int) -> Any:
    if res.status_code not in expected:
        raise SmokeError(
            f"{res.request.method} {res.request.url.path}: {res.status_code} {res.text}"
        )
    return res.json() if res.content else None


def poll(what: str, fetch: Callable[[], Any], done: Callable[[Any], bool], timeout: float) -> Any:
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
