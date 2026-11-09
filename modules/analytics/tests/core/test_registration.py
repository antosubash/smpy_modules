from simple_module_core.body_limits import BodyLimitRegistry
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_core.rate_limit import RateLimitRegistry
from sm_analytics.module import AnalyticsModule


def test_collector_has_method_scoped_body_and_rate_guards():
    module = AnalyticsModule()
    body = BodyLimitRegistry()
    rates = RateLimitRegistry()
    public = PublicRouteRegistry()
    module.register_body_limits(body)
    module.register_rate_limits(rates)
    module.register_public_routes(public)
    assert body.limit_for("POST", "/api/analytics/collect") == 8192
    assert body.limit_for("POST", "/api/analytics/properties") is None
    assert rates.match("POST", "/api/analytics/collect").key == "ip"
    assert rates.match("POST", "/api/analytics/collect").rate == "120/minute"
    assert rates.match("GET", "/api/analytics/config").rate == "1200/minute"
    assert rates.match("POST", "/api/analytics/properties") is None
    assert public.matches("POST", "/api/analytics/collect")
    assert public.matches("GET", "/api/analytics/config")
    assert not public.matches("GET", "/api/analytics/properties")
