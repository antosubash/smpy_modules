"""HoldsMixin reads only what HoldsHost declares, and IngestService supplies it."""

from __future__ import annotations

import ast
import inspect
import textwrap
from unittest.mock import MagicMock

from sm_images.ingest._holds_host import HoldsHost
from sm_images.ingest.service import IngestService
from sm_images.ingest.service_holds import HoldsMixin


def _self_members(tree: ast.AST) -> set[str]:
    return {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"
    }


def _undeclared(mixin: type) -> set[str]:
    used = _self_members(ast.parse(textwrap.dedent(inspect.getsource(mixin))))
    own = {name for klass in mixin.__mro__ if klass is not object for name in vars(klass)}
    declared = {*vars(HoldsHost), *inspect.get_annotations(HoldsHost)}
    return used - own - declared


def test_every_host_member_the_mixin_uses_is_declared() -> None:
    assert _undeclared(HoldsMixin) == set()


def test_the_scan_notices_an_undeclared_member() -> None:
    class Leaky(HoldsMixin):
        def peek(self) -> object:
            return self.not_on_the_host  # type: ignore[attr-defined]

    assert _undeclared(Leaky) == {"not_on_the_host"}


def test_ingest_service_satisfies_the_host() -> None:
    assert isinstance(IngestService(MagicMock(), MagicMock(), MagicMock()), HoldsHost)
