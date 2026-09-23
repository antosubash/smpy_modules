"""The fail-closed tenancy guard behind :func:`sm_records.tenancy.install_guard`.

Two listeners on the host's ``sync_session_class`` — the same class the
framework's own listeners hang off, so the guard sees every session the host
opens (spike 1g). Split from :mod:`sm_records.tenancy` because that module is
imported by every router and this one is only needed at startup and by the CLI.

* ``do_orm_execute``: an ORM statement naming a tenant-owned records mapper in
  its top-level entities, with no tenant bound and no
  :data:`~sm_records.tenancy.ALL_TENANTS` tag, raises
  :class:`~sm_records.tenancy.TenantUnbound`. Unbound, the framework would have
  returned every tenant's rows (FACT 1b).
* ``before_flush``: a new, changed or deleted tenant-owned records object with
  no tenant bound raises the same. Unbound, the framework stamps nothing (a
  ``NOT NULL`` 500, FACT 1a) and skips its tenant-change check, so a loaded row
  could silently move tenant (FACT 1a‴).

Only **records'** mappers are guarded — another module's ``MultiTenantMixin``
tables keep the framework's behaviour. And only mappers: a Core statement over
``__table__``, ``text()`` or a mapper that appears only inside an ``exists()``
or ``in_()`` is invisible here (FACT 1d), which is why §E makes an explicit
``tenant_id`` predicate mandatory for those shapes.
"""

from __future__ import annotations

from typing import Any

from simple_module_db.listeners import current_tenant_id
from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

from sm_records.models._base import Base
from sm_records.tenancy import ALL_TENANTS, TenantUnbound

__all__ = ["install", "is_guarded", "owned"]

_owned_cache: dict[type, bool] = {}


def owned(cls: type) -> bool:
    """Is ``cls`` a tenant-owned records class? Cached: the hot path asks per statement."""
    found = _owned_cache.get(cls)
    if found is None:
        found = issubclass(cls, MultiTenantMixin) and issubclass(cls, Base)
        _owned_cache[cls] = found
    return found


def _on_execute(state: ORMExecuteState) -> None:
    if current_tenant_id.get() is not None:
        return
    if state.execution_options.get(ALL_TENANTS, False):
        return
    for mapper in state.all_mappers:
        if owned(mapper.class_):
            raise TenantUnbound(
                f"{mapper.class_.__name__} queried with no tenant bound; bind one with "
                "sm_records.tenancy.tenant_scope, or tag a deliberate cross-tenant read "
                "with sm_records.tenancy.all_tenants"
            )


def _on_flush(session: Session, _context: Any, _instances: Any) -> None:
    if current_tenant_id.get() is not None:
        return
    touched = [obj for obj in session.dirty if session.is_modified(obj)]
    for obj in (*session.new, *touched, *session.deleted):
        if owned(type(obj)):
            raise TenantUnbound(
                f"{type(obj).__name__} written with no tenant bound; bind one with "
                "sm_records.tenancy.tenant_scope"
            )


def is_guarded(sync_session_class: Any) -> bool:
    return event.contains(sync_session_class, "do_orm_execute", _on_execute)


def install(sync_session_class: Any) -> None:
    """Register both listeners once per session class."""
    if not is_guarded(sync_session_class):
        event.listen(sync_session_class, "do_orm_execute", _on_execute)
    if not event.contains(sync_session_class, "before_flush", _on_flush):
        event.listen(sync_session_class, "before_flush", _on_flush)
