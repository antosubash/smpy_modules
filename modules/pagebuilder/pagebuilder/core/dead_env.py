"""Say so at boot when the environment still carries ``SM_PAGEBUILDER_*`` (#459).

Pagebuilder's settings are database-backed since 0.0.15 and the class drops
every env source, so such a variable does nothing. A deployment that set
``SM_PAGEBUILDER_MEDIA_ROOT`` kept booting, served no images and wrote new
uploads to the container's own layer, and nothing in the log named the cause.

Only the process environment is looked at: a ``.env`` file is the host's to
locate, and a container sets these as real variables. A value is never logged.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from pagebuilder.core.settings import PagebuilderSettings

_log = logging.getLogger("simple_module.pagebuilder")

PREFIX = "SM_PAGEBUILDER_"
MEDIA_ROOT_VAR = f"{PREFIX}MEDIA_ROOT"


def dead_env_vars(environ: Mapping[str, str] | None = None) -> list[tuple[str, str | None]]:
    """``(variable, setting it used to feed or None)`` for each one set, sorted by name."""
    env = os.environ if environ is None else environ
    found = []
    for name in sorted(env):
        if not name.upper().startswith(PREFIX):
            continue
        field = name[len(PREFIX) :].lower()
        found.append((name, field if field in PagebuilderSettings.model_fields else None))
    return found


def warn_on_dead_env(environ: Mapping[str, str] | None = None) -> list[str]:
    """One warning per variable; returns the names, for the media hint below."""
    names = []
    for name, field in dead_env_vars(environ):
        names.append(name)
        if field is None:
            _log.warning(
                "pagebuilder: the environment variable %s is ignored and matches no "
                "pagebuilder setting. Remove it.",
                name,
            )
        else:
            _log.warning(
                "pagebuilder: the environment variable %s is ignored. Pagebuilder settings "
                "are stored in the database: set %s on the Settings screen or with "
                "`python scripts/set_setting.py pagebuilder %s <value>`, restart if the "
                "screen marks it, then remove the variable.",
                name,
                field,
                field,
            )
    return names


def media_root_hint(environ: Mapping[str, str] | None = None) -> None:
    """Called when media rows have no file: name the likeliest cause if it is this one."""
    env = os.environ if environ is None else environ
    if any(name.upper() == MEDIA_ROOT_VAR for name in env):
        _log.warning(
            "pagebuilder.media: %s is set but ignored, so the files are probably in the "
            "directory it names. Set the media_root setting to that directory "
            "(`python scripts/set_setting.py pagebuilder media_root <dir>`) and restart.",
            MEDIA_ROOT_VAR,
        )
