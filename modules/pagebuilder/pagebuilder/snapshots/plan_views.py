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
import logging
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
logger = logging.getLogger(__name__)

DETAILS_UNAVAILABLE_KEY = "pagebuilder.plan.section_details_unavailable"
"""``{label}``: the details of this plan could not be read; the counts stand."""
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


def read_details(root: Path, import_id: int) -> Details | None:
    """The staged items, or ``None`` when the file is missing, unreadable or not a map."""
    path = _dir(root, import_id) / _DETAILS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def remove_details(root: Path, import_ids: list[int]) -> None:
    for import_id in import_ids:
        shutil.rmtree(_dir(root, import_id), ignore_errors=True)


def _counts_only(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: len(v) if isinstance(v, list) else v for k, v in value.items()}
    return value


def _bare(entry: dict[str, Any]) -> dict[str, Any]:
    """*entry* with every line's items cleared, whatever was stored."""
    return {**entry, "lines": [{**line, "items": []} for line in entry.get("lines") or []]}


def _items_for(entry: dict[str, Any], details: Details | None) -> list[list[Any]] | None:
    """The staged items of *entry*'s lines, or ``None`` if they cannot be read."""
    got = (details or {}).get(entry["section"])
    lines = entry.get("lines") or []
    if (
        isinstance(got, list)
        and len(got) == len(lines)
        and all(isinstance(items, list) for items in got)
    ):
        return got
    return None


def for_reader(
    plan: dict[str, Any],
    details: Details | None,
    registry: SectionRegistry,
    access: SectionAccess,
    *,
    import_id: int | None = None,
) -> dict[str, Any]:
    """*plan* as *access* may read it; see the module docstring.

    Items come only from *details*, never from the stored plan: a plan holding
    inline items (one staged by any other code path) is served bare, so the
    boundary holds whatever was stored. Details that cannot be read give the
    counts with ``details_unavailable`` rather than silently empty lists.
    """

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
        bare = _bare(entry)
        if lacking is not None:
            marker = {"redacted": True, "reason_key": REDACTED_REASON_KEY, "permissions": lacking}
            sections.append(bare | marker)
            continue
        items = _items_for(entry, details)
        if items is None:
            logger.warning(
                "plan details for import %s, section %r are missing or unreadable",
                import_id,
                entry["section"],
            )
            sections.append(
                bare | {"details_unavailable": True, "note_key": DETAILS_UNAVAILABLE_KEY}
            )
            continue
        lines = [{**line, "items": got} for line, got in zip(bare["lines"], items, strict=True)]
        sections.append({**bare, "lines": lines})
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
