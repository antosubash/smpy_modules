"""The shape of a schema change, shared by the classifier, the dry run, the
apply path and the API. Design doc §8.2, §8.5, §8.9.

Plain dataclasses: these are internal values the services layer passes
around. The API's SQLModel DTOs in ``contracts`` mirror them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sm_records.schema.types import CHANGE_SEVERITY, ChangeClass


@dataclass(frozen=True, slots=True)
class SchemaChange:
    """One classified difference between two field lists."""

    kind: ChangeClass
    field_key: str
    what: str
    """A stable machine-readable label: ``field_added``, ``field_removed``,
    ``type_changed``, ``required_added``, ``required_removed``,
    ``unique_added``, ``unique_removed``, ``indexed_on``, ``indexed_off``,
    ``constraint_tightened``, ``constraint_relaxed``, ``choice_added``,
    ``choice_removed``, ``options_changed``, ``relation_retargeted``,
    ``label_changed``."""
    before: Any = None
    after: Any = None


@dataclass(frozen=True, slots=True)
class SchemaDiff:
    """Every change between the current and proposed field lists."""

    changes: tuple[SchemaChange, ...]

    @property
    def kind(self) -> ChangeClass:
        """The class of the whole diff — the most severe change in it."""
        if not self.changes:
            return ChangeClass.ADDITIVE
        return max((c.kind for c in self.changes), key=CHANGE_SEVERITY.__getitem__)

    def keys(self, *kinds: ChangeClass) -> tuple[str, ...]:
        """Field keys touched by changes of the given classes, in order,
        without duplicates."""
        seen: dict[str, None] = {}
        for c in self.changes:
            if c.kind in kinds:
                seen.setdefault(c.field_key, None)
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class FailingRecord:
    uuid: str
    display_title: str
    errors: tuple[dict[str, str], ...]
    """``[{"field": key, "message": ...}]`` from the compiled validator."""


@dataclass(frozen=True, slots=True)
class DryRunReport:
    """What applying a diff would do to the records that already exist.
    Produced without writing anything (§8.2, §8.9)."""

    checked: int
    failing: int
    sample: tuple[FailingRecord, ...] = ()
    """At most ``DRY_RUN_SAMPLE`` failures, for the operator to read."""
    orphaned_conflicts: dict[str, int] = field(default_factory=dict)
    """Keys being (re-)added that already exist under ``_orphaned`` on some
    records, with the count — §8.8 refuses these until the caller chooses
    ``restore`` or ``discard``."""
    duplicates: dict[str, int] = field(default_factory=dict)
    """Keys gaining ``unique`` that records already hold duplicates of, with
    how many records hold one — :mod:`sm_records.services._duplicates`.

    Counted inside ``failing`` as well, which is what makes the change
    refusable without ``force`` like any other restrictive failure. It is
    carried separately because it is the one restrictive class ``force`` does
    not leave *recoverable*: every other marked record is fixed by its next
    ordinary write, and a duplicate cannot be — the write is refused until one
    of the values changes. The refusal says so, and it can only say so if it
    knows which half of ``failing`` is which. A record failing both a payload
    rule and this one is counted twice, so ``failing`` is capped at
    ``checked``: "12 of 10" would be a worse lie than a slight undercount."""

    @property
    def clean(self) -> bool:
        return self.failing == 0 and not self.orphaned_conflicts


DRY_RUN_SAMPLE = 10
