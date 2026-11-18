"""``records:dates`` registers through the events loader, and records runs without events."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[3] / "sm_records"


def test_events_extensions_imports_lazily():
    """records installs and runs without events: its extension file imports nothing of events
    until ``register`` is called (and events is what calls it)."""
    code = (
        "import sys, sm_records.events_extensions as m;"
        "assert 'sm_events' not in sys.modules, 'imported events at import time';"
        "assert callable(m.register)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr


def test_records_boots_without_events_importable():
    """No ``sm_events`` anywhere on the import path: records' module still imports."""
    code = (
        "import sys; sys.modules['sm_events'] = None;"
        "import sm_records.module, sm_records.events_extensions;"
        "print('ok')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr


def test_only_integrations_import_events():
    pattern = re.compile(r"^\s*(from|import)\s+sm_events\b([\w.]*)", re.MULTILINE)
    strings = re.compile(r"""(import_module|find_spec)\(\s*f?["']sm_events""")
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        text = path.read_text(encoding="utf-8")
        if strings.search(text):
            offenders.append(rel)
        for _kw, rest in pattern.findall(text):
            ok = rel.startswith("integrations/events/") and rest.startswith(".contracts")
            if not ok:
                offenders.append(f"{rel}: sm_events{rest}")
    assert offenders == []


def test_registers_records_dates():
    pytest.importorskip("sm_events")
    from sm_events.calendar.plugins import registry

    registry.reset_registry()
    try:
        source = registry.get_source("records:dates")
        assert source is not None and source.public is True
    finally:
        registry.reset_registry()
