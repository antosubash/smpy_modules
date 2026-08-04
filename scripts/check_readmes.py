"""Enforce per-package README.md presence and baseline quality.

Rules for every package directory (under modules/*):
  * A README.md must exist.
  * It must be at least 500 bytes (sanity check against stub files).
  * It must contain an H1 (line starting with "# ").
  * It must mention "Install" and "Usage" as section headings or inline text.

Exit 0 if all pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MIN_BYTES = 500
REQUIRED_SECTIONS = ("Install", "Usage")


def check_readme(package_dir: Path) -> list[str]:
    readme = package_dir / "README.md"
    if not readme.exists():
        return [f"{readme}: README.md not found"]

    text = readme.read_text(encoding="utf-8")
    errors: list[str] = []

    if len(text.encode("utf-8")) < MIN_BYTES:
        errors.append(f"{readme}: README.md too short (< {MIN_BYTES} bytes)")

    if not any(line.startswith("# ") for line in text.splitlines()):
        errors.append(f"{readme}: missing H1 heading")

    for section in REQUIRED_SECTIONS:
        if section not in text:
            errors.append(f"{readme}: missing '{section}' section/mention")

    return errors


def discover_packages(root: Path) -> list[Path]:
    dirs: list[Path] = []
    base_dir = root / "modules"
    if not base_dir.is_dir():
        return dirs
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir():
            continue
        if (child / "pyproject.toml").exists():
            dirs.append(child)
    return dirs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    errors: list[str] = []
    for pkg_dir in discover_packages(args.root):
        errors.extend(check_readme(pkg_dir))

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\nFAIL: {len(errors)} README violation(s).", file=sys.stderr)
        return 1
    print("All READMEs OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
