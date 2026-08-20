"""The module's declarative base.

Alone in its own file so every model file can import it without importing each
other — the cycle that would otherwise appear the moment two model files need to
reference the same Base.
"""

from __future__ import annotations

from simple_module_db.base import create_module_base

Base = create_module_base("pagebuilder")

PAGE_TABLE = "pagebuilder_pages"
