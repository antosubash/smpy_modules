"""Ledger vocabulary and argument checks for the metering calls.

A bad argument is a programming error in the consumer, so it raises
``ValueError`` rather than answering ``Exceeded``.
"""

from __future__ import annotations

CONSUME, RECORD, REFUND, ADJUST = "consume", "record", "refund", "adjust"
REFUND_SUFFIX = ":refund"
ADJUST_PREFIX = "adjust:"
ADMIN_SOURCE = "admin"
# Leaves room for the derived refund key inside the 128-character column.
KEY_MAX = 128 - len(REFUND_SUFFIX)
METER_MAX = SOURCE_MAX = 64
TENANT_MAX = 32


def check_text(name: str, value: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{name} must be 1-{maximum} characters")


def check_call(tenant_id: str, meter: str, qty: int, key: str, source: str) -> None:
    """A ``consume``/``record``: positive integer ``qty``, a key of the caller's own."""
    check_text("tenant_id", tenant_id, TENANT_MAX)
    check_text("meter", meter, METER_MAX)
    check_text("idempotency_key", key, KEY_MAX)
    check_text("source", source, SOURCE_MAX)
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise ValueError("qty must be a positive integer")
    if key.endswith(REFUND_SUFFIX) or key.startswith(ADJUST_PREFIX):
        reserved = f"keys ending {REFUND_SUFFIX!r} or starting {ADJUST_PREFIX!r} are reserved"
        raise ValueError(reserved)


def check_adjust(tenant_id: str, meter: str, quantity: int, reason: str) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity == 0:
        raise ValueError("quantity must be a non-zero integer")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required")
    check_text("tenant_id", tenant_id, TENANT_MAX)
    check_text("meter", meter, METER_MAX)
