"""A policy built without saying so never opens the intranet, and only ``effective`` builds one."""

from __future__ import annotations

from sm_events.feeds.subscriptions import policy

from tests.support.source_scan import constructions_of, package_sources


def test_a_bare_policy_has_no_private_access_whatever_the_setting():
    assert policy.Policy().intranet is False
    assert policy.Policy(allow_private=True).intranet is False
    assert policy.Policy(allow_private=True, may_use_private=True).intranet is True
    assert policy.effective(True, may_use_private=False).intranet is False


def test_no_production_code_builds_a_policy_outside_policy_py():
    found = [
        path
        for path, source in package_sources()
        if path != "feeds/subscriptions/policy.py" and constructions_of(source, "Policy")
    ]
    assert found == []


def test_the_scan_finds_an_aliased_or_copied_policy():
    planted = {
        "plain": "def f():\n    return Policy()\n",
        "alias": "from x.policy import Policy as P\ndef f():\n    return P(allow_private=True)\n",
        "module": "from x import policy\ndef f():\n    return policy.Policy()\n",
        "replace": (
            "import dataclasses\ndef f(policy):\n"
            "    return dataclasses.replace(policy, intranet=True)\n"
        ),
    }
    for spelling, source in planted.items():
        assert constructions_of(source, "Policy"), spelling
    assert constructions_of("def f(p):\n    return p.intranet\n", "Policy") == []
