"""A two-type graph with one field of every interesting shape, built over HTTP.

Shared by the import/export suites so each stays under the 300-line cap, and
built through the real API rather than seeded for the reason
``relation_helpers`` gives: a relation is only half stored in the payload, and
a seeded record has no ``records_index_ref`` row — which is exactly what an
export has to reproduce on the way back in.

The field list is deliberately one of each *cell shape* rather than one of
each ``FieldType``: a scalar, a decimal, a boolean, a date, a list
(``multiselect``), an opaque object (``json``) and a reference
(``relation``). Those are the seven things a CSV cell has to be able to say,
and the types that are not here share a spelling with one that is.
"""

from __future__ import annotations

from typing import Any

from tests.app_harness import ADMIN, roles

PRODUCT = "product"
BRAND = "brand"


def field(key: str, type_: str, **extra: Any) -> dict:
    options = extra.pop("options", {})
    return {
        "key": key,
        "type": type_,
        "label": key.replace("_", " ").title(),
        "required": extra.pop("required", False),
        "unique": extra.pop("unique", False),
        "indexed": extra.pop("indexed", False),
        "default": extra.pop("default", None),
        "help": None,
        "constraints": extra.pop("constraints", {}),
        "options": options,
    }


def product_fields() -> list[dict]:
    return [
        field("name", "text", required=True, indexed=True),
        field("price", "number"),
        field("in_stock", "boolean"),
        field("released", "date"),
        field(
            "tags",
            "multiselect",
            options={
                "choices": [
                    {"value": "new", "label": "New"},
                    {"value": "sale", "label": "Sale"},
                ]
            },
        ),
        field("extra", "json"),
        field("brand", "relation", options={"target_type": BRAND, "many": False}),
    ]


async def make_type(client, key: str, fields: list[dict], **cols: Any) -> dict:
    resp = await client.post(
        "/api/records/types",
        json={"key": key, "label": key.title(), "fields": fields, **cols},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_record(client, key: str, data: dict, *, actor: str = ADMIN, **cols: Any) -> dict:
    resp = await client.post(
        f"/api/records/types/{key}/records", json={"data": data, **cols}, headers=roles(actor)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def catalogue(client, *, products: int = 3) -> tuple[dict, list[dict]]:
    """A ``brand`` type with one record, and a ``product`` type pointing at it.

    ``slug_field="name"`` so slugs are derived rather than absent: a round
    trip that never produced one would prove nothing about the slug claims of
    §5, which are the write path most likely to refuse a re-import.
    """
    await make_type(client, BRAND, [field("name", "text", indexed=True)], display_field="name")
    brand = await make_record(client, BRAND, {"name": "Acme"})
    await make_type(client, PRODUCT, product_fields(), display_field="name", slug_field="name")
    rows = []
    for index in range(products):
        rows.append(
            await make_record(
                client,
                PRODUCT,
                {
                    "name": f"Widget {index}",
                    "price": f"{index}.25",
                    "in_stock": index % 2 == 0,
                    "released": f"2026-01-0{index + 1}",
                    "tags": ["new"] if index % 2 == 0 else ["new", "sale"],
                    "extra": {"note": f"n{index}"},
                    "brand": {"type": BRAND, "uuid": brand["uuid"]},
                },
                status="published" if index == 0 else "draft",
            )
        )
    return brand, rows


async def drop_type(client, key: str, count: int) -> None:
    """Purge a type and everything under it — the local stand-in for "import
    this file into a different install", since ``uuid`` is unique across the
    whole database and the round trip is supposed to keep it (§5)."""
    resp = await client.delete(
        f"/api/records/types/{key}?confirm_record_count={count}", headers=roles(ADMIN)
    )
    assert resp.status_code == 204, resp.text


async def export_text(client, key: str, fmt: str = "json", query: str = "") -> str:
    resp = await client.get(
        f"/api/records/types/{key}/records/export?format={fmt}{query}", headers=roles(ADMIN)
    )
    assert resp.status_code == 200, resp.text
    return resp.text


async def post_import(
    client, key: str, text: str, *, fmt: str = "json", actor: str = ADMIN, **opts
):
    params = "&".join(f"{name}={value}" for name, value in opts.items())
    media = "application/json" if fmt == "json" else "text/csv"
    return await client.post(
        f"/api/records/types/{key}/records/import?{params}",
        content=text.encode("utf-8"),
        headers={**roles(actor), "Content-Type": media},
    )


async def data_by_uuid(client, key: str) -> dict[str, dict]:
    resp = await client.get(f"/api/records/types/{key}/records?page_size=200", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return {item["uuid"]: item for item in resp.json()["items"]}
