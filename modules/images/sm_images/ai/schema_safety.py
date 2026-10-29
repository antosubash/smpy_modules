"""The trust boundary for a prompt's ``output_schema`` (user input).

:func:`check` runs at create/update (422 ``unsafe_output_schema``) and again
before every run, so a schema stored before a cap existed is refused too. It
admits only what :mod:`.schema_model` builds faithfully, with caps:

* size (:data:`MAX_BYTES` encoded), nesting (:data:`MAX_DEPTH`, both as
  written and through references), :data:`MAX_PROPERTIES` properties,
  :data:`MAX_REFS` ``$ref``, :data:`MAX_ENUM` enum values and
  :data:`MAX_PATTERN` characters per pattern;
* ``$ref`` only into the root's ``$defs`` or ``definitions`` (separate
  namespaces) - never a URL, a file or another document, never a cycle, and
  never beside other structure keywords - so nothing is fetched and
  resolution terminates;
* anything the model would not enforce is ``unsupported_schema`` rather than
  silently ignored: other keywords (``allOf``, ``not``, ``format``,
  ``patternProperties``, ``$dynamicRef``, ...) and ``required`` names that are
  not properties.

The walk is bounded by the depth cap before it recurses, so a deeply nested
schema under the size cap is ``too_deep``, never a ``RecursionError``. Then
the model is built once; anything pydantic refuses (a pattern its regex
engine rejects) is ``invalid_schema``. :func:`output_model` is the
deterministic per-``(prompt id, revision)`` cache of that model.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel

from sm_images.ai.schema_model import build_model, definitions, ref_name

__all__ = ["MAX_DEPTH", "UnsafeSchema", "check", "output_model"]

MAX_BYTES = 64 * 1024
MAX_DEPTH = 8
MAX_PROPERTIES = 200
MAX_REFS = 50
MAX_ENUM = 500
MAX_PATTERN = 200
MAX_ANY_OF = 20
CACHE_SIZE = 256

TYPES = frozenset({"object", "string", "integer", "number", "boolean", "array", "null"})
ANNOTATIONS = frozenset({"title", "description", "examples", "default", "$schema", "$comment"})
STRUCTURE = frozenset(
    {"type", "properties", "required", "items", "enum", "const", "anyOf", "$ref"}
    | {"additionalProperties", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}
    | {"minLength", "maxLength", "minItems", "maxItems", "pattern"}
)
ROOT_ONLY = frozenset({"$defs", "definitions"})


class UnsafeSchema(ValueError):  # noqa: N818 - reads as the verdict
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _too_deep() -> UnsafeSchema:
    return UnsafeSchema("too_deep", f"at most {MAX_DEPTH} levels")


class _Walk:
    def __init__(self, root: dict[str, Any]) -> None:
        self.defs = definitions(root)
        self.properties = 0
        self.refs = 0
        self.heights: dict[tuple[str, str], int] = {}

    def raw(self, node: Any, depth: int = 0, *, root: bool = False) -> None:
        """Keywords, references, patterns and counts as written (refs not followed)."""
        if depth > MAX_DEPTH:
            raise _too_deep()
        if not isinstance(node, dict):
            raise UnsafeSchema("invalid_schema", "a subschema must be an object")
        if "$ref" in node and STRUCTURE.intersection(node) - {"$ref"}:
            raise UnsafeSchema("unsupported_schema", "$ref takes no sibling keywords")
        for key, value in node.items():
            if key in ANNOTATIONS:
                continue
            if key in ROOT_ONLY and root and isinstance(value, dict):
                for sub in value.values():
                    self.raw(sub, depth + 1)
            elif key in STRUCTURE:
                self._keyword(key, value, depth)
            else:
                raise UnsafeSchema("unsupported_schema", f"keyword {str(key)[:100]!r}")
        missing = set(node.get("required") or ()) - set(node.get("properties") or {})
        if missing:
            raise UnsafeSchema(
                "unsupported_schema", f"required but not a property: {sorted(missing)[:5]}"
            )

    def _keyword(self, key: str, value: Any, depth: int) -> None:
        if key == "properties":
            if not isinstance(value, dict):
                raise UnsafeSchema("invalid_schema", "properties must be an object")
            self.properties += len(value)
            if self.properties > MAX_PROPERTIES:
                raise UnsafeSchema("too_many_properties", f"at most {MAX_PROPERTIES}")
            for sub in value.values():
                self.raw(sub, depth + 1)
        elif key == "items":
            self.raw(value, depth + 1)
        elif key == "anyOf":
            if not isinstance(value, list) or not 0 < len(value) <= MAX_ANY_OF:
                raise UnsafeSchema("invalid_schema", f"anyOf takes 1 to {MAX_ANY_OF} schemas")
            for sub in value:
                self.raw(sub, depth + 1)
        elif key == "$ref":
            self.refs += 1
            if self.refs > MAX_REFS:
                raise UnsafeSchema("too_many_refs", f"at most {MAX_REFS}")
            target = ref_name(value) if isinstance(value, str) else None
            if target is None:
                raise UnsafeSchema("remote_ref", "only #/$defs/<name> references are allowed")
            if target[1] not in self.defs[target[0]]:
                raise UnsafeSchema("invalid_schema", f"unknown reference {value[:100]!r}")
        else:
            _scalar_keyword(key, value)

    def height(self, node: dict[str, Any], stack: tuple[tuple[str, str], ...] = ()) -> int:
        """Nesting below ``node``, following references once each (memoised).
        Bounded: ``raw`` already capped the nesting as written."""
        if "$ref" in node:
            target = ref_name(node["$ref"]) or ("", "")
            if target in stack:
                raise UnsafeSchema("recursive_ref", target[1][:100])
            if target not in self.heights:
                found = self.height(self.defs[target[0]][target[1]], (*stack, target))
                self.heights[target] = found
            return self.heights[target]
        kids = list(node.get("properties", {}).values()) + list(node.get("anyOf", []))
        if isinstance(node.get("items"), dict):
            kids.append(node["items"])
        return 1 + max((self.height(k, stack) for k in kids), default=-1)


def _scalar_keyword(key: str, value: Any) -> None:
    ok: bool
    if key == "type":
        kinds = value if isinstance(value, list) else [value]
        ok = bool(kinds) and all(isinstance(k, str) and k in TYPES for k in kinds)
    elif key == "required":
        ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
    elif key == "enum":
        ok = isinstance(value, list) and 0 < len(value) <= MAX_ENUM and all(map(_scalar, value))
    elif key == "const":
        ok = _scalar(value)
    elif key == "additionalProperties":
        ok = isinstance(value, bool)
    elif key == "pattern":
        if isinstance(value, str) and len(value) > MAX_PATTERN:
            raise UnsafeSchema("pattern_too_long", f"at most {MAX_PATTERN} characters")
        ok = isinstance(value, str)
    elif key in ("minLength", "maxLength", "minItems", "maxItems"):
        ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    else:  # numeric bounds
        ok = isinstance(value, int | float) and not isinstance(value, bool)
    if not ok:
        raise UnsafeSchema("invalid_schema", f"bad value for {key!r}")


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def check(schema: Any) -> type[BaseModel]:
    """The model for ``schema``, or :class:`UnsafeSchema` (see the module)."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise UnsafeSchema("not_an_object", "the root must be {'type': 'object', ...}")
    try:
        size = len(json.dumps(schema, allow_nan=False).encode())
        if size > MAX_BYTES:
            raise UnsafeSchema("too_large", f"at most {MAX_BYTES} bytes")
        walk = _Walk(schema)
        walk.raw(schema, root=True)
        if walk.height(schema) > MAX_DEPTH:
            raise _too_deep()
    except RecursionError as exc:  # defence in depth: the depth cap comes first
        raise UnsafeSchema("invalid_schema", "nested too deeply") from exc
    except (TypeError, ValueError) as exc:
        if isinstance(exc, UnsafeSchema):
            raise
        raise UnsafeSchema("invalid_schema", "not JSON") from exc
    try:
        return build_model(schema)
    except Exception as exc:  # pydantic refused it (a pattern its engine rejects)
        raise UnsafeSchema("invalid_schema", f"{type(exc).__name__}: {exc}"[:500]) from exc


_cache: OrderedDict[Any, type[BaseModel]] = OrderedDict()
_lock = threading.Lock()


def output_model(schema: Any, *, key: Any = None) -> type[BaseModel]:
    """:func:`check`'s model, cached under ``key`` (prompt id, revision)."""
    if key is not None:
        with _lock:
            found = _cache.get(key)
            if found is not None:
                _cache.move_to_end(key)
                return found
    model = check(schema)
    if key is not None:
        with _lock:
            _cache[key] = model
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
    return model
