from __future__ import annotations

import csv
import io

import pytest
from sm_newsletter.imports.csv_safe import HEADER, errors_csv, neutralise, neutralise_text
from sm_newsletter.models import ImportJob


@pytest.mark.parametrize(
    "lead", ["=", "+", "-", "@", "\t", "\r", "\n", "\uff1d", "\uff0b", "\uff0d", "\uff20"]
)
def test_every_trigger_is_prefixed(lead):
    assert neutralise(f"{lead}cmd") == f"'{lead}cmd"


@pytest.mark.parametrize("cell", ["", "plain", "a=b", "x@y", "'quoted", "12"])
def test_safe_cells_are_unchanged(cell):
    assert neutralise(cell) == cell


@pytest.mark.parametrize(
    "cell", [" =1+1", "\t=1", "\uff1d1+1", "  @SUM", "\n=1", " \uff0b1", "@SUM"]
)
def test_lead_space_and_wide_triggers_are_neutralised(cell):
    assert neutralise(cell) == f"'{cell}"


def test_free_text_is_always_prefixed_unless_numeric():
    assert neutralise_text("report.csv") == "'report.csv"
    assert neutralise_text("a;=1+1") == "'a_=1+1"
    assert neutralise_text("") == ""
    assert neutralise_text("42") == "42"


def test_free_text_separators_are_replaced():
    assert neutralise_text("x;=1+1") == "'x_=1+1"
    assert neutralise_text("a\tb") == "'a_b"
    assert neutralise_text("a\r\nb") == "'a__b"


def test_file_name_with_control_separators_is_sanitised():
    job = ImportJob(
        files=[{"name": "a\tb\rc\nd.csv", "kind": "subscribed", "rows": 1}],
        errors=[{"file": 0, "line": 2, "code": "invalid_email", "field": "x;=1+1"}],
    )
    rows = list(csv.reader(io.StringIO(errors_csv(job))))
    assert rows[1][1] == "'a_b_c_d.csv"
    assert rows[1][4] == "'x_=1+1"


def test_semicolon_file_name_cannot_split_and_every_cell_is_quoted():
    job = ImportJob(
        files=[{"name": "a;=1+1.csv", "kind": "subscribed", "rows": 1}],
        errors=[{"file": 0, "line": 4, "code": "invalid_email", "field": " =x"}],
    )
    text = errors_csv(job)
    assert text.splitlines()[1] == '"0","\'a_=1+1.csv","4","invalid_email","\' =x"'
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert all(not c.lstrip('"').startswith("=") for r in rows for c in r)


def test_errors_csv_rows_and_header():
    job = ImportJob(
        files=[{"name": "=a.csv", "kind": "subscribed", "rows": 1}],
        errors=[
            {"file": 0, "line": 3, "code": "invalid_email", "field": "=HYPERLINK(x)"},
            {"file": 9, "line": None, "code": "tag_invalid", "field": None},
        ],
    )
    rows = list(csv.reader(io.StringIO(errors_csv(job))))
    assert rows[0] == list(HEADER) == ["file", "file_name", "line", "code", "field"]
    assert rows[1] == ["0", "'=a.csv", "3", "invalid_email", "'=HYPERLINK(x)"]
    assert rows[2] == ["9", "", "", "tag_invalid", ""]
    assert rows[1][2] == "3"
