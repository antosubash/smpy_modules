from __future__ import annotations

import csv
import io

import pytest
from sm_newsletter.imports.csv_safe import HEADER, errors_csv, neutralise
from sm_newsletter.models import ImportJob


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_every_trigger_is_prefixed(lead):
    assert neutralise(f"{lead}cmd") == f"'{lead}cmd"


@pytest.mark.parametrize("cell", ["", "plain", "a=b", "x@y", " =lead-space", "'quoted", "12"])
def test_safe_cells_are_unchanged(cell):
    assert neutralise(cell) == cell


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
