"""A record's counterparts in the install's other languages.

A translation is an ordinary record: same type, same table, same revisions,
same index rows, its own uuid, its own slug **in its own locale**, its own
draft. What makes two records translations of each other is that they share a
``translation_group`` — a generated key rather than a pointer at "the
original", because there is no original (see
:class:`sm_records.models.Record`).

That choice is what makes this file short. Publishing a German record,
trashing it, restoring one of its revisions, exporting it — none of it needed a
line of new code, because the German record is a record.

Split from :mod:`sm_records.services.records` for the 300-line cap, along the
seam that module's docstring already draws: that one is the lifecycle of one
document, this one is the relationship between several.
"""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import locales
from sm_records.constants import MAX_SLUG_LEN, ORPHANED_KEY
from sm_records.models import Record, RecordStatus, RecordType, tables_for
from sm_records.services import _claims
from sm_records.services.errors import Conflict
from sm_records.settings import RecordsSettings

__all__ = ["create_translation", "list_translations", "published_siblings"]

_MAX_SLUG_ATTEMPTS = 20
"""How many ``-2``, ``-3``… variants to try when the source's slug is already
taken in the target language. Far past any honest collision; it exists so a
pathological slug cannot spin."""


async def list_translations(db: AsyncSession, rtype: RecordType, group: str) -> list[Record]:
    """Every record in ``group``, the one you asked about included — **and the
    trashed ones**.

    Trashed siblings are listed rather than filtered out because
    ``(translation_group, locale)`` is unique regardless of ``is_deleted``: the
    language is occupied until the record is purged or restored, and
    :func:`create_translation` refuses it. Hiding the row would leave the
    editor offering an "Add translation" button that can only ever 409.
    ``TranslationRead.is_deleted`` is what lets the panel say *why* the
    language is unavailable instead of silently dropping its button.

    Ordered by locale, so a language switcher does not reshuffle itself between
    two loads of the same record.
    """
    cls = tables_for(rtype).record
    stmt = (
        select(cls)
        .where(cls.type_id == rtype.id, cls.translation_group == group)
        .order_by(cls.locale)
        .execution_options(include_deleted=True)
    )
    return list((await db.execute(stmt)).scalars().all())


async def published_siblings(
    db: AsyncSession,
    rtype: RecordType,
    records: list[Record],
    *,
    settings: RecordsSettings,
) -> dict[str, list[Record]]:
    """``{translation_group: [published, live records]}`` for a whole page.

    **One query for the page, keyed by group** — never one per row, which is
    the rule §9 already sets for relation expansion and the difference between
    a public listing and fifty round trips. Nothing lifts the framework's
    soft-delete filter here, so the trash cannot reach an anonymous reader; the
    ``status`` predicate is in the statement for the same reason
    :func:`sm_records.services.public.get_public_record` puts it there.

    A language switcher is built from this, so advertising a draft or a trashed
    sibling would point a reader — and a crawler — at a 404. **A sibling in a
    locale the install has since dropped from ``content_locales`` is the same
    kind of broken link**, and a worse one: the record is there, so the
    switcher offered a language the listing refuses to name and the by-uuid
    read now 404s. The predicate is the same one
    :func:`~sm_records.services.public.get_public_record` applies, so the two
    halves of the public surface agree about which languages exist.
    """
    groups = sorted({record.translation_group for record in records})
    if not groups:
        return {}
    cls = tables_for(rtype).record
    stmt = (
        select(cls)
        .where(
            cls.type_id == rtype.id,
            cls.translation_group.in_(groups),
            cls.status == RecordStatus.PUBLISHED,
            cls.locale.in_(locales.supported(settings)),
        )
        .order_by(cls.locale)
    )
    out: dict[str, list[Record]] = {group: [] for group in groups}
    for sibling in (await db.execute(stmt)).scalars().all():
        out[sibling.translation_group].append(sibling)
    return out


async def _sibling(db: AsyncSession, rtype: RecordType, group: str, locale: str) -> Record | None:
    """The group's record in ``locale``, trash included.

    Trashed siblings count. The slug is still claimed and the unique index
    still holds while a record sits restorable, so treating one as absent would
    offer to create a translation the database then refuses.
    """
    cls = tables_for(rtype).record
    stmt = (
        select(cls)
        .where(
            cls.type_id == rtype.id,
            cls.translation_group == group,
            cls.locale == locale,
        )
        .execution_options(include_deleted=True)
    )
    return (await db.execute(stmt)).scalars().first()


