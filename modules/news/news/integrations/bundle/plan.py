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

_KEY = "news.bundle.plan."


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
    dropped = prep.dropped_redirects()

    def line(name: str, keys: list[ArticleKey], tone: str | None = None) -> PlanLine:
        return PlanLine(
            _KEY + name,
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
            _KEY + "untouched",
            len(untouched),
            [PlanItem(title=r.title, slug=r.slug, locale=r.locale) for r in untouched],
        ),
        PlanLine(
            _KEY + "categories",
            len(prep.categories),
            [PlanItem(title=c["name"], slug=c["slug"]) for c in prep.categories],
        ),
        PlanLine(
            _KEY + "tags",
            len(prep.tags),
            [PlanItem(title=t["name"], slug=t["slug"]) for t in prep.tags],
        ),
        PlanLine(
            _KEY + "redirects_dropped",
            len(dropped),
            [
                PlanItem(title=r["from_slug"], slug=r["from_slug"], locale=r["locale"])
                for r in dropped
            ],
            "warning" if dropped else None,
        ),
    ]
    return SectionPlan(lines=lines, overwrites=len(overwritten) + len(revived))


async def plan(ctx: RestoreContext) -> SectionPlan:
    return plan_lines(await prepare(ctx))
