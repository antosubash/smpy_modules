"""Smoke tests: the demo host boots and mounts its modules.

These catch wiring breaks (missing dependency, entry point typo, route
prefix collision) that module-level tests can't see because they build a
minimal app instead of the real host.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.routing import iter_route_contexts
from simple_module_hosting import Settings, create_app

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))

# What ``main.py`` imports before ``create_app``, imported here for the same
# reason: the records module seals its collection registry in the first app it
# builds, and ``booted_host`` imports ``main`` after the fixtures above built one.
import records_collections  # noqa: E402, F401


@pytest.fixture
def app():
    return create_app(Settings())


def test_app_boots(app):
    assert app is not None


def _module_names(app) -> set[str]:
    """Booted modules live on the framework's Services container."""
    return {m.meta.name for m in app.state.sm.modules}


def test_core_modules_registered(app):
    assert {"Auth", "Users", "Dashboard", "Permissions"} <= _module_names(app)


def test_openapi_schema_generates(app):
    schema = app.openapi()
    assert schema["openapi"].startswith("3.")


def test_pagebuilder_registered(app):
    assert "PageBuilder" in _module_names(app)


def _route_paths(app) -> set[str]:
    """Every path the app serves, view routes included.

    Not ``app.routes``: since FastAPI 0.141 ``include_router`` wraps the
    sub-router in one lazily-resolved ``_IncludedRouter`` with no ``path``.
    Not the OpenAPI schema: since framework 0.0.37 view routers are included
    with ``include_in_schema=False``, so the schema lists only ``/api/...``
    (#186).
    ``iter_route_contexts`` ships with the FastAPI 0.141 every lock here
    resolves, so it is imported unguarded.
    """
    return {r.path for r in iter_route_contexts(app.routes) if r.path}


def test_pagebuilder_routes_mounted(app):
    paths = _route_paths(app)
    assert "/api/pagebuilder/pages" in paths
    assert "/pagebuilder/media" in paths


def test_ai_registered(app):
    assert "Ai" in _module_names(app)


def test_ai_routes_mounted(app):
    # Only /api/... paths, which stay in the OpenAPI schema on every framework.
    paths = set(app.openapi()["paths"])
    assert "/api/ai/settings" in paths
    assert "/api/ai/test" in paths


# Every distributable module in this repo. The subscriber check below is only
# evidence if each of them is booted, so it asserts that first.
REPO_MODULES = {"Ai", "Billing", "Images", "News", "PageBuilder", "Records"}


def _migrate(url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"],
        cwd=REPO,
        env={**os.environ, "SM_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.fixture
def booted_host(tmp_path, monkeypatch):
    """The demo host's own ``main:app``, against a migrated database of its own.

    Imported fresh with ``SM_DATABASE_URL`` pointing at ``tmp_path``, and
    taken back out of ``sys.modules`` afterwards, so neither the developer's
    ``host/app.db`` nor another test's import is involved.
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'host.db'}"
    _migrate(url)
    monkeypatch.setenv("SM_DATABASE_URL", url)
    sys.modules.pop("main", None)
    try:
        yield importlib.import_module("main").app
    finally:
        sys.modules.pop("main", None)


def test_no_module_subscribes_to_record_events(booted_host):
    """The evidence behind GH #157's "leave publishing inline" call.

    Record events publish at commit, inside the request, so whatever subscribes
    adds its time to every record write's response. Today nothing does, and a
    publish with no listener returns before gathering anything. When this
    fails, a module started listening: check that its handler is cheap, or
    hands its work off, before updating the expectation.

    Read inside the host's lifespan, since a module may subscribe from
    ``on_startup`` as well as from ``register_event_handlers``. ``_emitter`` is
    read because ``EventBus`` has no public way to list listeners.
    """
    from sm_records.contracts import events

    app = booted_host

    async def listening_inside_lifespan() -> set[str]:
        async with app.router.lifespan_context(app):
            assert app.state.migration["is_current"]
            assert _module_names(app) >= REPO_MODULES
            bus = app.state.sm.event_bus
            return {
                name
                for name in events.__all__
                if bus._emitter.listeners(bus._event_key(getattr(events, name)))
            }

    assert asyncio.run(listening_inside_lifespan()) == set()


def test_images_object_intents_work_in_the_real_app(booted_host):
    """``on_startup`` hands images the host's session factory, so a handler's
    bare ``object_intent(keys)`` writes to the host database."""
    from sm_images.core.storage.intents import object_intent, use_session_factory
    from sm_images.models import ObjectIntent
    from sqlalchemy import select

    app = booted_host

    async def write_and_read() -> list[str]:
        async with app.router.lifespan_context(app):
            async with object_intent(["images/default/boot-check"]):
                pass
            async with app.state.sm.db.session_factory() as session:
                return list((await session.execute(select(ObjectIntent.key))).scalars())

    try:
        assert "images/default/boot-check" in asyncio.run(write_and_read())
    finally:
        use_session_factory(None)


def test_images_public_page_is_not_shadowed_by_another_route(booted_host):
    """``/images/c/{slug}`` is mounted at the app root during the lifespan. Walk
    the routes in registration order, as Starlette does: the first that matches
    must be images' own, not a catch-all (a pagebuilder slug route, a locale
    prefix) registered before it."""
    from starlette.routing import compile_path

    app = booted_host

    async def first_match() -> str | None:
        async with app.router.lifespan_context(app):
            for route in iter_route_contexts(app.routes):
                if route.path and compile_path(route.path)[0].match("/images/c/some-slug"):
                    return route.path
        return None

    assert asyncio.run(first_match()) == "/images/c/{slug}"


def test_no_module_imports_the_deprecated_settings_shim():
    """``settings.registration`` warns on import and goes away in 0.1.0 (#273).

    Fresh interpreter: an earlier test may already have imported the shim, and
    a module imports it only once, so the warning would not fire again here.
    """
    code = (
        "import sys; sys.path.insert(0, 'host'); "
        "import records_collections; "
        "from simple_module_hosting import Settings, create_app; "
        "create_app(Settings())"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error:settings.registration is deprecated:DeprecationWarning",
            "-c",
            code,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_shipped_code_imports_no_deprecated_settings_shim():
    """The boot test above misses imports made later, inside a function: the
    worker's settings load, billing's live check and records' CLI (#273). The
    framework's ``settings.registration``, ``settings.hydrate`` and
    ``settings.module_registry`` all warn on import and go away in 0.1.0.
    Tests may still use them; shipped code and scripts may not.
    """
    shim = re.compile(r"^\s*(from|import) settings\.(registration|hydrate|module_registry)\b")
    shipped = [
        path
        for path in [*REPO.glob("modules/*/*/**/*.py"), *REPO.glob("scripts/*.py")]
        if "tests" not in path.relative_to(REPO).parts
    ]
    offenders = [
        f"{path.relative_to(REPO)}:{number}"
        for path in shipped
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if shim.match(line)
    ]
    assert offenders == []
