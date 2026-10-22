"""What the ``ArticlesService`` mixins require from the class that composes them.

The mixin chain (workflow → trash → revisions) reaches for ``self.db`` and
``self.get_article``, neither of which it defines. :class:`ArticlesHost` writes
that contract down (#133). :class:`~news.content._revisions.RevisionsMixin`, the
root of the chain, inherits :data:`HostBase`, which a type checker sees as the
Protocol and the interpreter sees as ``object`` — so a call to a member the
host does not declare is a type error, and the MRO is unchanged.

``tests/test_content_host.py`` asserts that ``ArticlesService`` satisfies it, so
a host member that is renamed or dropped fails a test even without a type
checker in CI. Add a member here before a mixin starts using it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from news.models import NewsArticle


@runtime_checkable
class ArticlesHost(Protocol):
    """The members every news content mixin may rely on."""

    db: AsyncSession

    async def get_article(
        self, article_id: int, *, include_trashed: bool = False
    ) -> NewsArticle: ...


if TYPE_CHECKING:
    HostBase = ArticlesHost
else:
    HostBase = object
