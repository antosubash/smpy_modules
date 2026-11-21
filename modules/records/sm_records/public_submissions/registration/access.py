"""Who may see, and who may use, a registration form (PR 9).

One definition for the console's list of forms and for the events provider's ``check_target`` /
``can_read``, so the two cannot drift: a form is **visible** to someone holding ``records.view``
whose roles the type's ``allowed_roles`` do not shut out (what the type list already does), and
**usable** for an event when it is visible and they may also configure types
(``records.manage_types``):
attaching an event changes what the form collects, who it notifies and how long it keeps what it
collects. A form that is not usable and one that does not exist are one refusal.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from sm_records.core import constants
from sm_records.records.services._access import role_blocked

__all__ = ["can_use", "can_view"]


def can_view(rtype: Any, roles: Sequence[str] | None, permissions: Collection[str]) -> bool:
    return constants.PERM_VIEW in permissions and not role_blocked(rtype, list(roles or ()))


def can_use(rtype: Any, roles: Sequence[str] | None, permissions: Collection[str]) -> bool:
    return can_view(rtype, roles, permissions) and constants.PERM_MANAGE_TYPES in permissions
