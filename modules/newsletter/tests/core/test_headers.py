import pytest
from sm_newsletter.core.headers import check_header_text


@pytest.mark.parametrize("bad", ["a\rb", "a\nb", "a\x00b", "a\tb", "a\x7fb"])
def test_refuses_control_characters(bad):
    with pytest.raises(ValueError) as exc:
        check_header_text(bad, field="subject")
    assert "subject" in str(exc.value)
    assert bad not in str(exc.value)


def test_accepts_plain_unicode():
    assert check_header_text("Grüße — 你好 ✉", field="subject") == "Grüße — 你好 ✉"
