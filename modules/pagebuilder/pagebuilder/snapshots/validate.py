"""Shape checks for the documents inside a bundle.

Split from ``archive.py`` so that file keeps to zip mechanics — extracting
entries, bounding their size, verifying digests — while everything that asks
"is this document one apply could survive?" lives here.

The split matters because these checks all share one rule: a bundle that is
going to fail must fail at the boundary, while it is still a file someone can
replace. By apply time a pre-restore snapshot has been taken and pages are
being written, so a malformed document surfaces as a 500 halfway through
overwriting a live site instead of as a rejection of the file that caused it.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pagebuilder import locales
from pagebuilder.models import PageStatus, SnapshotMedia
from pagebuilder.snapshots.assets import collect_sentinels
from pagebuilder.snapshots.format import (
    LAYOUT_NAME,
    PAGES_DIR,
    REDIRECTS_NAME,
)
from pagebuilder.snapshots.pages import payload_locale
from pagebuilder.snapshots.plan import redirect_locale


class BundleError(Exception):
    """A bundle that cannot be trusted, with a reason fit to show a user."""


def load_document(path: Path, label: str) -> Any:
    """Parse a bundle document, reporting bad JSON as a bundle problem.

    ``json.JSONDecodeError`` is a ``ValueError``, not a ``BundleError``, so
    without this every malformed document escaped the boundary as a 500 and
    skipped the caller's cleanup of the half-extracted directory.
    """
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise BundleError(f"{label} is not valid JSON") from exc


def _check_locale(label: str, value: Any) -> None:
    """Reject a locale a column could not hold or a URL could not carry.

    Absent is fine — a version 1 document predates the field and is read as
    the default locale. A tag this host does not publish is also fine, and is
    read the same way: refusing it would make a bundle from a site with one
    extra language unrestorable in full, when all that is actually true is
    that those pages land in the default locale. What is rejected is a value
    that is not a locale at all, because it would otherwise reach the column
    as junk.
    """
    if value is None:
        return
    if not isinstance(value, str) or not value:
        raise BundleError(f"{label} has an empty locale")
    if len(value) > locales.MAX_LOCALE_LEN:
        raise BundleError(f"{label} has a locale longer than {locales.MAX_LOCALE_LEN}")
    if not locales.LOCALE_PATTERN.match(value):
        raise BundleError(f"{label} has an unreadable locale: {value!r}")


def _check_page(label: str, payload: Any) -> None:
    """Reject a page document ``apply_payload`` would choke on."""
    if not isinstance(payload, dict):
        raise BundleError(f"{label} is not an object")
    slug = payload.get("slug")
    if not isinstance(slug, str) or not slug:
        raise BundleError(f"{label} has no slug")
    _check_locale(label, payload.get("locale"))
    status = payload.get("status")
    try:
        PageStatus(status)
    except ValueError as exc:
        raise BundleError(f"{label} has an unknown status: {status!r}") from exc
    for field in ("publish_at", "unpublish_at"):
        raw = payload.get(field)
        if not raw:
            continue
        try:
            datetime.fromisoformat(raw)
        except (TypeError, ValueError) as exc:
            raise BundleError(f"{label} has an unreadable {field}: {raw!r}") from exc


# Read off the column widths on `SnapshotMedia` rather than mirrored as
# literals, so widening a column cannot leave this check behind. Checked here
# so an over-long string fails as a 422 at the boundary rather than as a raw
# DataError from the insert — which SQLite silently accepts and Postgres turns
# into a 500.
def _width(column: str) -> int:
    return SnapshotMedia.__table__.columns[column].type.length


_MEDIA_FIELD_LIMITS = tuple(
    (field, _width(field))
    for field in ("original_filename", "content_type", "folder")
)


def check_media_entry(name: str, entry: dict[str, Any]) -> None:
    """Check that one ``media/index.json`` value fits what the row can hold."""
    if len(name) > _width("bundle_name"):
        raise BundleError(f"media entry name is too long: {name[:60]!r}...")
    for field, limit in _MEDIA_FIELD_LIMITS:
        value = entry.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise BundleError(f"media entry {name!r} has a non-string {field}")
        if len(value) > limit:
            raise BundleError(
                f"media entry {name!r} has a {field} longer than {limit} characters"
            )


def _check_redirects(dest: Path) -> None:
    """Validate ``redirects.json`` before anything tries to restore from it.

    Both the plan and apply read ``row["from_slug"]`` directly, and
    ``(locale, from_slug)`` is unique, so a missing key or a repeat within one
    language would otherwise escape as a 500 rather than as a rejected bundle.
    The pair is what is checked, not the bare slug: two languages retiring the
    same address is ordinary, and rejecting it would refuse a bundle the
    database would have accepted.
    """
    path = dest / REDIRECTS_NAME
    if not path.is_file():
        return
    rows = load_document(path, REDIRECTS_NAME)
    if not isinstance(rows, list):
        raise BundleError(f"{REDIRECTS_NAME} is not a list")
    seen: set[tuple[str, str]] = set()
    for position, row in enumerate(rows):
        label = f"{REDIRECTS_NAME}[{position}]"
        if not isinstance(row, dict):
            raise BundleError(f"{label} is not an object")
        for field in ("from_slug", "to_slug"):
            value = row.get(field)
            if not isinstance(value, str) or not value:
                raise BundleError(f"{label} has no {field}")
            if len(value) > 200:
                raise BundleError(f"{label} has a {field} longer than 200 characters")
        _check_locale(label, row.get("locale"))
        key = (redirect_locale(row), row["from_slug"])
        if key in seen:
            raise BundleError(f"{label} repeats from_slug {row['from_slug']!r}")
        seen.add(key)


def check_documents(dest: Path, index: dict[str, Any]) -> None:
    """Validate every document in the tree, in one pass.

    Each document is parsed once and both checked for shape and scanned for
    ``asset://`` references, so the two concerns cannot drift apart over which
    files they consider a document.
    """
    referenced: set[str] = set()
    seen_pages: set[tuple[str, str]] = set()
    for document in sorted((dest / PAGES_DIR).glob("*.json")):
        label = f"{PAGES_DIR}/{document.name}"
        payload = load_document(document, label)
        _check_page(label, payload)
        # Two files claiming one page would otherwise resolve as "last file
        # wins" in `read_documents`, dropping a page with nothing in the plan
        # to say it happened. Rejected here for the same reason repeated
        # `from_slug` values are — and on `(locale, slug)`, because two
        # languages publishing the same slug is the ordinary case this whole
        # change exists to support, not a malformed bundle.
        page_key = (payload_locale(payload), payload["slug"])
        if page_key in seen_pages:
            raise BundleError(
                f"{label} repeats slug {payload['slug']!r} in {page_key[0]}"
            )
        seen_pages.add(page_key)
        referenced |= collect_sentinels(payload)
    layout = dest / LAYOUT_NAME
    if layout.is_file():
        referenced |= collect_sentinels(load_document(layout, LAYOUT_NAME))
    _check_redirects(dest)

    missing = sorted(referenced - set(index))
    if missing:
        raise BundleError(
            "bundle references media it does not contain: " + ", ".join(missing)
        )
