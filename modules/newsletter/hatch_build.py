"""Wheel build hook: the packaged ``package.json`` points at the packaged layout (#472).

``package.json`` lives at the module root so npm workspaces see it, and its
entry points say so: ``"./<package>/index.ts"``. The wheel copies it *into* the
package, next to ``index.ts``, where that path names a folder that does not
exist; a host that installed the wheel could not import the bare package name.
This writes the copy with the ``<package>/`` step removed.

An editable install serves the source tree, so it keeps the file as written.
The same file sits in every module that ships an entry point; keep the copies
identical (``scripts/tests/test_wheel_contents.py``).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

ENTRY_KEYS = ("exports", "main", "module", "types")


def repoint(value: Any, package: str) -> Any:
    """``./<package>/x`` becomes ``./x`` in a string, at any depth of ``exports``."""
    prefix = f"./{package}/"
    if isinstance(value, str):
        return "./" + value[len(prefix) :] if value.startswith(prefix) else value
    if isinstance(value, dict):
        return {key: repoint(inner, package) for key, inner in value.items()}
    if isinstance(value, list):
        return [repoint(inner, package) for inner in value]
    return value


class PackageJsonHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        package = self.config["package"]
        source = Path(self.root) / "package.json"
        target = f"{package}/package.json"
        if version == "editable":
            build_data["force_include"][str(source)] = target
            return
        manifest = json.loads(source.read_text(encoding="utf-8"))
        for key in ENTRY_KEYS:
            if key in manifest:
                manifest[key] = repoint(manifest[key], package)
        self._scratch = tempfile.TemporaryDirectory()
        packaged = Path(self._scratch.name) / "package.json"
        packaged.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        build_data["force_include"][str(packaged)] = target

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        scratch = getattr(self, "_scratch", None)
        if scratch is not None:
            scratch.cleanup()
