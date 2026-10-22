"""What the ``PagesService`` mixins require from the class that composes them.

Each mixin reaches for ``self.db``, ``self.get_page`` and, in the trash,
``self.event_bus`` — none of which it defines. :class:`PagesHost` writes that
contract down (#133). The mixins inherit :data:`HostBase`, which a type checker
sees as the Protocol and the interpreter sees as ``object``, so a call to a
member the host does not declare is a type error instead of an
``AttributeError`` at runtime, and the composed class's MRO is unchanged.

``tests/test_service_host.py`` asserts that ``PagesService`` satisfies it, so a
host member that is renamed or dropped fails a test even without a type checker
in CI. Add a member here before a mixin starts using it.
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
    event_bus: EventBus | None

    async def get_page(self, page_id: int, *, include_trashed: bool = False) -> Page: ...


if TYPE_CHECKING:
    HostBase = PagesHost
else:
    HostBase = object
