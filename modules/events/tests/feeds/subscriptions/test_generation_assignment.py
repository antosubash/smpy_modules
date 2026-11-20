"""``policy_generation`` moves in one function only, and the scan that says so can fail."""

from __future__ import annotations

from tests.support.source_scan import assignments_to, package_sources


def test_the_policy_generation_is_written_by_generation_restart_only():
    writes = {
        (path, function)
        for path, source in package_sources()
        for _, function in assignments_to(source, "policy_generation")
    }
    assert writes == {("feeds/subscriptions/generation.py", "restart")}, writes


def test_the_scan_finds_every_spelling_of_a_write():
    planted = {
        "assign": "def f(s):\n    s.policy_generation = 3\n",
        "augmented": "def f(s):\n    s.policy_generation += 1\n",
        "setattr": 'def f(s):\n    setattr(s, "policy_generation", 3)\n',
        "keyword": "def f(q):\n    q.values(policy_generation=3)\n",
        "dict key": 'def f(q):\n    q.values(**{"policy_generation": 3})\n',
    }
    for spelling, source in planted.items():
        assert [fn for _, fn in assignments_to(source, "policy_generation")] == ["f"], spelling


def test_the_scan_ignores_a_declaration_and_a_read():
    source = (
        "class M:\n    policy_generation: int = counter()\n"
        "def f(s):\n    return s.policy_generation == 3\n"
    )
    assert assignments_to(source, "policy_generation") == []
