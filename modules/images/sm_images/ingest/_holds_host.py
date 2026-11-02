"""What :class:`~sm_images.ingest.service_holds.HoldsMixin` requires from the
class that composes it (#133).

The mixin reaches for ``self.db``, ``self.intent_factory`` and
``self.acquired``, none of which it defines. :class:`HoldsHost` writes that
contract down; the mixin inherits :data:`HostBase` (the Protocol for a type
checker, ``object`` for the interpreter, so the MRO is unchanged).
``tests/ingest/test_service_holds_host.py`` fails when the mixin uses a member
this does not declare. Add a member here before the mixin uses it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

__all__ = ["HoldsHost", "HostBase"]


@runtime_checkable
class HoldsHost(Protocol):
    db: Any
    intent_factory: Any
    acquired: list[Any]
    """Every op held in ``db`` (``HoldsMixin.release_holds``)."""


if TYPE_CHECKING:
    HostBase = HoldsHost
else:
    HostBase = object
