"""Index standalone report filters and tenant-wide retention.

Revision ID: b6d4e2a0c913
Revises: a9b8c7d6e501
"""

from alembic import op

revision = "b6d4e2a0c913"
down_revision = "a9b8c7d6e501"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for dimension in ("country", "region", "city", "path", "name"):
        op.create_index(
            f"ix_analytics_event_{dimension}",
            "analytics_event",
            ["tenant_id", "property_id", dimension, "created_at"],
        )
    for table, timestamp in (("analytics_event", "created_at"), ("analytics_session", "last_seen")):
        op.create_index(f"ix_{table}_retention", table, ["tenant_id", timestamp, "id"])
    op.drop_index("ix_analytics_event_geo", table_name="analytics_event")


def downgrade() -> None:
    op.create_index(
        "ix_analytics_event_geo",
        "analytics_event",
        ["tenant_id", "property_id", "country", "region", "city", "created_at"],
    )
    for table in ("analytics_event", "analytics_session"):
        op.drop_index(f"ix_{table}_retention", table_name=table)
    for dimension in ("country", "region", "city", "path", "name"):
        op.drop_index(f"ix_analytics_event_{dimension}", table_name="analytics_event")
