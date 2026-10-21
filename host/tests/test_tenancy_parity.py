"""The three tenancy-mode detectors agree, on stacks the framework really builds (#125).

pagebuilder, news and records each carry a copy of the detector — published
modules cannot import one another — and each reads framework internals
(``TenantMiddleware``'s ``fixed``/``header`` keywords off ``user_middleware``).
This is the one place that sees all three, so it pins two things: they give
the same answer, and that answer matches the framework's own public
``tenancy_mode`` for every way ``create_app`` installs the middleware. A
framework that renamed a keyword would make the copies fall back to MULTI
and fail the ``single`` rows here, rather than pass silently.
"""

from __future__ import annotations

import news.tenancy
import pagebuilder.tenancy
import pytest
import sm_records._tenancy_mode
from simple_module_hosting import Settings, create_app

_DETECTORS = {
    "pagebuilder": pagebuilder.tenancy,
    "news": news.tenancy,
    "records": sm_records._tenancy_mode,
}

# Every row spells out all three settings, so a developer's .env cannot move it.
_SINGLE = {"multi_tenant": False, "tenant_header": ""}
_MULTI = {"multi_tenant": True, "default_tenant": ""}
_HOSTS = {
    "no TenantMiddleware": ({**_SINGLE, "default_tenant": ""}, "single", None),
    "fixed to default": ({**_SINGLE, "default_tenant": "default"}, "single", None),
    "multi, no header": ({**_MULTI, "tenant_header": ""}, "multi", None),
    "multi, header": ({**_MULTI, "tenant_header": "X-Tenant-ID"}, "multi", "X-Tenant-ID"),
}


@pytest.fixture(scope="module", params=list(_HOSTS))
def host(request):
    overrides, mode, header = _HOSTS[request.param]
    return create_app(Settings(**overrides)), mode, header


@pytest.mark.parametrize("name", list(_DETECTORS))
def test_each_detector_reads_the_built_stack(host, name):
    app, mode, _header = host
    detector = _DETECTORS[name]
    entry = detector._tenant_middleware(app)
    if entry is not None:
        assert detector._kwargs(entry) is not None, (
            f"{name}: the framework installs TenantMiddleware with arguments the "
            f"detector does not recognise: args={entry.args!r} kwargs={entry.kwargs!r}"
        )
    assert detector.detect_mode(app) == mode


def test_the_detectors_agree_with_each_other_and_the_framework(host):
    from simple_module_hosting.tenancy import tenancy_mode

    app, mode, _header = host
    assert {name: d.detect_mode(app) for name, d in _DETECTORS.items()} == dict.fromkeys(
        _DETECTORS, mode
    )
    assert str(tenancy_mode(app)) == mode


def test_the_header_readers_agree(host):
    app, mode, header = host
    assert sm_records._tenancy_mode.tenant_header(app) == header
    expected = () if mode == "single" else ("Cookie", header) if header else ("Cookie",)
    # tenant_vary reads the stored mode, which needs on_startup; detect on the fly.
    for detector in (pagebuilder.tenancy, news.tenancy):
        assert detector.tenant_vary(app) == expected
