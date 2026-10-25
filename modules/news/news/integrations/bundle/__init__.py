"""News as a section of pagebuilder's content bundle (#80).

On a host running both modules, a snapshot (Import / Export, and the
``pre_restore`` safety snapshot) carries the tenant's articles in every
language, categories, tags and their links, article redirects and tag
redirects, under ``news/`` in the bundle. Media URLs inside articles travel as
pagebuilder's ``asset://`` sentinels. Not carried: revision history, trashed
articles, user ids on the audit columns and rejection notes. A restore never
deletes — articles, categories and tags the bundle does not carry are kept.

Optional (``required: false``): a host without news restores the pages and
keeps the section unread, and a bundle without it leaves the articles alone.

Inside the seam on purpose: this package imports :mod:`pagebuilder.contracts`
at module scope, and is imported only from
:func:`news.integrations.pagebuilder.register_bundle_section`, so news itself
never needs pagebuilder installed. It follows the contract's rules: it writes
only through ``ctx.db``, flushes and never commits, and uses the tenant
pagebuilder bound — it never resolves one (``news.tenancy`` is not consulted).
"""

from __future__ import annotations

from typing import ClassVar

from pagebuilder.contracts.bundle import (
    CaptureContext,
    RestoreContext,
    SectionApplied,
    SectionCapture,
    SectionPlan,
    ValidateContext,
)

from news.integrations.bundle import apply, capture, plan, validate

SECTION = "news"


class NewsBundleSection:
    name = SECTION
    version = 1
    readable_versions = frozenset({1})
    required = False
    label_key = "news.bundle.title"
    count_label_keys: ClassVar[dict[str, str]] = {
        kind: f"news.bundle.counts.{kind}"
        for kind in ("articles", "categories", "tags", "redirects")
    }

    async def capture(self, ctx: CaptureContext) -> SectionCapture:
        return await capture.capture(ctx)

    def validate(self, ctx: ValidateContext) -> None:
        validate.validate(ctx)

    async def plan(self, ctx: RestoreContext) -> SectionPlan:
        return await plan.plan(ctx)

    async def apply(self, ctx: RestoreContext) -> SectionApplied:
        return await apply.apply(ctx)


__all__ = ["SECTION", "NewsBundleSection"]
