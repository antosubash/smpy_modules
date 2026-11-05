"""Who in the list a campaign goes to: the seam segments fill (ruling S3).

Freeze takes its subscriber filters from :func:`audience_filters`. Until PR 6
ships segments and the tag picker, only the whole list (``all``) exists, and
anything else is refused with 422 ``audience_unsupported``.
"""

from __future__ import annotations

from sm_newsletter.core.errors import AudienceUnsupported

AUDIENCE_ALL = "all"


def audience_filters(audience: str) -> list[str]:
    """The subscriber filters for ``audience``: none for the whole list."""
    if audience == AUDIENCE_ALL:
        return []
    raise AudienceUnsupported()
