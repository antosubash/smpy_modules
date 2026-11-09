"""Use the repository's guarded Postgres opt-in without duplicating reset logic."""

import importlib.util
import sys
from pathlib import Path


def shared():
    name = "smpy_tests_pg_support"
    if name not in sys.modules:
        path = Path(__file__).resolve().parents[3] / "tests/pg_support.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]
