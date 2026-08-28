from __future__ import annotations

from pagebuilder.snapshots.blobs import BlobStore


def test_put_is_content_addressed_and_idempotent(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    first = store.put(b"hello")
    second = store.put(b"hello")
    assert first == second
    assert store.get(first) == b"hello"
    # One file on disk, not two.
    assert len(list(store.root.iterdir())) == 1


def test_put_leaves_no_partial_file_behind(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    store.put(b"hello")
    assert [p.suffix for p in store.root.iterdir()] == [""]


def test_delete_unreferenced_keeps_what_is_still_used(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    kept = store.put(b"kept")
    dropped = store.put(b"dropped")
    removed = store.delete_unreferenced(keep={kept})
    assert removed == 1
    assert store.exists(kept)
    assert not store.exists(dropped)


def test_delete_unreferenced_on_a_missing_root_is_a_no_op(tmp_path):
    assert BlobStore(tmp_path / "never-created").delete_unreferenced(keep=set()) == 0
