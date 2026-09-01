from __future__ import annotations

import pytest
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


def test_path_for_refuses_anything_that_is_not_a_digest(tmp_path):
    """A digest is a name, not a path.

    An uploaded bundle's media/index.json carries digest strings that never
    travel as zip member names, so the archive layer's path guard never sees
    them. Joining one onto the store root unchecked would read any file the
    server can.
    """
    store = BlobStore(tmp_path / "blobs")
    for hostile in ("../../../etc/passwd", "/etc/passwd", "..", "", "not-hex", "A" * 64):
        with pytest.raises(ValueError, match="sha256"):
            store.path_for(hostile)


def test_get_refuses_a_traversing_name(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"private")
    store = BlobStore(tmp_path / "blobs")
    with pytest.raises(ValueError, match="sha256"):
        store.get("../secret.txt")


def test_exists_answers_no_instead_of_raising(tmp_path):
    """Callers validating an untrusted bundle want a rejection, not a crash."""
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"private")
    store = BlobStore(tmp_path / "blobs")
    assert store.exists("../secret.txt") is False
