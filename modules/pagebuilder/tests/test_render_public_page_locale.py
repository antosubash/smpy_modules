"""``render_public_page`` names its language (#131).

It used to fall back to the default language when a caller left ``locale``
out. CLAUDE.md's rule is that every slug lookup takes a locale: a viewer that
forgot it would serve the default-language page at a translated address, which
is how ``/de/p/x`` starts serving the English one.
"""

from __future__ import annotations

import inspect

import pytest
from pagebuilder.endpoints.public_views import render_public_page


def test_the_locale_cannot_be_omitted() -> None:
    """Argument binding fails at the call, before any coroutine exists."""
    with pytest.raises(TypeError, match="locale"):
        render_public_page("about", None, None, None, None)  # type: ignore[call-arg, arg-type]


def test_the_locale_has_no_default() -> None:
    param = inspect.signature(render_public_page).parameters["locale"]

    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
