"""Content-addressed storage for the bytes a snapshot carries.

Blobs are keyed by sha256 and shared by every snapshot that references them, so
ten snapshots of a site whose photographs have not changed cost one copy of the
photographs. Without that, each snapshot of a real site would duplicate its
whole media library and the feature would be unusable on anything but a toy.
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


def _checked(sha256: str) -> str:
    if not isinstance(sha256, str) or not _DIGEST.match(sha256):
        raise ValueError(f"not a sha256 digest: {sha256!r}")
    return sha256


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
        digest = hashlib.sha256(data).hexdigest()
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
            if path.is_file() and path.name not in keep:
                path.unlink()
                removed += 1
        return removed
