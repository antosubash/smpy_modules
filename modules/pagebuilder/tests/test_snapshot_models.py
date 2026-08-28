from __future__ import annotations

from pagebuilder.models import (
    ContentSnapshot,
    ImportStatus,
    PendingImport,
    SnapshotMedia,
    SnapshotSource,
)


def test_tables_are_registered_under_the_module_prefix():
    assert ContentSnapshot.__tablename__ == "pagebuilder_snapshots"
    assert SnapshotMedia.__tablename__ == "pagebuilder_snapshot_media"
    assert PendingImport.__tablename__ == "pagebuilder_pending_imports"


def test_enum_values_are_the_wire_format():
    # These strings reach the API and the TSX; renaming one is a breaking change.
    assert SnapshotSource.MANUAL.value == "manual"
    assert SnapshotSource.UPLOAD.value == "upload"
    assert SnapshotSource.PRE_RESTORE.value == "pre_restore"
    assert ImportStatus.PENDING.value == "pending"
    assert ImportStatus.APPROVED.value == "approved"
    assert ImportStatus.REJECTED.value == "rejected"


def test_snapshot_media_cascades_so_blob_rows_cannot_outlive_their_snapshot():
    constraint = SnapshotMedia.__table__.c.snapshot_id.foreign_keys.pop()
    assert constraint.ondelete == "CASCADE"
