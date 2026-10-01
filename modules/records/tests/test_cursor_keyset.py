"""The keyset cursor's predicate, in both of the forms it takes — F11 and S3.

Split from :mod:`tests.test_list_pagination` for the 300-line cap, along the
seam the fix draws: that file is the *contract* of ``?after=`` — a cursor
resumes, a cursor from another sort is refused, the last page carries none —
and this one is about the SQL the predicate compiles to, which since S3 is two
different things depending on the sort.

A single **non-nullable** sort term plus the ``id`` tiebreaker is written as
the row-value comparison ``(col, id) > (:v, :id)``, which a planner can push
into ``(type_id, col, id)`` and seek with. Everything else — several terms,
mixed directions, and every ``NULLS LAST`` ordering, which is every sort on an
indexed field because those are reached by ``LEFT OUTER JOIN`` — keeps the
``OR`` expansion, because a row value cannot express any of the three.

Both forms have to select the same rows in the same order. That is what these
tests are: the pages, walked, compared against ``?page=``.
"""

from __future__ import annotations

import pytest

from tests.app_harness import ADMIN, roles
from tests.test_list_pagination import _API, _seed


@pytest.mark.parametrize("sort", ["position", "-position", "created_at", "-created_at"])
async def test_the_row_value_cursor_agrees_with_offset_paging(client, sort):
    """The keyset predicate for a **non-nullable** single sort term is a row
    value, ``(col, id) > (:v, :id)`` — S3.

    Three of the four parameters are the interesting ones. ``position`` is
    uniform across a seeded type, so every row ties on the sort value and the
    whole walk is decided by the ``id`` half of the tuple: that is the case a
    row-value comparison gets right and a hand-written "greater *or* equal and
    greater id" gets wrong by one row per page. ``-position`` and
    ``-created_at`` run the tiebreaker backwards
    (:func:`~sm_records.index._sorting.tiebreak_desc`), which is the other
    direction the tuple has to be written in.

    ``sort=name`` — an *indexed* field, reached by ``LEFT OUTER JOIN`` and
    therefore nullable — is covered by the tests above and keeps the ``OR``
    expansion, because ``NULLS LAST`` is not an order a row value can express.
    """
    await _seed(client, 6)
    first = (
        await client.get(f"{_API}/widget/records?page_size=2&sort={sort}", headers=roles(ADMIN))
    ).json()
    by_cursor = (
        await client.get(
            f"{_API}/widget/records?page_size=2&sort={sort}&after={first['next_cursor']}",
            headers=roles(ADMIN),
        )
    ).json()
    by_page = (
        await client.get(
            f"{_API}/widget/records?page_size=2&sort={sort}&page=2", headers=roles(ADMIN)
        )
    ).json()
    assert [i["uuid"] for i in by_cursor["items"]] == [i["uuid"] for i in by_page["items"]]
    repeated = {i["uuid"] for i in by_cursor["items"]} & {i["uuid"] for i in first["items"]}
    assert not repeated, f"the second page repeats {repeated} from the first"


@pytest.mark.parametrize("sort", ["position", "-created_at", "display_title"])
async def test_a_row_value_cursor_walks_the_whole_type_exactly_once(client, sort):
    """Every row, once, in order — the property a keyset rewrite can break
    silently. Page size 2 over 7 records means four boundaries to get wrong."""
    await _seed(client, 7)
    seen: list[str] = []
    url = f"{_API}/widget/records?page_size=2&sort={sort}&total=false"
    for _ in range(10):
        body = (await client.get(url, headers=roles(ADMIN))).json()
        seen += [item["uuid"] for item in body["items"]]
        if body["next_cursor"] is None:
            break
        url = (
            f"{_API}/widget/records?page_size=2&sort={sort}&total=false&after={body['next_cursor']}"
        )
    everything = (
        await client.get(f"{_API}/widget/records?page_size=50&sort={sort}", headers=roles(ADMIN))
    ).json()
    assert seen == [item["uuid"] for item in everything["items"]]
    assert len(set(seen)) == 7


def test_the_keyset_clause_is_a_row_value_only_where_it_means_the_same_thing():
    """The eligibility rule itself, without a database.

    A nullable term wears ``NULLS LAST``, which a row value cannot express; a
    descending term no index serves keeps an *ascending* tiebreaker, which is
    not a row value either; and two terms may run two ways. Each of those must
    fall back to the ``OR`` expansion, and the one case left must not.
    """
    from sm_records.index._sorting import SortTerm, keyset_clause
    from sm_records.models import Record

    def term(*, desc: bool, nullable: bool, index_served: bool) -> SortTerm:
        return SortTerm(
            expr=Record.created_at,
            desc=desc,
            nullable=nullable,
            kind=None,
            fixed="created_at",
            join=None,
            index_served=index_served,
        )

    plain = term(desc=False, nullable=False, index_served=True)
    usable = str(keyset_clause(Record, [plain], ["v", 1]))
    assert " OR " not in usable, usable
    assert "(records_record.created_at, records_record.id) >" in usable, usable

    descending = term(desc=True, nullable=False, index_served=True)
    assert "(records_record.created_at, records_record.id) <" in str(
        keyset_clause(Record, [descending], ["v", 1])
    )

    for unusable in (
        term(desc=False, nullable=True, index_served=True),
        term(desc=True, nullable=False, index_served=False),
    ):
        assert " OR " in str(keyset_clause(Record, [unusable], ["v", 1]))
    assert " OR " in str(keyset_clause(Record, [plain, plain], ["v", "w", 1]))

    # A ``NULL`` cursor value has no row-value reading either: SQL says nothing
    # is comparable to it, while the ordering says nothing is after it. The
    # expansion folds to "the ties, then the id", which is the right answer and
    # is not a tuple comparison.
    from_null = str(keyset_clause(Record, [plain], [None, 1]))
    assert "records_record.created_at, records_record.id" not in from_null, from_null
    assert "created_at IS NULL" in from_null, from_null
