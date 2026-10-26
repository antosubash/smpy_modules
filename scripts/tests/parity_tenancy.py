"""The tenancy copies, and every way they are allowed to differ (#127, #204).

Split out of ``parity_families.py``, which appends these to ``FAMILIES``; the
rules there apply here — an allowance is a decision, and says why.

Pagebuilder and news carry one design (#38, #125, #192, #211): mode detection
in ``_tenancy_mode.py`` and request binding in ``tenancy.py``, copied whole.
Records shares the mode detection (and, since #210, the mounted-child rule)
but keeps its own admin rule (#112), so its copies are compared declaration by
declaration for what they share; its other binding entry points are listed to
pin that the difference is deliberate.
"""

from __future__ import annotations

from parity_support import Copy, Family

PB = "modules/pagebuilder/pagebuilder"
NEWS = "modules/news/news"
RECORDS = "modules/records/sm_records"

_RECORDS_ADMIN = (
    "Records' admin rule (#112): on a multi-tenant host an anonymous request is "
    "401 before any tenant is resolved, and no organisation is TenantRequired "
    "with its own wording, where pagebuilder and news answer 403 tenant_required."
)

TENANCY_FAMILIES: tuple[Family, ...] = (
    Family(
        "tenancy mode detection",
        (
            Copy(f"{PB}/_tenancy_mode.py", {"pagebuilder": "MODULE"}),
            Copy(f"{NEWS}/_tenancy_mode.py", {"news": "MODULE"}),
        ),
    ),
    Family(
        "tenancy mode detection: records",
        (
            Copy(f"{PB}/_tenancy_mode.py"),
            Copy(
                f"{RECORDS}/_tenancy_mode.py",
                {"logger": "_log"},
            ),
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
            Copy(f"{PB}/tenancy.py", {"pagebuilder": "MODULE"}),
            Copy(
                f"{NEWS}/tenancy.py",
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
            "configure": "News also warns that public_base_url on a multi-tenant host points "
            "every tenant's links at one origin; pagebuilder has no such setting.",
            "mode_of": "News also reads app.state.news_tenancy, where configure stores the "
            "mode on an app without news' services container.",
        },
    ),
    Family(
        "tenancy binding: records",
        (
            Copy(f"{PB}/tenancy.py"),
            Copy(f"{RECORDS}/tenancy.py", {"_resolved": "upstream_tenant"}),
        ),
        shared=("resolve_public",),
        differ={
            "resolve_admin": _RECORDS_ADMIN,
            "bind_admin": "Records binds through its own tenant_scope, which refuses to "
            "rebind a different tenant inside a bound scope (TenantIsolationError).",
            "bind_public": "Records' public 404 is its NotFound error, rendered by its "
            "own error pages.",
        },
    ),
)
