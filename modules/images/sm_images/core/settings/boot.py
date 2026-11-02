"""The settings the module reads once, while booting - every ``requires_restart``
field of :class:`~sm_images.core.settings.ImagesSettings`, as its base class.

Split from ``settings.py`` along the one seam that means something: everything
declared here is consumed from ``on_startup`` (a binary located, a base URL
published) so an edit on the Settings screen takes effect at the next boot and
is marked ``requires_restart``. Everything declared on the subclass is read per
request, or per task by a worker through
``background_tasks.settings_for(ImagesSettings, "sm_images")``.

A base class and not a mixin: pydantic collects fields and validators only from
``BaseModel`` subclasses, and ``use_attribute_docstrings`` applies where a field
is declared, so the config is repeated here or the Settings screen would show
these two with no explanation.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from simple_module_core.settings_base import DbBackedSettings

_RESTART: Final[dict[str, Any]] = {"requires_restart": True}
"""Marks a field the module reads once, while booting. See the module docstring."""


class BootSettings(DbBackedSettings):
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    tippecanoe_path: str = Field(default="tippecanoe", json_schema_extra=_RESTART)
    """The ``tippecanoe`` binary that builds PMTiles for the map view.

    A bare name is looked up on ``PATH``, by the web process (the health check,
    as booted, so a new value needs a restart) and by each map build in a
    worker. Without it no PMTiles archive is built - the health check reports
    it - and the map falls back to GeoJSON points.
    """

    public_asset_base_url: str = Field(default="", json_schema_extra=_RESTART)
    """Origin (``https://cdn.example.org``) that serves public renditions.

    Empty (the default) serves them through this application. When set, public
    pages link renditions of public collections to this base instead. Read once,
    while booting, with the route table. Single-tenant hosts only: a
    multi-tenant host ignores it (with a boot warning), because a CDN origin
    carries no tenant and the public routes behind it would 404.
    """
