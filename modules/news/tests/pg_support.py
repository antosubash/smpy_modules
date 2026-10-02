"""This suite's window onto the repo-level Postgres opt-in.

The decision — in-memory SQLite, or the Postgres database an environment
variable names — belongs to ``tests/pg_support.py`` at the repo root, which
``records`` and ``pagebuilder`` reach the same way. Everything about *why* it
works the way it does is documented there.

What is local to news is which tables a database needs: news' own, plus
pagebuilder's when it is importable. News owns its content, so nothing here
joins to a page; pagebuilder is an optional extra whose admin-search sections
read its tables on a host that installed both, and this workspace is one.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _shared() -> Any:
    """Load ``<repo>/tests/pg_support.py`` under a name of its own.

    By path rather than by import: this directory is on ``sys.path`` while the
    suite runs and the repo root is not, so there is no import to make. The
    repo root is three directories up.
    """
    name = "smpy_tests_pg_support"
    module = sys.modules.get(name)
    if module is None:
        path = Path(__file__).resolve().parents[3] / "tests" / "pg_support.py"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


_pg = _shared()

arm_reset = _pg.arm_reset


async def make_db_state() -> Any:
    """A ``DatabaseState`` holding news' tables — and pagebuilder's, if installed."""
    from news.models import Base as NewsBase

    metadatas = [NewsBase.metadata]
    try:
        from pagebuilder.models import Base as PagebuilderBase
    except ImportError:  # pragma: no cover - the news-alone host
        pass
    else:
        metadatas.insert(0, PagebuilderBase.metadata)
    return await _pg.make_db_state(*metadatas)
