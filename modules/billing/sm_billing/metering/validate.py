"""Ledger vocabulary and argument checks for the metering calls.

A bad argument is a programming error in the consumer, so it raises
``ValueError`` rather than answering ``Exceeded``.
"""

from __future__ import annotations

from sm_billing.contracts.metering import HoldNotFound

CONSUME, RECORD, REFUND, ADJUST = "consume", "record", "refund", "adjust"
REFUND_SUFFIX = ":refund"
ADJUST_PREFIX = "adjust:"
ADMIN_SOURCE = "admin"
# Leaves room for the derived refund key inside the 128-character column.
KEY_MAX = 128 - len(REFUND_SUFFIX)
METER_MAX = SOURCE_MAX = 64
TENANT_MAX = 64  # a subject: tenant id or "user:<uuid>"
ACTOR_MAX = 255
# Far past any plan limit (int4), well inside the BIGINT counter: a larger
# quantity is a bug in the caller, not a reason for a database error.
QTY_MAX = 2**53
# A hold meant to outlive a month is a ``commit``, not a TTL.
TTL_MAX = 30 * 24 * 3600
HOLD_ID_MAX = 32


def check_text(name: str, value: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{name} must be 1-{maximum} characters")


def check_call(tenant_id: str, meter: str, qty: int, key: str, source: str) -> None:
    """A ``consume``/``record``: positive integer ``qty``, a key of the caller's own."""
    check_text("tenant_id", tenant_id, TENANT_MAX)
    check_text("meter", meter, METER_MAX)
    check_text("idempotency_key", key, KEY_MAX)
    check_text("source", source, SOURCE_MAX)
    if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= QTY_MAX:
        raise ValueError(f"qty must be an integer from 1 to {QTY_MAX}")
    if key.endswith(REFUND_SUFFIX) or key.startswith(ADJUST_PREFIX):
        reserved = f"keys ending {REFUND_SUFFIX!r} or starting {ADJUST_PREFIX!r} are reserved"
        raise ValueError(reserved)


def check_adjust(
    tenant_id: str, meter: str, quantity: int, reason: str, actor: str | None = None
) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("quantity must be a non-zero integer")
    if not 0 < abs(quantity) <= QTY_MAX:
        raise ValueError(f"quantity must be a non-zero integer within +/-{QTY_MAX}")
    if actor is not None:
        check_text("actor", actor, ACTOR_MAX)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required")
    check_text("tenant_id", tenant_id, TENANT_MAX)
    check_text("meter", meter, METER_MAX)


def check_ttl(ttl: int) -> int:
    """A hold's TTL in whole seconds."""
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= TTL_MAX:
        raise ValueError(f"ttl must be an integer from 1 to {TTL_MAX} seconds")
    return ttl


def check_hold_id(hold_id: str) -> None:
    """A hold id; one longer than any id ever issued names no hold (404, not 500)."""
    if isinstance(hold_id, str) and len(hold_id) > HOLD_ID_MAX:
        raise HoldNotFound(hold_id)
    check_text("hold_id", hold_id, HOLD_ID_MAX)
