import pytest
from sm_newsletter.content.merge import check_merge, personalise_html, personalise_text

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
