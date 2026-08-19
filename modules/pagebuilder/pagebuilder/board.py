"""Stage-grouped view of the page list — the board behind ``?view=board``.

The pipeline is two-state: a page is a draft or it is published. "Scheduled" is
not a third state, it is a draft carrying a future ``publish_at`` that will flip
itself; splitting it into its own column is a *display* decision, made here
rather than in the model precisely so nothing downstream has to learn a status
that does not exist.

Each column is capped and reports its own total, so a site with 400 published
pages renders three short columns and says how much it is not showing, instead
of paginating a board — which nobody can read anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.models import Page, PageStatus

DRAFT = "draft"
SCHEDULED = "scheduled"
IN_REVIEW = "in_review"
PUBLISHED = "published"

#: Rows shown per column before the "N more" line takes over.
PER_STAGE = 8


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    items: list[Page]
    total: int


def _search_filter(search: str | None):
    """Reuses the escaping rule from ``list_pages`` — a title containing ``%``
    is searched for literally rather than matching everything."""
    if not search or not search.strip():
        return None
    term = search.strip().translate(str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"}))
    pattern = f"%{term}%"
    return Page.title.ilike(pattern, escape="\\") | Page.slug.ilike(pattern, escape="\\")


def _conditions(stage: str, now: datetime) -> list:
    """What puts a page in this column.

    Templates are excluded from every column. They are ordinary pages, but they
    are not *in* the pipeline — nobody publishes a template — so listing them
    under Draft would put permanent residents in a column that is meant to read
    as a queue. They stay reachable in the list view, and in the New page
    dialog, which is where they are actually used.

    Draft and scheduled are deliberately complementary halves of
    ``status == DRAFT``: a page with no ``publish_at``, or one whose date has
    already passed, is simply a draft. Without the second half a scheduled page
    whose moment arrived but whose job has not yet run would vanish from the
    board entirely.
    """
    not_template = Page.is_template.is_(False)
    if stage == DRAFT:
        return [
            not_template,
            Page.status == PageStatus.DRAFT,
            (Page.publish_at.is_(None)) | (Page.publish_at <= now),
        ]
    if stage == SCHEDULED:
        return [not_template, Page.status == PageStatus.DRAFT, Page.publish_at > now]
    if stage == IN_REVIEW:
        return [not_template, Page.status == PageStatus.SUBMITTED_FOR_REVIEW]
    return [not_template, Page.status == PageStatus.PUBLISHED]


_ORDER = [
    (DRAFT, "Draft"),
    (SCHEDULED, "Scheduled"),
    (IN_REVIEW, "In review"),
    (PUBLISHED, "Published"),
]


async def load(
    db: AsyncSession, *, search: str | None = None, per_stage: int = PER_STAGE
) -> list[Stage]:
    """Every column, in pipeline order.

    ``In review`` is returned even when empty; the caller drops it, because
    whether the approval workflow is in use is a question about the site rather
    than about this query.
    """
    now = datetime.now(UTC)
    search_clause = _search_filter(search)

    stages: list[Stage] = []
    for key, label in _ORDER:
        clauses = _conditions(key, now)
        if search_clause is not None:
            clauses = [*clauses, search_clause]

        total = await db.scalar(select(func.count()).select_from(Page).where(*clauses))
        # Scheduled sorts by when it fires — the next one to go live is the one
        # worth seeing first. Every other column is newest-touched first.
        order = Page.publish_at.asc() if key == SCHEDULED else Page.id.desc()
        rows = await db.execute(select(Page).where(*clauses).order_by(order).limit(per_stage))
        stages.append(
            Stage(key=key, label=label, items=list(rows.scalars().all()), total=int(total or 0))
        )
    return stages
