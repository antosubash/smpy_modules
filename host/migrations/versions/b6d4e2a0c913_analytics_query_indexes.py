"""Index report filters, retention and property foreign-key checks.

Revision ID: b6d4e2a0c913
Revises: a9b8c7d6e501
"""

from alembic import op

revision = "b6d4e2a0c913"
down_revision = "a9b8c7d6e501"
branch_labels = None
depends_on = None


def _property_indexes(prefix: list[str]) -> None:
    for table, name, tail in (
        ("analytics_event", "time", ["created_at"]),
        ("analytics_session", "visitor", ["visitor", "last_seen"]),
    ):
        index = f"ix_{table}_{name}"
        op.drop_index(index, table_name=table)
        op.create_index(index, table, [*prefix, *tail])


def upgrade() -> None:
    _property_indexes(["property_id", "tenant_id"])
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
    _property_indexes(["tenant_id", "property_id"])
    op.create_index(
        "ix_analytics_event_geo",
        "analytics_event",
        ["tenant_id", "property_id", "country", "region", "city", "created_at"],
    )
    for table in ("analytics_event", "analytics_session"):
        op.drop_index(f"ix_{table}_retention", table_name=table)
    for dimension in ("country", "region", "city", "path", "name"):
        op.drop_index(f"ix_analytics_event_{dimension}", table_name="analytics_event")
