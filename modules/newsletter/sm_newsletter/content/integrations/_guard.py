"""The one guarded access to an optional sibling's contract, shared by every integration.

``importlib.import_module`` at call time, never ``from sibling.contracts import x``: the latter
finds an attribute left on the package and would ignore a blocked import. A source is available
when its contract imports *and* its module is mounted on the app (the contract's ``mounted``).
"""

from __future__ import annotations

import importlib
from typing import Any

from sm_newsletter.core.errors import IntegrationUnavailable

__all__ = ["Guard"]


class Guard:
    def __init__(self, contract: str) -> None:
        self.contract = contract

    def load(self) -> Any | None:
        try:
            return importlib.import_module(self.contract)
        except ImportError:
            return None

    def available(self, app: Any) -> bool:
        module = self.load()
        return module is not None and module.mounted(app)

    def require(self, app: Any) -> Any:
        """The contract module, or :class:`IntegrationUnavailable` (409 on the routes)."""
        module = self.load()
        if module is None or not module.mounted(app):
            raise IntegrationUnavailable()
        return module
