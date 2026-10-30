"""Detector weights: the configured directory, or a pinned, checksummed download
cached once. Never bundled in the wheel."""

from __future__ import annotations

import hashlib
import stat

import httpx
import pytest
from sm_images.pipeline.steps.anonymize import weights
from sm_images.pipeline.steps.anonymize.weights import WeightsSpec, WeightsUnavailable

BLOB = b"pretend these are weights"
SPEC = WeightsSpec(
    kind="face",
    filename="face.onnx",
    url="https://example.org/pinned/face.onnx",
    sha256=hashlib.sha256(BLOB).hexdigest(),
    size=len(BLOB),
)


@pytest.fixture
def served(monkeypatch):
    """The pinned URL answers with ``state['body']``; requests are counted."""
    state = {"body": BLOB, "requests": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"] += 1
        assert str(request.url) == SPEC.url
        return httpx.Response(200, content=state["body"])

    monkeypatch.setattr(weights, "WEIGHTS", {"face": SPEC})
    monkeypatch.setattr(
        weights, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    return state


def test_every_pinned_url_is_https_and_checksummed():
    assert set(weights.WEIGHTS) == {"face", "plate"}
    for spec in weights.WEIGHTS.values():
        assert spec.url.startswith("https://") and spec.filename == f"{spec.kind}.onnx"
        assert len(spec.sha256) == 64 and spec.size > 0
    # The face model is pinned to an opencv_zoo commit, not a branch.
    assert "/raw/eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4/" in weights.WEIGHTS["face"].url


def load(kind: str = "face", configured: str = "", **kw) -> bytes:
    """What onnxruntime would be handed."""
    return weights.weights_bytes(kind, configured, **kw)


def test_a_configured_directory_is_used_as_is(tmp_path, served):
    (tmp_path / "face.onnx").write_bytes(b"operator's own weights")
    assert load("face", str(tmp_path)) == b"operator's own weights"
    assert served["requests"] == 0  # never downloaded, never checksummed


def test_a_configured_directory_without_the_file_fails_closed(tmp_path, served):
    with pytest.raises(WeightsUnavailable, match=r"face\.onnx"):
        load("face", str(tmp_path))
    assert served["requests"] == 0


def test_downloaded_once_then_loaded_from_the_cache(tmp_path, served):
    cache = tmp_path / "cache"
    assert load(cache_dir=cache) == BLOB
    assert (cache / "face.onnx").read_bytes() == BLOB
    assert stat.S_IMODE(cache.stat().st_mode) == 0o700
    assert load(cache_dir=cache) == BLOB
    assert served["requests"] == 1


def test_a_file_swapped_after_verification_is_never_loaded(tmp_path, served, monkeypatch):
    """The hash covers the bytes the loader reads, not a path reopened later."""
    cache = tmp_path / "cache"
    load(cache_dir=cache)
    real = weights._matches

    def swap_after_hashing(data: bytes, spec) -> bool:
        ok = real(data, spec)
        (cache / "face.onnx").write_bytes(b"evil" * (len(BLOB) // 4) + b"e")
        return ok

    monkeypatch.setattr(weights, "_matches", swap_after_hashing)
    assert load(cache_dir=cache) == BLOB
    monkeypatch.setattr(weights, "_matches", real)
    # Re-verified on every load, never trusted by name: the swapped file is
    # refused and the pinned one fetched again.
    assert load(cache_dir=cache) == BLOB
    assert served["requests"] == 2


def test_a_symlink_in_the_cache_is_refused(tmp_path, served):
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    target = tmp_path / "elsewhere.onnx"
    target.write_bytes(BLOB)
    (cache / "face.onnx").symlink_to(target)
    with pytest.raises(WeightsUnavailable, match="symlink"):
        load(cache_dir=cache)
    assert served["requests"] == 0


def test_a_symlinked_cache_directory_is_refused(tmp_path, served):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (tmp_path / "cache").symlink_to(real_dir)
    with pytest.raises(WeightsUnavailable, match="symlink"):
        load(cache_dir=tmp_path / "cache")


def test_a_loose_cache_directory_is_tightened(tmp_path, served):
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o755)
    cache.chmod(0o755)
    load(cache_dir=cache)
    assert stat.S_IMODE(cache.stat().st_mode) == 0o700


def test_a_checksum_mismatch_is_refused_and_leaves_nothing(tmp_path, served):
    served["body"] = b"pretend these are WEIGHTS"  # same size, other bytes
    cache = tmp_path / "cache"
    with pytest.raises(WeightsUnavailable, match="checksum"):
        load(cache_dir=cache)
    assert list(cache.iterdir()) == []


def test_an_oversized_download_is_cut_off(tmp_path, served):
    served["body"] = BLOB * 10
    with pytest.raises(WeightsUnavailable):
        load(cache_dir=tmp_path)
    assert not (tmp_path / "face.onnx").exists()


def test_a_tampered_cache_file_is_fetched_again(tmp_path, served):
    (tmp_path / "face.onnx").write_bytes(b"x" * len(BLOB))
    assert load(cache_dir=tmp_path) == BLOB
    assert served["requests"] == 1


def test_the_default_cache_is_under_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(weights.Path, "home", classmethod(lambda cls: tmp_path))
    assert weights.default_cache_dir() == tmp_path / ".cache" / "simple_module_images" / "models"
