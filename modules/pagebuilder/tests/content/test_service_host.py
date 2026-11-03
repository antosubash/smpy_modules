"""``PagesService``'s mixins declare what they need from it, and it supplies it.

Two halves of one contract (#133). The AST scan catches a mixin that starts
using a ``self.<member>`` (or ``getattr(self, "<member>")``) neither it nor
its host Protocol defines; the ``isinstance``/signature checks catch
``PagesService`` dropping or reshaping a member the Protocol promises. No type
checker runs in CI, so these are what make the Protocol more than a comment.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest
from pagebuilder.content.service._host import PagesHost, TrashHost
from pagebuilder.content.service._revisions import RevisionsMixin
from pagebuilder.content.service._translations import TranslationsMixin
from pagebuilder.content.service._trash import TrashMixin
from pagebuilder.content.service._workflow import WorkflowMixin
from pagebuilder.content.service.pages import PagesService

from tests.support.host_contract import _undeclared

# Each mixin and the Protocol it is checked against: only the trash may use the
# event bus, so it alone gets the wider contract.
MIXINS = (
    (WorkflowMixin, PagesHost),
    (RevisionsMixin, PagesHost),
    (TrashMixin, TrashHost),
    (TranslationsMixin, PagesHost),
)


@pytest.mark.parametrize(("mixin", "host"), MIXINS, ids=[m.__name__ for m, _ in MIXINS])
def test_every_host_member_a_mixin_uses_is_declared(mixin: type, host: type) -> None:
    assert _undeclared(mixin, host) == set()


def test_only_the_trash_contract_carries_the_event_bus() -> None:
    class Announcer(RevisionsMixin):
        def bus(self) -> object:
            return self.event_bus  # type: ignore[attr-defined]

    assert _undeclared(Announcer, PagesHost) == {"event_bus"}
    assert _undeclared(Announcer, TrashHost) == set()


def test_the_scan_notices_an_undeclared_member() -> None:
    class Leaky(RevisionsMixin):
        def peek(self) -> object:
            return self.not_on_the_host  # type: ignore[attr-defined]

    assert _undeclared(Leaky, PagesHost) == {"not_on_the_host"}


def test_the_scan_notices_a_literal_reflective_lookup() -> None:
    class Leaky(RevisionsMixin):
        def peek(self) -> object:
            if hasattr(self, "probed"):
                setattr(self, "written", 1)  # noqa: B010
            return getattr(self, "not_on_the_host")  # noqa: B009

    assert _undeclared(Leaky, PagesHost) == {"probed", "written", "not_on_the_host"}


def test_the_scan_rejects_a_dynamic_reflective_lookup() -> None:
    class Leaky(RevisionsMixin):
        def peek(self, name: str) -> object:
            return getattr(self, name)

    assert _undeclared(Leaky, PagesHost) == {"<dynamic getattr>"}


def test_a_reflective_lookup_of_a_declared_member_passes() -> None:
    class Fine(RevisionsMixin):
        def peek(self) -> object:
            return getattr(self, "db")  # noqa: B009

    assert _undeclared(Fine, PagesHost) == set()


@pytest.mark.parametrize("host", [PagesHost, TrashHost], ids=lambda h: h.__name__)
def test_pages_service_satisfies_the_host_protocols(host: type) -> None:
    assert isinstance(PagesService(MagicMock()), host)


def test_get_page_keeps_the_signature_the_mixins_call() -> None:
    assert inspect.signature(PagesService.get_page) == inspect.signature(PagesHost.get_page)
