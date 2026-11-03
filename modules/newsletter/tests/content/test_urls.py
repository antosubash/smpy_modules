import pytest
from sm_newsletter.content.urls import (
    UNSUBSCRIBE_TAG,
    absolute,
    check_image,
    check_link,
    is_relative,
)


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:x",
        "data:text/html,x",
        "vbscript:",
        "//evil",
        "http://a b",
        "\nhttp://a",
        "{{first_name}}",
        "/\\evil",
        "/\\\\evil",
    ],
)
def test_check_link_refuses(bad):
    with pytest.raises(ValueError):
        check_link(bad)


@pytest.mark.parametrize("ok", ["https://ex.org/a", "mailto:a@b", "/de/p/x", UNSUBSCRIBE_TAG])
def test_check_link_accepts(ok):
    assert check_link(ok) == ok


def test_check_link_length():
    with pytest.raises(ValueError):
        check_link("https://ex.org/" + "a" * 2000)


def test_check_image():
    for ok in ["", "https://a/i.png", "//cdn/i.png", "/m.png"]:
        assert check_image(ok) == ok
    for bad in [
        "javascript:x",
        "data:image/png;base64,xx",
        "///x",
        "a b",
        "/\\evil",
        "//?x",
        "//#",
    ]:
        with pytest.raises(ValueError):
            check_image(bad)


@pytest.mark.parametrize(
    ("base", "url", "want"),
    [
        ("https://ex.org/", "/de/p/x", "https://ex.org/de/p/x"),
        ("https://ex.org/base", "/m.png", "https://ex.org/base/m.png"),
        ("", "/x", "/x"),
        ("https://ex.org", "//cdn/i.png", "https://cdn/i.png"),
        ("https://ex.org", "mailto:a@b", "mailto:a@b"),
        ("https://ex.org", UNSUBSCRIBE_TAG, UNSUBSCRIBE_TAG),
        ("https://ex.org", "https://a/b", "https://a/b"),
    ],
)
def test_absolute(base, url, want):
    assert absolute(base, url) == want


def test_is_relative():
    assert is_relative("/x") and is_relative("//h/x")
    assert not is_relative("https://a") and not is_relative("mailto:a@b")
