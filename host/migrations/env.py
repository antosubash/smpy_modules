"""Alembic environment for a SimpleModule host.

Discovery + metadata aggregation lives in `simple_module_db.migrations` so
this file stays small and identical across all hosts. Don't add module-
specific imports here — install the module package and re-run autogenerate.

The one import below is not a module-specific import but a **host**-specific
one, and it is why ``alembic.ini`` prepends the host directory to ``sys.path``:
record collections (Phase 5 §6.1) are declared by this host in
``records_collections.py``, and their tables are only on the module metadata
once that module has been imported. Without it autogenerate cannot create them
and ``alembic check`` cannot see them. A host that declares no collection has
no such file, and the import is skipped.
"""

from __future__ import annotations

import logging
from importlib.util import find_spec
from logging.config import fileConfig

from alembic import context
from simple_module_db import build_module_metadata, make_include_object, render_item
from simple_module_hosting.migrations import ALEMBIC_DATABASE_URL_ATTRIBUTE
from simple_module_hosting.settings import Settings
from sqlalchemy import Column, engine_from_config, pool

logger = logging.getLogger("alembic.env")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ``find_spec`` rather than a bare ``try/except ImportError``: the file being
# absent is the ordinary case for a host with no collections, while an
# ``ImportError`` raised *inside* it is a bug that must not be swallowed into a
# silently empty migration.
if find_spec("records_collections") is not None:
    import records_collections  # noqa: F401

target_metadata = build_module_metadata()
_include_object = make_include_object(target_metadata)

# An index mixing columns and an expression (file_storage's ``tenant_browse``,
# ``created_at DESC``, framework 0.0.44). SQLite reflects it as plain columns, so
# autogenerate reports a change on every run, and ``make migration`` would write
# a drop and recreate of it. Postgres reflects it faithfully and keeps comparing.
_EXPRESSION_INDEXES = frozenset(
    index.name
    for table in target_metadata.tables.values()
    for index in table.indexes
    if any(not isinstance(element, Column) for element in index.expressions)
)


def include_object(object_, name, type_, reflected, compare_to):
    if (
        type_ == "index"
        and name in _EXPRESSION_INDEXES
        and context.get_context().dialect.name == "sqlite"
    ):
        return False
    return _include_object(object_, name, type_, reflected, compare_to)


def _get_url() -> str:
    """Read database URL from settings, convert async to sync driver."""
    url = config.attributes.get(ALEMBIC_DATABASE_URL_ATTRIBUTE) or Settings().database_url
    return url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg2")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without a live DB."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            render_item=render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
