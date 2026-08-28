"""Content-addressed storage for the bytes a snapshot carries.

Blobs are keyed by sha256 and shared by every snapshot that references them, so
ten snapshots of a site whose photographs have not changed cost one copy of the
photographs. Without that, each snapshot of a real site would duplicate its
whole media library and the feature would be unusable on anything but a toy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_PARTIAL_SUFFIX = ".partial"


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, sha256: str) -> Path:
        return self.root / sha256

    def exists(self, sha256: str) -> bool:
        return self.path_for(sha256).is_file()

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
