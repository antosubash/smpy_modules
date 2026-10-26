"""Files a restore writes, kept only if its transaction commits (#250).

A restore's database work is one transaction, but the media files it writes
onto disk are not part of it: before this, a section that failed after the
media step rolled every row back and left the files behind, named by no row.
Each path a restore writes is recorded on its session here and removed when
that session's outermost transaction ends without committing — the apply
raised or was cancelled, the request's commit failed afterwards, or the
session was closed with the transaction still open.

Only paths this transaction *created* are ever recorded: freshly minted media
names (``uuid4().hex`` and its variants) and the pre-restore snapshot's own
directory. A file that already existed — an asset the restore matched and
reused, a content-addressed blob shared with other snapshots — is never named,
so no rollback can remove it. Each path is already inside its own tenant's
directory, which is what keeps the cleanup to the tenant that wrote it.

SQLAlchemy's session events rather than the framework's ``on_commit``: there
is no after-rollback or on-close hook in ``simple_module_db``, and these fire on any
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
        event.listen(sync, "after_transaction_end", _on_end)
    written.extend(paths)


def tracked(db: AsyncSession) -> list[Path]:
    """What a rollback of *db* would remove now (for tests and logs)."""
    return list(db.sync_session.info.get(_KEY) or [])


def discard(db: AsyncSession) -> None:
    """Remove everything recorded on *db* now, ahead of its rollback."""
    _remove(db.sync_session)


def _forget(session: Session) -> None:
    # `after_commit` fires on a savepoint's release too, while that savepoint
    # is still the session's nested transaction; only the outermost commit
    # makes the rows naming these files durable, so only it keeps the files.
    if session.get_nested_transaction() is None:
        session.info.get(_KEY, []).clear()


def _on_end(session: Session, transaction: SessionTransaction) -> None:
    # The outermost transaction ending by any route but a commit strands the
    # files: a rollback, a failed commit, and a plain `close()` — which ends it
    # without a rollback event, as when a cancelled request's session context
    # exits (CancelledError passes every `except Exception`). After a commit
    # `_forget` has emptied the list already. A savepoint's or a failed flush's
    # inner transaction ending leaves the outermost one to decide, so a file
    # written inside a rolled-back savepoint stays tracked until then.
    if transaction.parent is None:
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
