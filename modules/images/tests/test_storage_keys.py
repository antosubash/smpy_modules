"""The exact object-key layout. Changing a string here moves every stored object."""

from __future__ import annotations

from sm_images import storage_keys as k

T, C, IMG = "t1", "c1", "i1"


def test_original_key():
    assert k.original_key(T, C, IMG, "jpg") == "images/t1/c1/i1/original.jpg"


def test_display_key_carries_the_generation_and_attempt():
    assert k.display_key(T, C, IMG, 3, "ab12") == "images/t1/c1/i1/display.3.ab12.jpg"
    assert k.display_key(T, C, IMG, 4, "ab12") != k.display_key(T, C, IMG, 3, "ab12")


def test_two_attempts_at_one_generation_never_share_a_key():
    """A stale worker and the reclaimer both load generation 3: a DB fence alone
    cannot stop the loser overwriting the winner's bytes, the key must differ."""
    assert k.display_key(T, C, IMG, 4, "aaaa") != k.display_key(T, C, IMG, 4, "bbbb")
    assert k.rendition_key(T, C, IMG, "small", 0, "aaaa") != k.rendition_key(
        T, C, IMG, "small", 0, "bbbb"
    )


def test_rendition_key():
    assert k.rendition_key(T, C, IMG, "marker", 0, "ff") == "images/t1/c1/i1/r/marker.0.ff.jpg"
    assert k.rendition_key(T, C, IMG, "large", 2, "ff") == "images/t1/c1/i1/r/large.2.ff.jpg"


def test_attempt_is_sanitised():
    assert k.display_key(T, C, IMG, 1, "../X y") == "images/t1/c1/i1/display.1.xy.jpg"


def test_map_and_import_keys():
    assert k.map_key(T, C, 3, "AB/x") == "images/t1/c1/map.3.abx.pmtiles"
    assert k.import_key(T, "j1", "source.json") == "images/t1/imports/j1/source.json"


def test_extension_is_sanitised():
    assert k.original_key(T, C, IMG, ".JPG") == "images/t1/c1/i1/original.jpg"
    assert k.original_key(T, C, IMG, "../x/y") == "images/t1/c1/i1/original.xy"
