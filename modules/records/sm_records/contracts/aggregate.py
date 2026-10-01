"""The aggregate endpoint's response shape — Phase 5 §5.1 and §5.2.

**One shape for both readings**, which is the whole point of putting the
maintained aggregate on the same endpoint as the live ``GROUP BY``: a caller
switches ``?reduce=`` on and off and compares the two without reshaping
anything. ``stored`` is what says which one answered.

Every value is a **string**, including the numbers. A group read from
``records_index_reduce`` is text by construction (one column holds every
spec's groups, whatever a host folded on), and a live group that came back as
a ``Decimal`` here and as a string there would make the comparison the two
readings exist for a per-field exercise in coercion. ``count`` is the one
integer, because it is a count in both readings and always will be.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import SQLModel


class AggregateGroup(SQLModel):
    """One group. ``sum``/``min``/``max`` are ``null`` unless the metric asked
    for them — a stored row carries ``sum`` only when its spec declares a
    ``value``, and a ``count`` metric carries none of the three."""

    value: str | None
    count: int
    sum: str | None = None
    min: str | None = None
    max: str | None = None


class AggregateResponse(SQLModel):
    """``total_groups`` is how many groups this response carries, not how many
    exist: the query stops at ``max_aggregate_groups``, and ``truncated`` says
    whether it stopped early. An unbounded group count is as expensive as an
    unbounded record count and is capped for the same reason (F4)."""

    group_by: str
    metric: str
    groups: list[AggregateGroup]
    total_groups: int
    truncated: bool
    stored: bool = False
    """``true`` when the rows came from ``records_index_reduce`` rather than
    from a live ``GROUP BY`` — i.e. when the caller passed ``?reduce=``."""
    updated_at: datetime | None = None
    """The newest ``updated_at`` across the stored rows, so a caller can see
    how far behind a maintained aggregate is. ``null`` for a live aggregate,
    which is by definition current."""
