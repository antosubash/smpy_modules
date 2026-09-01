"""Structured diff between two ``PageRevision`` snapshots.

Puck stores the page document as ``{content: [...blocks], root: {...}}``
where every block carries a ``props.id`` Puck assigned. Diffing by id
keeps the result stable when authors reorder blocks instead of
rewriting them — and lets the editor render a per-block added /
removed / changed summary without trying to read minds about field
intent.
"""

from __future__ import annotations

from typing import Any

from pagebuilder.models import PageRevision

_TRACKED_METADATA = ("title", "meta_description", "og_image")


def _normalise_blocks(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Pull the block list out of a Puck document.

    Returns an empty list for ``None`` / malformed input so the diff
    treats "no doc" as "no blocks" instead of raising — a missing
    snapshot is a 404 at the route layer.
    """
    if not isinstance(data, dict):
        return []
    content = data.get("content")
    return content if isinstance(content, list) else []


def _block_key(block: dict[str, Any]) -> str | None:
    """Block identity used to pair entries across revisions.

    Puck assigns ``props.id`` at insertion time; falling back to
    positional indexing only when an id is missing avoids treating an
    entire reorder as "remove all + add all".
    """
    if not isinstance(block, dict):
        return None
    props = block.get("props")
    if isinstance(props, dict):
        block_id = props.get("id")
        if isinstance(block_id, str) and block_id:
            return block_id
    return None


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [k for k in keys if before.get(k) != after.get(k)]


def revision_diff(before: PageRevision, after: PageRevision) -> dict[str, Any]:
    """Compute a block-level diff between two revision snapshots.

    The result has two top-level keys:

    - ``metadata`` lists per-field ``before``/``after`` tuples for the
      page-level columns that survive in a revision row (title,
      meta_description, og_image).
    - ``blocks`` groups Puck blocks into ``added`` / ``removed`` /
      ``changed``, keyed by ``props.id``. Changed entries include
      ``fields`` — the list of prop names whose value differs.
    """
    metadata: dict[str, dict[str, Any]] = {}
    for field in _TRACKED_METADATA:
        before_value = getattr(before, field)
        after_value = getattr(after, field)
        if before_value != after_value:
            metadata[field] = {"before": before_value, "after": after_value}

    return {"metadata": metadata, "blocks": block_diff(before.data, after.data)}


def block_diff(
    before_data: dict[str, Any] | None, after_data: dict[str, Any] | None
) -> dict[str, list[dict[str, Any]]]:
    """Group two Puck documents' blocks into added / removed / changed.

    Split out of :func:`revision_diff` so callers holding raw documents rather
    than ``PageRevision`` rows — the snapshot restore plan, for one — can pair
    blocks by ``props.id`` without reimplementing the rules.
    """
    before_blocks = _normalise_blocks(before_data)
    after_blocks = _normalise_blocks(after_data)

    before_by_id = {key: b for b in before_blocks if (key := _block_key(b)) is not None}
    after_by_id = {key: b for b in after_blocks if (key := _block_key(b)) is not None}

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    for block_id, block in after_by_id.items():
        if block_id in before_by_id:
            continue
        added.append({"id": block_id, "type": block.get("type")})

    for block_id, block in before_by_id.items():
        if block_id in after_by_id:
            continue
        removed.append({"id": block_id, "type": block.get("type")})

    for block_id, after_block in after_by_id.items():
        before_block = before_by_id.get(block_id)
        if before_block is None:
            continue
        type_changed = before_block.get("type") != after_block.get("type")
        before_props = before_block.get("props") or {}
        after_props = after_block.get("props") or {}
        if not isinstance(before_props, dict):
            before_props = {}
        if not isinstance(after_props, dict):
            after_props = {}
        # ``id`` is the diff key itself — reporting it as a changed
        # field would be noise on every entry that survives.
        fields = [f for f in _changed_fields(before_props, after_props) if f != "id"]
        if type_changed or fields:
            changed.append(
                {
                    "id": block_id,
                    "type": after_block.get("type"),
                    "fields": fields,
                    **(
                        {"type_before": before_block.get("type")}
                        if type_changed
                        else {}
                    ),
                }
            )

    return {"added": added, "removed": removed, "changed": changed}
