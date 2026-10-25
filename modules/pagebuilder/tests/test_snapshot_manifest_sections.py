"""The manifest's known-section table belongs to the host (#80).

``check_manifest(payload, known)``: the sections a host registered, and the
versions of each it reads. Split from ``test_snapshot_manifest.py``, which
covers the manifest's own shape.
"""

from __future__ import annotations

import pytest
from pagebuilder.snapshots.archive import BundleError
from pagebuilder.snapshots.manifest import check_manifest


def _section(name: str, **extra) -> dict:
    return {"section": name, "version": 1, **extra}


def _with(*sections: dict) -> dict:
    return {"format_version": 2, "contents": [_section("pagebuilder"), *sections]}


_KNOWN = {"news": frozenset({1, 2})}


@pytest.mark.parametrize("required", [True, False])
def test_a_known_section_at_a_readable_version_is_accepted(required):
    news = _section("news", version=2, required=required, paths=["news/"], counts={"a": 3})
    assert check_manifest(_with(news), _KNOWN)["contents"][1]["counts"] == {"a": 3}


@pytest.mark.parametrize("required", [True, False])
def test_a_known_section_at_an_unreadable_version_is_refused(required):
    # Refused even when optional (#80 Q1): never a silent partial restore.
    news = _section("news", version=3, required=required, paths=["news/"])
    with pytest.raises(BundleError, match="unsupported version 3 of the 'news' section"):
        check_manifest(_with(news), _KNOWN)


def test_a_known_section_is_confined_to_its_own_paths():
    news = _section("news", required=False, paths=["pages/"])
    with pytest.raises(BundleError, match="outside news/"):
        check_manifest(_with(news), _KNOWN)


@pytest.mark.parametrize("counts", [[1], {"a": "1"}, {"a": True}])
def test_section_counts_must_be_integers(counts):
    news = _section("news", required=False, paths=["news/"], counts=counts)
    with pytest.raises(BundleError, match="counts"):
        check_manifest(_with(news))


def test_the_known_table_never_widens_pagebuilders_own_versions():
    contents = [_section("pagebuilder", version=2)]
    with pytest.raises(BundleError, match="unsupported version 2"):
        check_manifest({"format_version": 2, "contents": contents}, {"pagebuilder": frozenset({2})})
