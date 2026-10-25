"""Website submissions (#101): exactly which paths are anonymous, the limits
wired into the host, and the settings that govern them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_core.rate_limit import RateLimitRegistry
from sm_records import boot, constants
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings

SUBMIT = "/api/records/submissions/contact/submit"
DEFINITION = "/api/records/submissions/contact"


def _registry() -> PublicRouteRegistry:
    """What the host's registry holds once both halves have run: the fixed
    submissions rule at construction, the read API's at startup."""
    registry = PublicRouteRegistry()
    RecordsModule().register_public_routes(registry)
    boot.exempt_public_routes(
        SimpleNamespace(state=SimpleNamespace(public_routes=registry)), RecordsSettings()
    )
    return registry


@pytest.mark.parametrize(("method", "path"), [("GET", DEFINITION), ("POST", SUBMIT)])
def test_the_submission_routes_are_anonymous(method, path):
    assert _registry().matches(method, path)


@pytest.mark.parametrize(
    "path", ["/api/records/submissions/confirm", "/api/records/submissions/unsubscribe"]
)
def test_the_newsletter_links_are_anonymous(path):
    assert _registry().matches("POST", path)


@pytest.mark.parametrize(
    "path", ["/records/submissions/confirm", "/records/submissions/unsubscribe"]
)
def test_the_landing_pages_are_anonymous_for_get_only(path):
    registry = _registry()
    assert registry.matches("GET", path)
    for method in ("POST", "PUT", "DELETE"):
        assert not registry.matches(method, path), method
    assert not registry.matches("GET", "/records/submissionsx/confirm")
    assert not registry.matches("GET", "/records/other")


def test_the_confirm_link_lifetime_is_bounded():
    assert RecordsSettings().public_submissions_confirm_ttl_hours == 168
    with pytest.raises(ValidationError):
        RecordsSettings(public_submissions_confirm_ttl_hours=0)


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_only_get_and_post_are_exempt(method):
    assert not _registry().matches(method, SUBMIT)


@pytest.mark.parametrize(
    "path",
    [
        "/api/records/submissionsx/contact",
        "/api/records/types/contact/records",
        "/api/records/types/contact/records/0123456789abcdef0123456789abcdef/submission/spam",
        "/admin/records/contact",
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_the_admin_surface_stays_gated(method, path):
    assert not _registry().matches(method, path), f"{method} {path} must require auth"


def test_the_read_api_is_still_read_only():
    registry = _registry()
    assert registry.matches("GET", "/api/records/public/article")
    assert not registry.matches("POST", "/api/records/public/article")


@pytest.mark.parametrize(
    "prefix",
    ["/api/records/submissions", "/api/records/submissions/", "/api/records/submissions/x"],
)
def test_the_read_api_cannot_live_under_the_submissions_prefix(prefix):
    with pytest.raises(ValidationError, match="website submissions"):
        RecordsSettings(public_route_prefix=prefix)


def test_the_definition_has_a_static_rate_limit():
    registry = RateLimitRegistry()
    RecordsModule().register_rate_limits(registry)
    rule = registry.match("GET", DEFINITION)
    assert rule is not None and rule.key == "ip"
    assert registry.match("POST", SUBMIT) is None, "submits are limited by the module"


def test_the_routes_are_mounted_at_the_fixed_prefix():
    from tests.route_table_support import route_table

    mounted = set(route_table())
    assert ("GET", "/api/records/submissions/{type_key}") in mounted
    assert ("POST", "/api/records/submissions/{type_key}/submit") in mounted
    assert constants.PUBLIC_SUBMISSIONS_API_PREFIX == "/api/records/submissions/"


def test_the_body_ceiling_is_the_submissions_one():
    from sm_records._body_limit import BodyLimitMiddleware

    settings = RecordsSettings(public_submissions_max_body_bytes=2048)
    app = SimpleNamespace(state=SimpleNamespace(sm_records=SimpleNamespace(settings=settings)))
    guard = BodyLimitMiddleware(app=None)  # type: ignore[arg-type]
    scope = {"type": "http", "method": "POST", "path": SUBMIT, "app": app}
    assert guard._limit(scope) == 2048
    admin = {**scope, "path": "/api/records/types/contact/records"}
    assert guard._limit(admin) > 2048


# --- settings ------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "public_submissions_rate_per_ip",
        "public_submissions_type_rate",
        "public_submissions_confirm_rate_per_email",
    ],
)
def test_a_rate_must_parse(field):
    assert getattr(RecordsSettings(**{field: "off"}), field) == "off"
    assert getattr(RecordsSettings(**{field: "10/hour"}), field) == "10/hour"
    with pytest.raises(ValidationError):
        RecordsSettings(**{field: "lots"})


def test_allowed_origins_are_origins():
    settings = RecordsSettings(
        public_submissions_allowed_origins=["https://WWW.Example.org/", "https://www.example.org"]
    )
    assert settings.public_submissions_allowed_origins == ("https://www.example.org",)
    for bad in ("www.example.org", "https://example.org/path", "ftp://example.org"):
        with pytest.raises(ValidationError):
            RecordsSettings(public_submissions_allowed_origins=[bad])


def test_the_body_ceiling_is_bounded():
    with pytest.raises(ValidationError):
        RecordsSettings(public_submissions_max_body_bytes=100)
    # A lower ``max_payload_bytes`` is not a conflict (an install with no
    # submitting type must not be refused for it): it is the ceiling instead.
    from sm_records._body_limit import BodyLimitMiddleware

    settings = RecordsSettings(max_payload_bytes=64)
    app = SimpleNamespace(state=SimpleNamespace(sm_records=SimpleNamespace(settings=settings)))
    scope = {"type": "http", "method": "POST", "path": SUBMIT, "app": app}
    assert BodyLimitMiddleware(app=None)._limit(scope) == 64  # type: ignore[arg-type]


def test_the_environment_is_not_a_source(monkeypatch):
    """Stored settings only (CLAUDE.md): a stray variable changes nothing."""
    for name in ("PUBLIC_SUBMISSIONS_ENABLED", "SM_RECORDS_PUBLIC_SUBMISSIONS_ENABLED"):
        monkeypatch.setenv(name, "false")
    assert RecordsSettings().public_submissions_enabled is True
