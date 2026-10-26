"""Who may reach a type's records: ``allowed_roles``, widened by a per-type grant.

Design §10's narrowing has one owner, :func:`role_blocked`, and every path
that applies it — ``deps.check_type_roles`` (the type in the URL), the delete
planner (a type a cascade or a ``set_null`` reaches), the reads that report a
relation target as ``restricted``, and the per-type sidebar entries — asks it
the same question. A second copy of "may this caller see this type" is how the
read path ends up more permissive than the write path.

Since framework 0.0.36 (upstream #334) a type also has a framework permission
of its own, ``records.type.<key>``, which the role editor lists through
``PermissionRegistry.add_source`` (:mod:`sm_records.type_permissions`). It
*widens* the narrowing: a caller holding it is admitted to the type even when
``allowed_roles`` names none of their roles. Nothing else changes, so an
install that grants none of these keys keeps exactly the access it had.

The caller reaches the services as a role list — the signature every one of
them already takes — so the per-type grants ride along on it as
:class:`CallerRoles`, a ``list`` with the keys attached.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from simple_module_core.permissions import DEFAULT_ROLE_PERMISSIONS, WILDCARD

from sm_records import constants

__all__ = [
    "CallerRoles",
    "caller_access",
    "request_role_map",
    "role_blocked",
    "type_grants",
    "type_permission",
]


class CallerRoles(list[str]):
    """A caller's roles, plus the type keys they hold ``records.type.<key>`` for."""

    def __init__(self, roles: Sequence[str] = (), granted: Collection[str] = ()) -> None:
        super().__init__(roles)
        self.granted_types: frozenset[str] = frozenset(granted)


def type_permission(key: str) -> str:
    """The per-type permission for type ``key``."""
    return f"{constants.PERM_TYPE_PREFIX}{key}"


def type_grants(held: Collection[str]) -> frozenset[str]:
    """The type keys ``held`` (a resolved permission set) grants per-type access to.

    A wildcard holder gets none, deliberately: narrowing has never had an
    admin exception (an ``admin`` not listed in ``allowed_roles`` is refused),
    and the ``permissions`` module mirrors every registered key onto the admin
    role at startup — honouring those rows would make admin exempt from every
    narrowed type the first time the host restarted. An admin is let in the
    way it always was: by naming the role in ``allowed_roles``.
    """
    if WILDCARD in held:
        return frozenset()
    prefix = constants.PERM_TYPE_PREFIX
    return frozenset(p.removeprefix(prefix) for p in held if p.startswith(prefix))


def _wildcard_by_role(roles: Sequence[str], role_map: Mapping[str, Any] | None) -> bool:
    """Whether one of ``roles`` maps to the wildcard — the admin role, by default."""
    mapping = role_map if role_map is not None else DEFAULT_ROLE_PERMISSIONS
    return any(WILDCARD in (mapping.get(role) or ()) for role in roles)


def caller_access(
    user: Any, held: Collection[str], role_map: Mapping[str, Any] | None = None
) -> CallerRoles:
    """:class:`CallerRoles` for ``user`` holding the resolved set ``held``.

    ``role_map`` is the registry's merged role map. A caller whose *roles*
    carry the wildcard gets no per-type grants even when ``held`` no longer
    shows it: the framework's ``apply_scope_cap`` replaces an admin token's
    wildcard with the token's scopes, and those scopes may name any
    registered key — ``records.type.<key>`` included — because the wildcard
    expands to all of them. Without this an admin excluded by
    ``allowed_roles`` could mint a token scoped to the type's key and read
    what their own session is refused. So a token never holds more per-type
    access than its owner's genuine (non-wildcard) grants.
    """
    roles = list(getattr(user, "roles", None) or []) if user is not None else []
    if _wildcard_by_role(roles, role_map):
        return CallerRoles(roles)
    return CallerRoles(roles, type_grants(held))


def request_role_map(request: Any) -> Mapping[str, Any] | None:
    """The permission registry's role map for ``request``'s app, if it has one."""
    sm = getattr(getattr(request.app, "state", None), "sm", None)
    registry = getattr(sm, "permissions", None)
    return registry.role_map if registry is not None else None


def role_blocked(rtype: Any, roles: Sequence[str] | None) -> bool:
    """Whether ``rtype``'s ``allowed_roles`` shut this caller out.

    ``roles is None`` means "no caller": the CLI, a background task, any path
    with no user behind it, which keeps the unrestricted behaviour. An empty
    list is a caller holding no roles, and a narrowed type blocks them —
    unless they hold the type's own ``records.type.<key>`` (a
    :class:`CallerRoles` carries it; a plain list never does).

    An ``admin`` wildcard is not an exception: narrowing is a list of role
    names, and a role not on it is refused however powerful it is elsewhere
    (see :func:`type_grants` for why the wildcard grants no per-type key).
    """
    if roles is None:
        return False
    allowed = getattr(rtype, "allowed_roles", None) or []
    if not allowed or set(roles).intersection(allowed):
        return False
    return getattr(rtype, "key", None) not in getattr(roles, "granted_types", ())
