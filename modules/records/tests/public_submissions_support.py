"""Shared builders for the public-submissions tests (#101)."""

from __future__ import annotations

from typing import Any

from tests.app_harness import ADMIN, field, roles

API = "/api/records/types"

FORM_SYSTEM_KEYS = [
    "sm_source_page",
    "sm_source_block",
    "sm_locale",
    "sm_ip_hash",
    "sm_user_agent",
    "sm_consent_text",
    "sm_spam",
    "sm_notified_at",
]


def contact_fields() -> list[dict[str, Any]]:
    """The *Contact form* preset's ordinary fields."""
    triage = field(
        "triage",
        "select",
        choices=[{"value": v, "label": v} for v in ("new", "in_progress", "done")],
    )
    triage["default"] = "new"
    return [
        field("name", required=True, indexed=False),
        field("email", "email", required=True),
        field("message", "longtext", required=True, indexed=False),
        triage,
    ]


def form_config(**overrides: Any) -> dict[str, Any]:
    return {"kind": "form", "public_fields": ["name", "email", "message"], **overrides}


async def create(client, key: str = "contact", *, fields=None, config=None, **cols: Any):
    """``POST /types``; the response, unasserted."""
    body = {
        "key": key,
        "label": key.title(),
        "fields": contact_fields() if fields is None else fields,
        "public_submissions": form_config() if config is None else config,
        **cols,
    }
    return await client.post(API, json=body, headers=roles(ADMIN))


async def update(client, key: str, **changes: Any):
    """``PUT /types/{key}`` against the type's current version."""
    current = (await client.get(f"{API}/{key}", headers=roles(ADMIN))).json()
    return await client.put(
        f"{API}/{key}",
        json={"expected_version": current["version"], **changes},
        headers=roles(ADMIN),
    )


def keys_of(type_json: dict[str, Any]) -> list[str]:
    return [entry["key"] for entry in type_json["fields"]]


def system_keys(type_json: dict[str, Any]) -> list[str]:
    return [entry["key"] for entry in type_json["fields"] if entry.get("system")]
