"""The tenancy copies, and every way they are allowed to differ (#127, #204).

Split out of ``parity_families.py``, which appends these to ``FAMILIES``; the
rules there apply here — an allowance is a decision, and says why.

Pagebuilder and news carry one design (#38, #125, #192, #211): mode detection
in ``core/tenancy/_mode.py``, the boot-time ``configure`` in ``_configure.py``,
binding outside a request in ``_scope.py`` and request binding in
``__init__.py``, copied whole. Records shares the mode detection (and, since
#210, the mounted-child rule) but keeps its own admin rule (#112), so its
copies are compared declaration by declaration for what they share; its other
binding entry points are listed to pin that the difference is deliberate.

The fail-closed ORM guard (#335) is one file in five modules — ``_guard.py``,
records' ``_tenant_guard.py`` — copied whole, and the names it imports
(``ALL_TENANTS``, ``TenantUnbound``) and the two entry points beside it
(``all_tenants``, ``install_guard``) are compared wherever each module keeps
them: the package ``__init__`` in records, images and newsletter, ``_scope.py``
in pagebuilder and news.
"""

from __future__ import annotations

from parity_support import Copy, Family

PB = "modules/pagebuilder/pagebuilder"
NEWS = "modules/news/news"
RECORDS = "modules/records/sm_records"
IMAGES = "modules/images/sm_images"
NEWSLETTER = "modules/newsletter/sm_newsletter"

_RECORDS_ADMIN = (
    "Records' admin rule (#112): on a multi-tenant host an anonymous request is "
    "401 before any tenant is resolved, and no organisation is TenantRequired "
    "with its own wording, where pagebuilder and news answer 403 tenant_required."
)

