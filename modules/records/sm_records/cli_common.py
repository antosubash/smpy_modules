"""What every ``python -m sm_records.cli`` subcommand shares: the connection,
the settings, and ``--tenant``.

Split from :mod:`sm_records.cli` for the 300-line cap, and so that
:mod:`sm_records.cli_io` and :mod:`sm_records.cli_reindex` can import it
without importing the dispatcher that imports them.

**Tenancy** (design §A.5, §J). A CLI process has no request, so nothing binds
a tenant for it. Each subcommand takes ``--tenant`` (default
:data:`~sm_records.tenancy.DEFAULT_TENANT`, validated with
:data:`~sm_records.tenancy.TENANT_RE`) and runs its work inside
:func:`~sm_records.tenancy.tenant_scope`. :func:`open_db` installs the
fail-closed guard, so a code path that forgets to bind raises
``TenantUnbound`` and does not read every tenant's rows. A command that visits
several tenants (``reindex`` and ``verify`` without ``--type``) opens a fresh
session per tenant, because ``tenant_scope`` refuses to re-bind a scope, and
one session serving two tenants is how the identity map leaks (FACT 1e).
"""

from __future__ import annotations

import argparse
from typing import Any

from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db

from sm_records.constants import PACKAGE
from sm_records.settings import RecordsSettings
from sm_records.tenancy import DEFAULT_TENANT, install_guard, valid_tenant

__all__ = ["add_tenant_argument", "load_settings", "open_db", "tenant_type"]


def open_db(database_url: str) -> Any:
    """A ``DatabaseState`` with the framework's listeners and records' guard.

    The caller disposes of the engine. Every command already does, in a
    ``finally``.
    """
    db_state = init_db(database_url)
    register_listeners(db_state)
    install_guard(db_state.sync_session_class)
    return db_state


async def load_settings(db_state: Any) -> RecordsSettings:
    """The module's settings as the running host would see them.

    They live in the database (``CLAUDE.md``: no ``SM_RECORDS_*`` env var
    exists), so the CLI reads the same overrides the Settings screen writes —
    ``reindex_batch_size`` in particular, which an operator will have tuned for
    exactly this command. A host whose settings tables are not there yet, or a
    module never registered, falls back to the declared defaults rather than
    refusing to reindex.
    """
    try:
        from settings.hydrate import hydrate_settings
        from settings.service import SettingService
        from settings.store import SettingsStore

        async with db_state.session_factory() as session:
            store = SettingsStore(SettingService(session))
            return await hydrate_settings(RecordsSettings, store, PACKAGE)
    except Exception as exc:  # pragma: no cover - depends on the host's install
        print(f"warning: using default settings ({exc.__class__.__name__}: {exc})")
        return RecordsSettings()


def tenant_type(value: str) -> str:
    """``argparse`` type for ``--tenant``: a malformed id is a usage error."""
    if not valid_tenant(value):
        raise argparse.ArgumentTypeError(
            f"not a valid tenant id: {value!r} (1-50 characters, letters, digits and "
            "_ . : -, starting with a letter or digit)"
        )
    return value


def add_tenant_argument(parser: Any, *, every_tenant: bool = False) -> None:
    """``--tenant`` on one subparser.

    ``every_tenant`` is for ``reindex``/``verify``. Without ``--type`` they
    visit every tenant unless ``--tenant`` narrows them, so the default is
    ``None`` there, and the command resolves it to ``default`` once a
    ``--type`` needs a tenant to look its key up in.
    """
    parser.add_argument(
        "--tenant",
        type=tenant_type,
        default=None if every_tenant else DEFAULT_TENANT,
        help=(
            "the tenant to act in; omit it to visit every tenant, or, with --type, "
            f"to look the key up in {DEFAULT_TENANT!r}"
            if every_tenant
            else f"the tenant to act in (default: {DEFAULT_TENANT!r})"
        ),
    )
