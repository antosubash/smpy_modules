"""The five demo Record Types, as ``create_type``-ready field lists.

Kept as data rather than a builder function per type: the shapes are what the
task asked for, and reading the five side by side here is the fastest way to
check them against ``schema/fields.py``'s rules (allowed options per type,
``on_delete`` choices, unique-implies-indexed) without running anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sm_records.seed.data import ORDER_STATUSES, PRODUCT_CATEGORIES, TAG_POOL, US_STATES


def _choices(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in pairs]


def _self_choices(values: list[str]) -> list[dict[str, str]]:
    return [
        {"value": value, "label": value.replace("-", " ").replace("_", " ").title()}
        for value in values
    ]


_STATE_CHOICES = _choices(US_STATES)


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


COMPANY = TypeDef(
    key="company",
    label="Company",
    label_plural="Companies",
    display_field="name",
    slug_field="name",
    fields=[
        _f("name", "text", "Name", required=True, indexed=True),
        _f("state", "select", "State", indexed=True, options={"choices": _STATE_CHOICES}),
        _f("city", "text", "City", indexed=True),
        _f("founded", "date", "Founded", indexed=True),
        _f("employees", "integer", "Employees", indexed=True),
        _f("annual_revenue", "number", "Annual revenue", indexed=True),
        _f("website", "url", "Website"),
        _f("is_public", "boolean", "Publicly traded", indexed=True),
        _f("description", "longtext", "Description"),
    ],
)

CONTACT = TypeDef(
    key="contact",
    label="Contact",
    label_plural="Contacts",
    display_field="email",
    fields=[
        _f("first_name", "text", "First name"),
        _f("last_name", "text", "Last name", indexed=True),
        _f("email", "email", "Email", unique=True, indexed=True),
        _f("title", "text", "Title"),
        _f(
            "company",
            "relation",
            "Company",
            indexed=True,
            options=_relation("company", on_delete="set_null"),
        ),
        _f("phone", "text", "Phone"),
        _f("birthday", "date", "Birthday", indexed=True),
        _f("newsletter", "boolean", "Newsletter", indexed=True),
        _f("notes", "longtext", "Notes"),
    ],
)

PRODUCT = TypeDef(
    key="product",
    label="Product",
    label_plural="Products",
    display_field="name",
    slug_field="sku",
    fields=[
        _f("sku", "text", "SKU", unique=True, indexed=True),
        _f("name", "text", "Name", indexed=True),
        _f(
            "category",
            "select",
            "Category",
            indexed=True,
            options={"choices": _self_choices(PRODUCT_CATEGORIES)},
        ),
        _f("price", "number", "Price", indexed=True),
        _f("in_stock", "boolean", "In stock", indexed=True),
        _f(
            "tags",
            "multiselect",
            "Tags",
            indexed=True,
            options={"choices": _self_choices(TAG_POOL)},
        ),
        _f("weight_lbs", "number", "Weight (lbs)"),
        _f("specs", "json", "Specs"),
        _f("image", "media", "Image"),
    ],
)

STORE = TypeDef(
    key="store",
    label="Store",
    label_plural="Stores",
    display_field="name",
    slug_field="name",
    fields=[
        _f("name", "text", "Name", indexed=True),
        _f("street", "text", "Street"),
        _f("city", "text", "City", indexed=True),
        _f("state", "select", "State", indexed=True, options={"choices": _STATE_CHOICES}),
        _f("zip", "text", "ZIP", indexed=True),
        _f("opened", "date", "Opened", indexed=True),
        _f(
            "manager",
            "relation",
            "Manager",
            indexed=True,
            options=_relation("contact", on_delete="set_null"),
        ),
        _f("sq_ft", "integer", "Square feet", indexed=True),
        _f("hours", "json", "Hours"),
    ],
)

ORDER = TypeDef(
    key="order",
    label="Order",
    label_plural="Orders",
    display_field="order_no",
    slug_field="order_no",
    fields=[
        _f("order_no", "text", "Order #", unique=True, indexed=True),
        _f(
            "customer",
            "relation",
            "Customer",
            indexed=True,
            options=_relation("contact", on_delete="restrict"),
        ),
        _f(
            "products",
            "relation",
            "Products",
            indexed=True,
            options=_relation("product", many=True, on_delete="restrict"),
        ),
        _f("total", "number", "Total", indexed=True),
        _f("placed_at", "datetime", "Placed at", indexed=True),
        _f(
            "status",
            "select",
            "Status",
            indexed=True,
            options={"choices": _self_choices(ORDER_STATUSES)},
        ),
        _f(
            "ship_state",
            "select",
            "Ship-to state",
            indexed=True,
            options={"choices": _STATE_CHOICES},
        ),
        _f("gift", "boolean", "Gift"),
    ],
)

#: Dependency order: every relation's target is defined earlier in this list
#: (design doc §9) — company before contact, contact and product before order
#: and store. ``runner.py`` creates types and records in exactly this order,
#: and reverses it to delete them on ``--reset``.
TYPE_DEFS: list[TypeDef] = [COMPANY, CONTACT, PRODUCT, STORE, ORDER]
