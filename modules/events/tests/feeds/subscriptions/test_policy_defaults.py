"""A policy built without saying so never opens the intranet, and only ``effective`` builds one."""

from __future__ import annotations

import re
from pathlib import Path

import sm_events
from sm_events.feeds.subscriptions import policy


def test_a_bare_policy_has_no_private_access_whatever_the_setting():
    assert policy.Policy().intranet is False
    assert policy.Policy(allow_private=True).intranet is False
    assert policy.Policy(allow_private=True, may_use_private=True).intranet is True
    assert policy.effective(True, may_use_private=False).intranet is False


def test_no_production_code_builds_a_policy_outside_policy_py():
    root = Path(sm_events.__file__).parent
    found = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if p.name != "policy.py" and re.search(r"\bPolicy\(", p.read_text())
    ]
    assert found == []
