"""``RestoreMixin`` declares what it needs from ``SnapshotService`` (#80, #133).

The restore gate was split out of ``snapshots/service.py``; the same two
checks ``test_service_host.py`` runs for ``PagesService`` hold it to
:class:`~pagebuilder.content.snapshots._host.SnapshotHost`.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from pagebuilder.content.snapshots._host import SnapshotHost
from pagebuilder.content.snapshots.restore import RestoreMixin
from pagebuilder.content.snapshots.service import SnapshotService
from pagebuilder.core.settings import PagebuilderSettings

from tests.support.host_contract import _undeclared


def test_every_host_member_the_restore_gate_uses_is_declared() -> None:
    assert _undeclared(RestoreMixin, SnapshotHost) == set()


def test_the_snapshot_service_satisfies_the_host() -> None:
    assert isinstance(SnapshotService(MagicMock(), PagebuilderSettings()), SnapshotHost)


def test_take_keeps_the_signature_the_gate_calls() -> None:
    assert inspect.signature(SnapshotService.take) == inspect.signature(SnapshotHost.take)
