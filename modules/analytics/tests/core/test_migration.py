from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sm_analytics.models import Base
from sqlalchemy import create_engine, inspect


def test_migration_creates_and_removes_only_analytics_tables(tmp_path):
    revision = (
        Path(__file__).resolve().parents[4] / "host/migrations/versions/a9b8c7d6e501_analytics.py"
    )
    assert revision.exists(), "Analytics host migration is missing"
    spec = spec_from_file_location("analytics_migration", revision)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path}/migration.db")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            assert set(inspect(connection).get_table_names()) == {
                "analytics_property",
                "analytics_session",
                "analytics_event",
            }
            assert compare_metadata(context, Base.metadata) == []
            migration.downgrade()
            assert inspect(connection).get_table_names() == []
    engine.dispose()
