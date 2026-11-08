from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from sm_newsletter.core.errors_import import (
    ImportEmptyFile,
    ImportMalformedCsv,
    ImportNoEmailColumn,
    ImportNotUtf8,
    ImportTooManyColumns,
)
from sm_newsletter.imports import mailchimp as mc
from sm_newsletter.imports.constants import MAX_CELL, MAX_COLUMNS
from sm_records.contracts.newsletter_admin import FieldChoice

from tests.imports.fixtures import csv_bytes

SYSTEM = [
    "MEMBER_RATING", "OPTIN_TIME", "OPTIN_IP", "CONFIRM_TIME", "CONFIRM_IP", "LATITUDE",
    "LONGITUDE", "GMTOFF", "DSTOFF", "TIMEZONE", "CC", "REGION", "LAST_CHANGED", "LEID",
    "EUID", "NOTES",
]  # fmt: skip
REAL = ["Email Address", "First Name", "Last Name", *SYSTEM, "TAGS"]


def _row(email: str, tags: str, **over: str) -> list[str]:
    values = dict.fromkeys(REAL, "")
    values.update(
        {
            "Email Address": email,
            "First Name": "Ada",
            "Last Name": "L",
            "OPTIN_TIME": "2020-01-02 03:04:05",
            "CONFIRM_TIME": "2020-01-03 04:05:06",
            "TAGS": tags,
        }
    )
    values.update(over)
    return [values[h] for h in REAL]


def _stream(data: bytes):
    return mc.text_stream(io.BytesIO(data))


def _read(data: bytes, kind: str = "subscribed"):
    stream = _stream(data)
    header = mc.read_header(stream)
    return header, list(mc.read_rows(stream, header, kind))


def _header(*names: str) -> mc.Header:
    return mc.read_header(_stream(csv_bytes(names, [])))


@pytest.mark.parametrize(
    ("name", "columns", "kind"),
    [
        ("subscribed_members_export_ab12.csv", ["Email Address"], "subscribed"),
        ("unsubscribed_members_export_x.csv", ["Email Address"], "unsubscribed"),
        ("cleaned_email_audience_export_x.csv", ["Email Address"], "cleaned"),
        ("nonsubscribed_members_export_x.csv", ["Email Address"], "ignored"),
        ("list.csv", ["Email Address", "UNSUB_TIME"], "unsubscribed"),
        ("list.csv", ["Email Address", "CLEAN_TIME"], "cleaned"),
        ("list.csv", ["Email Address"], "subscribed"),
    ],
)
def test_detect_kind_by_name_then_columns(name, columns, kind):
    assert mc.detect_kind(name, _header(*columns)) == kind


def test_standard_export_row():
    data = csv_bytes(REAL, [_row("  Ada@Example.COM ", '"VIP","Customers, 2020"')])
    header, rows = _read(data)
    assert header.delimiter == ","
    assert [header.names[i] for i in header.mappable] == ["First Name", "Last Name"]
    assert header.tags == REAL.index("TAGS")
    assert header.times["confirm"] == REAL.index("CONFIRM_TIME")
    (row,) = rows
    assert isinstance(row, mc.Parsed)
    assert row.line == 2
    assert row.email == "ada@example.com"
    assert row.tags == ["VIP", "Customers, 2020"]
    assert row.event_at == datetime(2020, 1, 3, 4, 5, 6, tzinfo=UTC)
    assert row.consent_at == datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert row.fields == {1: "Ada", 2: "L"}


def test_event_at_by_kind():
    data = csv_bytes(
        ["Email Address", "OPTIN_TIME", "UNSUB_TIME"],
        [["a@example.com", "2020-01-02 03:04:05", "2021-05-06 07:08:09"]],
    )
    _, (sub,) = _read(data, "subscribed")
    _, (uns,) = _read(data, "unsubscribed")
    assert sub.event_at == datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert uns.event_at == datetime(2021, 5, 6, 7, 8, 9, tzinfo=UTC)


def test_semicolon_bom_german_headers():
    data = csv_bytes(
        ["E-Mail-Adresse", "Vorname", "Nachname", "TAGS"],
        [["a@example.com", "Ada", "L", ""]],
        delimiter=";",
        bom=True,
    )
    header, rows = _read(data)
    assert header.email == 0
    assert header.delimiter == ";"
    assert header.names[0] == "E-Mail-Adresse"
    assert rows[0].email == "a@example.com"


def test_tag_rules():
    assert mc.parse_tags("") == ([], False)
    assert mc.parse_tags("VIP,,x") == (["VIP", "x"], True)
    assert mc.parse_tags('VIP,"a\x01b"') == (["VIP"], True)
    assert mc.parse_tags("t" * 101) == ([], True)
    labels, dropped = mc.parse_tags(",".join(f"t{i}" for i in range(51)))
    assert len(labels) == 50
    assert dropped
    assert mc.parse_tags(",".join(f"t{i}" for i in range(50)))[1] is False
    assert mc.parse_tags("t" * 100) == (["t" * 100], False)


