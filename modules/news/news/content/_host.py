"""What the ``ArticlesService`` mixins require from the class that composes them.

The mixin chain (workflow → trash → revisions) reaches for ``self.db`` and
``self.get_article``, neither of which it defines. :class:`ArticlesHost` writes
that contract down (#133). :class:`~news.content._revisions.RevisionsMixin`, the
root of the chain, inherits :data:`HostBase`, which a type checker would see as
the Protocol and the interpreter sees as ``object``, so the MRO is unchanged.

No type checker runs in CI, so the enforcement is ``tests/test_content_host.py``:
an AST scan fails when a mixin uses a member the Protocol does not declare, and
an ``isinstance`` check fails when ``ArticlesService`` stops supplying one. Add a
member here before a mixin starts using it.
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
