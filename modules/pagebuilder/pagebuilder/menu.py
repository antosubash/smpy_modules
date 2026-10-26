"""Pagebuilder's sidebar entries.

Split out of ``module.py``, which sat at the file-size warning line, when
Import / Export stopped being an entry for everyone.

Pages, Site layout and Media library are deliberately not role-gated. Menu
role filtering is a plain intersection with no admin bypass, so listing the
pagebuilder roles would hide them from an ``admin`` user; and those screens
require authentication only — their write endpoints carry the per-permission
dependencies.

Import / Export is different: the screen is gated on ``pagebuilder.publish``
*or* ``pagebuilder.approve`` (``require_publish_or_approve``), and a static
``MenuItem.permissions`` list means *all of* — declaring both would hide it
from a publisher who cannot approve. So it comes from a per-request provider
that asks the same question the route does. An entry that 403s on click is
worse than no entry at all.
"""

from __future__ import annotations

from collections.abc import Iterable

from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_hosting.permissions import ensure_resolved_permissions
from starlette.requests import Request

from pagebuilder.permissions import may_use_import_export

# Grouped under "Site" so the rail reads News / Site, and a screen's section
# is visible before you click it.
_GROUP = "Site"
#: Catalogue keys under this module's namespace (`pagebuilder.menu.*`).
_KEY = "pagebuilder.menu"
URL_CONTENT = "/pagebuilder/content"


def _item(label: str, key: str, url: str, icon: str, order: int) -> MenuItem:
    return MenuItem(
        label=label,
        label_key=f"{_KEY}.{key}",
        url=url,
        icon=icon,
        order=order,
        section=MenuSection.SIDEBAR,
        group=_GROUP,
        group_key=f"{_KEY}.group_site",
    )


IMPORT_EXPORT = _item("Import / Export", "import_export", URL_CONTENT, "package", 230)
"""After Media library (220), so the group reads in workflow order."""


async def import_export_items(request: Request) -> Iterable[MenuItem]:
    """Import / Export, for a reader holding ``pagebuilder.publish`` or ``.approve``.

    The same rule as ``require_publish_or_approve``, over the permission set
    the layout middleware already resolved and cached for this request (roles
    plus grant sources), so it costs a set lookup, not a second resolution.
    """
    if getattr(request.state, "user", None) is None:
        return []
    held = await ensure_resolved_permissions(request)
    return [IMPORT_EXPORT] if may_use_import_export(held) else []


def register(registry: MenuRegistry) -> None:
    registry.add_many(
        [
            _item("Pages", "pages", "/pagebuilder/", "file-text", 200),
            _item("Site layout", "layout", "/pagebuilder/layout", "layout", 210),
            _item("Media library", "media", "/pagebuilder/media", "image", 220),
        ]
    )
    registry.add_provider(import_export_items)
