"""file_storage: tenant_id and public on stored files (framework 0.0.36)

Revision ID: 6afd6d2551f7
Revises: 5b210e4cf54f
Create Date: 2026-10-19

The framework's own revisions ``c7f2d9a41e83`` (#383, ``StoredFile`` adopts
``MultiTenantMixin``) and ``e5a8c1f27b94`` (#353, opt-in anonymous serving),
ported unchanged into this host's history, since the host owns its migrations.

``tenant_id`` is added nullable, back-filled, then made NOT NULL, and the
unique ``key`` index widens to ``(tenant_id, key)``. Existing rows keep their
key, so their bytes are still found where they were written; only new uploads
get the ``{tenant_id}/`` prefix. Rows land in ``DEFAULT_TENANT_ID``, except the
files the SYSTEM-scope branding settings point at (logo, dark logo, favicon),
which become platform files so the anonymous asset routes can still read them.
Existing rows stay private (``public`` false).
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from simple_module_db import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID

# revision identifiers, used by Alembic.
revision: str = "6afd6d2551f7"
down_revision: str | None = "5b210e4cf54f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "file_storage_stored_file"
_OLD_KEY = "ix_file_storage_stored_file_key"
_TENANT_KEY = "ix_file_storage_stored_file_tenant_key"
_TENANT = "ix_file_storage_stored_file_tenant_id"
_SETTINGS = "settings_setting"
# SYSTEM-scope settings whose value is a platform file id (branding images).
_PLATFORM_FILE_KEYS = (
    "branding.logo_file_id",
    "branding.logo_dark_file_id",
    "branding.favicon_file_id",
)


def _platform_file_ids(bind: sa.engine.Connection) -> list[uuid.UUID]:
    """File ids the system branding settings reference (malformed values skipped)."""
    if not sa.inspect(bind).has_table(_SETTINGS):
        return []
    settings = sa.table(
        _SETTINGS,
        sa.column("scope", sa.String),
        sa.column("scope_id", sa.String),
        sa.column("key", sa.String),
        sa.column("value", sa.String),
    )
    rows = bind.execute(
        sa.select(settings.c.value).where(
            settings.c.scope == "system",
            settings.c.scope_id == "",
            settings.c.key.in_(_PLATFORM_FILE_KEYS),
        )
    ).scalars()
    ids: list[uuid.UUID] = []
    for raw in rows:
        try:
            ids.append(uuid.UUID(str(raw).strip().strip('"')))
        except ValueError:
            continue
    return ids


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("tenant_id", sa.String(length=50), nullable=True))
    files = sa.table(_TABLE, sa.column("id", sa.Uuid), sa.column("tenant_id", sa.String))
    bind = op.get_bind()
    if platform_ids := _platform_file_ids(bind):
        bind.execute(
            sa.update(files)
            .where(files.c.id.in_(platform_ids))
            .values(tenant_id=PLATFORM_TENANT_ID)
        )
    bind.execute(
        sa.update(files).where(files.c.tenant_id.is_(None)).values(tenant_id=DEFAULT_TENANT_ID)
    )
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(length=50), nullable=False)
        batch.drop_index(_OLD_KEY)
        batch.create_index(_TENANT_KEY, ["tenant_id", "key"], unique=True)
        batch.create_index(_TENANT, ["tenant_id"], unique=False)
    op.add_column(
        _TABLE,
        sa.Column("public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    # Fails if two tenants hold the same key — only possible for keys written
    # by hand, since generated keys carry a uuid. Resolve those rows first.
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("public")
        batch.drop_index(_TENANT)
        batch.drop_index(_TENANT_KEY)
        batch.create_index(_OLD_KEY, ["key"], unique=True)
        batch.drop_column("tenant_id")
