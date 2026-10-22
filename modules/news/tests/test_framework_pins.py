"""Pins on the framework internals news reads (#125).

The module range admits any 0.0.x framework, but tenancy-mode detection reads
names the framework does not promise to keep: the ``TenantMiddleware`` class,
its ``fixed``/``header`` keywords, and Starlette's ``user_middleware`` entry
shape. Each test here fails, with a message naming the call site, the moment
one of them changes — in CI on the framework bump, not in production.

Since the 0.0.36 floor (#211) the framework's public answers come first:
``tenancy_mode`` for the mode and ``single_tenant_id`` for a ``create_app``
host's pinned tenant. The stack reading stays as the fallback for an app
built outside ``create_app`` (whose ``tenancy_mode`` is always ``SINGLE``),
and for the tenant header the public cache key varies on, which has no
public replacement yet. ``require_tenant`` is not used: it binds
``single_tenant_id`` whatever an upstream layer resolved, which breaks the
request-time rule of #192.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from news import tenancy
from news.tenancy import TenancyMode

_SITE = "news/tenancy.py (_tenant_middleware / _kwargs)"


def test_tenant_middleware_is_importable():
    try:
        from simple_module_hosting.middleware import TenantMiddleware  # noqa: F401
    except ImportError as exc:  # pragma: no cover - only on a framework change
        pytest.fail(f"{_SITE}: simple_module_hosting.middleware.TenantMiddleware is gone: {exc}")


@pytest.mark.parametrize("name", sorted(tenancy._KNOWN_KWARGS))
def test_tenant_middleware_still_takes_the_keywords_read(name):
    from simple_module_hosting.middleware import TenantMiddleware

    params = inspect.signature(TenantMiddleware.__init__).parameters
    assert name in params and params[name].kind is inspect.Parameter.KEYWORD_ONLY, (
        f"{_SITE}: TenantMiddleware.__init__ no longer takes keyword {name!r} "
        f"(has {list(params)}); mode detection reads it off the built stack"
    )


def test_starlette_middleware_entries_keep_cls_args_kwargs():
    from simple_module_hosting.middleware import TenantMiddleware

    app = FastAPI()
    app.add_middleware(TenantMiddleware, fixed="default")
    entries = getattr(app, "user_middleware", None)
    assert isinstance(entries, list), f"{_SITE}: app.user_middleware is gone"
    [entry] = entries
    assert entry.cls is TenantMiddleware, f"{_SITE}: user_middleware entries lost .cls"
    assert tuple(entry.args) == (), f"{_SITE}: user_middleware entries lost .args"
    assert dict(entry.kwargs) == {"fixed": "default"}, f"{_SITE}: entries lost .kwargs"


# --- fail-safe ----------------------------------------------------------------


def _with_entry(**fields):
    """A FastAPI app whose one stack entry is shaped by *fields*."""
    from simple_module_hosting.middleware import TenantMiddleware

    app = FastAPI()
    app.user_middleware = [SimpleNamespace(cls=TenantMiddleware, **fields)]
    return app


@pytest.mark.parametrize(
    "fields",
    [
        {"args": (), "kwargs": {"pinned": "default"}},  # ``fixed`` renamed
        {"args": ("default",), "kwargs": {}},  # passed positionally
        {"args": ()},  # entries lost .kwargs
    ],
)
def test_unrecognised_arguments_are_multi_not_single(fields, caplog):
    app = _with_entry(**fields)
    app.state.news = SimpleNamespace()
    assert tenancy.detect_mode(app) is TenancyMode.MULTI
    with caplog.at_level(logging.WARNING, logger="simple_module.news"):
        assert tenancy.configure(app) is TenancyMode.MULTI
    assert "does not recognise" in caplog.text


def test_a_subclassed_middleware_is_still_found():
    from simple_module_hosting.middleware import TenantMiddleware

    class Wrapped(TenantMiddleware):
        pass

    app = FastAPI()
    app.add_middleware(Wrapped)
    assert tenancy.detect_mode(app) is TenancyMode.MULTI


def test_an_unreadable_stack_refuses_to_guess():
    app = FastAPI()
    app.user_middleware = [object()]  # entries without .cls
    with pytest.raises(RuntimeError, match="Refusing to guess"):
        tenancy.configure(app)


def test_the_frameworks_own_multi_wins():
    app = FastAPI()  # no TenantMiddleware at all
    app.state.sm = SimpleNamespace(tenancy="multi")
    assert tenancy.detect_mode(app) is TenancyMode.MULTI


def _create_app_host(default_tenant_id):
    app = FastAPI()
    app.state.sm = SimpleNamespace(
        tenancy="single", db=SimpleNamespace(default_tenant_id=default_tenant_id)
    )
    app.state.news = SimpleNamespace()
    return app


def test_a_create_app_hosts_pinned_tenant_is_the_frameworks_answer():
    """``single_tenant_id``, not the stack: no ``TenantMiddleware`` here."""
    assert tenancy.configure(_create_app_host(None)) is TenancyMode.SINGLE
    with pytest.raises(RuntimeError, match="default_tenant='acme'"):
        tenancy.configure(_create_app_host("acme"))


def test_an_explicit_fixed_pin_must_agree_with_the_frameworks_answer():
    """``single_tenant_id`` says ``"default"`` but the stack pins ``"acme"``:
    requests would follow the middleware and background work the framework,
    so startup refuses the split (#212)."""
    from simple_module_hosting.middleware import TenantMiddleware

    split = _create_app_host(None)
    split.add_middleware(TenantMiddleware, fixed="acme")
    with pytest.raises(RuntimeError, match="default_tenant='acme'"):
        tenancy.configure(split)
    agreeing = _create_app_host(None)
    agreeing.add_middleware(TenantMiddleware, fixed="default")
    assert tenancy.configure(agreeing) is TenancyMode.SINGLE


def test_the_recorded_vary_headers_come_from_the_framework():
    from simple_module_hosting.middleware import TenantMiddleware

    app = FastAPI()
    app.add_middleware(TenantMiddleware, header="X-Tenant-ID")
    state = SimpleNamespace(tenant_id="acme", tenant_vary=("Host",))
    request = SimpleNamespace(app=app, state=state, scope={})
    assert tenancy.request_vary(request) == ("Cookie", "X-Tenant-ID", "Host")


# --- no shared or premature cache ---------------------------------------------


def test_each_app_keeps_its_own_mode():
    """The mode lives on the app it was read from — nothing module-level."""
    from simple_module_hosting.middleware import TenantMiddleware

    single, multi = FastAPI(), FastAPI()
    multi.add_middleware(TenantMiddleware, header="X-Tenant-ID")
    single.state.news = SimpleNamespace()
    multi.state.news = SimpleNamespace()
    assert tenancy.configure(single) is TenancyMode.SINGLE
    assert tenancy.configure(multi) is TenancyMode.MULTI
    assert tenancy.mode_of(single) is TenancyMode.SINGLE
    assert tenancy.mode_of(multi) is TenancyMode.MULTI


def test_a_detection_before_the_middleware_is_added_does_not_stick():
    from simple_module_hosting.middleware import TenantMiddleware

    app = FastAPI()
    assert tenancy.mode_of(app) is TenancyMode.SINGLE  # nothing stored by this
    app.add_middleware(TenantMiddleware)
    assert tenancy.mode_of(app) is TenancyMode.MULTI
