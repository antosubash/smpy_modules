"""Per-field-type coercion — every type's valid value, invalid value, and the
constraints it accepts. Pure, no database.

Split from ``test_schema_compile.py`` only for the 300-line cap; the two
halves are one suite over ``schema/_builders.py`` and ``schema/compile.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from .schema_helpers import CHOICES, UUID_A, UUID_B, check, field, refuses


class TestTextLike:
    def test_text_round_trips(self):
        assert check(field("title", "text"), "hello") == "hello"

    def test_text_refuses_a_non_string(self):
        refuses(field("title", "text"), 5)

    def test_text_constraints_are_applied(self):
        definition = field("title", "text", constraints={"min_length": 2, "max_length": 4})
        assert check(definition, "abc") == "abc"
        refuses(definition, "a")
        refuses(definition, "abcde")

    def test_text_pattern_is_applied(self):
        definition = field("code", "text", constraints={"pattern": "^[a-z]+$"})
        assert check(definition, "abc") == "abc"
        refuses(definition, "AB1")

    def test_longtext_accepts_a_long_string(self):
        assert check(field("body", "longtext"), "x" * 10_000) == "x" * 10_000

    @pytest.mark.parametrize("value", ["a@b.com", "first.last@sub.example.co.uk"])
    def test_email_accepts(self, value):
        assert check(field("mail", "email"), value) == value

    @pytest.mark.parametrize("value", ["a@b", "nope", "a b@c.com", "@b.com"])
    def test_email_refuses(self, value):
        refuses(field("mail", "email"), value)

    @pytest.mark.parametrize("value", ["https://x.com", "http://x.com/a?b=1"])
    def test_url_accepts_http_and_https(self, value):
        assert check(field("site", "url"), value) == value

    @pytest.mark.parametrize("value", ["ftp://x.com", "x.com", "javascript:alert(1)", "https://"])
    def test_url_refuses_anything_else(self, value):
        refuses(field("site", "url"), value)

    def test_media_is_capped(self):
        assert check(field("pic", "media"), "a" * 500) == "a" * 500
        refuses(field("pic", "media"), "a" * 501)


class TestNumbers:
    def test_number_accepts_five_decimal_places(self):
        assert check(field("price", "number"), "1.23456") == Decimal("1.23456")

    def test_number_refuses_six_decimal_places(self):
        # The index column is Numeric(19, 5); storing this would put the
        # payload and the index out of step. Design §7.3.
        refuses(field("price", "number"), "1.234567")

    def test_number_coerces_a_string(self):
        assert check(field("price", "number"), "123") == Decimal("123")

    def test_number_coerces_int_and_float(self):
        assert check(field("price", "number"), 5) == Decimal("5")
        assert check(field("price", "number"), 0.1) == Decimal("0.1")

    def test_number_refuses_a_boolean(self):
        refuses(field("price", "number"), True)

    def test_number_refuses_too_many_integer_digits(self):
        refuses(field("price", "number"), "1" * 15)
        assert check(field("price", "number"), "1" * 14) == Decimal("1" * 14)

    def test_number_range(self):
        definition = field("price", "number", constraints={"min": 0, "max": 10})
        assert check(definition, "10") == Decimal("10")
        refuses(definition, "-1")
        refuses(definition, "10.1")

    def test_integer_accepts_an_exact_string(self):
        assert check(field("qty", "integer"), "3") == 3

    def test_integer_refuses_a_fractional_value(self):
        refuses(field("qty", "integer"), 1.5)
        refuses(field("qty", "integer"), "1.5")

    def test_integer_accepts_a_whole_float(self):
        assert check(field("qty", "integer"), 2.0) == 2

    def test_integer_refuses_a_boolean(self):
        refuses(field("qty", "integer"), True)

    def test_integer_range(self):
        definition = field("qty", "integer", constraints={"min": 1, "max": 3})
        assert check(definition, 3) == 3
        refuses(definition, 0)
        refuses(definition, 4)


class TestBooleanAndTemporal:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(True, True), (False, False), (1, True), (0, False), ("true", True), ("False", False)],
    )
    def test_boolean_accepts(self, value, expected):
        assert check(field("live", "boolean"), value) is expected

    @pytest.mark.parametrize("value", ["yes", "no", "on", 2, "1"])
    def test_boolean_refuses_anything_looser(self, value):
        refuses(field("live", "boolean"), value)

    def test_date_accepts_iso_and_date(self):
        assert check(field("d", "date"), "2026-09-19") == date(2026, 9, 19)
        assert check(field("d", "date"), date(2026, 9, 19)) == date(2026, 9, 19)

    def test_date_refuses_a_datetime(self):
        # A calendar date stored as a tz-aware midnight changes meaning with
        # the connection timezone — design §7.3.
        refuses(field("d", "date"), datetime(2026, 9, 19, tzinfo=UTC))
        refuses(field("d", "date"), "2026-09-19T00:00:00Z")

    def test_datetime_requires_an_offset(self):
        aware = datetime(2026, 9, 19, 12, tzinfo=UTC)
        assert check(field("dt", "datetime"), aware) == aware
        east = datetime(2026, 9, 19, 12, tzinfo=timezone(timedelta(hours=2)))
        assert check(field("dt", "datetime"), "2026-09-19T12:00:00+02:00") == east

    def test_datetime_refuses_a_naive_input(self):
        refuses(field("dt", "datetime"), datetime(2026, 9, 19, 12))
        refuses(field("dt", "datetime"), "2026-09-19T12:00:00")


class TestChoicesAndStructures:
    def test_select_enforces_the_choice_set(self):
        definition = field("cat", "select", options=CHOICES)
        assert check(definition, "a") == "a"
        refuses(definition, "z")

    def test_multiselect_enforces_the_choice_set(self):
        definition = field("tags", "multiselect", options=CHOICES)
        assert check(definition, ["a", "b"]) == ["a", "b"]
        refuses(definition, ["a", "z"])

    def test_multiselect_refuses_duplicates(self):
        refuses(field("tags", "multiselect", options=CHOICES), ["a", "a"])

    def test_multiselect_refuses_a_bare_string(self):
        refuses(field("tags", "multiselect", options=CHOICES), "a")

    def test_json_accepts_objects_and_arrays_only(self):
        assert check(field("blob", "json"), {"a": 1}) == {"a": 1}
        assert check(field("blob", "json"), [1, 2]) == [1, 2]
        refuses(field("blob", "json"), "scalar")
        refuses(field("blob", "json"), 3)

    def test_relation_shape(self):
        definition = field("author", "relation", options={"target_type": "person"})
        assert check(definition, {"type": "person", "uuid": UUID_A}) == {
            "type": "person",
            "uuid": UUID_A,
        }

    @pytest.mark.parametrize(
        "value",
        [
            {"type": "person"},
            {"uuid": UUID_A},
            {"type": "person", "uuid": "short"},
            {"type": "Person", "uuid": UUID_A},
            {"type": "person", "uuid": UUID_A, "label": "x"},
            UUID_A,
        ],
    )
    def test_relation_refuses_a_malformed_value(self, value):
        refuses(field("author", "relation", options={"target_type": "person"}), value)

    def test_a_many_relation_takes_a_list(self):
        definition = field("eds", "relation", options={"target_type": "person", "many": True})
        value = [{"type": "person", "uuid": UUID_A}, {"type": "person", "uuid": UUID_B}]
        assert check(definition, value) == value
        refuses(definition, {"type": "person", "uuid": UUID_A})
