"""``ArticlesService``'s mixins declare what they need from it, and it supplies it.

Two halves of one contract (#133). The AST scan catches a mixin that starts
using a ``self.<member>`` (or ``getattr(self, "<member>")``) neither its chain nor
:class:`ArticlesHost` defines; the ``isinstance``/signature checks catch
``ArticlesService`` dropping or reshaping a member the Protocol promises. No type
checker runs in CI, so these are what make the Protocol more than a comment.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from unittest.mock import MagicMock

import pytest
from news.content import ArticlesService
from news.content._host import ArticlesHost
from news.content._revisions import RevisionsMixin
from news.content._trash import TrashMixin
from news.content._workflow import WorkflowMixin

MIXINS = (WorkflowMixin, TrashMixin, RevisionsMixin)


_REFLECTION = frozenset({"getattr", "hasattr", "setattr"})


def _self_members(tree: ast.AST) -> set[str]:
    """Every ``self.<name>`` and ``getattr/hasattr/setattr(self, "<name>")``.

    A reflective call whose name is not a string literal cannot be checked, so
    it is reported as ``<dynamic getattr>`` (etc.) and fails the scan.
    """
    used: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            used.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _REFLECTION
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "self"
        ):
            name = node.args[1]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                used.add(name.value)
            else:
                used.add(f"<dynamic {node.func.id}>")
    return used


def _undeclared(mixin: type, host: type) -> set[str]:
    """Members *mixin* uses on ``self`` that neither its MRO nor *host* defines."""
    used = _self_members(ast.parse(textwrap.dedent(inspect.getsource(mixin))))
    own = {name for klass in mixin.__mro__ if klass is not object for name in vars(klass)}
    return used - own - set(host.__annotations__) - set(vars(host))


@pytest.mark.parametrize("mixin", MIXINS, ids=lambda m: m.__name__)
def test_every_host_member_a_mixin_uses_is_declared(mixin: type) -> None:
    assert _undeclared(mixin, ArticlesHost) == set()


def test_the_scan_notices_an_undeclared_member() -> None:
    class Leaky(RevisionsMixin):
        def peek(self) -> object:
            return self.not_on_the_host  # type: ignore[attr-defined]

    assert _undeclared(Leaky, ArticlesHost) == {"not_on_the_host"}


def test_the_scan_notices_a_literal_reflective_lookup() -> None:
    class Leaky(RevisionsMixin):
        def peek(self) -> object:
            if hasattr(self, "probed"):
                setattr(self, "written", 1)  # noqa: B010
            return getattr(self, "not_on_the_host")  # noqa: B009

    assert _undeclared(Leaky, ArticlesHost) == {"probed", "written", "not_on_the_host"}


def test_the_scan_rejects_a_dynamic_reflective_lookup() -> None:
    class Leaky(RevisionsMixin):
        def peek(self, name: str) -> object:
            return getattr(self, name)

    assert _undeclared(Leaky, ArticlesHost) == {"<dynamic getattr>"}


def test_a_reflective_lookup_of_a_declared_member_passes() -> None:
    class Fine(RevisionsMixin):
        def peek(self) -> object:
            return getattr(self, "db")  # noqa: B009

    assert _undeclared(Fine, ArticlesHost) == set()


def test_articles_service_satisfies_the_host_protocol() -> None:
    assert isinstance(ArticlesService(MagicMock()), ArticlesHost)


def test_get_article_keeps_the_signature_the_mixins_call() -> None:
    assert inspect.signature(ArticlesService.get_article) == inspect.signature(
        ArticlesHost.get_article
    )
