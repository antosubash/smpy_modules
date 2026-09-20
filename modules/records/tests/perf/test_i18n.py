"""What a second content locale costs — Phase 5 §4, measured both ways.

The design's claim is that content i18n is opt-in per host and inert on one
that publishes in one language. That is two separate questions and this file
asks both:

* **Off** — one content locale, no record with a sibling. Every row must cost
  what it cost before the feature existed, and the statement counts are the
  hard half of that.
* **On** — two locales with half of one type translated. The extra work is
  named rather than averaged away: a locale predicate on the list, the
  per-locale slug claim, and the ``translations`` batch the public shape
  carries.

Everything runs against ``perf_db_copy``. Translating half a type and flipping
``is_public`` are mutations, and the seeded file is reused across runs.
"""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient
from sm_records import settings_checks
from sm_records.models import RecordStatus
from sm_records.services import _claims
from sm_records.services._translations import create_translation, published_siblings
from sm_records.settings import RecordsSettings

from tests.app_harness import build_app
from tests.perf._bench import Results, Timing, capture, explain, repeat
from tests.perf._http import API, get_ok, measure, plan_label
from tests.perf.conftest import REPS, load_type, type_counts

pytestmark = pytest.mark.perf

PUBLIC = settings_checks.DEFAULT_PUBLIC_ROUTE_PREFIX
TYPE = "company"
SECOND = "de"
TRANSLATED_SHARE = 2
"""Every other record of the type gets a sibling — the 50% the study asks for."""


async def _public_app(db_state, tmp_path, settings: RecordsSettings):
    """The harness app with the anonymous read API mounted, at ``settings``."""
    app, _ = await build_app(tmp_path, db_state)
    app.state.sm_records.settings = settings
    await app.state.records_module.on_startup(app)
    return app


async def _make_public(session, key: str) -> None:
    rtype = await load_type(session, key)
    rtype.is_public = True
    await session.commit()


async def _translate_half(session, settings) -> tuple[int, int]:
    """Give every other record of ``TYPE`` a published sibling in ``SECOND``.

    Returns ``(records, translations)``. The siblings are published by hand
    rather than through a second service call: ``create_translation`` starts a
    draft on purpose (§4.3) and what this file needs to measure is a public
    listing with something in it.
    """
    from sm_records.index.query import build_query

    rtype = await load_type(session, TYPE)
    rtype.translatable = True
    await session.commit()
    records = list((await session.execute(build_query(rtype, []))).scalars().all())
    made = 0
    for index, record in enumerate(records):
        if index % TRANSLATED_SHARE:
            continue
        sibling = await create_translation(session, rtype, record, locale=SECOND, settings=settings)
        sibling.status = RecordStatus.PUBLISHED
        sibling.published_at = record.published_at or sibling.created_at
        made += 1
        if made % 100 == 0:
            await session.commit()
    await session.commit()
    return len(records), made


