"""Analytics properties, anonymous sessions and events.

Revision ID: a9b8c7d6e501
Revises: f6c2d4e8b109
"""

import sqlalchemy as sa
from alembic import op

revision = "a9b8c7d6e501"
down_revision = "f6c2d4e8b109"
branch_labels = ("analytics",)
depends_on = None


def _tenant():
    return sa.Column("tenant_id", sa.String(50), nullable=False)


def upgrade() -> None:
    op.create_table(
        "analytics_property",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("origins", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("route_patterns", sa.JSON(), nullable=False),
        sa.Column("event_allowlist", sa.JSON(), nullable=False),
        sa.Column("utm_parameters", sa.JSON(), nullable=False),
    )
    op.create_table(
        "analytics_session",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column(
            "property_id", sa.String(36), sa.ForeignKey("analytics_property.id"), nullable=False
        ),
        sa.Column("visitor", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    columns = [
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column(
            "property_id", sa.String(36), sa.ForeignKey("analytics_property.id"), nullable=False
        ),
        sa.Column(
            "session_id", sa.String(36), sa.ForeignKey("analytics_session.id"), nullable=False
        ),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("visitor", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
    ]
    for name, length in [
        ("kind", 10),
        ("path", 500),
        ("name", 50),
        ("referrer", 253),
        ("browser", 30),
        ("os", 30),
        ("device", 10),
        ("utm_source", 200),
        ("utm_medium", 200),
        ("utm_campaign", 200),
        ("utm_term", 200),
        ("utm_content", 200),
        ("country", 2),
        ("country_name", 200),
        ("region", 20),
        ("region_name", 200),
        ("city", 20),
        ("city_name", 200),
    ]:
        columns.append(sa.Column(name, sa.String(length), nullable=False))
    op.create_table(
        "analytics_event",
        *columns,
        sa.UniqueConstraint("tenant_id", "property_id", "event_id", name="uq_analytics_event_id"),
    )
    for table in ("analytics_property", "analytics_session", "analytics_event"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(
        "ix_analytics_session_visitor",
        "analytics_session",
        ["tenant_id", "property_id", "visitor", "last_seen"],
    )
    op.create_index("ix_analytics_event_session_id", "analytics_event", ["session_id"])
    op.create_index(
        "ix_analytics_event_time", "analytics_event", ["tenant_id", "property_id", "created_at"]
    )
    op.create_index(
        "ix_analytics_event_geo",
        "analytics_event",
        ["tenant_id", "property_id", "country", "region", "city", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("analytics_event")
    op.drop_table("analytics_session")
    op.drop_table("analytics_property")