def test_tag_values_distinct_and_deterministic():
    labels = ["Customers, 2020", "Customers; 2020", "VIP"]
    values = mc.tag_values(labels, [])
    assert values["VIP"] == "VIP"
    assert values["Customers, 2020"] != values["Customers; 2020"]
    assert all("," not in v for v in values.values())
    assert mc.tag_values(labels, []) == values
    assert mc.tag_values(list(reversed(labels)), []) == values


def test_tag_values_collision_with_existing_choice():
    taken = [FieldChoice(value="VIP", label="Very important")]
    assert mc.tag_values(["VIP"], taken)["VIP"].startswith("vip-")
    assert mc.tag_values(["VIP"], taken)["VIP"] != "VIP"
    reused = [FieldChoice(value="v1", label="VIP")]
    assert mc.tag_values(["VIP"], reused) == {"VIP": "v1"}
    assert mc.tag_values(["!!!"], [])["!!!"].startswith("tag-") is False  # label itself, no comma


def test_tag_values_fallback_already_taken():
    """The hashed fallback is itself a value another label holds: never reused, resolved
    deterministically with a counter until free."""
    fallback = mc.tag_values(["VIP"], [FieldChoice(value="VIP", label="Very important")])["VIP"]
    taken = [
        FieldChoice(value="VIP", label="Very important"),
        FieldChoice(value=fallback, label="Someone else"),
    ]
    values = mc.tag_values(["VIP"], taken)
    assert values["VIP"] not in {c.value for c in taken}
    assert values == {"VIP": f"{fallback}-2"}
    taken.append(FieldChoice(value=f"{fallback}-2", label="A third"))
    assert mc.tag_values(["VIP"], taken) == {"VIP": f"{fallback}-3"}
    assert (
        len(mc.tag_values(["x" * 100], [FieldChoice(value="x" * 100, label="y")])["x" * 100]) <= 100
    )


def test_tag_values_empty_slug():
    assert mc.tag_values(["a,"], [])["a,"].startswith("a-")
    assert mc.tag_values([",,"], [])[",,"].startswith("tag-")


def test_time_parse():
    assert mc.parse_time("2020-01-02 03:04:05") == datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    for bad in ("", "yesterday", "2020-13-40 00:00:00"):
        assert mc.parse_time(bad) is None


def test_invalid_email_is_a_row_error_without_value():
    data = csv_bytes(["Email Address"], [["ok@example.com"], ["secret-not-an-address"]])
    _, rows = _read(data)
    error = rows[1]
    assert error == mc.RowError(line=3, code="invalid_email", field=None)
    assert "secret-not-an-address" not in repr(error)


def test_cell_too_long_drops_cell_keeps_row():
    long = "x" * (MAX_CELL + 1)
    data = csv_bytes(["Email Address", "First Name"], [["a@example.com", long]])
    _, rows = _read(data)
    assert rows[0] == mc.RowError(line=2, code="cell_too_long", field="first name")
    assert isinstance(rows[1], mc.Parsed)
    assert rows[1].fields == {}


def test_a_cell_of_exactly_max_cell_is_kept():
    data = csv_bytes(["Email Address", "First Name"], [["a@example.com", "x" * MAX_CELL]])
    _, rows = _read(data)
    assert [type(r) for r in rows] == [mc.Parsed]
    assert list(rows[0].fields.values()) == ["x" * MAX_CELL]


def test_max_columns_exactly_is_accepted():
    header = ["Email Address", *[f"c{i}" for i in range(MAX_COLUMNS - 1)]]
    _read(csv_bytes(header, []))


def test_long_email_cell_is_invalid_email():
    data = csv_bytes(["Email Address"], [["a" * MAX_CELL + "@example.com"]])
    _, rows = _read(data)
    assert rows == [mc.RowError(line=2, code="invalid_email")]


def test_tag_problems_flag_the_row():
    data = csv_bytes(["Email Address", "TAGS"], [["a@example.com", "VIP,,"]])
    _, rows = _read(data)
    assert mc.RowError(line=2, code="tag_invalid", field="tags") in rows
    assert next(r for r in rows if isinstance(r, mc.Parsed)).tags == ["VIP"]


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"", ImportEmptyFile),
        (csv_bytes(["Name", "Phone"], [["secret", "1"]]), ImportNoEmailColumn),
        (csv_bytes(["Email Address", *[f"c{i}" for i in range(200)]], []), ImportTooManyColumns),
        (csv_bytes(["Email Address"], [["a@example.com"]]) + b"\xff\xfe\n", ImportNotUtf8),
        (csv_bytes(["Email Address"], [["a@example.com"]]) + b"secret\x00,x\n", ImportMalformedCsv),
    ],
)
def test_parse_refusals(data, error):
    with pytest.raises(error) as caught:
        _read(data)
    assert "secret" not in caught.value.detail
    if error in (ImportNotUtf8, ImportMalformedCsv):
        assert "line 3" in caught.value.detail
