"""The exact object-key layout. Changing a string here moves every stored object."""

from __future__ import annotations

from sm_images import storage_keys as k

T, C, IMG = "t1", "c1", "i1"


def test_original_key():
    assert k.original_key(T, C, IMG, "jpg") == "images/t1/c1/i1/original.jpg"


def test_display_key_carries_the_generation():
    assert k.display_key(T, C, IMG, 3) == "images/t1/c1/i1/display.3.jpg"
    assert k.display_key(T, C, IMG, 4) != k.display_key(T, C, IMG, 3)


def test_rendition_key():
    assert k.rendition_key(T, C, IMG, "marker", 0) == "images/t1/c1/i1/r/marker.0.jpg"
    assert k.rendition_key(T, C, IMG, "large", 2) == "images/t1/c1/i1/r/large.2.jpg"


def test_map_and_import_keys():
    assert k.map_key(T, C) == "images/t1/c1/map.pmtiles"
    assert k.import_key(T, "j1", "source.json") == "images/t1/imports/j1/source.json"


def test_extension_is_sanitised():
    assert k.original_key(T, C, IMG, ".JPG") == "images/t1/c1/i1/original.jpg"
    assert k.original_key(T, C, IMG, "../x/y") == "images/t1/c1/i1/original.xy"
