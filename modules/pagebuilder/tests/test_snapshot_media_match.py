from __future__ import annotations

import hashlib

import pytest
from pagebuilder.media_files import resolve_media_root
from pagebuilder.models import MediaAsset
from pagebuilder.snapshots.media_match import match_existing

pytestmark = pytest.mark.asyncio

_OURS = b"the picture this host already has"
_THEIRS = b"a completely different picture"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _add(snapshot_db, *, filename: str, original: str, data: bytes | None):
    root = resolve_media_root(snapshot_db.settings.media_root) / "default"
    root.mkdir(parents=True, exist_ok=True)
    if data is not None:
        (root / filename).write_bytes(data)
    asset = MediaAsset(
        filename=filename, original_filename=original, content_type="image/jpeg"
    )
    snapshot_db.session.add(asset)
    await snapshot_db.session.flush()
    return asset


def _index(sha: str, original: str = "hero.jpg", bundle_name: str = "hero.jpg"):
    return {bundle_name: {"sha256": sha, "original_filename": original}}


async def test_same_name_and_same_bytes_matches(snapshot_db):
    """Re-running a restore must not duplicate an asset it already has."""
    asset = await _add(snapshot_db, filename="u1.jpg", original="hero.jpg", data=_OURS)
    matched = await match_existing(
        snapshot_db.session, snapshot_db.settings, _index(_sha(_OURS))
    )
    assert matched["hero.jpg"].id == asset.id


async def test_same_name_but_different_bytes_does_not_match(snapshot_db):
    """The bug this exists to prevent.

    Two hosts can each have their own `hero.jpg`. Matching on the name alone
    would repoint every restored page at this host's picture and report
    nothing — the restored site would look wrong with no error anywhere.
    """
    await _add(snapshot_db, filename="u1.jpg", original="hero.jpg", data=_OURS)
    matched = await match_existing(
        snapshot_db.session, snapshot_db.settings, _index(_sha(_THEIRS))
    )
    assert matched == {}


async def test_matches_the_right_one_when_a_name_is_ambiguous(snapshot_db):
    """One name, two assets: the digest picks, not the ordering."""
    await _add(snapshot_db, filename="u1.jpg", original="hero.jpg", data=_OURS)
    wanted = await _add(
        snapshot_db, filename="u2.jpg", original="hero.jpg", data=_THEIRS
    )
    matched = await match_existing(
        snapshot_db.session, snapshot_db.settings, _index(_sha(_THEIRS))
    )
    assert matched["hero.jpg"].id == wanted.id


async def test_a_row_whose_file_is_missing_does_not_match(snapshot_db):
    """Issue #14's divergence reads as 'no match', so the restore repairs it."""
    await _add(snapshot_db, filename="gone.jpg", original="hero.jpg", data=None)
    matched = await match_existing(
        snapshot_db.session, snapshot_db.settings, _index(_sha(_OURS))
    )
    assert matched == {}


async def test_a_name_this_host_has_never_seen_does_not_match(snapshot_db):
    matched = await match_existing(
        snapshot_db.session, snapshot_db.settings, _index(_sha(_OURS), "unseen.jpg")
    )
    assert matched == {}


async def test_a_disambiguated_bundle_name_still_matches_by_original(snapshot_db):
    """`hero~2.jpg` is a bundle-local label; the asset's own name is `hero.jpg`."""
    asset = await _add(snapshot_db, filename="u1.jpg", original="hero.jpg", data=_OURS)
    matched = await match_existing(
        snapshot_db.session,
        snapshot_db.settings,
        _index(_sha(_OURS), original="hero.jpg", bundle_name="hero~2.jpg"),
    )
    assert matched["hero~2.jpg"].id == asset.id
