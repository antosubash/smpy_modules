"""``is_color`` is what keeps the accent safe to put in a style attribute."""

from __future__ import annotations

import pytest
from sm_newsletter.content.render.styles import is_color, link_style


@pytest.mark.parametrize("value", ["#fff", "#2563eb", "#2563EBff"])
def test_hex_colours_pass(value: str) -> None:
    assert is_color(value)


@pytest.mark.parametrize("value", ["", "red", "#xyz", "#2563eb\n", "#2563eb;x:y", " #fff"])
def test_anything_else_is_refused(value: str) -> None:
    assert not is_color(value)
    with pytest.raises(ValueError):
        link_style(value)
