"""What moved: the packages, the rename list, and where each old directory went (#319).

Shared by ``moved_paths.py`` and its Python and TypeScript halves. A move is
one source file of a published package that ``git diff -M`` reports renamed
or deleted between the two releases, with paths relative to the package
directory (``modules/pagebuilder/pagebuilder/``).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

OLD_REF, NEW_REF = "v0.0.13", "v0.0.14"
REMOVE_IN = "0.0.17"
TABLE = "core/moved_paths.json"
HOOK = "core/moved_paths.py"
# Tests, e2e specs and docs moved too, but nobody imports them.
SKIP = re.compile(
    r"(^|/)(tests|__tests__|e2e|docs|page-tests)/|\.test\.[jt]sx?$|(^|/)test-dom\.tsx$"
    r"|-test-support\.ts$"
)


@dataclass(frozen=True)
class Package:
    module: str  # modules/<module>
    name: str  # the import name, e.g. sm_records
    rel: str  # repo-relative package dir, e.g. modules/records/sm_records

    def dotted(self, rel: str) -> str:
        """``content/service/__init__.py`` → ``pagebuilder.content.service``."""
        path = PurePosixPath(rel)
        parts = [self.name, *path.parent.parts]
        if path.name != "__init__.py":
            parts.append(path.stem)
        return ".".join(p for p in parts if p)


@dataclass(frozen=True)
class Move:
    package: Package
    old: str  # relative to the package dir
    new: str | None  # same; None when deleted (or paired outside the package)


def packages(root: Path) -> list[Package]:
    """Every package that carries the moved-path hook."""
    found = []
    for hook in sorted(root.glob(f"modules/*/*/{HOOK}")):
        pkg_dir = hook.parent.parent
        found.append(
            Package(
                pkg_dir.parent.name, pkg_dir.name, f"modules/{pkg_dir.parent.name}/{pkg_dir.name}"
            )
        )
    return found


def owner(rel: str, pkgs: list[Package]) -> tuple[Package, str] | None:
    """The package a repo-relative path lies in, and the path relative to its directory."""
    for pkg in pkgs:
        if rel.startswith(f"{pkg.rel}/"):
            return pkg, rel[len(pkg.rel) + 1 :]
    return None


def parse_moves(listing: str, pkgs: list[Package]) -> list[Move]:
    """The renames and deletes of package sources in a ``--name-status`` listing."""

    def locate(path: str) -> tuple[Package, str] | None:
        return None if SKIP.search(path) else owner(path, pkgs)

    moves = []
    for line in listing.splitlines():
        fields = line.split("\t")
        status = fields[0][:1]
        if status not in ("R", "D"):
            continue
        old = locate(fields[1])
        if old is None:
            continue
        new = locate(fields[2]) if status == "R" else None
        # Git pairs identical files across packages (empty ``__init__.py``s); a
        # pairing outside the package counts as a delete.
        same_package = new is not None and new[0] == old[0]
        moves.append(Move(old[0], old[1], new[1] if same_package else None))
    return moves


def dir_map(moves: list[Move]) -> dict[tuple[Package, str], str]:
    """Where each old directory's files went, from the files that kept their name.

    An ``__init__.py`` does not vote: empty ones are identical, so git pairs
    them at random.
    """
    votes: dict[tuple[Package, str], Counter[str]] = defaultdict(Counter)
    for move in moves:
        old, new = PurePosixPath(move.old), move.new and PurePosixPath(move.new)
        if new and old.name == new.name and old.name != "__init__.py":
            votes[move.package, str(old.parent)][str(new.parent)] += 1
    return {key: count.most_common(1)[0][0] for key, count in votes.items() if key[1] != "."}


def guess(move: Move, dirs: dict[tuple[Package, str], str]) -> str | None:
    """The old file's path under its directory's new home, if that directory moved.

    A directory none of whose files kept their name (every one deleted) goes
    where its nearest moved ancestor went.
    """
    old = PurePosixPath(move.old)
    for ancestor in old.parents:
        new_dir = dirs.get((move.package, str(ancestor)))
        if new_dir:
            return str(PurePosixPath(new_dir) / old.relative_to(ancestor))
    return None


def read_table(root: Path, pkg: Package) -> dict:
    return json.loads((root / pkg.rel / TABLE).read_text(encoding="utf-8"))


def write_table(root: Path, pkg: Package, table: dict) -> None:
    text = json.dumps(table, indent=2, sort_keys=True) + "\n"
    (root / pkg.rel / TABLE).write_text(text, encoding="utf-8")
