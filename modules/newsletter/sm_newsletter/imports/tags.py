"""Tag cells and the choice values they become (R8, D8). Pure."""

from __future__ import annotations

import csv

# ``tag_values`` is records' own rule (``tag_choice_values``, D8) for staging's preview; the
# tags step takes the authoritative values from ``add_tag_choices``.
from sm_records.contracts.newsletter_import import tag_choice_values as tag_values

from sm_newsletter.imports.constants import MAX_TAG_LEN, MAX_TAGS_PER_ROW

__all__ = ["parse_tags", "tag_values"]


def parse_tags(cell: str) -> tuple[list[str], bool]:
    """``(labels, any dropped)``: 1-100 printable characters (``str.isprintable``), at most 50."""
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
