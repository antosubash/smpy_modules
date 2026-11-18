"""Who may read a type's records through :mod:`sm_records.contracts.dated`: records' own
rules and nothing wider. Split out of ``dated`` and re-exported there."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from simple_module_core.permissions import grants  # pyright: ignore[reportPrivateImportUsage] - the public name (re-exported at runtime)

from sm_records.core import constants
from sm_records.records.services._access import caller_access, role_blocked


@dataclass(frozen=True)
class DatedCaller:
    """The person a read is for: their roles, the permissions resolved for them and the host's
    role map (for the wildcard rule)."""

    roles: tuple[str, ...]
    permissions: frozenset[str]
    role_map: Mapping[str, Any] | None = None


def may_read(rtype: Any, caller: DatedCaller | None) -> bool:
    """Whether ``caller`` may read ``rtype``'s records as records' own list API would.

    ``None`` is the public: only a type that is ``is_public``. A person needs ``records.view``
    and must not be shut out by the type's ``allowed_roles`` (a ``records.type.<key>`` grant
    widens it; the admin wildcard does not, exactly as in the list API)."""
    if caller is None:
        return bool(rtype.is_public)
    if not grants(caller.permissions, constants.PERM_VIEW):
        return False
    access = caller_access(
        SimpleNamespace(roles=list(caller.roles)), caller.permissions, caller.role_map
    )
    return not role_blocked(rtype, access)
