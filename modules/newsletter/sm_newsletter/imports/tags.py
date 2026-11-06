"""Tag cells and the choice values they become (R8, D8). Pure."""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Sequence

from sm_records.contracts.newsletter_admin import FieldChoice

from sm_newsletter.imports.constants import MAX_TAG_LEN, MAX_TAGS_PER_ROW


def parse_tags(cell: str) -> tuple[list[str], bool]:
    """``(labels, any dropped)``: 1-100 characters, no control characters, at most 50."""
    if not cell.strip():
        return [], False
    try:
        raw = next(csv.reader([cell]), [])
    except csv.Error:
        return [], True
    labels: list[str] = []
    dropped = False
    for item in raw:
        label = item.strip()
        if not label or len(label) > MAX_TAG_LEN or not label.isprintable():
            dropped = True
        elif label not in labels:
            labels.append(label)
    if len(labels) > MAX_TAGS_PER_ROW:
        return labels[:MAX_TAGS_PER_ROW], True
    return labels, dropped


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-") or "tag"


def _fallback(label: str, taken: set[str]) -> str:
    """Slug plus a hash; ``-2``, ``-3``... appended while another choice holds it."""
    base = f"{_slug(label)[:80]}-{hashlib.sha256(label.encode()).hexdigest()[:8]}"
    value, n = base, 1
    while value in taken:
        n += 1
        value = f"{base}-{n}"
    return value


def tag_values(labels: Sequence[str], existing: Sequence[FieldChoice]) -> dict[str, str]:
    """Label to choice value (D8): reused, else the label, else slug plus a hash (and a
    counter while that is taken). Labels in sorted order, so the result is deterministic."""
    by_label: dict[str, str] = {}
    for choice in existing:
        by_label.setdefault(choice.label, choice.value)
    taken = {choice.value for choice in existing}
    result: dict[str, str] = {}
    for label in sorted(set(labels)):
        if label in by_label:
            result[label] = by_label[label]
        elif "," not in label and label not in taken:
            result[label] = label
        else:
            result[label] = _fallback(label, taken)
        taken.add(result[label])
    return result
