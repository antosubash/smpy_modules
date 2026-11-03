"""The copied helpers, and every way their copies are allowed to differ (#127).

Read by ``test_helper_parity.py``; the mechanics are in ``parity_support.py``.
An entry in a ``differ`` or ``own`` map is a decision, so each one says why.
Adding one to get a red build green is the drift this file exists to catch —
the fix is usually to change the lagging copy instead.

The tenancy families (``{pagebuilder,news,records}/tenancy.py`` and
``_tenancy_mode.py``) live in ``parity_tenancy.py`` and are appended below.
"""

from __future__ import annotations

from parity_support import Copy, Family
from parity_tenancy import TENANCY_FAMILIES

PB = "modules/pagebuilder/pagebuilder"
NEWS = "modules/news/news"
AI = "modules/ai/sm_ai"
BILLING = "modules/billing/sm_billing"
RECORDS = "modules/records/sm_records"

_AS_MODULE = {"pagebuilder": "MODULE", "news": "MODULE", "sm_ai": "MODULE", "sm_records": "MODULE"}

FAMILIES: tuple[Family, ...] = (
    Family(
        "public cache headers",
        (
            Copy(f"{PB}/web/public_cache.py", {"PagebuilderSettings": "Settings"}),
            Copy(f"{NEWS}/web/endpoints/public/_urls.py", {"NewsSettings": "Settings"}),
        ),
        shared=("SIGNED_IN_CACHE_CONTROL", "signed_in", "_user_key", "viewer_key", "cache_control"),
        differ={
            "etag_for": "A page's chrome also changes with the site layout and the nav list, "
            "so pagebuilder digests layout_updated_at and nav as well; an article has neither.",
        },
    ),
    Family(
        "slug redirects",
        (
            Copy(
                f"{PB}/content/redirects.py",
                {
                    "PageRedirect": "DocRedirect",
                    "PageStatus": "DocStatus",
                    "Page": "Doc",
                    "page_id": "doc_id",
                    "clear_for_page": "clear_for_doc",
                },
            ),
            Copy(
                f"{NEWS}/content/redirects.py",
                {
                    "NewsArticleRedirect": "DocRedirect",
                    "ArticleStatus": "DocStatus",
                    "NewsArticle": "Doc",
                    "article_id": "doc_id",
                    "clear_for_article": "clear_for_doc",
                },
            ),
        ),
    ),
    Family(
        "content locales",
        (Copy(f"{PB}/core/locales.py"), Copy(f"{NEWS}/core/locales.py")),
        shared=("is_default", "resolve", "path_prefix"),
        differ={
            "use": "Pagebuilder publishes its settings object; news publishes a vocabulary, "
            "because it may run without pagebuilder and borrows its list when it does not.",
            "reset": "Each forgets what its own `use` published.",
            "supported": "Read from where each `use` put it.",
            "default": "Read from where each `use` put it.",
        },
    ),
    Family(
        "slugify (TypeScript)",
        (
            Copy(
                f"{NEWS}/ui/utils/slugify.ts",
                own={
                    "SLUG_PATTERN": "News' article screen lets an author type a slug; "
                    "pagebuilder's editors only ever derive one.",
                },
            ),
            Copy(f"{PB}/ui/utils/slugify.ts"),
        ),
    ),
    Family(
        "CSRF token sharing (Python)",
        (
            Copy(f"{NEWS}/web/csrf.py"),
            Copy(
                f"{PB}/web/csrf.py",
                own={
                    "_check": "Pagebuilder alone keeps `csrf_protect`, for a host that guards "
                    "writes above the app, so it wraps the framework check instead of mounting it.",
                    "verify_csrf_if_configured": "See `_check`.",
                },
            ),
            Copy(f"{AI}/web/csrf.py"),
            Copy(f"{RECORDS}/web/csrf.py"),
        ),
    ),
    Family(
        "CSRF token store (TypeScript)",
        (
            Copy(f"{NEWS}/ui/utils/csrf.ts"),
            Copy(
                f"{PB}/ui/utils/csrf.ts",
                own={
                    "isCsrfRefusalBody": "Media uploads go through XHR, which hands back a raw "
                    "body rather than a Response.",
                },
            ),
            Copy(f"{AI}/ui/utils/csrf.ts"),
            Copy(f"{RECORDS}/ui/utils/csrf.ts"),
        ),
    ),
    Family(
        "admin HTTP client",
        (
            Copy(
                f"{NEWS}/ui/utils/http.ts",
                _AS_MODULE,
                own={
                    "HttpError": "News' callers tell a stale write (409) from a vanished "
                    "article (404); pagebuilder's throw a plain Error.",
                    "isHttpStatus": "See HttpError.",
                    "errorFrom": "News' errorMessage, returning an HttpError; "
                    "scripts/http-error-parity.test.ts holds the two to the same messages.",
                    "describeError": "News words the common Pydantic errors itself; pagebuilder "
                    "shows Pydantic's own msg. A wording upgrade pagebuilder can adopt, not drift.",
                    "read": "News splits GET from writes; pagebuilder has one `request`.",
                    "write": "See read.",
                },
            ),
            Copy(
                f"{PB}/ui/utils/request.ts",
                _AS_MODULE,
                own={
                    "errorMessage": "See news' errorFrom.",
                    "request": "See news' read.",
                },
            ),
        ),
        differ={
            "fromValidationErrors": "News delegates each entry to describeError.",
        },
    ),
    Family(
        "secret encryption",
        (
            Copy(
                f"{AI}/core/crypto.py",
                {"AiKeyUnreadableError": "KeyUnreadableError"},
                own={
                    "_dotenv_secret": "The AI module also runs in a Celery worker with no app, "
                    "so it falls back to SM_SECRET_KEY from the environment and .env.",
                    "explicit_secret": "See _dotenv_secret.",
                },
                messages=(
                    "AI setting %r is stored unencrypted; re-save it via the AI "
                    "settings page to encrypt it.",
                ),
            ),
            Copy(
                f"{BILLING}/core/crypto.py",
                {"BillingKeyUnreadableError": "KeyUnreadableError"},
                own={
                    "BillingKeyUnreadableError": "AI keeps its error in sm_ai.contracts.errors, "
                    "where its API maps it to a response.",
                },
                messages=(
                    "Billing setting %r is stored unencrypted; re-save it on "
                    "/admin/billing/connection to encrypt it.",
                ),
            ),
        ),
        differ={
            "_fernet": "Billing reads no environment, so it has no fallback after the provider.",
        },
    ),
    Family(
        "scheduler shutdown",
        (
            Copy(
                f"{PB}/scheduling/scheduler.py",
                {
                    "_log": "logger",
                    "contextlib.suppress": "suppress",
                    "PagebuilderSettings": "Settings",
                },
                messages=("pagebuilder.scheduler.stop_failed",),
            ),
            Copy(
                f"{NEWS}/scheduling/scheduler.py",
                {"NewsSettings": "Settings"},
                messages=("news.scheduler.stop_failed",),
            ),
        ),
        # `_run` and `_due_tenants` are the per-tenant tick: each queries its
        # own table and shapes the tick differently, so they are not compared.
        shared=("Scheduler.__init__", "Scheduler.start", "Scheduler.stop"),
    ),
    Family(
        "test scaffolding: default tenant",
        (
            Copy("modules/pagebuilder/tests/support/tenant_fixture.py"),
            Copy("modules/news/tests/support/tenant_fixture.py"),
        ),
    ),
    Family(
        "test scaffolding: header tenant",
        (
            Copy("modules/pagebuilder/tests/support/tenant_app.py"),
            Copy("modules/news/tests/support/tenant_app.py"),
        ),
        shared=("HeaderTenant", "as_tenant"),
    ),
    Family(
        "test scaffolding: Postgres opt-in",
        (
            Copy("modules/pagebuilder/tests/pg_support.py"),
            Copy("modules/news/tests/pg_support.py"),
            Copy("modules/records/tests/pg_support.py"),
            Copy("modules/images/tests/pg_support.py"),
        ),
        shared=("_shared", "_pg", "arm_reset", "USING_POSTGRES"),
    ),
    *TENANCY_FAMILIES,
)
