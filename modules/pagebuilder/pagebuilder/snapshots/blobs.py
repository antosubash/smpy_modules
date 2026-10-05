"""Content-addressed storage for the bytes a snapshot carries.

Blobs are keyed by sha256 and shared by every snapshot that references them, so
ten snapshots of a site whose photographs have not changed cost one copy of the
photographs. Without that, each snapshot of a real site would duplicate its
whole media library and the feature would be unusable on anything but a toy.

Each tenant has its own store, ``<blobs root>/<tenant_id>/`` (issue #38).
Sharing one would be unsafe rather than merely untidy: ``delete_unreferenced``
keeps only what the *tenant-filtered* ``SnapshotMedia`` rows name, so it would
delete every other tenant's blobs.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_PARTIAL_SUFFIX = ".partial"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
"""What a blob name is allowed to be: 64 lowercase hex characters.

Enforced because a digest is not always one this process computed. An uploaded
bundle's ``media/index.json`` carries digest *strings*, and joining one onto the
store root without checking it would let ``../..`` walk out of the store and
read any file the server can — the zip-member guard in ``archive`` does not
cover them, because they never travel as archive member names.
"""


def is_digest(value: object) -> bool:
    """Whether *value* is a usable blob name.

    Exported so ``archive`` can reject a bundle's declared digests early with a
    message fit for a user, without keeping a second copy of the pattern that
    would then be free to drift from the one actually guarding the store.
    """
    return isinstance(value, str) and _DIGEST.match(value) is not None


def _checked(sha256: str) -> str:
    if not is_digest(sha256):
        raise ValueError(f"not a sha256 digest: {sha256!r}")
    return sha256


BLOBS_DIR = "blobs"
"""The blob root's name under ``snapshot_root``."""


def tenant_store(blobs_root: Path, tenant_id: str | None = None) -> BlobStore:
    """The store of *tenant_id*, or of the bound tenant."""
    from pagebuilder.media_files import tenant_media_dir

    return BlobStore(tenant_media_dir(Path(blobs_root), tenant_id))


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, sha256: str) -> Path:
        """The path a digest names. Rejects anything that is not a digest.

        Every read, write and existence check goes through here, so the store
        cannot be walked out of no matter which caller supplies the name.
        """
        return self.root / _checked(sha256)

    def exists(self, sha256: str) -> bool:
        """Whether this store holds that blob.

        A malformed name answers ``False`` rather than raising: this is a
        question, the honest answer to "do you have ../../etc/passwd" is no,
        and callers validating an untrusted bundle want a rejection they can
        report rather than an exception they have to catch.
        """
        try:
            return self.path_for(sha256).is_file()
        except ValueError:
            return False

    def put(self, data: bytes) -> str:
        """Store *data* and return its sha256. Storing twice is a no-op."""
        return self.put_known(hashlib.sha256(data).hexdigest(), data)

    def put_known(self, digest: str, data: bytes) -> str:
        """Store *data* under an already-computed *digest*.

        For callers that had to hash the bytes anyway to validate them — an
        uploaded bundle checks every blob against the name it arrived under —
        so the same megabytes are not hashed twice on the way in. *digest* is
        still validated as a digest by ``path_for``; what is skipped is only
        the recomputation, never the check that the name is safe.
        """
        target = self.path_for(digest)
        if not target.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            # Write under a temp name and rename: a reader must never observe a
            # half-written file under a name that promises those exact bytes.
            tmp = target.with_name(target.name + _PARTIAL_SUFFIX)
            tmp.write_bytes(data)
            tmp.replace(target)
        return digest

    def get(self, sha256: str) -> bytes:
        return self.path_for(sha256).read_bytes()

    def delete_unreferenced(self, keep: set[str]) -> int:
        """Drop every blob no surviving snapshot names. Returns how many went.

        Callers pass the sha set still referenced by ``SnapshotMedia`` rows, so
        deletion never has to open another snapshot's index to discover which
        bytes are still spoken for.
        """
        if not self.root.is_dir():
            return 0
        removed = 0
        for path in self.root.iterdir():
            # A concurrent put() writes here before its rename; a `.partial`
            # name never appears in `keep` (which only ever holds digests),
            # so without this guard a scan landing mid-write deletes the file
            # out from under that write's `tmp.replace(target)`.
            if path.name.endswith(_PARTIAL_SUFFIX):
                continue
            if path.is_file() and path.name not in keep:
                path.unlink()
                removed += 1
        return removed
