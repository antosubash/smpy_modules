"""Validated ingestion and property management boundaries."""

from __future__ import annotations

import math
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from sm_analytics.core.constants import UTM_PARAMETERS

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,49}$")
_SEGMENT = re.compile(r"^(?:[A-Za-z0-9_~.-]+|:[A-Za-z][A-Za-z0-9_]*)$")
Scalar = StrictStr | StrictBool | StrictInt | StrictFloat


def origin(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Expected an exact http(s) origin without a path")
    port = parts.port
    host = parts.hostname.lower()
    host = f"[{host}]" if ":" in host else host
    suffix = (
        f":{port}" if port and (parts.scheme, port) not in {("https", 443), ("http", 80)} else ""
    )
    return f"{parts.scheme}://{host}{suffix}"


class PropertyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["public", "application"] = "public"
    origins: list[str] = Field(min_length=1, max_length=20)
    enabled: bool = False
    route_patterns: list[str] = Field(default_factory=list, max_length=100)
    event_allowlist: dict[str, list[str]] = Field(default_factory=dict, max_length=50)
    utm_parameters: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(origin(v) for v in values))

    @field_validator("route_patterns")
    @classmethod
    def validate_patterns(cls, values: list[str]) -> list[str]:
        for value in values:
            if (
                len(value) > 500
                or not value.startswith("/")
                or value.startswith("//")
                or any(
                    not _SEGMENT.fullmatch(s) or s in {".", ".."}
                    for s in value.strip("/").split("/")
                    if s
                )
            ):
                raise ValueError("Use literal path segments or :name placeholders")
        return list(dict.fromkeys(values))

    @field_validator("event_allowlist")
    @classmethod
    def validate_events(cls, values: dict[str, list[str]]) -> dict[str, list[str]]:
        for key, names in values.items():
            if (
                not _NAME.fullmatch(key)
                or len(names) > 20
                or any(not _NAME.fullmatch(n) for n in names)
            ):
                raise ValueError(
                    "Invalid event or property name (max 50 characters, 20 properties)"
                )
        return values

    @field_validator("utm_parameters")
    @classmethod
    def validate_utm(cls, values: list[str]) -> list[str]:
        if set(values) - UTM_PARAMETERS:
            raise ValueError("Unsupported UTM parameter")
        return list(dict.fromkeys(values))


class CollectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: str = Field(min_length=1, max_length=36)
    event_id: UUID
    kind: Literal["pageview", "event"]
    path: str = Field(min_length=1, max_length=2000)
    referrer: str = Field(default="", max_length=2000)
    name: str = Field(default="", max_length=50)
    properties: dict[str, Scalar] = Field(default_factory=dict, max_length=20)
    utm: dict[str, str] = Field(default_factory=dict, max_length=5)

    @model_validator(mode="after")
    def validate_event(self) -> CollectIn:
        if self.kind == "event" and not _NAME.fullmatch(self.name):
            raise ValueError("Custom events require a valid name")
        if self.kind == "pageview" and (self.name or self.properties):
            raise ValueError("Pageviews cannot include event properties")
        if any(
            len(k) > 50
            or (isinstance(v, str) and len(v) > 500)
            or (isinstance(v, float) and not math.isfinite(v))
            for k, v in self.properties.items()
        ):
            raise ValueError("Event property exceeds its bounds")
        if set(self.utm) - UTM_PARAMETERS or any(len(v) > 200 for v in self.utm.values()):
            raise ValueError("Invalid campaign parameters")
        return self
