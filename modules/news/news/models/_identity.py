"""Article identity and persisted workflow status values."""

import enum
from uuid import uuid4


def _new_translation_group() -> str:
    return uuid4().hex


# Deliberately (str, Enum) rather than enum.StrEnum: these values are persisted
# and serialised, and StrEnum changes what str()/f-strings produce for a member
# ("draft" instead of "ArticleStatus.DRAFT"). Switching is a data-format change,
# not a style fix.
class ArticleStatus(str, enum.Enum):  # noqa: UP042
    """Workflow state of an article.

    The values are the ones the wire format has always carried, so a client
    written against the sidecar era still reads them. What changed is who owns
    them: this is news' own enum on news' own column, not a neighbour's status
    mapped across a module boundary.
    """

    DRAFT = "draft"
    SUBMITTED_FOR_REVIEW = "submitted_for_review"
    PUBLISHED = "published"
