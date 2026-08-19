"""Pydantic request/response schemas for the pagebuilder API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from pagebuilder.models import PageStatus, RevisionEvent

PuckData = dict[str, Any]


def _blank_to_none(value: Any) -> Any:
    return None if value == "" else value


# A status filter read off a query string. "?status=" — what an unset filter
# control serialises to, and what a hand-edited URL naturally produces — means
# "no filter", not "the empty status", which would otherwise 422. A non-empty
# value that is not a status still fails validation.
StatusFilter = Annotated[PageStatus | None, BeforeValidator(_blank_to_none)]


class PageCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    slug: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9-]*$")
    meta_title: str | None = Field(default=None, max_length=200)
    meta_description: str | None = Field(default=None, max_length=500)
    show_in_header_nav: bool = False
    show_in_footer: bool = False
    og_image: str | None = Field(default=None, max_length=500)
    canonical_url: str | None = Field(default=None, max_length=500)
    index_in_search: bool = True
    json_ld: dict[str, Any] | None = None
    draft_data: PuckData = Field(default_factory=dict)
    publish_at: datetime | None = None
    unpublish_at: datetime | None = None
    parent_id: int | None = None
    """Breadcrumb parent. Deliberately does not affect the public URL."""

    is_template: bool = False
    copy_from_page_id: int | None = None
    """Start from an existing page's content — the New page dialog's
    "Copy a page" and its template list are the same operation.

    Write-only: it seeds ``draft_data`` at creation and is not stored, so a
    later edit of the source never reaches back into the copy.
    """


class PageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    slug: str | None = Field(
        default=None, min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    meta_title: str | None = Field(default=None, max_length=200)
    meta_description: str | None = Field(default=None, max_length=500)
    show_in_header_nav: bool | None = None
    show_in_footer: bool | None = None
    og_image: str | None = Field(default=None, max_length=500)
    canonical_url: str | None = Field(default=None, max_length=500)
    index_in_search: bool | None = None
    json_ld: dict[str, Any] | None = None
    draft_data: PuckData | None = None
    parent_id: int | None = None
    is_template: bool | None = None


class PageScheduleRequest(BaseModel):
    """Schedule a future flip into / out of ``published``.

    Both fields are optional and independent — set ``publish_at`` to flip
    a draft live, set ``unpublish_at`` to take a published page down, or
    set both for a bounded campaign. Send ``null`` to clear an existing
    schedule. Sending ``{}`` is a no-op.
    """

    publish_at: datetime | None = None
    unpublish_at: datetime | None = None


class PageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    status: PageStatus
    has_published: bool
    meta_title: str | None = None
    meta_description: str | None
    og_image: str | None
    canonical_url: str | None = None
    index_in_search: bool = True
    rejection_note: str | None
    publish_at: datetime | None = None
    unpublish_at: datetime | None = None
    parent_id: int | None = None
    is_template: bool = False
    show_in_header_nav: bool = False
    show_in_footer: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None


class PageDetail(PageRead):
    draft_data: PuckData
    published_data: PuckData | None
    json_ld: dict[str, Any] | None = None


class PageListResponse(BaseModel):
    items: list[PageRead]
    # Matches before paging, so a caller showing one page at a time can size
    # its pager. Equal to len(items) whenever the whole result set was asked
    # for, which is the default.
    total: int = 0


class PageRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    page_id: int
    title: str
    meta_description: str | None
    og_image: str | None
    event: RevisionEvent
    note: str | None
    created_at: datetime
    created_by: str | None


class PageRevisionDetail(PageRevisionRead):
    data: PuckData


class PageRevisionListResponse(BaseModel):
    items: list[PageRevisionRead]


class PageRejectRequest(BaseModel):
    """Approver-supplied reason for sending a submission back to draft.

    Required and non-empty so the editor history panel always has
    actionable feedback — an empty rejection is a 422 from the API.
    """

    note: str = Field(min_length=1, max_length=2000)


class PageNoteRequest(BaseModel):
    """Optional author note attached to a publish / approve / unpublish.

    Body is always required by FastAPI when the endpoint declares this
    schema; clients send ``{}`` (or ``{"note": null}``) to opt out.
    """

    note: str | None = Field(default=None, max_length=2000)


class BlockChange(BaseModel):
    id: str
    type: str | None = None
    fields: list[str] = Field(default_factory=list)
    type_before: str | None = None


class MetadataChange(BaseModel):
    before: Any = None
    after: Any = None


class RevisionDiffResponse(BaseModel):
    """Block-level diff between two revisions.

    ``metadata`` only contains keys whose value actually changed;
    ``blocks`` is always present so the client can render an empty diff
    ("no changes") deterministically.
    """

    before_id: int
    after_id: int
    metadata: dict[str, MetadataChange] = Field(default_factory=dict)
    blocks: dict[str, list[BlockChange]] = Field(default_factory=dict)


class LayoutUpdate(BaseModel):
    """``None`` leaves a slot alone; an empty Puck doc clears it."""

    header_data: PuckData | None = None
    footer_data: PuckData | None = None
    note: str | None = Field(default=None, max_length=2000)


class LayoutRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None


class LayoutDetail(LayoutRead):
    header_data: PuckData
    footer_data: PuckData


class LayoutRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    layout_id: int
    note: str | None
    created_at: datetime
    created_by: str | None


class LayoutRevisionDetail(LayoutRevisionRead):
    header_data: PuckData
    footer_data: PuckData


class LayoutRevisionListResponse(BaseModel):
    items: list[LayoutRevisionRead]


class MediaAssetVariant(BaseModel):
    """One server-generated derivative of an uploaded image.

    Width is the canonical key for ``srcset`` so it's required; height is
    optional because some derivatives (e.g. a same-size webp transcode of
    a non-decodable input) may not carry it back.
    """

    filename: str
    url: str
    content_type: str
    width: int
    height: int | None = None
    size_bytes: int


class MediaAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    original_filename: str
    content_type: str
    size_bytes: int
    url: str
    width: int | None = None
    height: int | None = None
    folder: str | None = None
    variants: dict[str, MediaAssetVariant] = Field(default_factory=dict)
    created_at: datetime


class MediaAssetListResponse(BaseModel):
    """Cursor-paginated page of media assets.

    ``next_cursor`` is the ``id`` to pass back as the ``cursor`` query
    param to fetch the next page (assets are returned newest-first, so
    the cursor advances toward smaller ids). ``None`` when there are no
    more rows. ``folders`` is the full set of distinct folder names in
    the library — independent of the current filter so the sidebar
    doesn't disappear when the user drills in.
    """

    items: list[MediaAssetRead]
    next_cursor: int | None = None
    folders: list[str] = Field(default_factory=list)
    total: int | None = None
    """Row count matching the filters. Only set for offset paging — cursor
    paging deliberately avoids the extra COUNT query."""
