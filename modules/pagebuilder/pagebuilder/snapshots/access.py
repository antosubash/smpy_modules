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
  could not have captured it.
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

if TYPE_CHECKING:
    from pagebuilder.contracts.bundle import BundleSection

Stage = Literal["capture", "apply"]

DENIED_REASON_KEY = "pagebuilder.plan.section_denied"
"""``{label}`` was left out of this restore: it needs ``{permissions}``."""
OMITTED_REASON = "permission"
OMITTED_REASON_KEY = "pagebuilder.plan.section_omitted"
"""``{label}`` was left out of this snapshot: its taker lacked ``{permissions}``."""


def needed(section: BundleSection, stage: Stage) -> tuple[str, ...]:
    """The permissions *section* declares for *stage*, sorted; none by default."""
    return tuple(sorted(getattr(section, f"{stage}_permissions", None) or ()))


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
        return [p for p in needed(section, stage) if not grants(self.permissions, p)]


SYSTEM = SectionAccess(None)


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
