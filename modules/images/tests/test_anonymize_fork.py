"""Celery's prefork pool forks workers: an onnxruntime session (its thread pool)
or a lock held by another thread must not cross into a child. Each process
creates its own sessions."""

from __future__ import annotations

import os
import signal

import pytest
from PIL import Image as PILImage

pytest.importorskip("numpy")

from sm_images.steps.anonymize import detectors
from sm_images.steps.anonymize import weights as weights_mod

from tests.onnx_support import FakeOrt, weights_dir


@pytest.fixture
def ort(monkeypatch) -> FakeOrt:
    fake = FakeOrt()
    fake.install(monkeypatch)
    return fake


def _detect(det: detectors.OnnxDetector) -> None:
    det.detect(PILImage.new("RGB", (64, 48)), faces=True, plates=True, min_confidence=0.5)


def test_a_session_is_not_reused_in_another_process(tmp_path, ort, monkeypatch):
    det = detectors.OnnxDetector(weights_dir(tmp_path))
    _detect(det)
    _detect(det)
    assert ort.created == 2  # face + plate, once
    parent = os.getpid()
    monkeypatch.setattr(detectors.os, "getpid", lambda: parent + 1)  # as in a forked child
    _detect(det)
    assert ort.created == 4


def test_a_forked_child_gets_fresh_detectors_and_unheld_locks(tmp_path, ort):
    cfg = weights_dir(tmp_path)
    parent_det = detectors.shared_detector(cfg)
    _detect(parent_det)
    read, write = os.pipe()
    # Another thread of the parent holds every lock at the moment of the fork.
    held = [detectors._shared_lock, parent_det._lock, weights_mod._lock]
    for lock in held:
        lock.acquire()
    try:
        pid = os.fork()
        if pid == 0:  # the child: never returns into pytest
            code = 1
            try:
                signal.alarm(5)  # a lock inherited held would hang here
                child_det = detectors.shared_detector(cfg)
                before = ort.created
                _detect(child_det)
                fresh = child_det is not parent_det and ort.created == before + 2
                code = 0 if fresh else 2
            finally:
                os.write(write, bytes([code]))
                os._exit(0)
    finally:
        for lock in held:
            lock.release()
    os.close(write)
    _, status = os.waitpid(pid, 0)
    result = os.read(read, 1)
    os.close(read)
    assert os.WIFEXITED(status) and result == bytes([0]), (status, result)
