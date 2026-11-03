"""records services _import_envelope helpers."""

from __future__ import annotations
from sm_records.models import RecordStatus
from sm_records.records.services._import_parse import ImportRow
from sm_records.records.services.errors import ValidationFailed


class Envelope:
    """The non-payload half of a row, coerced once. A named object rather
    than a tuple because most of its members are optional in different ways,
    and a positional unpack is how ``position`` lands in ``status``.

    ``locale`` arrives raw and is replaced by the *resolved* content locale in
    ``import_._validate`` — where the settings are in reach and where a bad one
    becomes this row's error rather than the whole file's. ``translation_group``
    is carried verbatim: the importer never rewrites it, because that would
    rewrite the relationships the file is describing. It does **check** it —
    a group is a uniqueness exemption, not data (``_import_plan._forged_group``)
    — and a row naming a group this file does not describe is refused.
    """

    __slots__ = ("has_slug", "locale", "position", "slug", "status", "translation_group")

    def __init__(
        self,
        status: RecordStatus | None,
        slug: str | None,
        has_slug: bool,
        position: int | None,
        locale: str | None = None,
        translation_group: str | None = None,
    ) -> None:
        self.status = status
        self.slug = slug
        self.has_slug = has_slug
        self.position = position
        self.locale = locale
        self.translation_group = translation_group


def envelope_for(row: ImportRow) -> Envelope:
    """Coerce ``status``/``slug``/``position``, or raise the row's error.

    CSV hands every cell over as a string (``position`` arrives as ``"3"``),
    JSON hands it over typed. One coercion for both is the only reason having
    two formats is not two features that drift.
    """
    raw_status = row.envelope.get("status")
    status: RecordStatus | None = None
    if raw_status not in (None, ""):
        try:
            status = RecordStatus(str(raw_status))
        except ValueError as exc:
            raise ValidationFailed(
                f"unknown status {raw_status!r}",
                [{"field": "status", "message": "status must be 'draft' or 'published'"}],
            ) from exc
    raw_position = row.envelope.get("position")
    position: int | None = None
    if raw_position not in (None, ""):
        try:
            position = int(raw_position)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(
                f"position {raw_position!r} is not a whole number",
                [{"field": "position", "message": "position must be a whole number"}],
            ) from exc
    slug = row.envelope.get("slug")
    locale = row.envelope.get("locale")
    group = row.envelope.get("translation_group")
    return Envelope(
        status,
        None if slug is None else str(slug),
        "slug" in row.envelope,
        position,
        None if locale in (None, "") else str(locale),
        None if group in (None, "") else str(group),
    )
