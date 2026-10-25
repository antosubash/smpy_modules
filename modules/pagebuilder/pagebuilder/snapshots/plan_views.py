"""A staged restore's plan as each reader may see it (#80).

A contributed section's plan lines name its rows — article titles and slugs,
live ones the bundle leaves alone included — and those are the contributor's
to show, not pagebuilder's. So they never go into the ``PendingImport.plan``
column, which is audited and served to everyone with Import / Export rights:

* **Stored:** each section's lines with their counts and tones, items
  emptied. The items go to a host-side file beside the snapshot store,
  ``<snapshot_root>/imports/<import id>/sections.json``, written when the
  restore is staged and removed with the import's snapshot.
* **Served:** :func:`for_reader` puts the items back only for a reader who may
  capture that section (the permissions that also gate downloading it), and
  only for a section registered here now. Anyone else gets the counts and a
  ``redacted`` marker; the same goes for the section's ``applied`` record,
  which becomes counts only. Every response carrying a plan goes through
  ``SnapshotService.readable``, which calls this.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pagebuilder.snapshots.files import write_json
from pagebuilder.snapshots.manifest import PAGEBUILDER_SECTION

if TYPE_CHECKING:
    from pagebuilder.snapshots.access import SectionAccess
    from pagebuilder.snapshots.registry import SectionRegistry

IMPORTS_DIR = "imports"
_DETAILS = "sections.json"
REDACTED_REASON_KEY = "pagebuilder.plan.section_redacted"
"""``{label}``: only the counts are shown; the details need ``{permissions}``."""

Details = dict[str, list[list[dict[str, Any]]]]
"""Section name -> the items of each of its plan lines, in line order."""


def split_items(plan: dict[str, Any]) -> tuple[dict[str, Any], Details]:
    """*plan* with every contributed line's items removed, and those items."""
    details: Details = {}
    sections = []
    for entry in plan.get("sections") or []:
        details[entry["section"]] = [line.get("items") or [] for line in entry["lines"]]
        sections.append({**entry, "lines": [{**line, "items": []} for line in entry["lines"]]})
    return {**plan, "sections": sections}, details


def _dir(root: Path, import_id: int) -> Path:
    return root / IMPORTS_DIR / str(import_id)


def write_details(root: Path, import_id: int, details: Details) -> None:
    """Replace whatever an earlier import with this id left (SQLite reuses ids)."""
    directory = _dir(root, import_id)
    shutil.rmtree(directory, ignore_errors=True)
    write_json(directory / _DETAILS, details)


def read_details(root: Path, import_id: int) -> Details:
    path = _dir(root, import_id) / _DETAILS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def remove_details(root: Path, import_ids: list[int]) -> None:
    for import_id in import_ids:
        shutil.rmtree(_dir(root, import_id), ignore_errors=True)


def _counts_only(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: len(v) if isinstance(v, list) else v for k, v in value.items()}
    return value


def for_reader(
    plan: dict[str, Any], details: Details, registry: SectionRegistry, access: SectionAccess
) -> dict[str, Any]:
    """*plan* as *access* may read it; see the module docstring."""

    def missing(name: str) -> list[str] | None:
        """What the reader lacks to see *name*; ``None`` when they may see it."""
        section = registry.get(name)
        if section is None:
            return []  # no longer registered: nothing says who may see it
        lacking = access.missing(section, "capture")
        return lacking or None

    sections = []
    for entry in plan.get("sections") or []:
        lacking = missing(entry["section"])
        items = details.get(entry["section"]) or []
        if lacking is None and len(items) == len(entry["lines"]):
            lines = [
                {**line, "items": got} for line, got in zip(entry["lines"], items, strict=True)
            ]
            sections.append({**entry, "lines": lines})
        elif lacking is None:
            sections.append(entry)
        else:
            sections.append(
                {
                    **entry,
                    "redacted": True,
                    "reason_key": REDACTED_REASON_KEY,
                    "permissions": lacking,
                }
            )
    out = {**plan, "sections": sections} if "sections" in plan else dict(plan)
    applied = plan.get("applied")
    # Keyed by section since #80; an older row's flat shape is pagebuilder's alone.
    if isinstance(applied, dict) and PAGEBUILDER_SECTION in applied:
        out["applied"] = {
            name: value
            if name == PAGEBUILDER_SECTION or missing(name) is None
            else _counts_only(value)
            for name, value in applied.items()
        }
    return out