async def test_one_locale_is_the_phase_4_read_path(perf_db_copy, tmp_path):
    """Off: the list, the public list and one record, on a monolingual host.

    The statement counts are the assertion. A locale predicate the code adds
    unconditionally, or a sibling lookup that runs whether or not siblings can
    exist, shows up here as a number that is one too high — which is exactly
    what ``published_siblings`` turns out to do, and the note below says so.
    """
    settings = RecordsSettings(content_locales=("en",), default_content_locale="en")
    async with perf_db_copy.session_factory() as session:
        await _make_public(session, TYPE)
        counts = await type_counts(session)
    app = await _public_app(perf_db_copy, tmp_path, settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        async with perf_db_copy.session_factory() as session:
            n = counts.get(TYPE, 0)
            admin, _ = await measure(
                client,
                f"GET {TYPE} list, 1 content locale",
                f"{API}/{TYPE}/records",
                n,
                perf_db_copy.engine,
                session,
            )
            public, _ = await measure(
                client,
                f"GET public {TYPE} list, 1 content locale",
                f"{PUBLIC}/{TYPE}",
                n,
                perf_db_copy.engine,
                session,
            )
    assert admin.count == 3, f"the admin list costs {admin.count} statements on one locale"
    Results.note(
        f"public list on a monolingual host: {public.count} statements "
        f"(admin list: {admin.count}) — the extra one is the unconditional "
        "published_siblings batch"
    )


async def test_a_second_locale_on_the_list_and_the_public_page(perf_db_copy, tmp_path):
    """On: half of ``company`` translated, and every row it moves."""
    settings = RecordsSettings(
        content_locales=("en", SECOND), default_content_locale="en", max_count=10**9
    )
    async with perf_db_copy.session_factory() as session:
        await _make_public(session, TYPE)
        began = time.perf_counter()
        records, made = await _translate_half(session, settings)
        elapsed = time.perf_counter() - began
    Results.add(
        f"create_translation x{made} ({TYPE})",
        records,
        Timing([elapsed * 1000.0]),
        statements="batched",
        plan=f"{made / max(elapsed, 1e-9):.0f} rec/s",
    )
    app = await _public_app(perf_db_copy, tmp_path, settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        async with perf_db_copy.session_factory() as session:
            n = records + made
            cases = [
                ("list, all locales", f"{API}/{TYPE}/records"),
                ("list, ?locale=en", f"{API}/{TYPE}/records?locale=en"),
                (f"list, ?locale={SECOND}", f"{API}/{TYPE}/records?locale={SECOND}"),
                ("public list (default locale)", f"{PUBLIC}/{TYPE}"),
                (f"public list ?locale={SECOND}", f"{PUBLIC}/{TYPE}?locale={SECOND}"),
            ]
            boxes = {}
            for label, url in cases:
                box, _plan = await measure(
                    client,
                    f"GET {TYPE} {label}, 2 content locales",
                    url,
                    n,
                    perf_db_copy.engine,
                    session,
                )
                boxes[label] = box.count
            body = (await get_ok(client, f"{PUBLIC}/{TYPE}")).json()
    assert boxes["list, ?locale=en"] == boxes["list, all locales"], (
        "a locale filter is a fixed-column predicate and must cost no extra statement"
    )
    translated = [item for item in body["items"] if item["translations"]]
    Results.note(
        f"public page carried {len(translated)} of {len(body['items'])} items with a "
        f"sibling; the translations batch is {boxes['public list (default locale)']} - "
        f"{boxes['list, all locales']} = one statement per page, never per row"
    )


async def test_the_slug_check_is_per_locale_and_still_one_statement(perf_db_copy, tmp_path):
    """``ensure_slug_free`` gained a ``locale`` column in its predicate (§4.3).

    The partial unique index it has to agree with is ``(type_id, locale,
    slug)``, so the check must be answered from that index and not from a scan
    of the type — the F2 shape, one locale later.
    """
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, TYPE)
        counts = await type_counts(session)

        async def check(locale: str):
            await _claims.ensure_slug_free(session, rtype, "no-such-slug-perf", locale)

        for locale in ("en", SECOND):
            timing = await repeat(lambda locale=locale: check(locale), reps=REPS, warmup=3)
            with capture(perf_db_copy.engine) as box:
                await check(locale)
            plan = await explain(session, *box.last())
            Results.add(
                f"ensure_slug_free({TYPE}, locale={locale})",
                counts.get(TYPE, 0),
                timing,
                statements=box.count,
                plan=plan_label(plan),
                plan_lines=plan,
            )
            assert box.count == 1, f"the slug check cost {box.count} statements"


async def test_published_siblings_is_one_query_for_a_whole_page(perf_db_copy, tmp_path):
    """The translations batch, priced on its own.

    §4.4 says the sibling lookup is "one query per record read, never on the
    list" and ``published_siblings`` is the list's version of it: one query for
    the page, keyed by group. What it costs is therefore a function of the page
    size, not of the type — measured over a full page.
    """
    from sm_records.index.query import build_query

    # The install's content locales: ``published_siblings`` narrows to them, so
    # a sibling in a language the site has stopped publishing is not advertised
    # (it is a 404 by uuid). One predicate on the same statement — no extra
    # query, which is what the assertion below is about.
    settings = RecordsSettings(content_locales=("en", SECOND), default_content_locale="en")
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, TYPE)
        counts = await type_counts(session)
        page = list((await session.execute(build_query(rtype, []).limit(25))).scalars().all())

        async def run():
            await published_siblings(session, rtype, page, settings=settings)

        timing = await repeat(run, reps=REPS, warmup=3)
        with capture(perf_db_copy.engine) as box:
            await run()
        Results.add(
            f"published_siblings({TYPE}, 25 records)",
            counts.get(TYPE, 0),
            timing,
            statements=box.count,
        )
    assert box.count == 1, f"the sibling batch cost {box.count} statements for one page"
