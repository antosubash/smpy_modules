from __future__ import annotations

from pagebuilder.snapshots.assets import (
    bundle_names,
    collect_sentinels,
    from_sentinels,
    to_sentinels,
)

DOC = {
    "content": [
        {"type": "Image", "props": {"src": "/media/pagebuilder/abc123.jpg"}},
        {"type": "Logo", "props": {"src": "/canopy-atlas/static/gca/logo.svg"}},
        {"type": "Link", "props": {"href": "/gca/contact"}},
    ]
}

_LIVE_URL = "/media/pagebuilder/abc123.jpg"


def test_to_sentinels_only_rewrites_known_media_urls():
    out = to_sentinels(DOC, {_LIVE_URL: "hero.jpg"})
    props = [block["props"] for block in out["content"]]
    assert props[0]["src"] == "asset://hero.jpg"
    # A module static mount and an in-site link are not media; both survive.
    assert props[1]["src"] == "/canopy-atlas/static/gca/logo.svg"
    assert props[2]["href"] == "/gca/contact"


def test_to_sentinels_does_not_mutate_its_input():
    to_sentinels(DOC, {_LIVE_URL: "hero.jpg"})
    assert DOC["content"][0]["props"]["src"] == _LIVE_URL


def test_round_trip_restores_the_url_this_host_assigned():
    sentinels = to_sentinels(DOC, {_LIVE_URL: "hero.jpg"})
    back = from_sentinels(sentinels, {"hero.jpg": "/media/pagebuilder/zzz999.jpg"})
    assert back["content"][0]["props"]["src"] == "/media/pagebuilder/zzz999.jpg"


def test_unknown_sentinel_is_left_alone_for_the_caller_to_reject():
    # Blanking it would turn a malformed bundle into an invisible broken image.
    back = from_sentinels({"src": "asset://missing.jpg"}, {})
    assert back["src"] == "asset://missing.jpg"
    assert collect_sentinels(back) == {"missing.jpg"}


def test_collect_sentinels_walks_lists_and_nested_dicts():
    doc = {"a": [{"b": "asset://one.jpg"}], "c": {"d": "asset://two.png"}}
    assert collect_sentinels(doc) == {"one.jpg", "two.png"}


def test_bundle_names_disambiguate_duplicates_stably():
    # Two different uploads can share an original_filename; the bundle name is
    # what makes them addressable, so it must be unique and reproducible.
    assert bundle_names([(1, "hero.jpg"), (5, "hero.jpg"), (9, "other.png")]) == {
        1: "hero.jpg",
        5: "hero~2.jpg",
        9: "other.png",
    }


def test_bundle_names_are_independent_of_input_order():
    shuffled = bundle_names([(9, "other.png"), (5, "hero.jpg"), (1, "hero.jpg")])
    assert shuffled == {1: "hero.jpg", 5: "hero~2.jpg", 9: "other.png"}


def test_bundle_names_handle_a_third_collision():
    names = bundle_names([(1, "a.jpg"), (2, "a.jpg"), (3, "a.jpg")])
    assert names == {1: "a.jpg", 2: "a~2.jpg", 3: "a~3.jpg"}
