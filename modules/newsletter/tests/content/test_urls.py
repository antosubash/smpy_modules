import pytest
from sm_newsletter.content.urls import (
    MAX_URL,
    UNSUBSCRIBE_TAG,
    absolute,
    check_image,
    check_link,
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
    at_limit = "https://ex.org/" + "a" * (MAX_URL - len("https://ex.org/"))
    assert check_link(at_limit) == at_limit
    with pytest.raises(ValueError):
        check_link(at_limit + "a")


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


# I5: format characters (RLO, ZWSP, BOM) and C1 controls make a link look like
# something it is not; refuse them anywhere in a link or an image address.
SPOOF = ["\u202e", "\u200b", "\ufeff", "\x85", "\x9b"]


@pytest.mark.parametrize("ch", SPOOF)
def test_format_and_c1_characters_refused(ch):
    with pytest.raises(ValueError):
        check_link(f"https://exa{ch}mple.org/")
    with pytest.raises(ValueError):
        check_link(f"https://example.org/{ch}gnp.exe")
    with pytest.raises(ValueError):
        check_image(f"https://example.org/a{ch}.png")
    with pytest.raises(ValueError):
        check_image(f"/media/a{ch}.png")
