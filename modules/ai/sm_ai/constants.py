"""AI module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import Final

PACKAGE: Final = "sm_ai"
# Namespace the console strings in ``locales/en.json`` are registered under.
LOCALE_NAMESPACE: Final = "ai"
MODULE_NAME: Final = "Ai"

# Outside the web host (a Celery worker) settings are hydrated lazily and
# cached this long — framework 0.0.35 has no cross-process reload signal.
LAZY_SETTINGS_TTL_SECONDS: Final = 60.0
# How long an env/default fallback (database unreachable) is kept before retrying.
LAZY_SETTINGS_RETRY_SECONDS: Final = 5.0
# Upper bound on one worker-side settings read, connect included.
LAZY_SETTINGS_READ_TIMEOUT_SECONDS: Final = 5.0
# Where the host stores the secret it generated when SM_SECRET_KEY is unset
# (``simple_module_hosting._secret_key``; both names are private there, and
# tests/test_framework_pins.py fails when either moves, #125).
HOST_SETTINGS_PACKAGE: Final = "host"
HOST_SECRET_FIELD: Final = "secret_key"

ROUTE_PREFIX_API: Final = "/api/ai"
VIEW_PREFIX: Final = "/ai"
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_LABEL: Final = "AI"
MENU_LABEL_KEY: Final = "ai.menu.ai"
MENU_GROUP: Final = "Administration"
MENU_GROUP_KEY: Final = "ui.nav.admin"  # the shared header, not an ai.* key
MENU_ICON: Final = "sparkles"
MENU_ORDER: Final = 116  # just after Branding's 115

# Modules this one depends on (value = that module's ModuleMeta.name).
_MODULE_SETTINGS: Final = "Settings"

# Inertia page identifier, rendered via this constant at the view (the
# in-repo check_hardcoded_strings convention; the framework's SM003/SM004
# literal-pairing convention loses that tie-break — see endpoints/views.py).
# A unit test pins the value to pages/Settings.tsx.
_PAGE_SETTINGS: Final = f"{MODULE_NAME}/Settings"

PERM_MANAGE: Final = "ai.manage"

# Provider identifiers (stored values — changing them breaks existing rows).
PROVIDER_ANTHROPIC: Final = "anthropic"
PROVIDER_OPENAI: Final = "openai"
PROVIDER_GOOGLE: Final = "google"
PROVIDER_OPENAI_COMPATIBLE: Final = "openai_compatible"

CHAT_PROVIDERS: Final = (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI_COMPATIBLE,
)
# Anthropic offers no embeddings API.
EMBEDDING_PROVIDERS: Final = (
    PROVIDER_OPENAI,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI_COMPATIBLE,
)

# vLLM and friends ignore the key but the OpenAI protocol requires a non-empty
# value — same literal GeoWiki's AiClientFactory substitutes.
PLACEHOLDER_API_KEY: Final = "not-needed"

# Smallest valid embedding width; 0 means "not set". The API rejects anything
# lower, and AiSettings reads a lower stored value as 0 (#164).
MIN_EMBEDDING_DIM: Final = 0

# Providers with no default endpoint: their slot is unusable without a base URL.
PROVIDERS_NEEDING_BASE_URL: Final = frozenset({PROVIDER_OPENAI_COMPATIBLE})

SLOT_CHAT: Final = "chat"
SLOT_EMBEDDING: Final = "embedding"
TEST_SLOTS: Final = (SLOT_CHAT, SLOT_EMBEDDING)
TEST_PROMPT: Final = "Reply with the single word: ok"
TEST_TIMEOUT_SECONDS: Final = 30

SECRET_FIELDS: Final = frozenset({"chat_api_key", "embedding_api_key"})

# Usage metering (#99): the billing counter every AI request charges, and the
# label its usage screens show, from this module's catalogue. The key is a
# ``Plan.limits`` key, so changing it orphans every plan's limit.
METER_REQUESTS: Final = "ai.requests"
METER_REQUESTS_LABEL_KEY: Final = "ai.meters.requests"
METER_KIND_COUNTER: Final = "counter"
METER_UNIT_COUNT: Final = "count"
# The optional billing module's RequiresQuota, and the registry it puts on
# app.state.
BILLING_QUOTA_MODULE: Final = "sm_billing.metering.deps"
BILLING_METERS_ATTR: Final = "billing_meters"