async def _free_slug(db: AsyncSession, rtype: RecordType, base: str, locale: str) -> str:
    """``base`` if it is free in ``locale``, else ``base-2``, ``base-3``…

    Usually the first: slugs are unique per language (§4.1), so the source's
    own slug is available in the new one unless an unrelated record already
    took it there. One query for the whole candidate set rather than a
    create-and-catch loop, which would roll back anything the caller had
    already written in the same transaction.

    ``include_deleted``, because the trash keeps its claim per locale.
    """
    cls = tables_for(rtype).record
    stmt = (
        select(cls.slug)
        .where(
            cls.type_id == rtype.id,
            cls.locale == locale,
            cls.slug.startswith(base[: _stem(base)]),
        )
        .execution_options(include_deleted=True)
    )
    taken = {slug for slug in (await db.execute(stmt)).scalars().all() if slug}
    if base not in taken:
        return base
    for suffix in range(2, _MAX_SLUG_ATTEMPTS + 2):
        candidate = f"{base[: MAX_SLUG_LEN - len(str(suffix)) - 1]}-{suffix}"
        if candidate not in taken:
            return candidate
    raise Conflict(f"could not derive a free slug from {base!r} in {locale!r}; set one explicitly")


def _stem(base: str) -> int:
    """How much of ``base`` every candidate is guaranteed to share.

    A base already at the column's limit has to be cut to make room for the
    suffix, so its variants do not start with ``base`` — prefiltering on the
    full string would miss them and hand back a slug that is in fact taken.
    """
    longest = len(str(_MAX_SLUG_ATTEMPTS + 1))
    return min(len(base), MAX_SLUG_LEN - longest - 1)


async def create_translation(
    db: AsyncSession,
    rtype: RecordType,
    source: Record,
    *,
    locale: str,
    settings: RecordsSettings,
    slug: str | None = None,
    actor: str | None = None,
) -> Record:
    """Start ``source``'s counterpart in ``locale`` (Phase 5 §4.3).

    The new record joins the source's group, copies its payload and its
    ``position``, and starts as a **draft** whatever the source's status — a
    translation going live the moment it is created would publish untranslated
    copy at an address that did not exist a second earlier.

    Its slug is regenerated **in the target locale** and never inherited
    verbatim without being checked there: the source's slug belongs to another
    language's namespace, and the whole point of scoping the unique index to
    the locale is that the same word may be the address in both. An explicit
    ``slug`` is used as given, and refused with the ordinary 409 if it is taken
    in that locale — the caller asked for one address, so a silently
    suffixed one would be the wrong answer.

    Four refusals: a type that is not ``translatable`` (409 — translations of
    it are not a thing that exists), a locale that is not configured (422,
    naming it), a source already in the target locale (409), and a sibling that
    already holds that language (409, **trash included**).

    There is no fifth about ``unique``, and no uniqueness check of its own
    here: the sibling is written by :func:`create_record` with the source's
    group, and a record's ``unique`` claims do not apply to the group it is in
    (see :func:`sm_records.services._claims.ensure_unique`). Copying a payload
    that carries a ``unique`` value is the ordinary case — a German product
    carries the English product's SKU — and checking it here would only refuse
    it one layer earlier.
    """
    if not rtype.translatable:
        raise Conflict(
            f"type {rtype.key!r} is not translatable; enable 'translatable' on the "
            "type before creating translations of its records"
        )
    target = locales.require(settings, locale)
    if target == source.locale:
        raise Conflict(f"record {source.uuid} is already in {target!r}")
    existing = await _sibling(db, rtype, source.translation_group, target)
    if existing is not None:
        state = "in the trash" if existing.is_deleted else "already exists"
        raise Conflict(
            f"a {target!r} translation of record {source.uuid} {state} "
            f"({existing.uuid}); restore or purge it rather than creating a second"
        )

    if slug is not None:
        # Checked before the write so the refusal names the locale rather than
        # arriving as the partial unique index's ``IntegrityError``.
        await _claims.ensure_slug_free(db, rtype, slug, target)
        resolved_slug: str | None = slug
    elif source.slug:
        resolved_slug = await _free_slug(db, rtype, source.slug, target)
    else:
        resolved_slug = None

    # ``_orphaned`` is the admin's undo buffer for deleted fields (§8.2) and is
    # refused on every inbound payload, this one included — the sibling starts
    # from what the source's schema currently declares, not from its history.
    data = deepcopy(dict(source.data or {}))
    data.pop(ORPHANED_KEY, None)

    # Imported here rather than at module scope: ``services.records``
    # re-exports this function, so a top-level import would close the cycle
    # while that module is still executing.
    from sm_records.services.records import create_record

    return await create_record(
        db,
        rtype,
        data=data,
        settings=settings,
        status=RecordStatus.DRAFT,
        slug=resolved_slug,
        position=source.position,
        actor=actor,
        locale=target,
        translation_group=source.translation_group,
    )
