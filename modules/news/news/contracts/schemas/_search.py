"""Results of the admin search, which spans articles, pages and media."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    """One result, in whatever section found it."""

    id: int
    title: str
    subtitle: str
    """The line under the title — category and status, or a path, or a MIME
    type. Which of those it is depends on the section, which is why it is one
    pre-rendered string rather than a shape the screen has to branch on."""

    url: str
    excerpt: str = ""


class SearchResults(BaseModel):
    """Hits per section, plus how many each section actually has.

    The totals are separate from the lists because each section shows only its
    first few: "17 more articles" is the design's own affordance, and it needs a
    number the list itself cannot supply.
    """

    query: str
    articles: list[SearchHit] = Field(default_factory=list)
    pages: list[SearchHit] = Field(default_factory=list)
    media: list[SearchHit] = Field(default_factory=list)
    article_total: int = 0
    page_total: int = 0
    media_total: int = 0

    pages_more_url: str = ""
    media_more_url: str = ""
    """Where each section's "see all" goes.

    Sent rather than assembled in the screen because both land in pagebuilder,
    and how that module routes its own list and its media library is not
    something this one should be spelling out in TSX — see
    ``news.integrations.pagebuilder``.
    """

    @property
    def total(self) -> int:
        return self.article_total + self.page_total + self.media_total
