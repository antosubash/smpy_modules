import pytest
from sm_newsletter.content.merge import (
    CAPABILITY_TAGS,
    check_merge,
    check_no_capability,
    personalise_html,
    personalise_text,
)
from sm_newsletter.content.urls import UNSUBSCRIBE_TAG

U = "https://ex.org/u/t?a=1&b=2"


def test_unknown_tag_refused():
    with pytest.raises(ValueError):
        check_merge("Hi {{last_name}}")
    with pytest.raises(ValueError):
        check_merge("Hi {{first_name")


def test_fallback_rules():
    check_merge("Hi {{first_name|Friend}} {{first_name}} {{unsubscribe_url}}")
    with pytest.raises(ValueError):
        check_merge("{{first_name|" + "x" * 101 + "}}")
    with pytest.raises(ValueError):
        check_merge("{{unsubscribe_url|x}}")


def test_personalise_html_escapes():
    out = personalise_html("Hi {{first_name}}", first_name="<b>", unsubscribe_url=U)
    assert out == "Hi &lt;b&gt;"
    assert (
        personalise_html("{{unsubscribe_url}}", first_name=None, unsubscribe_url=U)
        == "https://ex.org/u/t?a=1&amp;b=2"
    )


def test_empty_first_name_uses_fallback():
    for name in (None, "", "   "):
        assert (
            personalise_html("Hi {{first_name|Friend}}!", first_name=name, unsubscribe_url=U)
            == "Hi Friend!"
        )
    assert personalise_html("Hi {{first_name}}!", first_name=None, unsubscribe_url=U) == "Hi !"


def test_text_fallback_raw():
    assert (
        personalise_text("{{first_name|Tom & Jerry}}", first_name=None, unsubscribe_url=U)
        == "Tom & Jerry"
    )
    assert (
        personalise_text(
            "{{first_name}} {{unsubscribe_url}}", first_name=" Ann ", unsubscribe_url=U
        )
        == f"Ann {U}"
    )


def test_escaped_fallback_near_cap_is_substituted():
    import html

    raw = "Tom & Jerry " * 8
    check_merge("{{first_name|" + raw + "}}")
    out = personalise_html(
        "{{first_name|" + html.escape(raw) + "}}", first_name=None, unsubscribe_url=U
    )
    assert out == html.escape(raw) and "{{" not in out


def test_check_no_capability():
    with pytest.raises(ValueError) as err:
        check_no_capability("Hi {{unsubscribe_url}} there", field="subject")
    assert str(err.value) == "subject: merge field not allowed here"
    assert "unsubscribe_url" not in str(err.value)
    assert check_no_capability("Hi {{first_name|x}}", field="preheader") == "Hi {{first_name|x}}"
    assert UNSUBSCRIBE_TAG in CAPABILITY_TAGS
