"""MINOR 1: the CSV export is no longer a formula somebody else chose.

``=cmd|' /C calc'!A0`` stored in a ``text`` field was exported verbatim into a
file served as ``Content-Disposition: attachment`` — i.e. straight into the
spreadsheet of whichever admin clicked Export — and any caller who can create
a record picks that value.

The mitigation is the conventional leading apostrophe, and the reason this
module refused it before was that it looked lossy. It is not, if the apostrophe
is escaped too: exactly one is added on the way out and exactly one taken off
on the way in, for every cell. So the tests come in pairs — what the file says,
and what re-importing that file gives back — and the pair includes a value that
genuinely starts with an apostrophe, which is the case the objection was about.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles

_API = "/api/records/types"
_FIELDS = [
    {"key": "name", "type": "text", "label": "Name", "indexed": True},
    {"key": "note", "type": "text", "label": "Note", "indexed": False},
]
_DANGEROUS = [
    "=cmd|' /C calc'!A0",
    "+1+1",
    "-2+3",
    "-1+1",
    "-cmd",
    "@SUM(A1)",
    "\tstarts-with-tab",
    "\rstarts-with-cr",
]
_HARMLESS = ["plain text", "a=b", "x - y", ""]
_NEGATIVE_NUMBERS = ["-5", "-5.25", "-0", "-12345.00001"]
"""Cells a spreadsheet evaluates to themselves. Every negative number in an
export starts with a hyphen, and prefixing those made a readable column of
figures into a column of ``'-5``."""


async def _type(client, key: str) -> dict:
    resp = await client.post(
        _API,
        json={"key": key, "label": key.title(), "fields": _FIELDS, "display_field": "name"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create(client, key: str, data: dict) -> dict:
    resp = await client.post(f"{_API}/{key}/records", json={"data": data}, headers=roles(ADMIN))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _export_csv(client, key: str) -> str:
    resp = await client.get(f"{_API}/{key}/records/export?format=csv", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return resp.text


def _cells(csv_text: str, column: str) -> list[str]:
    import csv
    import io

    reader = csv.reader(io.StringIO(csv_text, newline=""))
    header = next(reader)
    index = header.index(column)
    return [row[index] for row in reader if row]


async def test_a_dangerous_cell_is_written_with_a_leading_apostrophe(client):
    await _type(client, "csvesc")
    for position, value in enumerate(_DANGEROUS):
        await _create(client, "csvesc", {"name": f"row{position}", "note": value})
    exported = sorted(_cells(await _export_csv(client, "csvesc"), "note"))
    assert exported == sorted("'" + value for value in _DANGEROUS)


async def test_a_plain_negative_number_is_written_bare(client):
    """The exemption: ``-5`` is not a formula, it is minus five, and the
    apostrophe was showing up in every column of figures."""
    await _type(client, "csvneg")
    for position, value in enumerate(_NEGATIVE_NUMBERS):
        await _create(client, "csvneg", {"name": f"row{position}", "note": value})
    exported = sorted(_cells(await _export_csv(client, "csvneg"), "note"))
    assert exported == sorted(_NEGATIVE_NUMBERS)


async def test_a_hyphen_cell_that_is_not_a_number_is_still_escaped(client):
    """The exemption is a *number*, not a leading hyphen — ``-1+1`` is an
    expression and ``-cmd`` is a cell reference away from being one."""
    await _type(client, "csvhyph")
    values = ["-1+1", "-cmd", "-1e5", "-.5", "-5 apples", "-"]
    for position, value in enumerate(values):
        await _create(client, "csvhyph", {"name": f"row{position}", "note": value})
    exported = sorted(_cells(await _export_csv(client, "csvhyph"), "note"))
    assert exported == sorted("'" + value for value in values)


async def test_a_harmless_cell_is_written_verbatim(client):
    await _type(client, "csvplain")
    for position, value in enumerate(_HARMLESS):
        await _create(client, "csvplain", {"name": f"row{position}", "note": value})
    exported = sorted(_cells(await _export_csv(client, "csvplain"), "note"))
    assert exported == sorted(_HARMLESS)


async def test_a_value_that_genuinely_starts_with_an_apostrophe_is_doubled(client):
    """The case the old "the prefix is not lossless" objection was about."""
    await _type(client, "csvapos")
    await _create(client, "csvapos", {"name": "quoted", "note": "'tis a quote"})
    assert _cells(await _export_csv(client, "csvapos"), "note") == ["''tis a quote"]


async def test_export_then_import_round_trips_every_shape(client):
    """The pair, end to end — and the assertion is ``skipped``, not ``updated``.

    Re-importing an export converges: a row the file already agrees with is
    counted as skipped and writes nothing (``_import_rows.unchanged``). So if
    a single apostrophe were added on the way out and not taken off on the way
    in, every one of these rows would come back as an *update* rather than a
    skip — which makes ``skipped == len(values)`` a stricter statement about
    the round trip than comparing payloads by hand.
    """
    await _type(client, "csvout")
    # The empty string is left out on purpose: an empty cell means ``None`` to
    # the importer, which is a round-trip asymmetry this module has always had
    # and nothing to do with the escape. It is covered verbatim above.
    values = [
        *_DANGEROUS,
        *_NEGATIVE_NUMBERS,
        *filter(None, _HARMLESS),
        "'tis a quote",
        "''already doubled",
    ]
    for position, value in enumerate(values):
        await _create(client, "csvout", {"name": f"row{position}", "note": value})

    exported = await _export_csv(client, "csvout")
    resp = await client.post(
        f"{_API}/csvout/records/import?dry_run=false&format=csv&on_error=abort",
        content=exported.encode(),
        headers={**roles(ADMIN), "Content-Type": "text/csv"},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert (report["skipped"], report["created"], report["updated"]) == (len(values), 0, 0)

    listed = await client.get(f"{_API}/csvout/records?page_size=200", headers=roles(ADMIN))
    assert listed.status_code == 200, listed.text
    back = {item["data"]["name"]: item["data"]["note"] for item in listed.json()["items"]}
    assert back == {f"row{position}": value for position, value in enumerate(values)}


async def test_the_envelope_columns_round_trip_too(client):
    """``position`` is negative here — a plain number, so it is written bare
    (the exemption) and the importer has to give the number back."""
    await _type(client, "csvenv")
    resp = await client.post(
        f"{_API}/csvenv/records",
        json={"data": {"name": "neg", "note": "x"}, "position": -7},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    exported = await _export_csv(client, "csvenv")
    assert _cells(exported, "position") == ["-7"]

    imported = await client.post(
        f"{_API}/csvenv/records/import?dry_run=false&format=csv&on_error=abort",
        content=exported.encode(),
        headers={**roles(ADMIN), "Content-Type": "text/csv"},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["skipped"] == 1
    listed = await client.get(f"{_API}/csvenv/records", headers=roles(ADMIN))
    assert [item["position"] for item in listed.json()["items"]] == [-7]
