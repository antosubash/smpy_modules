"""SQLModel tables for the news module.

An article owns its body, its address and its workflow. It was once a sidecar
over a ``pagebuilder_pages`` row — see :mod:`news.models._article` for what that
cost and why it ended.

Split into one file per concern so no single file carries the whole schema, and
re-exported here so ``from news.models import NewsArticle`` keeps working
wherever it already did.
"""

from __future__ import annotations

from news.models._article import NOT_TRASHED, ArticleStatus, NewsArticle
from news.models._base import ARTICLE_TABLE, Base
from news.models._redirect import NewsArticleRedirect
from news.models._revision import NewsArticleRevision, RevisionEvent
from news.models._taxonomy import NewsArticleTag, NewsCategory, NewsTag

__all__ = [
    "ARTICLE_TABLE",
    "NOT_TRASHED",
    "ArticleStatus",
    "Base",
    "NewsArticle",
    "NewsArticleRedirect",
    "NewsArticleRevision",
    "NewsArticleTag",
    "NewsCategory",
    "NewsTag",
    "RevisionEvent",
]
