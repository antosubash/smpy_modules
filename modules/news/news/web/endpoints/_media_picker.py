"""Optional media browsing uses the same read gate as the library itself."""

from fastapi import Request
from simple_module_hosting.permissions import ensure_resolved_permissions

from news.integrations import pagebuilder


async def media_picker_allowed(request: Request) -> bool:
    """Offer the picker only where the library is mounted and this user may read it."""
    if not pagebuilder.mounted(request.app):
        return False
    return pagebuilder.may_read(await ensure_resolved_permissions(request))
