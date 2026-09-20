"""The multilingual half of the demo dataset.

Split from :mod:`sm_records.seed.runner` for the 300-line cap, along a seam
that is really a property: **on a single-locale install nothing in this module
runs**, and the seeded database is byte-for-byte the one the module produced
before content i18n existed. That is what "opt-in per host, off by default,
inert when unused" means for the seeder, and keeping it in one file is what
makes it checkable at a glance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sm_records import locales
from sm_records.models import Record, RecordType
from sm_records.seed.log import log
from sm_records.services.errors import RecordsError
from sm_records.services.records import create_translation
from sm_records.settings import RecordsSettings

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime, types only
    pass

__all__ = ["seed_translations"]

_TRANSLATED_SHARE = 10
"""Every Nth ``company`` gets a translation when the install publishes in more
than one language (Phase 5 §4.6) — roughly 10%.

Enough that a multilingual host has something to look at on the Languages panel
and something for ``?locale=`` to return, few enough that the seeded dataset is
still recognisably the one a monolingual install gets."""


async def seed_translations(
    db: Any,
    committer: Any,
    rtype: RecordType,
    companies: list[Record],
    *,
    settings: RecordsSettings,
) -> int:
    """Give roughly a tenth of the companies a sibling in the second locale.

    Nothing at all on a single-locale install — which is the point: content
    i18n is opt-in per host, and a seeder that produced a different dataset
    once the feature existed would make "off by default" untestable.

    The type is marked ``translatable`` first, because ``create_translation``
    refuses a type that is not (§4.3) and the demo types are declared without
    the flag; a host that turns its second locale on later does the same thing
    from the type editor. A refusal on one record is logged and skipped rather
    than failing the run: the seeder's job is a plausible dataset, and a
    company whose slug collides in the target language is not a reason to lose
    the other 299 records.
    """
    supported = locales.supported(settings)
    if len(supported) < 2 or not companies:
        return 0
    target = supported[1]
    rtype.translatable = True
    db.add(rtype)
    await db.flush()

    created = 0
    for company in companies[::_TRANSLATED_SHARE]:
        try:
            await create_translation(
                db, rtype, company, locale=target, settings=settings, actor="records-seed-cli"
            )
        except RecordsError as exc:
            log(f"skipped {target} translation of {company.uuid}: {exc.detail}")
            continue
        created += 1
        await committer.tick()
    log(f"created {created} {target} translation(s) of companies")
    return created
