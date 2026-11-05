"""Failures of segments and audiences (PR 6). None repeats a submitted value."""

from __future__ import annotations

from sm_newsletter.core.errors import NewsletterError


class InvalidSegment(NewsletterError):  # noqa: N818 - names the payload
    """Detail ``rules[i]: ...`` or ``filter: <records reason>``."""

    status = 422
    code = "invalid_segment"
    detail = "The segment is not valid"


class SegmentNameTaken(NewsletterError):  # noqa: N818 - the state it refuses
    status = 409
    code = "segment_name_taken"
    detail = "A segment with that name already exists on this list"


class SegmentInUse(NewsletterError):  # noqa: N818 - the state it refuses
    status = 409
    code = "segment_in_use"
    detail = "A draft campaign still uses this segment"


class UnknownSegment(NewsletterError):  # noqa: N818 - names the field
    status = 422
    code = "unknown_segment"
    detail = "No such segment"


class SegmentListMismatch(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "segment_list_mismatch"
    detail = "The segment belongs to a different list"


class UnknownTag(NewsletterError):  # noqa: N818 - names the field
    status = 422
    code = "unknown_tag"
    detail = "That tag does not exist on this list"


class InvalidAudience(NewsletterError):  # noqa: N818 - names the field
    status = 422
    code = "invalid_audience"
    detail = "The audience is not valid"


class InvalidQuery(NewsletterError):  # noqa: N818 - names the parameter
    """A bad query parameter on a listing; never echoes it."""

    status = 422
    code = "invalid_query"
    detail = "A query parameter is not valid"
