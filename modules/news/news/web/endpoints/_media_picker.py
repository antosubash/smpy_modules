"""Optional media browsing uses the same read gate as the library itself."""

from fastapi import Request
from simple_module_hosting.permissions import ensure_resolved_permissions

from news.integrations import pagebuilder


async def media_picker_allowed(request: Request) -> bool:
    if not pagebuilder.available() or not pagebuilder.may_read(
        await ensure_resolved_permissions(request)
    ):
        return False
    from pagebuilder.contracts.cards import mounted

    return mounted(request.app)
