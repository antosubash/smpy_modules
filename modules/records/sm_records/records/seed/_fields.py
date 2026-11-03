"""seed _fields helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _choices(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in pairs]


def _self_choices(values: list[str]) -> list[dict[str, str]]:
    return [
        {"value": value, "label": value.replace("-", " ").replace("_", " ").title()}
        for value in values
    ]


def _f(
    key: str,
    type_: str,
    label: str,
    *,
    required: bool = False,
    unique: bool = False,
    indexed: bool = False,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One raw field definition, in the shape ``RecordType.fields`` stores.

    Mirrors ``tests/conftest.py``'s ``field_def`` fixture — same defaults for
    ``default``/``help``/``constraints`` — so this reads as "the same kind of
    thing the test suite already builds", not a third shape.
    """
    return {
        "key": key,
        "type": type_,
        "label": label,
        "required": required,
        "unique": unique,
        "indexed": indexed,
        "default": None,
        "help": None,
        "constraints": {},
        "options": options or {},
    }


def _relation(target: str, *, many: bool = False, on_delete: str = "restrict") -> dict[str, Any]:
    return {"target_type": target, "many": many, "on_delete": on_delete}


@dataclass(frozen=True, slots=True)
class TypeDef:
    key: str
    label: str
    label_plural: str
    fields: list[dict[str, Any]] = field(default_factory=list)
    display_field: str | None = None
    slug_field: str | None = None
    collection: str | None = None
    """Which table set the type is created in (Phase 5 §6.2). ``None`` — the
    global tables — for every type but ``event``."""
    show_in_menu: bool = True
    """Whether the seeded type gets its own admin-sidebar entry.

    ``True`` for every demo type, which is the opposite of the column's own
    default — the demo host exists to show the feature, and a seeded install
    where the switch is off everywhere shows nothing of it. A real install
    starts with no types at all, so nothing here changes what an operator
    gets by default."""
