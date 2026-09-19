"""The module's declarative base.

Alone in its own file so every model file can import it without importing each
other — the cycle that would otherwise appear the moment two model files need to
reference the same Base.
"""

from __future__ import annotations

from simple_module_db.base import create_module_base

Base = create_module_base("records")

TYPE_TABLE = "records_type"
TYPE_REVISION_TABLE = "records_type_revision"
RECORD_TABLE = "records_record"
REVISION_TABLE = "records_revision"
INDEX_TEXT_TABLE = "records_index_text"
INDEX_NUMBER_TABLE = "records_index_number"
INDEX_BOOL_TABLE = "records_index_bool"
INDEX_DATE_TABLE = "records_index_date"
INDEX_DATETIME_TABLE = "records_index_datetime"
INDEX_REF_TABLE = "records_index_ref"
