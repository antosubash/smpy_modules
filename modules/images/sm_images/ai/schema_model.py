"""A pydantic model from a prompt's JSON Schema (only after ``schema_safety.check``).

The subset is what :mod:`.schema_safety` admits: ``object`` with
``properties``/``required``/``additionalProperties`` (a bool), ``string``
(lengths, ``pattern``), ``integer``/``number`` (bounds), ``boolean``,
``null``, ``array`` (``items``, item counts), ``enum``, ``const``, ``anyOf``,
a list of types, and local ``$ref`` into the root's ``$defs``/``definitions``.

Property names are user data, so fields get generated names (``f0``, ``f1``,
...) with the JSON name as the alias: a property called ``model_config`` or
``schema`` cannot shadow pydantic. The model's JSON schema (what the provider
is shown) and its validation both use the aliases; dump with
``by_alias=True``. An optional property may be omitted but is null only when
its type allows it; properties the schema does not list are kept unless
``additionalProperties`` is ``false``. ``pattern`` is checked by pydantic-core's Rust regex
engine, which has no backtracking, so a user pattern cannot pin a worker.
Each ``$defs`` entry is built once, so a schema that references one
definition many times stays linear.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

import annotated_types
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    create_model,
)

__all__ = ["build_model", "definitions", "ref_name"]

REF = re.compile(r"^#/(\$defs|definitions)/([^/]+)$")


def ref_name(ref: str) -> tuple[str, str] | None:
    """``(namespace, name)`` of a local reference: ``$defs`` and ``definitions``
    are separate namespaces, as in JSON Schema."""
    match = REF.match(ref)
    return (match.group(1), match.group(2)) if match else None


def definitions(root: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ns: dict(root.get(ns) or {}) for ns in ("$defs", "definitions")}


def _ident(text: str) -> str:
    cleaned = re.sub(r"\W", "_", text)
    return cleaned if cleaned and not cleaned[0].isdigit() else f"M_{cleaned}"


def _union(members: list[Any]) -> Any:
    return members[0] if len(members) == 1 else Union[tuple(members)]  # noqa: UP007


class _Builder:
    def __init__(self, root: dict[str, Any]) -> None:
        self.defs = definitions(root)
        self.built: dict[tuple[str, str], Any] = {}

    def type_of(self, node: dict[str, Any], name: str) -> Any:
        if "$ref" in node:
            ns, ref = ref_name(node["$ref"]) or ("", "")
            if (ns, ref) not in self.built:
                label = f"{name}_{_ident(ref)}"
                self.built[(ns, ref)] = self.type_of(self.defs[ns][ref], label)
            return self.built[(ns, ref)]
        if "const" in node:
            self._check_values(node, [node["const"]], name)
            return Literal[node["const"]]
        if "enum" in node:
            self._check_values(node, node["enum"], name)
            return Literal[tuple(node["enum"])]
        if "anyOf" in node:
            return _union([self.type_of(m, f"{name}_{i}") for i, m in enumerate(node["anyOf"])])
        kind = node.get("type")
        if kind is None:
            return Any
        kinds = kind if isinstance(kind, list) else [kind]
        return _union([self._single(node, k, name) for k in kinds])

    def _single(self, node: dict[str, Any], kind: str, name: str) -> Any:
        if kind == "null":
            return type(None)
        if kind == "boolean":
            return bool
        if kind == "string":
            return Annotated[
                str,
                StringConstraints(
                    min_length=node.get("minLength"),
                    max_length=node.get("maxLength"),
                    pattern=node.get("pattern"),
                ),
            ]
        if kind in ("integer", "number"):
            base = int if kind == "integer" else float
            bounds = annotated_types.Interval(
                ge=node.get("minimum"),
                le=node.get("maximum"),
                gt=node.get("exclusiveMinimum"),
                lt=node.get("exclusiveMaximum"),
            )
            extra = [] if base is int else [annotated_types.Predicate(lambda v: v == v)]  # no NaN
            return Annotated[base, bounds, *extra]
        if kind == "array":
            item = self.type_of(node["items"], f"{name}_item") if "items" in node else Any
            size = annotated_types.Len(node.get("minItems", 0), node.get("maxItems"))
            return Annotated[list[item], size]
        if node.get("properties") or node.get("additionalProperties") is False:
            return self.model(node, name)  # an empty one forbids every key
        return dict[str, Any]

    def _check_values(self, node: dict[str, Any], values: list[Any], name: str) -> None:
        """Every ``enum``/``const`` value must satisfy the node's own constraints
        (type, lengths, pattern, bounds): a ``Literal`` alone would admit a value
        the schema forbids. ``ValueError`` for an inconsistent schema."""
        kind = node.get("type")
        declared = kind if isinstance(kind, list) else [kind] if kind else None
        for value in values:
            if declared is not None:
                kinds = declared
            elif isinstance(value, bool) or value is None:
                continue
            else:
                kinds = ["string" if isinstance(value, str) else "number"]
            allowed = _union([self._single(node, k, name) for k in kinds])
            try:
                TypeAdapter(allowed).validate_python(value, strict=True)
            except ValidationError as exc:
                raise ValueError(f"enum value {value!r} breaks the schema's own rules") from exc

    def model(self, node: dict[str, Any], name: str) -> type[BaseModel]:
        required = set(node.get("required", []))
        fields: dict[str, Any] = {}
        for i, (prop, sub) in enumerate(node.get("properties", {}).items()):
            kind = self.type_of(sub, f"{name}_{_ident(prop)}")
            desc = sub.get("description")
            if prop in required:
                fields[f"f{i}"] = (kind, Field(..., alias=prop, description=desc))
            else:
                # Omitted is fine; an explicit null only where the schema allows it
                # (the default is never validated, so it need not fit ``kind``).
                fields[f"f{i}"] = (kind, Field(None, alias=prop, description=desc))
        # JSON Schema allows other properties unless ``additionalProperties: false``.
        extra = "forbid" if node.get("additionalProperties") is False else "allow"
        config = ConfigDict(extra=extra, title=node.get("title") or name)
        return create_model(_ident(name), __config__=config, **fields)


def build_model(schema: dict[str, Any], name: str = "Output") -> type[BaseModel]:
    """The model for a schema :func:`sm_images.ai.schema_safety.check` admitted."""
    return _Builder(schema).model(schema, name)
