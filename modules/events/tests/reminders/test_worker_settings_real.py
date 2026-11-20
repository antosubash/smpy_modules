"""The worker reads host settings from the database, per tick, through the REAL headless app.

A ``host.public_base_url`` saved on the Settings screen lives only in the database. The worker's
app has no lifespan, so nothing hydrated its runtime host fields: it saw ``""`` while the web
process (hydrated, and reloaded on every save) said reminders were available. A tick now reads the
stored settings before it builds its runtime, so the two cannot disagree, and a change reaches the
next tick without restarting the worker. Subprocesses, from the project root, on a migrated
scratch database, with no ``SM_PUBLIC_BASE_URL`` in the environment."""

from __future__ import annotations

import subprocess
import sys
import textwrap

from tests.reminders.test_worker_real_build import ROOT, _run

KEY = "a-key-for-this-test-only-0123456789abcdef"


def _set(db: str, value: str) -> None:
    done = _run(
        "import sys, runpy; sys.argv = ['set_setting.py', 'host', 'public_base_url', "
        f"{value!r}]; sys.path.insert(0, 'scripts'); "
        "runpy.run_path('scripts/set_setting.py', run_name='__main__')",
        db,
        SM_SECRET_KEY=KEY,
    )
    assert done.returncode == 0, done.stderr[-1500:]


def _migrate(tmp_path):
    env = {
        "SM_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/scratch.db",
        "SM_ENVIRONMENT": "development",
        "SM_SECRET_KEY": KEY,
        "PATH": "/usr/bin:/bin",
    }
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-1500:]


READ = textwrap.dedent(
    """
    import asyncio, subprocess, sys
    from sm_events.core.host_settings import public_base_url
    from sm_events.core.worker import worker_session_factory
    from sm_events.reminders import worker_app

    def put(package, field, value):
        code = (
            f"import sys, runpy; sys.argv = ['set_setting.py', {package!r}, {field!r}, "
            f"{value!r}]; sys.path.insert(0, 'scripts'); "
            "runpy.run_path('scripts/set_setting.py', run_name='__main__')"
        )
        subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True)

    def set_to(value):
        put("host", "public_base_url", value)

    async def main():
        factory = worker_session_factory()
        seen = []
        for value in (None, "https://b.example.org", ""):
            if value is not None:
                set_to(value)
            async with factory() as db:
                runtime = await worker_app.worker_runtime(db)
            seen.append(runtime.public_base_url if runtime else "NO-RUNTIME")
            seen.append(public_base_url(worker_app._built.app))
        print("RESULT", "|".join(seen))
        # The other settings the worker reads: all from the database, none from the web's memory.
        from simple_module_core.mail import resolve_mail_sender
        from sm_events.reminders import tick

        put("mail", "backend", "smtp")
        put("mail", "smtp_host", "smtp.example.org")
        put("sm_events", "content_locales", '["en", "de"]')
        put("sm_events", "public_prefix", "/termine")
        async with factory() as db:
            await worker_app.worker_runtime(db)  # a tick's own hydration
            sender = await resolve_mail_sender(db)
        stored = tick._stored_settings()
        print("MAIL", type(sender).__name__, sender.delivers_email)
        locales = list(stored.content_locales)
        print("EVENTS", locales, stored.public_prefix, stored.reminders_enabled)

    asyncio.run(main())
    """
)


def test_a_database_only_public_address_reaches_the_worker_and_follows_changes(tmp_path):
    _migrate(tmp_path)
    _set(tmp_path, "https://a.example.org")
    done = _run(READ, tmp_path, SM_SECRET_KEY=KEY)
    assert done.returncode == 0, done.stderr[-2500:]
    line = next(x for x in done.stdout.splitlines() if x.startswith("RESULT "))
    assert line.removeprefix("RESULT ").split("|") == [
        "https://a.example.org",  # stored only in the database, no env: the worker has it
        "https://a.example.org",  # and so does the one function the web process reads
        "https://b.example.org",  # changed: the next tick uses it, no restart
        "https://b.example.org",
        "",  # cleared: both say unavailable
        "",
    ]
    mail = next(x for x in done.stdout.splitlines() if x.startswith("MAIL "))
    assert mail == "MAIL SmtpMailSender True"  # the transport comes from the stored mail settings
    events = next(x for x in done.stdout.splitlines() if x.startswith("EVENTS "))
    assert events == "EVENTS ['en', 'de'] /termine True"  # locales, prefix, reminders switch