TENANCY_FAMILIES: tuple[Family, ...] = (
    Family(
        "tenancy mode detection",
        (
            Copy(f"{PB}/core/tenancy/_mode.py", {"pagebuilder": "MODULE"}),
            Copy(f"{NEWS}/core/tenancy/_mode.py", {"news": "MODULE"}),
        ),
    ),
    Family(
        "tenancy mode detection: records",
        (
            Copy(f"{PB}/core/tenancy/_mode.py"),
            Copy(
                f"{RECORDS}/core/tenancy/_mode.py",
                {"logger": "_log"},
            ),
            Copy(f"{IMAGES}/core/tenancy/_mode.py", {"logger": "_log"}),
            Copy(f"{NEWSLETTER}/core/tenancy/_mode.py", {"logger": "_log"}),
        ),
        shared=(
            "TenancyMode",
            "DEFAULT_TENANT",
            "_KNOWN_KWARGS",
            "_UNREADABLE",
            "_tenant_middleware",
            "_kwargs",
            "_fixed_tenant",
            "_warn_if_unrecognised",
            "_opaque_middleware",
            "_framework_mode",
            "request_mode",
            "pinned_tenants",
            "_PIN_SHOWN",
            "stray_pins",
            "detect_mode",
        ),
        differ={
            "mounted": "Pagebuilder and news take an own_prefix, a mount the app made itself "
            "(pagebuilder's media), which does not count as a parent's; records mounts none.",
            "scope_mode": "Passes own_prefix through to mounted; see mounted.",
        },
    ),
    Family(
        "tenancy binding",
        (
            # Both viewers answer a request that resolved no tenant with the
            # site's branded 404 (#89, #248), so bind_public_viewer is shared.
            Copy(f"{PB}/core/tenancy/__init__.py", {"pagebuilder": "MODULE"}),
            Copy(
                f"{NEWS}/core/tenancy/__init__.py",
                {"news": "MODULE"},
                own={
                    "search_tenant": "News' search reads pagebuilder's tables from outside "
                    "pagebuilder, so it pins tenant_id itself (CLAUDE.md, #38).",
                },
            ),
        ),
        differ={
            "_NOT_FOUND": "Each public viewer's own 404 wording, reused word for word for "
            "a request that resolved no tenant.",
            "__all__": "News also exports search_tenant.",
            "mode_of": "News also reads app.state.news_tenancy, where configure stores the "
            "mode on an app without news' services container.",
        },
    ),
    Family(
        "tenancy configure",
        (
            Copy(f"{PB}/core/tenancy/_configure.py", {"pagebuilder": "MODULE"}),
            Copy(f"{NEWS}/core/tenancy/_configure.py", {"news": "MODULE"}),
        ),
        differ={
            "configure": "News also warns that public_base_url on a multi-tenant host points "
            "every tenant's links at one origin, and stores the mode on "
            "app.state.news_tenancy without a services container; pagebuilder has neither.",
        },
    ),
    Family(
        "tenancy scope",
        (
            Copy(
                f"{PB}/core/tenancy/_scope.py",
                {"pagebuilder": "MODULE", "pagebuilder_all_tenants": "MODULE_all_tenants"},
            ),
            Copy(
                f"{NEWS}/core/tenancy/_scope.py",
                {"news": "MODULE", "news_all_tenants": "MODULE_all_tenants"},
            ),
        ),
    ),
    Family(
        "tenancy guard",
        (
            Copy(
                f"{PB}/core/tenancy/_guard.py",
                {"pagebuilder": "MODULE", "_pagebuilder_tenant_guard": "_MODULE_tenant_guard"},
            ),
            Copy(
                f"{NEWS}/core/tenancy/_guard.py",
                {"news": "MODULE", "_news_tenant_guard": "_MODULE_tenant_guard"},
            ),
            Copy(
                f"{RECORDS}/core/tenancy/_tenant_guard.py",
                {"sm_records": "MODULE", "_sm_records_tenant_guard": "_MODULE_tenant_guard"},
            ),
            Copy(
                f"{IMAGES}/core/tenancy/_guard.py",
                {"sm_images": "MODULE", "_sm_images_tenant_guard": "_MODULE_tenant_guard"},
            ),
            Copy(
                f"{NEWSLETTER}/core/tenancy/_guard.py",
                {
                    "sm_newsletter": "MODULE",
                    "_sm_newsletter_tenant_guard": "_MODULE_tenant_guard",
                },
            ),
        ),
    ),
    Family(
        "tenancy guard entry points",
        (
            Copy(
                f"{PB}/core/tenancy/_scope.py",
                {"pagebuilder": "MODULE", "pagebuilder_all_tenants": "MODULE_all_tenants"},
            ),
            Copy(
                f"{NEWS}/core/tenancy/_scope.py",
                {"news": "MODULE", "news_all_tenants": "MODULE_all_tenants"},
            ),
            Copy(
                f"{RECORDS}/core/tenancy/__init__.py",
                {
                    "sm_records": "MODULE",
                    "records_all_tenants": "MODULE_all_tenants",
                    "_tenant_guard": "_guard",
                },
            ),
            Copy(
                f"{IMAGES}/core/tenancy/__init__.py",
                {"sm_images": "MODULE", "images_all_tenants": "MODULE_all_tenants"},
            ),
            Copy(
                f"{NEWSLETTER}/core/tenancy/__init__.py",
                {"sm_newsletter": "MODULE", "newsletter_all_tenants": "MODULE_all_tenants"},
            ),
        ),
        shared=("ALL_TENANTS", "TenantUnbound", "all_tenants", "install_guard"),
    ),
    Family(
        "tenancy binding: records",
        (
            Copy(f"{PB}/core/tenancy/__init__.py"),
            Copy(f"{RECORDS}/core/tenancy/__init__.py", {"_resolved": "upstream_tenant"}),
            Copy(f"{IMAGES}/core/tenancy/__init__.py", {"_resolved": "upstream_tenant"}),
            Copy(f"{NEWSLETTER}/core/tenancy/__init__.py", {"_resolved": "upstream_tenant"}),
        ),
        shared=("resolve_public",),
        differ={
            "resolve_admin": _RECORDS_ADMIN,
            "bind_admin": "Records binds through its own tenant_scope, which refuses to "
            "rebind a different tenant inside a bound scope (TenantIsolationError).",
            "bind_public": "Records', images' and newsletter's public 404 is their NotFound error, "
            "rendered by their own error handlers.",
        },
    ),
)
