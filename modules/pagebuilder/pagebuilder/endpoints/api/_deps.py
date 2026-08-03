"""Permission dependencies shared by every admin API sub-router.

Per-endpoint :class:`~pagebuilder.permissions.RequiresPermission` deps let
hosts run the editor → publisher workflow without granting every editor
publish rights.
"""

from __future__ import annotations

from fastapi import Depends

from pagebuilder.permissions import (
    PERM_APPROVE,
    PERM_EDIT,
    PERM_PUBLISH,
    RequiresPermission,
)

require_edit = Depends(RequiresPermission(PERM_EDIT))
require_publish = Depends(RequiresPermission(PERM_PUBLISH))
require_approve = Depends(RequiresPermission(PERM_APPROVE))
