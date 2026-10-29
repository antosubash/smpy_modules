"""Detector weights: the configured directory, or a pinned, checksummed download
cached once. Never bundled in the wheel."""

from __future__ import annotations

import hashlib

import httpx
import pytest
from sm_images.steps.anonymize import weights
from sm_images.steps.anonymize.weights import WeightsSpec, WeightsUnavailable

BLOB = b"pretend these are weights"
SPEC = WeightsSpec(
    kind="face",
    filename="face.pt",
    url="https://example.org/pinned/face.pt",
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
        assert spec.url.startswith("https://") and "/resolve/" in spec.url
        assert len(spec.sha256) == 64 and spec.size > 0


def test_a_configured_directory_is_used_as_is(tmp_path, served):
    (tmp_path / "face.pt").write_bytes(b"operator's own weights")
    assert weights.weights_file("face", str(tmp_path)) == tmp_path / "face.pt"
    assert served["requests"] == 0  # never downloaded, never checksummed


def test_a_configured_directory_without_the_file_fails_closed(tmp_path, served):
    with pytest.raises(WeightsUnavailable, match=r"face\.pt"):
        weights.weights_file("face", str(tmp_path))
    assert served["requests"] == 0


def test_downloaded_once_then_served_from_the_cache(tmp_path, served):
    cache = tmp_path / "cache"
    path = weights.weights_file("face", "", cache_dir=cache)
    assert path == cache / "face.pt" and path.read_bytes() == BLOB
    assert weights.weights_file("face", "", cache_dir=cache) == path
    assert served["requests"] == 1


def test_a_checksum_mismatch_is_refused_and_leaves_nothing(tmp_path, served):
    served["body"] = b"pretend these are WEIGHTS"  # same size, other bytes
    cache = tmp_path / "cache"
    with pytest.raises(WeightsUnavailable, match="checksum"):
        weights.weights_file("face", "", cache_dir=cache)
    assert list(cache.iterdir()) == []


def test_an_oversized_download_is_cut_off(tmp_path, served):
    served["body"] = BLOB * 10
    with pytest.raises(WeightsUnavailable):
        weights.weights_file("face", "", cache_dir=tmp_path)
    assert not (tmp_path / "face.pt").exists()


def test_a_tampered_cache_file_is_fetched_again(tmp_path, served):
    (tmp_path / "face.pt").write_bytes(b"x" * len(BLOB))
    assert weights.weights_file("face", "", cache_dir=tmp_path).read_bytes() == BLOB
    assert served["requests"] == 1


def test_the_default_cache_is_under_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(weights.Path, "home", classmethod(lambda cls: tmp_path))
    assert weights.default_cache_dir() == tmp_path / ".cache" / "simple_module_images" / "models"
