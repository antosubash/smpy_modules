"""Registration identifiers and ingestion limits."""

PACKAGE = "sm_analytics"
MODULE_NAME = "Analytics"
_MODULE_SETTINGS = "Settings"
API_PREFIX = "/api/analytics"
VIEW_PREFIX = "/analytics"
PERM_VIEW = "analytics.view"
PERM_MANAGE = "analytics.manage"
_PAGE_DASHBOARD = "Analytics/Dashboard"
COLLECT_PATH = f"{API_PREFIX}/collect"
CONFIG_PATH = f"{API_PREFIX}/config"
MAX_BODY_BYTES = 8192
UTM_PARAMETERS = frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"})
EXCLUDED_SEGMENTS = frozenset({"auth", "login", "logout", "register", "settings", "analytics"})
