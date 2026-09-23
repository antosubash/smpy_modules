"""Running the host's real Alembic chain from the records suite.

For ``test_migration_tenant_id.py`` (tenancy design K10), which needs a
database *as it stood at a revision* — the models only describe head, so the
old schema can only come from the revisions themselves.

**Alembic runs in a subprocess**, from the repo root, with ``SM_DATABASE_URL``
naming the scratch database: that is how an operator runs it (``env.py`` reads
the URL from the host settings and imports the host's ``records_collections``),
and ``env.py``'s ``fileConfig`` would otherwise reconfigure this process's
logging for every test that runs after it.

On Postgres the scratch database is a **schema** of the suite's own database,
selected with ``search_path`` — no ``CREATE DATABASE`` privilege needed, and
``pg_support``'s per-test ``TRUNCATE`` (of ``current_schema()``) never sees it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from tests.pg_support import TEST_URL, USING_POSTGRES

REPO = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO / "host" / "alembic.ini"


def alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=REPO,
        env={**os.environ, "SM_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )


def must(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stderr[-4000:]
    return result.stdout + result.stderr


def scratch_urls(tmp_path: Path, schema: str) -> tuple[str, str]:
    """``(async URL for alembic's env.py, sync URL for this process)``."""
    if not USING_POSTGRES:
        path = tmp_path / "migration.db"
        return f"sqlite+aiosqlite:///{path}", f"sqlite:///{path}"
    joiner = "&" if "?" in TEST_URL else "?"
    url = f"{TEST_URL}{joiner}options=-csearch_path%3D{schema}"
    return url, url.replace("+asyncpg", "+psycopg2")


def reset_schema(schema: str, *, create: bool) -> None:
    if not USING_POSTGRES:
        return
    engine = sa.create_engine(TEST_URL.replace("+asyncpg", "+psycopg2"))
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        if create:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine.dispose()


def index_definitions(conn: Any) -> dict[str, str]:
    """Every records index as the database itself spells it."""
    if conn.dialect.name == "sqlite":
        sql = (
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' "
            "AND sql IS NOT NULL AND tbl_name LIKE :prefix"
        )
    else:
        sql = (
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() "
            "AND tablename LIKE :prefix"
        )
    rows = conn.execute(sa.text(sql), {"prefix": "records%"})
    return {name: " ".join(str(body).split()) for name, body in rows}


def column_default(conn: Any, table: str, column: str) -> Any:
    if conn.dialect.name == "sqlite":
        rows = conn.exec_driver_sql(f"PRAGMA table_info('{table}')").all()
        return next(row[4] for row in rows if row[1] == column)
    return conn.execute(
        sa.text(
            "SELECT column_default FROM information_schema.columns WHERE "
            "table_schema = current_schema() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar_one()


def populate(conn: Any) -> dict[str, int]:
    """A single-tenant install's worth of rows, written against the tables as
    reflected — the models describe head, not this revision. Returns the row
    count of each table written."""
    meta = sa.MetaData()
    meta.reflect(conn, only=lambda name, _: name.startswith("records_"))
    t = meta.tables
    now = datetime.now(UTC)
    type_row = {
        "label": "T",
        "label_plural": "Ts",
        "fields": [{"key": "title", "type": "text", "label": "Title", "indexed": True}],
        "schema_version": 1,
        "version": 1,
        "reindex_pending": {},
        "allowed_roles": [],
        "is_public": False,
        "show_in_menu": False,
        "translatable": False,
        "created_at": now,
    }
    conn.execute(t["records_type"].insert().values(key="post", **type_row))
    conn.execute(t["records_type"].insert().values(key="gig", collection="events", **type_row))
    for type_id in (1, 2):
        conn.execute(
            t["records_type_revision"]
            .insert()
            .values(type_id=type_id, version=1, schema_version=1, fields=[], created_at=now)
        )
    for prefix, type_id in (("records_", 1), ("records_c_events_", 2)):
        for n in (1, 2):
            uuid = f"{type_id:016x}{n:016x}"
            conn.execute(
                t[f"{prefix}record"]
                .insert()
                .values(
                    uuid=uuid,
                    type_id=type_id,
                    data={"title": f"t{n}"},
                    schema_version=1,
                    version=1,
                    status="PUBLISHED",
                    slug=f"s{n}",
                    locale="en",
                    translation_group=uuid,
                    display_title=f"t{n}",
                    position=n,
                    created_at=now,
                    updated_at=now,
                    published_at=now if n == 1 else None,
                    is_deleted=False,
                )
            )
            conn.execute(
                t[f"{prefix}revision"]
                .insert()
                .values(
                    record_id=n,
                    schema_version=1,
                    version=1,
                    data={},
                    display_title="",
                    event="CREATE",
                    created_at=now,
                )
            )
            conn.execute(
                t[f"{prefix}index_text"]
                .insert()
                .values(type_id=type_id, field_key="title", record_id=n, value=f"t{n}")
            )
    return {
        name: conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
        for name, table in t.items()
    }
