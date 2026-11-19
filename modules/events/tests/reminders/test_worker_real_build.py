"""The headless build for real: the framework's own factory, in a fresh isolated process.

``create_app`` finds the consuming host's templates from the framework's project root (the
directory the process runs in, as for ``make worker``), so these run from the project root, which
is the one thing a headless build needs from its host. Nothing here imports a host package: the
script runs with ``-I`` (no cwd, no ``PYTHONPATH``) and checks that none was loaded."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

BUILD = textwrap.dedent(
    """
    import sys
    from sm_events.reminders import worker_app
    app = worker_app._create_app(worker_app._settings())
    from simple_module_core.app_state import get_services
    from simple_module_core.user_directory import NullUserDirectory, get_user_directory
    registry = get_services(app).permissions
    print("RESULT directory_is_real", not isinstance(get_user_directory(app), NullUserDirectory))
    print("RESULT has_membership_store", getattr(app.state, "tenant_members", None) is not None)
    print("RESULT events_view_mapped", "events.view" in registry.all_permissions)
    print("RESULT base_url_attr", hasattr(app.state.sm.settings, "public_base_url"))
    print("RESULT host_package_imported", "main" in sys.modules or "host" in sys.modules)
    """
)


ROOT = Path(__file__).resolve().parents[4]
"""The project root this suite runs the host from."""


def _run(code: str, tmp_path, **env):
    import os

    base = {k: v for k, v in os.environ.items() if not k.startswith("SM_")}
    base.update(
        {"SM_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/scratch.db"},
        SM_ENVIRONMENT="development",
    )
    base.update(env)
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=ROOT,
        env=base,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def test_the_framework_factory_builds_the_app_without_a_host_package(tmp_path):
    done = _run(BUILD, tmp_path, SM_SECRET_KEY="a-key-for-this-test-only-0123456789abcdef")
    assert done.returncode == 0, done.stderr[-2000:]
    out = dict(
        line.split(" ")[1:3] for line in done.stdout.splitlines() if line.startswith("RESULT ")
    )
    assert out["directory_is_real"] == "True"
    assert out["has_membership_store"] == "True"
    assert out["events_view_mapped"] == "True"
    assert out["base_url_attr"] == "True"
    assert out["host_package_imported"] == "False"


def test_without_a_provisioned_key_nothing_is_built_or_written(tmp_path):
    code = textwrap.dedent(
        """
        from sm_events.reminders import worker_app
        try:
            worker_app._settings()
        except worker_app.NoSecretKey:
            print("refused")
        """
    )
    done = _run(code, tmp_path)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "refused"
    import sqlite3

    scratch = tmp_path / "scratch.db"  # opened to look for a key; nothing may be created in it
    assert (
        not scratch.exists()
        or not sqlite3.connect(scratch).execute("select name from sqlite_master").fetchall()
    )


@pytest.mark.parametrize("bad", ["not a url"])
def test_an_unusable_host_degrades_to_unavailable_not_a_crash(tmp_path, bad):
    code = textwrap.dedent(
        """
        import asyncio
        from sm_events.reminders import worker_app
        class Db:  # the overlay replay is never reached when the build fails
            pass
        print(asyncio.run(worker_app.worker_runtime(Db())), worker_app.worker_runtime_supported())
        """
    )
    done = _run(code, tmp_path, SM_DATABASE_URL=bad)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.split()[-2:] == ["None", "False"]
