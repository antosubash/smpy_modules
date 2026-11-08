"""Segment rules: validation and compilation to records filter terms.

A rule is ``field op value``; a segment's rules are ANDed. Each compiles to one
or more ``key:op:value`` terms of records' filter grammar. Pure: no I/O. Errors
name the rule's index and never echo a submitted value.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sm_records.contracts.newsletter_admin import ListField

RuleOp = Literal[
    "is", "is_not", "any", "all", "none", "contains", "starts_with",
    "gt", "gte", "lt", "lte", "before", "since",
]  # fmt: skip

SIGNUP_FIELD = "created_at"
MAX_RULES = 10
MAX_TERMS = 20
MAX_VALUES = 20
MAX_VALUE_LEN = 200

_EQ: dict[str, str] = {"is": "eq", "is_not": "ne"}
_NUM: dict[str, str] = {**_EQ, "gt": "gt", "gte": "gte", "lt": "lt", "lte": "lte"}
_DATES: dict[str, str] = {"before": "lt", "since": "gte"}
# Field type -> {rule op: records filter op}.
TABLE: dict[str, dict[str, str]] = {
    "multiselect": {"any": "in", "all": "eq", "none": "ne"},
    "select": {**_EQ, "any": "in"},
    "text": {**_EQ, "contains": "contains", "starts_with": "starts_with"},
    "email": {**_EQ, "contains": "contains", "starts_with": "starts_with"},
    "url": {**_EQ, "contains": "contains", "starts_with": "starts_with"},
    "number": _NUM,
    "integer": _NUM,
    "boolean": {"is": "eq"},
    "date": _DATES,
    "datetime": _DATES,
}
_LIST_OPS = ("any", "all", "none")
_NUMBER = re.compile(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=64)
    op: RuleOp
    value: str | list[str]


class RuleError(ValueError):
    def __init__(self, index: int, message: str) -> None:
        super().__init__(f"rules[{index}]: {message}")
        self.index = index


def segment_fields(fields: Sequence[ListField]) -> dict[str, ListField]:
    """The fields a rule may name: supported types only, plus the signup time."""
    out = {f.key: f for f in fields if f.key != "sm_status" and f.type in TABLE}
    out[SIGNUP_FIELD] = ListField(
        key=SIGNUP_FIELD, label="Signed up", type="datetime", many=False, choices=[], system=True
    )
    return out


def _kind(field: ListField) -> str:
    return field.type


def ops_for(field: ListField) -> tuple[RuleOp, ...]:
    return tuple(TABLE[_kind(field)])  # type: ignore[return-value]


def _text(index: int, v: object) -> str:
    if (
        not isinstance(v, str)
        or not 1 <= len(v) <= MAX_VALUE_LEN
        or any(ord(c) < 32 or ord(c) == 127 for c in v)
    ):
        raise RuleError(index, "invalid value")
    return v


def _scalar(index: int, field: ListField, v: str) -> str:
    kind = _kind(field)
    if kind in ("number", "integer"):
        if not _NUMBER.fullmatch(v) or not math.isfinite(float(v)):
            raise RuleError(index, "value must be a number")
        if kind == "integer" and not re.fullmatch(r"[+-]?\d+", v):
            raise RuleError(index, "value must be a whole number")
    elif kind == "boolean":
        v = v.lower()
        if v not in ("true", "false"):
            raise RuleError(index, "value must be true or false")
    elif kind in ("date", "datetime"):
        try:
            if not _DATE.fullmatch(v):
                raise ValueError
            date.fromisoformat(v)
        except ValueError:
            raise RuleError(index, "value must be a date (YYYY-MM-DD)") from None
        if kind == "datetime":
            v = f"{v}T00:00:00+00:00"
    elif field.key == "sm_email":
        v = v.lower()
    if field.choices and v not in {c.value for c in field.choices}:
        raise RuleError(index, "value is not one of the field's choices")
    return v


def _compile(index: int, rule: Rule, field: ListField) -> list[str]:
    op = rule.op
    allowed = TABLE[_kind(field)]
    if op not in allowed:
        raise RuleError(index, "operator is not valid for this field")
    term_op, key = allowed[op], field.key
    if op in _LIST_OPS:
        if not isinstance(rule.value, list) or not 1 <= len(rule.value) <= MAX_VALUES:
            raise RuleError(index, f"value must be a list of 1 to {MAX_VALUES} items")
        values = [_scalar(index, field, _text(index, v)) for v in rule.value]
        if any("," in v for v in values):
            raise RuleError(index, "list values cannot contain a comma")
        if term_op == "in":
            return [f"{key}:in:{','.join(values)}"]
        return [f"{key}:{term_op}:{v}" for v in values]
    if not isinstance(rule.value, str):
        raise RuleError(index, "value must be a single string")
    return [f"{key}:{term_op}:{_scalar(index, field, _text(index, rule.value))}"]


def compile_rules(rules: Sequence[Rule], fields: Mapping[str, ListField]) -> list[str]:
    if len(rules) > MAX_RULES:
        raise RuleError(MAX_RULES, f"at most {MAX_RULES} rules")
    terms: list[str] = []
    for i, rule in enumerate(rules):
        field = fields.get(rule.field)
        if field is None:
            raise RuleError(i, "unknown field")
        terms.extend(_compile(i, rule, field))
        if len(terms) > MAX_TERMS:
            raise RuleError(i, f"rules compile to more than {MAX_TERMS} terms")
    return terms
