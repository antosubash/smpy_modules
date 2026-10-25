"""Which contributed sections the acting principal may capture, download and apply (#80).

A contributor names the permissions its section needs
(``BundleSection.capture_permissions`` / ``apply_permissions``, both empty by
default); pagebuilder only checks them, with the framework's own resolution —
:func:`~simple_module_hosting.permissions.ensure_resolved_permissions` and
:func:`~simple_module_core.permissions.grants`, the pair ``RequiresPermission``
uses on every route — so the door and this check cannot disagree. Pagebuilder
never learns what the names mean, and never imports the contributor.

* **Capture.** A snapshot a user takes leaves out a section whose capture
  permissions they lack, and the manifest's ``omitted`` list says so: a
  restore then reads it as "not in this bundle", which never deletes
  anything. A snapshot with no principal behind it — ``pre_restore`` — is a
  system snapshot and captures every section, so a restore stays reversible.
* **Download.** A bundle carrying such a section is a 403 for someone who
  could not have captured it. What each section needed is recorded on the
  snapshot row when the bundle is captured or uploaded
  (:data:`DOWNLOAD_PERMISSIONS_KEY`), so it still holds once the contributor
  is unregistered; a section this host never knew — an upload carrying a
  section no module here registers — has unknown needs, and only someone
  holding ``pagebuilder.approve`` may download it (deny by default).
* **Restore.** A section whose apply permissions the stager lacks is not
  planned (its rows are not shown) and is listed under ``plan.denied``; one
  the approver lacks at approval is skipped the same way. Pages restore
  either way.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from fastapi import Request
from simple_module_core.permissions import grants
from simple_module_hosting.permissions import ensure_resolved_permissions

from pagebuilder.permissions import PERM_APPROVE
from pagebuilder.snapshots.manifest import PAGEBUILDER_SECTION

if TYPE_CHECKING:
    from pagebuilder.contracts.bundle import BundleSection
    from pagebuilder.snapshots.registry import SectionRegistry

Stage = Literal["capture", "apply"]

DENIED_REASON_KEY = "pagebuilder.plan.section_denied"
"""``{label}`` was left out of this restore: it needs ``{permissions}``."""
OMITTED_REASON = "permission"
OMITTED_REASON_KEY = "pagebuilder.plan.section_omitted"
"""``{label}`` was left out of this snapshot: its taker lacked ``{permissions}``."""


def needed(section: BundleSection, stage: Stage) -> tuple[str, ...]:
    """The permissions *section* declares for *stage*, sorted; none by default."""
    return tuple(sorted(getattr(section, f"{stage}_permissions", None) or ()))


DOWNLOAD_PERMISSIONS_KEY = "host_download_permissions"
"""Key on the *stored* manifest (``ContentSnapshot.manifest``, never the
bundle's ``manifest.json``): ``{section: [permission, ...] | None}``, written
by this host. ``None`` is a section it did not know when the bundle arrived."""


@dataclass(frozen=True)
class SectionAccess:
    permissions: frozenset[str] | None
    """What the principal holds; ``None`` is a system action, which holds everything."""

    @classmethod
    async def for_request(cls, request: Request) -> SectionAccess:
        """The request's principal; an anonymous one holds nothing."""
        if getattr(request.state, "user", None) is None:
            return cls(frozenset())
        return cls(frozenset(await ensure_resolved_permissions(request)))

    def missing(self, section: BundleSection, stage: Stage) -> list[str]:
        """The permissions *section* needs for *stage* that this principal lacks."""
        if self.permissions is None:
            return []
        return self.lacking(needed(section, stage))

    def lacking(self, permissions: Iterable[str]) -> list[str]:
        """Which of *permissions* this principal does not hold, sorted."""
        if self.permissions is None:
            return []
        held = self.permissions
        return sorted(p for p in set(permissions) if not grants(held, p))


SYSTEM = SectionAccess(None)


def download_record(
    manifest: dict[str, Any], registry: SectionRegistry
) -> dict[str, list[str] | None]:
    """What each contributed section in *manifest* needs to be downloaded, per this host."""
    record: dict[str, list[str] | None] = {}
    for entry in manifest.get("contents") or []:
        name = entry.get("section") if isinstance(entry, dict) else None
        if not isinstance(name, str) or name == PAGEBUILDER_SECTION:
            continue
        section = registry.get(name)
        record[name] = list(needed(section, "capture")) if section is not None else None
    return record


def download_needs(manifest: dict[str, Any], registry: SectionRegistry) -> set[str]:
    """Every permission downloading a stored bundle takes, beyond ``pagebuilder.publish``.

    The recorded needs and the registered section's current ones, together; a
    section with neither — unknown when it arrived and not registered now, or a
    row from before the record existed — needs ``pagebuilder.approve``.
    """
    recorded = manifest.get(DOWNLOAD_PERMISSIONS_KEY)
    recorded = recorded if isinstance(recorded, dict) else {}
    needs: set[str] = set()
    for name, now in download_record(manifest, registry).items():
        then = recorded.get(name)
        known = isinstance(then, list) and all(isinstance(p, str) for p in then)
        if known:
            needs.update(then)
        if now is not None:
            needs.update(now)
        elif not known:
            needs.add(PERM_APPROVE)
    return needs


def omitted_entry(section: BundleSection, missing: Iterable[str]) -> dict[str, Any]:
    """The manifest's record of a section a capture left out."""
    return {
        "section": section.name,
        "label_key": section.label_key,
        "reason": OMITTED_REASON,
        "reason_key": OMITTED_REASON_KEY,
        "permissions": list(missing),
    }


def denied_entry(section: BundleSection, missing: Iterable[str]) -> dict[str, Any]:
    """The plan's (and the result's) record of a section a restore skips."""
    return {
        "section": section.name,
        "label_key": section.label_key,
        "reason_key": DENIED_REASON_KEY,
        "permissions": list(missing),
    }
