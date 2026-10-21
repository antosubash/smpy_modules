"""Decide whether CI is green on the commit a release ships (#115).

    gh api --paginate "repos/$REPO/actions/workflows/ci.yml/runs?head_sha=$SHA&per_page=100" \
      | python3 scripts/release_ci_gate.py "$SHA"

Reads the runs API output on stdin — one or more page objects, concatenated as
``gh api --paginate`` prints them — and exits:

    0  every counted run is green: release
    2  a counted run is still queued or in progress: wait and ask again
    1  no counted run, or one that did not succeed: refuse

A run counts when it is ci.yml's own (``path`` re-checked, so no other
workflow satisfies it), on exactly this SHA, and triggered by ``push`` or
``workflow_dispatch``. A pull-request run tested a merge ref, not this SHA.

*Every* counted run must be green, not just the newest. The API reports each
run as its latest attempt, and re-running a run does not change its
``created_at``: picking the newest run by creation would let a successful run
B authorize the release while a later re-run of an older run A had just
failed. Requiring all of them makes attempt order irrelevant; a run that
failed is cleared by re-running it until it passes.

Stdlib only: release.yml runs it before anything is installed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Iterator

CI_PATH = ".github/workflows/ci.yml"
EVENTS = frozenset({"push", "workflow_dispatch"})

GREEN, REFUSE, PENDING = 0, 1, 2


def iter_runs(text: str) -> Iterator[dict]:
    """Every run object in ``text``: concatenated page objects or run objects."""
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return
        value, pos = decoder.raw_decode(text, pos)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if "workflow_runs" in item:
                yield from item["workflow_runs"]
            else:
                yield item


def counted(runs: Iterable[dict], sha: str) -> list[dict]:
    return [
        r
        for r in runs
        if r.get("head_sha") == sha
        # Runs from a non-default ref report ``<path>@<ref>``; compare the file.
        and (r.get("path") or "").split("@", 1)[0] == CI_PATH
        and r.get("event") in EVENTS
    ]


def _describe(run: dict) -> str:
    attempt = run.get("run_attempt", 1)
    state = run.get("conclusion") or run.get("status")
    return f"{run.get('event')} run, attempt {attempt}: {state} {run.get('html_url', '')}".rstrip()


def decide(runs: Iterable[dict], sha: str) -> tuple[int, list[str]]:
    """The verdict and one message line per counted run (or why there are none)."""
    mine = counted(runs, sha)
    if not mine:
        return REFUSE, [
            f"no CI run for {sha}. Run the CI workflow on main (Actions → CI → Run workflow)"
            " and dispatch the release once it is green"
        ]
    lines = [_describe(r) for r in mine]
    if any(r.get("status") != "completed" for r in mine):
        return PENDING, lines
    if all(r.get("conclusion") == "success" for r in mine):
        return GREEN, lines
    return REFUSE, [
        *lines,
        "every CI run on this commit must end green: re-run the failed one(s) and dispatch again",
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: release_ci_gate.py <sha> < runs.json", file=sys.stderr)
        return REFUSE
    verdict, lines = decide(iter_runs(sys.stdin.read()), argv[1])
    for line in lines:
        print(line)
    return verdict


if __name__ == "__main__":
    sys.exit(main(sys.argv))
