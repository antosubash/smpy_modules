"""Permission constants + suggested role map for the pagebuilder module.

The approval workflow carves three permissions out of what was
previously a single admin surface:

* ``pagebuilder.edit`` — draft, save, submit for review, restore.
* ``pagebuilder.publish`` — publish / unpublish directly.
* ``pagebuilder.approve`` — approve or reject a submitted page.

Enforcement reuses ``simple_module_hosting.permissions.RequiresPermission``
unchanged — re-exported here so endpoint code only needs one import.
"""

from __future__ import annotations

from simple_module_hosting.permissions import RequiresPermission

__all__ = [
    "ALL_PERMISSIONS",
    "DEFAULT_ROLE_MAP",
    "PERM_APPROVE",
    "PERM_EDIT",
    "PERM_PUBLISH",
    "ROLE_APPROVER",
    "ROLE_EDITOR",
    "ROLE_PUBLISHER",
    "RequiresPermission",
]

PERM_EDIT = "pagebuilder.edit"
PERM_PUBLISH = "pagebuilder.publish"
PERM_APPROVE = "pagebuilder.approve"

ALL_PERMISSIONS: tuple[str, ...] = (PERM_EDIT, PERM_PUBLISH, PERM_APPROVE)

ROLE_EDITOR = "pagebuilder_editor"
ROLE_PUBLISHER = "pagebuilder_publisher"
ROLE_APPROVER = "pagebuilder_approver"

DEFAULT_ROLE_MAP: dict[str, list[str]] = {
    ROLE_EDITOR: [PERM_EDIT],
    ROLE_PUBLISHER: [PERM_EDIT, PERM_PUBLISH],
    ROLE_APPROVER: [PERM_EDIT, PERM_PUBLISH, PERM_APPROVE],
}
