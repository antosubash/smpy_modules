"""Plain text from the sanitised description, for feeds and metadata."""

from __future__ import annotations

from sm_events.feeds.plaintext import to_text


def test_blocks_become_lines():
    assert to_text("<p>a</p><p>b</p>") == "a\n\nb"
    assert to_text("<h2>Title</h2><p>body</p>") == "Title\n\nbody"


def test_lists():
    assert to_text("<ul><li>x</li><li>y</li></ul>") == "- x\n- y"
    assert to_text("<ol><li>x</li><li>y</li></ol>") == "1. x\n2. y"
    assert to_text("<p>a</p><ul><li>x</li></ul><p>b</p>") == "a\n\n- x\n\nb"


def test_links():
    assert to_text('<p><a href="https://a.example/">site</a></p>') == "site (https://a.example/)"
    same = '<p><a href="https://a.example/">https://a.example/</a></p>'
    assert to_text(same) == "https://a.example/"
    assert to_text('<p><a href="mailto:x@y.org">write</a></p>') == "write (mailto:x@y.org)"


def test_entities_decoded():
    assert to_text("<p>a &amp; b &lt;c&gt;</p>") == "a & b <c>"


def test_br():
    assert to_text("<p>a<br>b</p>") == "a\nb"


def test_inline_marks_are_dropped():
    assert to_text("<p><strong>a</strong> <em>b</em> <u>c</u> <s>d</s></p>") == "a b c d"


def test_blockquote():
    assert to_text("<blockquote><p>q</p></blockquote>") == "q"


def test_script_never_survives():
    out = to_text("<p>a</p><script>alert(1)</script><p>b</p>")
    assert "alert" not in out and "<" not in out
    assert out == "a\n\nb"


def test_unsafe_link_is_text_only():
    out = to_text('<p><a href="javascript:alert(1)">x</a></p>')
    assert out == "x" and "javascript" not in out


def test_empty():
    assert to_text("") == "" and to_text("<p></p>") == ""


def test_truncate_word_boundary():
    text = "<p>" + " ".join(["word"] * 50) + "</p>"
    out = to_text(text, max_chars=22)
    assert out.endswith("…") and len(out) <= 22
    assert out[:-1].rstrip().split(" ")[-1] == "word"
    assert to_text("<p>short</p>", max_chars=22) == "short"


def test_truncate_a_single_long_word():
    out = to_text("<p>" + "x" * 100 + "</p>", max_chars=10)
    assert out == "x" * 9 + "…"
