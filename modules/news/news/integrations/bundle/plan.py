"""What restoring the ``news/`` section would do, for the approver (#80).

Read-only. The lines answer the approver's question — *what am I about to
lose?* — the way pagebuilder's own page groups do: new articles, the ones
overwritten (a warning), the trashed ones the restore brings back, the ones
moved back to their snapshot address, and the ones the bundle does not carry,
which are kept rather than deleted. A restore never deletes.
"""

from __future__ import annotations

from pagebuilder.contracts.bundle import PlanItem, PlanLine, RestoreContext, SectionPlan

from news.integrations.bundle.documents import ArticleKey
from news.integrations.bundle.prepare import Prepared, prepare

LINE_KEYS: dict[str, str] = {
    "new": "news.bundle.plan.new",
    "overwritten": "news.bundle.plan.overwritten",
    "revived": "news.bundle.plan.revived",
    "renamed_from": "news.bundle.plan.renamed_from",
    "unchanged": "news.bundle.plan.unchanged",
    "untouched": "news.bundle.plan.untouched",
    "category_respelled": "news.bundle.plan.category_respelled",
    "categories": "news.bundle.plan.categories",
    "tags": "news.bundle.plan.tags",
    "redirects_dropped": "news.bundle.plan.redirects_dropped",
}
"""Every plan line's label, spelled out (the catalogue check reads these)."""


def _item(prep: Prepared, key: ArticleKey) -> PlanItem:
    title = prep.articles[key].get("title") or key[1]
    return PlanItem(title=title, slug=key[1], locale=key[0])


def plan_lines(prep: Prepared) -> SectionPlan:
    match = prep.match
    new = sorted(match.creates)
    revived = sorted(k for k, row in match.rows.items() if row.deleted_at is not None)
    overwritten = sorted(k for k in match.rows if k not in revived and prep.changed(k))
    unchanged = sorted(k for k in match.rows if k not in revived and k not in overwritten)
    untouched = sorted(
        (row for row in match.untouched if row.deleted_at is None),
        key=lambda row: (row.locale, row.slug),
    )
    # Article redirects carry their language; tag redirects have none.
    respelled = prep.respelled()
    dropped = [
        PlanItem(title=r["from_slug"], slug=r["from_slug"], locale=r["locale"])
        for r in prep.dropped_redirects()
    ] + [
        PlanItem(title=r["from_slug"], slug=r["from_slug"], note_key=LINE_KEYS["tags"])
        for r in prep.dropped_tag_redirects()
    ]

    def line(name: str, keys: list[ArticleKey], tone: str | None = None) -> PlanLine:
        return PlanLine(
            LINE_KEYS[name],
            len(keys),
            [_item(prep, k) for k in keys],
            "warning" if tone else None,
        )

    lines = [
        line("new", new),
        line("overwritten", overwritten, "warning"),
        line("revived", revived, "warning"),
        line("renamed_from", sorted(match.renames)),
        line("unchanged", unchanged),
        PlanLine(
            LINE_KEYS["untouched"],
            len(untouched),
            [PlanItem(title=r.title, slug=r.slug, locale=r.locale) for r in untouched],
        ),
        PlanLine(
            LINE_KEYS["category_respelled"],
            len(respelled),
            [PlanItem(title=r.title, slug=r.slug, locale=r.locale) for r in respelled],
            "warning" if respelled else None,
        ),
        PlanLine(
            LINE_KEYS["categories"],
            len(prep.categories),
            [PlanItem(title=c["name"], slug=c["slug"]) for c in prep.categories],
        ),
        PlanLine(
            LINE_KEYS["tags"],
            len(prep.tags),
            [PlanItem(title=t["name"], slug=t["slug"]) for t in prep.tags],
        ),
        PlanLine(
            LINE_KEYS["redirects_dropped"],
            len(dropped),
            dropped,
            "warning" if dropped else None,
        ),
    ]
    return SectionPlan(lines=lines, overwrites=len(overwritten) + len(revived))


async def plan(ctx: RestoreContext) -> SectionPlan:
    return plan_lines(await prepare(ctx))
