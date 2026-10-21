"""release.yml's CI gate and PyPI re-upload check (#115), on fixture API output."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import release_ci_gate as gate
import release_pypi_check as pypi

SHA = "a" * 40
OTHER = "b" * 40


def run(
    run_id: int,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    event: str = "push",
    sha: str = SHA,
    path: str = gate.CI_PATH,
    attempt: int = 1,
    created: str = "2026-10-01T00:00:00Z",
) -> dict:
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "event": event,
        "head_sha": sha,
        "path": path,
        "run_attempt": attempt,
        "created_at": created,
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
    }


def page(*runs: dict) -> str:
    return json.dumps({"total_count": len(runs), "workflow_runs": list(runs)})


def verdict(text: str) -> int:
    return gate.decide(gate.iter_runs(text), SHA)[0]


def test_single_green_push_run_releases():
    assert verdict(page(run(1))) == gate.GREEN


def test_no_run_refuses():
    assert verdict(page()) == gate.REFUSE


def test_in_progress_run_waits():
    assert verdict(page(run(1), run(2, status="in_progress", conclusion=None))) == gate.PENDING


def test_queued_run_waits_even_beside_a_failure():
    runs = page(run(1, conclusion="failure"), run(2, status="queued", conclusion=None))
    assert verdict(runs) == gate.PENDING


def test_failed_rerun_of_older_run_refuses_despite_newer_green_run():
    """Codex P2: run A, green run B, then A re-run (same created_at) fails."""
    older = run(1, conclusion="failure", attempt=2, created="2026-10-01T00:00:00Z")
    newer = run(2, created="2026-10-01T01:00:00Z")
    assert verdict(page(older, newer)) == gate.REFUSE


def test_failed_run_rerun_to_green_releases():
    assert verdict(page(run(1, attempt=3), run(2, event="workflow_dispatch"))) == gate.GREEN


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", None])
def test_any_non_success_conclusion_refuses(conclusion):
    assert verdict(page(run(1, conclusion=conclusion))) == gate.REFUSE


@pytest.mark.parametrize(
    "ignored",
    [
        run(9, conclusion="failure", event="pull_request"),
        run(9, conclusion="failure", sha=OTHER),
        run(9, conclusion="failure", path=".github/workflows/framework-latest.yml"),
    ],
)
def test_runs_that_do_not_count_are_ignored(ignored):
    assert verdict(page(run(1), ignored)) == gate.GREEN
    assert verdict(page(ignored)) == gate.REFUSE


def test_paginated_pages_are_all_read():
    """`gh api --paginate` prints one object per page, back to back."""
    text = page(run(1)) + "\n" + page(run(2, conclusion="failure"))
    assert verdict(text) == gate.REFUSE
    assert len(list(gate.iter_runs(text))) == 2


def test_main_reads_stdin_and_returns_the_verdict(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(page(run(1, status="in_progress", conclusion=None)))
    )
    assert gate.main(["release_ci_gate.py", SHA]) == gate.PENDING
    assert "attempt 1: in_progress" in capsys.readouterr().out


def released(**files: str) -> list[dict]:
    return [{"filename": name, "digests": {"sha256": digest}} for name, digest in files.items()]


def test_nothing_on_pypi_uploads_everything():
    assert pypi.compare({"x.whl": "1", "x.tar.gz": "2"}, []) == ([], [])


def test_identical_files_already_uploaded_are_reported():
    local = {"x.whl": "1", "x.tar.gz": "2"}
    assert pypi.compare(local, released(**{"x.whl": "1"})) == (["x.whl"], [])


def test_different_contents_are_a_mismatch():
    local = {"x.whl": "1", "x.tar.gz": "2"}
    remote = released(**{"x.whl": "1", "x.tar.gz": "other"})
    assert pypi.compare(local, remote) == (["x.whl"], ["x.tar.gz"])


def test_main_fails_on_mismatch(tmp_path, monkeypatch, capsys):
    (tmp_path / "x.whl").write_bytes(b"built")
    monkeypatch.setattr(pypi, "fetch_released", lambda d, v: released(**{"x.whl": "nope"}))
    assert pypi.main(["release_pypi_check.py", "x", "1.0.0", str(tmp_path)]) == 1
    assert "different sha256" in capsys.readouterr().out


def test_main_passes_on_identical_file(tmp_path, monkeypatch):
    (tmp_path / "x.whl").write_bytes(b"built")
    digest = pypi.sha256(tmp_path / "x.whl")
    monkeypatch.setattr(pypi, "fetch_released", lambda d, v: released(**{"x.whl": digest}))
    assert pypi.main(["release_pypi_check.py", "x", "1.0.0", str(tmp_path)]) == 0
