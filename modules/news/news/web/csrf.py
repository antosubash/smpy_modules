"""Kept only as the target of the deprecated ``news.csrf`` alias (#319, #342).

News no longer shares a CSRF token of its own. Its API still checks the
framework's ``RequiresCsrf`` on every write, and the console gets the token as
the framework's ``csrfToken`` shared prop, which every signed-in page carries
(``simple_module_hosting`` 0.0.38+). ``ui/utils/csrf.ts`` reads it through
``currentCsrfToken`` from ``@simple-module-py/ui``.

This module goes in 0.0.17 together with the alias.
"""

from __future__ import annotations

#: The framework's shared-prop name for the token (``CSRF_SHARED_PROP``).
CSRF_PROP = "csrfToken"
