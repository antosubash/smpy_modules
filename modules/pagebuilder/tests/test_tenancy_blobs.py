"""Per-tenant snapshot blob stores (#38).

The garbage collector keeps only the digests the *tenant-filtered*
``SnapshotMedia`` rows name, so one shared store would let tenant A's GC delete
tenant B's blobs. Each tenant gets ``<blobs root>/<tenant>/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.blobs import BLOBS_DIR, tenant_store
from pagebuilder.snapshots.service import SnapshotService
from simple_module_db import tenant_context


def test_service_store_is_rooted_in_the_bound_tenant(db, tmp_path: Path) -> None:
    service = SnapshotService(db, PagebuilderSettings(snapshot_root=tmp_path))
    with tenant_context("acme"):
        assert service.blobs.root == tmp_path / BLOBS_DIR / "acme"
    assert service.blobs.root == tmp_path / BLOBS_DIR / "default"


def test_gc_in_one_tenant_never_deletes_anothers_blobs(tmp_path: Path) -> None:
    acme = tenant_store(tmp_path, "acme")
    globex = tenant_store(tmp_path, "globex")
    shared = acme.put(b"same bytes")
    assert globex.put(b"same bytes") == shared
    only_globex = globex.put(b"globex only")

    assert acme.delete_unreferenced(keep=set()) == 1
    assert not acme.exists(shared)
    assert globex.exists(shared)
    assert globex.exists(only_globex)


@pytest.mark.unbound_tenant
def test_unbound_store_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        tenant_store(tmp_path)
