import pytest
from sm_newsletter.segments.rules import (
    MAX_RULES,
    Rule,
    RuleError,
    compile_rules,
    ops_for,
    segment_fields,
)
from sm_records.contracts.newsletter_admin import FieldChoice, ListField

FILTER_OPS = {"eq", "ne", "in", "contains", "starts_with", "gt", "gte", "lt", "lte"}


def _f(key, type_, many=False, choices=(), system=False):
    return ListField(
        key=key,
        label=key,
        type=type_,
        many=many,
        choices=[FieldChoice(value=c, label=c) for c in choices],
        system=system,
    )


FIELDS = segment_fields(
    [
        _f("tags", "multiselect", many=True, choices=("a", "b", "c")),
        _f("plan", "select", choices=("free", "pro")),
        _f("city", "text"),
        _f("sm_email", "email", system=True),
        _f("age", "integer"),
        _f("vip", "boolean"),
        _f("born", "date"),
        _f("sm_status", "select", choices=("pending", "confirmed"), system=True),
    ]
)


def _c(field, op, value):
    return compile_rules([Rule(field=field, op=op, value=value)], FIELDS)


@pytest.mark.parametrize(
    ("field", "op", "value", "expected"),
    [
        ("tags", "any", ["a", "b"], ["tags:in:a,b"]),
        ("tags", "all", ["a", "b"], ["tags:eq:a", "tags:eq:b"]),
        ("tags", "none", ["a", "b"], ["tags:ne:a", "tags:ne:b"]),
        ("plan", "is", "free", ["plan:eq:free"]),
        ("plan", "is_not", "free", ["plan:ne:free"]),
        ("plan", "any", ["free", "pro"], ["plan:in:free,pro"]),
        ("city", "is", "Oslo", ["city:eq:Oslo"]),
        ("city", "is_not", "Oslo", ["city:ne:Oslo"]),
        ("city", "contains", "slo", ["city:contains:slo"]),
        ("city", "starts_with", "Os", ["city:starts_with:Os"]),
        ("sm_email", "contains", "x.com", ["sm_email:contains:x.com"]),
        ("age", "is", "30", ["age:eq:30"]),
        ("age", "is_not", "30", ["age:ne:30"]),
        ("age", "gt", "30", ["age:gt:30"]),
        ("age", "gte", "30", ["age:gte:30"]),
        ("age", "lt", "30", ["age:lt:30"]),
        ("age", "lte", "30", ["age:lte:30"]),
        ("vip", "is", "true", ["vip:eq:true"]),
        ("vip", "is", "false", ["vip:eq:false"]),
        ("born", "before", "2026-01-01", ["born:lt:2026-01-01"]),
        ("born", "since", "2026-01-01", ["born:gte:2026-01-01"]),
        ("created_at", "before", "2026-01-01", ["created_at:lt:2026-01-01T00:00:00+00:00"]),
        ("created_at", "since", "2026-01-01", ["created_at:gte:2026-01-01T00:00:00+00:00"]),
    ],
)
def test_compile_table(field, op, value, expected):
    terms = _c(field, op, value)
    assert terms == expected
    assert all(t.split(":", 2)[1] in FILTER_OPS for t in terms)


def test_rules_are_anded_in_order():
    rules = [
        Rule(field="plan", op="is", value="pro"),
        Rule(field="age", op="gt", value="3"),
    ]
    assert compile_rules(rules, FIELDS) == ["plan:eq:pro", "age:gt:3"]


@pytest.mark.parametrize(
    ("rules", "secret"),
    [
        ([Rule(field="nope", op="is", value="zzsecret")], "zzsecret"),
        ([Rule(field="sm_status", op="is", value="pending")], "pending"),
        ([Rule(field="tags", op="contains", value="zzsecret")], "zzsecret"),
        ([Rule(field="plan", op="is", value="zzsecret")], "zzsecret"),
        ([Rule(field="tags", op="any", value=["a", "zz,secret"])], "zz,secret"),
        ([Rule(field="age", op="is", value="abc")], "abc"),
        ([Rule(field="age", op="is", value="inf")], "inf"),
        ([Rule(field="born", op="before", value="2026-02-30")], "2026-02-30"),
        ([Rule(field="city", op="is", value="x")] * (MAX_RULES + 1), "zzsecret"),
        ([Rule(field="tags", op="all", value=["a"] * 21)], "zzsecret"),
        ([Rule(field="city", op="is", value="")], "zzsecret"),
        ([Rule(field="city", op="is", value="a\x00zzsecret")], "zzsecret"),
        ([Rule(field="city", op="is", value="a\nzzsecret")], "zzsecret"),
        ([Rule(field="city", op="is", value=["x"])], "zzsecret"),
        ([Rule(field="tags", op="any", value="a")], "zzsecret"),
        ([Rule(field="vip", op="is", value="yes")], "yes"),
    ],
)
def test_refusals(rules, secret):
    with pytest.raises(RuleError) as exc:
        compile_rules(rules, FIELDS)
    msg = str(exc.value)
    assert msg.startswith("rules[")
    assert secret not in msg


def test_refusal_index_is_the_bad_rule():
    rules = [Rule(field="plan", op="is", value="pro"), Rule(field="nope", op="is", value="x")]
    with pytest.raises(RuleError, match=r"^rules\[1\]: "):
        compile_rules(rules, FIELDS)


def test_term_cap():
    rules = [Rule(field="tags", op="all", value=["a", "b", "c", "a", "b", "c"])] * 4
    with pytest.raises(RuleError):
        compile_rules(rules, FIELDS)


def test_email_is_lowercased():
    assert _c("sm_email", "is", "Ann@Example.COM") == ["sm_email:eq:ann@example.com"]


def test_segment_fields_drops_and_adds():
    assert "sm_status" not in FIELDS
    assert FIELDS["created_at"].type == "datetime"
    assert FIELDS["created_at"].system is True
    assert segment_fields([_f("body", "longtext"), _f("j", "json")]).keys() == {"created_at"}


def test_ops_for_matches_table():
    assert ops_for(FIELDS["tags"]) == ("any", "all", "none")
    assert ops_for(FIELDS["plan"]) == ("is", "is_not", "any")
    assert ops_for(FIELDS["city"]) == ("is", "is_not", "contains", "starts_with")
    assert ops_for(FIELDS["age"]) == ("is", "is_not", "gt", "gte", "lt", "lte")
    assert ops_for(FIELDS["vip"]) == ("is",)
    assert ops_for(FIELDS["born"]) == ("before", "since")
    assert ops_for(FIELDS["created_at"]) == ("before", "since")


def test_value_colons_survive():
    assert _c("city", "is", "a:b") == ["city:eq:a:b"]
