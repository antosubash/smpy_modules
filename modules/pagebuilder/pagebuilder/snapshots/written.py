"""Files a restore writes, kept only if its transaction commits (#250).

A restore's database work is one transaction, but the media files it writes
onto disk are not part of it: before this, a section that failed after the
media step rolled every row back and left the files behind, named by no row.
Each path a restore writes is recorded on its session here and removed when
that session's transaction rolls back — whether the apply raised, or the
apply returned and the request's commit failed afterwards.

Only paths this transaction *created* are ever recorded: freshly minted media
names (``uuid4().hex`` and its variants) and the pre-restore snapshot's own
directory. A file that already existed — an asset the restore matched and
reused, a content-addressed blob shared with other snapshots — is never named,
so no rollback can remove it. Each path is already inside its own tenant's
directory, which is what keeps the cleanup to the tenant that wrote it.

SQLAlchemy's session events rather than the framework's ``on_commit``: there
is no after-rollback hook in ``simple_module_db``, and these fire on any
session, the request's ``RequestSession`` and a test's plain one alike.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

logger = logging.getLogger(__name__)

_KEY = "pagebuilder_restore_written"


def track(db: AsyncSession, paths: Iterable[Path]) -> None:
    """Record *paths* as written by *db*'s open transaction."""
    sync = db.sync_session
    written: list[Path] | None = sync.info.get(_KEY)
    if written is None:
        written = sync.info[_KEY] = []
        event.listen(sync, "after_commit", _forget)
        event.listen(sync, "after_soft_rollback", _on_rollback)
    written.extend(paths)


def tracked(db: AsyncSession) -> list[Path]:
    """What a rollback of *db* would remove now (for tests and logs)."""
    return list(db.sync_session.info.get(_KEY) or [])


def discard(db: AsyncSession) -> None:
    """Remove everything recorded on *db* now, ahead of its rollback."""
    _remove(db.sync_session)


def _forget(session: Session) -> None:
    # Committed: the rows naming these files are durable, so the files stay.
    session.info.get(_KEY, []).clear()


def _on_rollback(session: Session, previous: SessionTransaction) -> None:
    # Only the outermost transaction ending strands the files: a savepoint's
    # rollback, or a failed flush's inner one, leaves it able to commit still
    # (or to be rolled back, which fires this again with the outermost).
    if previous.parent is None:
        _remove(session)


def _remove(session: Session) -> None:
    written: list[Path] = session.info.get(_KEY) or []
    while written:
        path = written.pop()
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            # Never mask the failure that caused the rollback: a file left
            # here is the pre-#250 behaviour, logged rather than raised.
            logger.warning("pagebuilder.restore: could not remove %s", path, exc_info=True)
