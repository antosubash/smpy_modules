"""Pagebuilder's sidebar entries.

Split out of ``module.py``, which sat at the file-size warning line, when
Import / Export stopped being an entry for everyone.

Pages, Site layout and Media library are shown to a reader holding any
pagebuilder permission (#346), the rule ``require_reader`` applies to every
admin route. They are not role-gated: menu role filtering is a plain
intersection with no admin bypass, so listing the pagebuilder roles would hide
them from an ``admin`` user, and a static ``MenuItem.permissions`` list means
*all of*, which no single role here satisfies. So, like Import / Export, they
come from a per-request provider that asks the same question the routes do.

Import / Export is narrower: the screen is gated on ``pagebuilder.publish``
*or* ``pagebuilder.approve`` (``require_publish_or_approve``). An entry that
403s on click is worse than no entry at all.
"""

from __future__ import annotations

from collections.abc import Iterable

from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_hosting.permissions import ensure_resolved_permissions
from starlette.requests import Request

from pagebuilder.core.permissions import may_read, may_use_import_export

# Grouped under "Site" so the rail reads News / Site, and a screen's section
# is visible before you click it.
_GROUP = "Site"
#: Catalogue keys under this module's namespace (`pagebuilder.web.menu.*`).
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


PAGES = _item("Pages", "pages", "/pagebuilder/", "file-text", 200)
LAYOUT = _item("Site layout", "layout", "/pagebuilder/layout", "layout", 210)
MEDIA = _item("Media library", "media", "/pagebuilder/media", "image", 220)

IMPORT_EXPORT = _item("Import / Export", "import_export", URL_CONTENT, "package", 230)
"""After Media library (220), so the group reads in workflow order."""


async def sidebar_items(request: Request) -> Iterable[MenuItem]:
    """The entries this reader may open, asked the way the routes ask.

    Over the permission set the layout middleware already resolved and cached
    for this request (roles plus grant sources), so it costs a set lookup, not
    a second resolution. Pages, Site layout and Media library need any
    pagebuilder permission (``require_reader``); Import / Export needs publish
    or approve (``require_publish_or_approve``).
    """
    if getattr(request.state, "user", None) is None:
        # No user: ``require_reader`` lets the request through (an authenticating
        # proxy in front, ``requires_auth`` off), so the screens are offered as before.
        return [PAGES, LAYOUT, MEDIA]
    held = await ensure_resolved_permissions(request)
    items = [PAGES, LAYOUT, MEDIA] if may_read(held) else []
    if may_use_import_export(held):
        items.append(IMPORT_EXPORT)
    return items


def register(registry: MenuRegistry) -> None:
    registry.add_provider(sidebar_items)
