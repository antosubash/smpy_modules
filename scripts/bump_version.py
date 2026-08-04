"""Bump the version of every publishable package in this repo, in lockstep.

Rewrites ``project.version`` in the root ``pyproject.toml`` and in every
``modules/*/pyproject.toml``, plus ``version`` in every
``modules/*/package.json``.

Deliberately does NOT touch dependency specifiers. The framework repo's
script rewrites every ``simple_module_*`` requirement to ``==<version>``;
here those requirements point at the *framework's* versions, which move
independently of this repo's. Rewriting them would pin the framework to a
version that does not exist. ``scripts/tests/test_bump_version.py`` guards
this.

Usage:
  python scripts/bump_version.py 0.2.0
  python scripts/bump_version.py 0.2.0 --dry-run
  python scripts/bump_version.py --check 0.2.0
  python scripts/bump_version.py --check-current
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import tomlkit

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-.]?(a|b|rc|alpha|beta)\d*)?$")


def _root_pyproject() -> Path:
    return REPO_ROOT / "pyproject.toml"


def targets() -> list[Path]:
    """Every manifest carrying this repo's lockstep version."""
    modules = REPO_ROOT / "modules"
    return [
        _root_pyproject(),
        *sorted(modules.glob("*/pyproject.toml")),
        *sorted(modules.glob("*/package.json")),
    ]


def read_version(path: Path) -> str:
    if path.suffix == ".toml":
        return str(tomlkit.parse(path.read_text(encoding="utf-8"))["project"]["version"])
    return str(json.loads(path.read_text(encoding="utf-8"))["version"])


def write_version(path: Path, version: str) -> None:
    if path.suffix == ".toml":
        # tomlkit preserves comments and formatting, so the diff is one line.
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        doc["project"]["version"] = version
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="target version, e.g. 0.2.0")
    parser.add_argument("--check", metavar="VERSION", help="verify every package is at VERSION")
    parser.add_argument(
        "--check-current",
        action="store_true",
        help="verify every package matches the root version",
    )
    parser.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    args = parser.parse_args(argv)

    expected = read_version(_root_pyproject()) if args.check_current else args.check or args.version

    if not expected:
        parser.error("a version, --check VERSION, or --check-current is required")
    if not VERSION_RE.match(expected):
        print(f"error: {expected!r} is not a valid version", file=sys.stderr)
        return 2

    checking = bool(args.check or args.check_current)
    drift: list[str] = []

    for path in targets():
        rel = path.relative_to(REPO_ROOT)
        current = read_version(path)
        if current == expected:
            continue
        if checking:
            drift.append(f"{rel}: {current} (expected {expected})")
        elif args.dry_run:
            print(f"{rel}: {current} -> {expected}")
        else:
            write_version(path, expected)
            print(f"{rel}: {current} -> {expected}")

    if drift:
        print("version drift detected:", file=sys.stderr)
        for line in drift:
            print(f"  {line}", file=sys.stderr)
        return 1

    if checking:
        print(f"all packages at {expected}")
    elif args.dry_run:
        print(f"(dry run — nothing written; target {expected})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
