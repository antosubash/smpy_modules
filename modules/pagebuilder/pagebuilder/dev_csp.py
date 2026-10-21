"""Let the editor's bundled font load from the Vite dev server (#188).

The editor's Inter is self-hosted: ``@fontsource-variable/inter`` is part of
the bundle, so in production its files are served from the host's own origin
and the console's ``font-src 'self'`` already allows them. Under ``vite dev``
every bundled asset comes from the Vite origin instead, and the framework's
development CSP widens ``script-src``, ``style-src`` and ``connect-src`` for
that origin but not ``font-src`` — so a module that ships a font file is
blocked in development only.

This provider adds the Vite origin to ``font-src`` in development and nothing
otherwise; the production policy is unchanged. It belongs in the framework's
``dev_csp`` and can go once that widens ``font-src`` itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def vite_font_source(app: Any) -> Iterable[tuple[str, str]]:
    """``[("font-src", <vite origin>)]`` under the Vite dev server, else ``[]``."""
    sm = getattr(app.state, "sm", None)
    config = getattr(sm, "inertia_config", None)
    if config is None or getattr(config, "environment", None) != "development":
        return []
    origin = str(getattr(config, "dev_url", "") or "").rstrip("/")
    # The host validates the pair and drops (and logs) one it would refuse.
    return [("font-src", origin)] if origin else []
