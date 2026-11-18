"""The public-surface copies of events and their siblings, and how they may differ (#127).

Split out of ``parity_families.py``, which appends these to ``FAMILIES``; the rules there apply
here: an allowance is a decision, and says why.
"""

from __future__ import annotations

from parity_support import Copy, Family

PB = "modules/pagebuilder/pagebuilder"
NEWS = "modules/news/news"
EVENTS = "modules/events/sm_events"

NEWSLETTER = "modules/newsletter/sm_newsletter"

PUBLIC_FAMILIES: tuple[Family, ...] = (
    Family(
        "tenant a host resolved, for a token link (newsletter, events)",
        (
            Copy(f"{NEWSLETTER}/web/endpoints/public_tenant.py"),
            Copy(f"{EVENTS}/web/endpoints/public/_host_tenant.py"),
        ),
        shared=("HOST_SOURCES", "host_tenant"),
    ),
    Family(
        "public cache-control (pagebuilder, news)",
        (
            Copy(f"{PB}/web/public_cache.py", {"PagebuilderSettings": "Settings"}),
            Copy(f"{NEWS}/web/endpoints/public/_urls.py", {"NewsSettings": "Settings"}),
        ),
        shared=("cache_control", "etag_for"),
        differ={
            "etag_for": "A page's chrome also changes with the site layout and the nav list, "
            "so pagebuilder digests layout_updated_at and nav as well; an article has neither.",
        },
    ),
    Family(
        "content locales: resolve (pagebuilder, news)",
        (Copy(f"{PB}/core/locales.py"), Copy(f"{NEWS}/core/locales.py")),
        shared=("resolve",),
    ),
    Family(
        "public head injection (Python)",
        (
            Copy(f"{NEWS}/web/endpoints/public/_head.py"),
            Copy(f"{EVENTS}/web/endpoints/public/_head.py"),
        ),
        shared=("_CLOSE_HEAD", "_EXISTING_TITLE", "_tag", "_alternate_links", "inject"),
    ),
    Family(
        "plugin loader: find the extensions module (images, events)",
        (
            Copy(
                "modules/images/sm_images/pipeline/extensions.py",
                messages=("images: entry-point package %r is not importable; skipped",),
            ),
            Copy(
                "modules/events/sm_events/calendar/plugins/extensions.py",
                {"constants.EXTENSIONS_MODULE": "EXTENSIONS_MODULE"},
                messages=("events: entry-point package %r is not importable; skipped",),
            ),
        ),
        shared=("_find",),
    ),
)
