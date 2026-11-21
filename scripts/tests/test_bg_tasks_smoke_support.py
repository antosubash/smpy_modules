"""The smoke scripts share helpers through one module, with no import cycle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import bg_tasks_smoke_support as support  # noqa: E402


@pytest.mark.parametrize(
    "first", ["bg_tasks_smoke", "bg_tasks_smoke_events", "bg_tasks_smoke_support"]
)
def test_each_script_imports_alone_in_a_fresh_interpreter(first: str) -> None:
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import {first}",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr[-600:]


def test_the_helpers_are_public_and_the_scripts_use_them_not_each_other() -> None:
    for name in ("bg_tasks_smoke.py", "bg_tasks_smoke_events.py"):
        source = (SCRIPTS / name).read_text()
        assert "import _check" not in source and "_poll" not in source, name
    events = (SCRIPTS / "bg_tasks_smoke_events.py").read_text()
    assert "from bg_tasks_smoke import" not in events


def _client(status: int, body: object) -> httpx.Response:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    with httpx.Client(transport=transport, base_url="http://t") as client:
        return client.get("/x")


def test_check_returns_the_json_or_says_what_was_seen() -> None:
    assert support.check(_client(200, {"a": 1}), 200) == {"a": 1}
    with pytest.raises(support.SmokeError, match="GET /x: 500"):
        support.check(_client(500, {"detail": "boom"}), 200)


def test_poll_returns_when_done_and_raises_with_the_last_value(monkeypatch) -> None:
    monkeypatch.setattr(support.time, "sleep", lambda _s: None)
    seen = iter([1, 2, 3])
    assert support.poll("counter", lambda: next(seen), lambda v: v == 3, 5) == 3
    with pytest.raises(support.SmokeError, match="never: not reached within 0 s; last seen 7"):
        support.poll("never", lambda: 7, lambda v: False, 0.01)


def test_the_events_step_refuses_a_public_address_from_the_environment() -> None:
    import bg_tasks_smoke_events as events

    events.require_database_only({})
    with pytest.raises(support.SmokeError, match="SM_PUBLIC_BASE_URL is set"):
        events.require_database_only({"SM_PUBLIC_BASE_URL": "http://x"})
