"""What the ``PagesService`` mixins require from the class that composes them.

Each mixin reaches for ``self.db`` and ``self.get_page``, neither of which it
defines; the trash also needs ``self.event_bus``. :class:`PagesHost` writes the
shared contract down (#133) and :class:`TrashHost` adds the trash's one extra
member, so every other mixin's contract stays narrow and a new dependency on
the bus shows up in a test. The mixins inherit :data:`HostBase` (the trash
:data:`TrashHostBase`), which a type checker would see as the Protocol and the
interpreter sees as ``object``, so the composed class's MRO is unchanged.

No type checker runs in CI, so the enforcement is ``tests/test_service_host.py``:
an AST scan fails when a mixin uses a member its Protocol does not declare, and
an ``isinstance`` check fails when ``PagesService`` stops supplying one. Add a
member here before a mixin starts using it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from simple_module_core.events import EventBus
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.models import Page


@runtime_checkable
class PagesHost(Protocol):
    """The members every pagebuilder service mixin may rely on."""

    db: AsyncSession

    async def get_page(self, page_id: int, *, include_trashed: bool = False) -> Page: ...


@runtime_checkable
class TrashHost(PagesHost, Protocol):
    """:class:`PagesHost`, plus the bus the trash announces deletions on."""

    event_bus: EventBus | None


if TYPE_CHECKING:
    HostBase = PagesHost
    TrashHostBase = TrashHost
else:
    HostBase = object
    TrashHostBase = object
