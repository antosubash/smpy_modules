"""Revision ``4ecb931245dd`` on a populated database — tenancy design K10.

The schema is built by the host's own chain up to ``8f3d223f8605`` (global set
plus the demo host's ``events`` collection), filled the way a single-tenant
install is, and then migrated. What has to hold afterwards:

* every owned row is in tenant ``default``, and nothing else moved;
* no ``server_default`` is left behind — a forgotten tenant fails loudly;
* every index the revision did not mean to touch is byte-for-byte what it was,
  on SQLite too, where the table rebuild would have flattened the three
  ``…_desc`` indexes to ascending without the repair;
* the composite foreign key and the per-tenant uniques exist, and the global
  ones are gone;
* ``alembic check`` finds nothing about records: the migrated schema is the
  one ``create_all`` builds from the models.

Then the downgrade round-trips single-tenant data exactly, and refuses once two
tenants share a type key or a record uuid — the lossy half its docstring owns
up to — before any DDL, so the schema, the revision and the per-tenant uniques
are exactly as they were and a retry after removing the duplicate succeeds.

Runs on whichever backend the suite is pointed at (see ``migration_support``).
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

from tests.migration_support import (
    ALEMBIC_INI,
    alembic,
    column_default,
    index_definitions,
    must,
    populate,
    reset_schema,
    scratch_urls,
)

pytestmark = [
    pytest.mark.unbound_tenant,
    pytest.mark.skipif(not ALEMBIC_INI.is_file(), reason="needs the repo's host migrations"),
]

BEFORE = "8f3d223f8605"
THIS = "4ecb931245dd"
SETS = ("records_", "records_c_events_")
OWNED = (
    "records_type",
    "records_type_revision",
    *(f"{prefix}{suffix}" for prefix in SETS for suffix in ("record", "revision")),
)
NEW_INDEXES = {
    "uq_records_type_tenant_key",
    *(f"ix_{table}_tenant_id" for table in OWNED),
    *(f"uq_{prefix}record_tenant_uuid" for prefix in SETS),
}
GONE_INDEXES = {"ix_records_type_key", *(f"ix_{prefix}record_uuid" for prefix in SETS)}


@pytest.fixture
def scratch(tmp_path):
    schema = f"records_mig_{os.getpid()}"
    reset_schema(schema, create=True)
    async_url, sync_url = scratch_urls(tmp_path, schema)
    must(alembic(async_url, "upgrade", BEFORE))
    engine = sa.create_engine(sync_url)
    yield async_url, engine
    engine.dispose()
    reset_schema(schema, create=False)


def _snapshot(engine) -> tuple[dict[str, str], dict[str, int]]:
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        counts = {
            table: conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in inspector.get_table_names()
            if table.startswith("records_")
        }
        return index_definitions(conn), counts


def _type_fk(inspector, table: str) -> dict:
    return next(
        fk for fk in inspector.get_foreign_keys(table) if "type_id" in fk["constrained_columns"]
    )


def test_upgrade_backfills_default_and_leaves_every_other_index_alone(scratch):
    url, engine = scratch
    with engine.begin() as conn:
        populate(conn)
    before_indexes, before_counts = _snapshot(engine)

    must(alembic(url, "upgrade", THIS))
    after_indexes, after_counts = _snapshot(engine)
    assert after_counts == before_counts

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        for table in OWNED:
            tenants = conn.execute(sa.text(f"SELECT DISTINCT tenant_id FROM {table}")).all()
            assert tenants == [("default",)], table
            assert column_default(conn, table, "tenant_id") is None, table
        for prefix in SETS:
            fk = _type_fk(inspector, f"{prefix}record")
            assert fk["name"] == f"fk_{prefix}record_type_id_records_type"
            assert fk["constrained_columns"] == ["type_id", "tenant_id"]
            assert (fk["referred_table"], fk["referred_columns"]) == (
                "records_type",
                ["id", "tenant_id"],
            )
            assert fk["options"].get("ondelete") == "RESTRICT"
        uniques = {
            c["name"]: c["column_names"] for c in inspector.get_unique_constraints("records_type")
        }
        assert uniques.get("uq_records_type_id_tenant_id") == ["id", "tenant_id"]

    # Postgres lists the index behind the ``(id, tenant_id)`` unique constraint
    # too; SQLite keeps it as an unnamed autoindex with no SQL of its own.
    backing = {"uq_records_type_id_tenant_id"} if engine.dialect.name != "sqlite" else set()
    assert set(after_indexes) == (set(before_indexes) - GONE_INDEXES) | NEW_INDEXES | backing
    untouched = set(before_indexes) - GONE_INDEXES
    assert {name: after_indexes[name] for name in untouched} == {
        name: before_indexes[name] for name in untouched
    }, "an index the revision does not own changed (the SQLite DESC repair, or the slug/group keys)"
    assert "tenant_id" in after_indexes["uq_records_record_tenant_uuid"]
    assert "WHERE" in after_indexes["ix_records_record_type_slug"]
    assert "DESC" in after_indexes["ix_records_c_events_record_type_updated_desc"]

    # ``check`` refuses a database below head, and the revisions after this one
    # (the framework 0.0.35 ``users`` columns) touch no records table.
    must(alembic(url, "upgrade", "heads"))
    report = alembic(url, "check")
    if report.returncode != 0:  # another module's drift is not this revision's business
        output = (report.stdout + report.stderr).splitlines()
        detected = [line for line in output if "upgrade operations detected" in line]
        assert detected, report.stderr[-2000:]
        assert "records" not in detected[0], detected[0]


def test_a_forgotten_tenant_is_loud_again_after_the_upgrade(scratch):
    url, engine = scratch
    must(alembic(url, "upgrade", THIS))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO records_type (key, label, label_plural, fields, schema_version, "
                "version, reindex_pending, allowed_roles, is_public, show_in_menu, translatable, "
                "created_at) VALUES ('x', 'X', 'Xs', '[]', 1, 1, '{}', '[]', false, false, "
                "false, CURRENT_TIMESTAMP)"
            )
        )


def test_downgrade_round_trips_single_tenant_data(scratch):
    url, engine = scratch
    with engine.begin() as conn:
        populate(conn)
    before = _snapshot(engine)
    must(alembic(url, "upgrade", THIS))
    must(alembic(url, "downgrade", BEFORE))
    assert _snapshot(engine) == before
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        for table in OWNED:
            assert "tenant_id" not in {c["name"] for c in inspector.get_columns(table)}, table
        assert _type_fk(inspector, "records_record")["constrained_columns"] == ["type_id"]


def _schema(engine) -> dict:
    """Everything a half-applied downgrade could disturb, plus the revision."""
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        return {
            "indexes": index_definitions(conn),
            "revision": conn.execute(sa.text("SELECT version_num FROM alembic_version")).all(),
            **{
                table: (
                    [c["name"] for c in inspector.get_columns(table)],
                    sorted(str(u["column_names"]) for u in inspector.get_unique_constraints(table)),
                    sorted(
                        str(f["constrained_columns"]) for f in inspector.get_foreign_keys(table)
                    ),
                )
                for table in OWNED
            },
        }


_TYPE = (
    "INSERT INTO records_type (key, label, label_plural, fields, schema_version, version, "
    "reindex_pending, allowed_roles, is_public, show_in_menu, translatable, created_at, "
    "tenant_id) VALUES (:key, 'P', 'Ps', '[]', 1, 1, '{}', '[]', false, false, false, "
    "CURRENT_TIMESTAMP, 'acme')"
)
_RECORD = (
    "INSERT INTO records_record (uuid, type_id, data, schema_version, version, status, slug, "
    "locale, translation_group, display_title, position, created_at, updated_at, is_deleted, "
    "tenant_id) SELECT uuid, :type_id, data, schema_version, version, status, slug, locale, "
    "translation_group, display_title, position, created_at, updated_at, is_deleted, 'acme' "
    "FROM records_record WHERE id = 1"
)


@pytest.mark.parametrize("shared", ["type key", "record uuid"])
def test_downgrade_refuses_before_any_ddl_once_two_tenants_share_a_natural_key(scratch, shared):
    """Review M1: on SQLite the DDL is not transactional, so the refusal has to
    come before the first ``DROP INDEX`` or the schema is left half downgraded
    at a revision that still says head."""
    url, engine = scratch
    with engine.begin() as conn:
        populate(conn)
    must(alembic(url, "upgrade", THIS))
    with engine.begin() as conn:
        conn.execute(sa.text(_TYPE), {"key": "post" if shared == "type key" else "acme_only"})
        if shared == "record uuid":
            type_id = conn.execute(sa.text("SELECT max(id) FROM records_type")).scalar_one()
            conn.execute(sa.text(_RECORD), {"type_id": type_id})
    before = _schema(engine)

    refused = alembic(url, "downgrade", BEFORE)
    assert refused.returncode != 0
    assert "refusing to downgrade 4ecb931245dd" in refused.stderr, refused.stderr[-2000:]
    expected = "records_type.key='post'" if shared == "type key" else "records_record.uuid="
    assert expected in refused.stderr
    assert _schema(engine) == before
    assert before["revision"] == [(THIS,)]
    assert "uq_records_type_tenant_key" in before["indexes"]
    assert "uq_records_record_tenant_uuid" in before["indexes"]

    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM records_record WHERE tenant_id = 'acme'"))
        conn.execute(sa.text("DELETE FROM records_type WHERE tenant_id = 'acme'"))
    must(alembic(url, "downgrade", BEFORE))
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).all() == [(BEFORE,)]
        assert "ix_records_type_key" in index_definitions(conn)
