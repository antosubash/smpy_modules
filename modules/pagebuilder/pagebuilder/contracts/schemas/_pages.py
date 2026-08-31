"""Page create/read/update, revisions and diffs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from pagebuilder.locales import MAX_LOCALE_LEN
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
    locale: str | None = Field(default=None, max_length=MAX_LOCALE_LEN)
    """Language to author in. ``None`` means the default content locale.

    A page created this way starts a translation group of its own. Joining an
    existing one is ``POST /pages/{id}/translations`` and nothing else — a
    group id on this schema would let any caller graft a page onto any other
    page's language set, which is a data-integrity decision rather than a
    field.
    """

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
    locale: str
    translation_group: str
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


class LocalesResponse(BaseModel):
    """The languages this deployment publishes in.

    Served to the admin client so the language switcher, the New page dialog
    and news' own article screens offer exactly what the API will accept.
    Hardcoding the list in the frontend is the failure this prevents: it shows
    a language, the author picks it, and the create call 422s.
    """

    locales: list[str]
    default: str
    """The one that serves at the unprefixed public URL."""


class PageTranslationRead(BaseModel):
    """One page of a translation group, as its siblings need to see it.

    Deliberately not a ``PageRead``: the language switcher needs a name, an
    address and whether the translation is live, and shipping the whole read
    model for every sibling would put N copies of every SEO field on a page
    that renders one row per language.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    locale: str
    slug: str
    title: str
    status: PageStatus
    trashed: bool = False
    """This counterpart is in the trash awaiting purge.

    Carried because ``(translation_group, locale)`` is unique *including*
    trashed rows, so the language is occupied and starting a new translation
    in it would be refused. A panel that omitted trashed siblings would offer
    a button that only ever 409s.
    """


class PageTranslationCreate(BaseModel):
    """Start a page's counterpart in another language."""

    locale: str = Field(min_length=2, max_length=MAX_LOCALE_LEN)

    slug: str | None = Field(
        default=None, min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    """Address within the new language. Defaults to the source page's own.

    Reusing it is safe and usually right — slugs are unique per language, so
    ``/p/about`` and ``/de/p/about`` do not collide — and a translator who
    wants ``/de/p/ueber-uns`` says so here.
    """

    title: str | None = Field(default=None, min_length=1, max_length=300)
    """Defaults to the source's title, i.e. untranslated. That is deliberate:
    an empty heading is not a better starting point than the original text,
    and it makes what still needs translating obvious."""

    copy_content: bool = True
    """Seed the draft from the source page's blocks.

    On by default because a translator's job is to replace copy, not to
    rebuild a layout. Turn it off to start from an empty document.
    """


class PageDetail(PageRead):
    draft_data: PuckData
    published_data: PuckData | None
    json_ld: dict[str, Any] | None = None
    translations: list[PageTranslationRead] = Field(default_factory=list)
    """Every page in this one's translation group, itself included.

    Populated by the caller rather than by ``from_attributes``: the siblings
    are a separate query, and a lazy relationship would load them on attribute
    access — under the async session, that raises ``MissingGreenlet`` rather
    than working.
    """


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


