"""Optional media browsing uses the same read gate as the library itself."""

from fastapi import Request
from simple_module_hosting.permissions import ensure_resolved_permissions

from news.integrations import pagebuilder


async def media_picker_allowed(request: Request) -> bool:
    return pagebuilder.available() and pagebuilder.may_read(
        await ensure_resolved_permissions(request)
    )
