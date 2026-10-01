"""Every rule in ``schema.diff``, one test apiece. Design doc §8.2.

Pure and databaseless on purpose: the classifier is what the dry run, the
refusal and the reindex all key off, and it has to be decidable from two field
lists alone. A rule that is only checked through an HTTP test is a rule whose
counterexample is expensive to write down.

Both sides go through ``validate_fields`` first, exactly as the service does —
diffing raw input against the normalised stored form would report changes
nobody made (``unique`` implying ``indexed``, a defaulted ``on_delete``).
"""

from __future__ import annotations

from sm_records.schema.diff import diff_fields
from sm_records.schema.fields import validate_fields
from sm_records.schema.types import ChangeClass

from tests.schema_helpers import CHOICES, field

ADDITIVE = ChangeClass.ADDITIVE
INDEXING = ChangeClass.INDEX_AFFECTING
RESTRICTIVE = ChangeClass.RESTRICTIVE
DESTRUCTIVE = ChangeClass.DESTRUCTIVE


def diff(before: list[dict], after: list[dict]):
    return diff_fields(validate_fields(before), validate_fields(after))


def kinds(result, what: str) -> list[ChangeClass]:
    return [c.kind for c in result.changes if c.what == what]


def whats(result) -> list[str]:
    return [c.what for c in result.changes]


NAME = field("name", "text")
PRICE = field("price", "number")


def test_an_identical_list_is_no_change():
    assert diff([NAME, PRICE], [NAME, PRICE]).changes == ()


def test_reordering_alone_is_no_change():
    """The order of ``fields`` is presentation — the form's field order — and
    matching is by key, so moving one is not a schema change at all."""
    assert diff([NAME, PRICE], [PRICE, NAME]).changes == ()


def test_an_optional_field_added_is_additive():
    result = diff([NAME], [NAME, PRICE])
    assert kinds(result, "field_added") == [ADDITIVE]
    assert result.kind is ADDITIVE


def test_a_required_field_added_without_a_default_is_restrictive():
    """Every record that exists is missing the key, so it reads as ``None``
    and every one of them is invalid at once."""
    added = {**field("sku", "text"), "required": True}
    assert kinds(diff([NAME], [NAME, added]), "field_added") == [RESTRICTIVE]


def test_a_required_field_added_with_a_default_is_additive():
    added = {**field("sku", "text"), "required": True, "default": "none"}
    assert kinds(diff([NAME], [NAME, added]), "field_added") == [ADDITIVE]


def test_an_indexed_field_added_is_also_index_affecting():
    added = {**field("sku", "text"), "indexed": True}
    result = diff([NAME], [NAME, added])
    assert whats(result) == ["field_added", "indexed_on"]
    assert kinds(result, "indexed_on") == [INDEXING]
    assert result.keys(INDEXING) == ("sku",)


def test_a_removed_field_is_destructive_and_index_affecting():
    """Destructive because the field stops existing; index-affecting because
    its rows are derived from a definition that is gone and have to follow."""
    result = diff([NAME, PRICE], [NAME])
    assert whats(result) == ["field_removed", "indexed_off"]
    assert result.kind is DESTRUCTIVE
    assert result.keys(INDEXING) == ("price",)


def test_a_type_change_is_restrictive_and_moves_the_index():
    result = diff([field("price", "text", indexed=True)], [field("price", "number", indexed=True)])
    assert kinds(result, "type_changed") == [RESTRICTIVE, INDEXING]
    assert result.keys(INDEXING) == ("price",)


def test_a_type_change_on_an_unindexed_field_only_affects_validation():
    before = field("price", "text", indexed=False)
    after = field("price", "number", indexed=False)
    result = diff([before], [after])
    assert kinds(result, "type_changed") == [RESTRICTIVE]
    assert result.keys(INDEXING) == ()


def test_required_added_and_removed():
    required = {**NAME, "required": True}
    assert kinds(diff([NAME], [required]), "required_added") == [RESTRICTIVE]
    assert kinds(diff([required], [NAME]), "required_removed") == [ADDITIVE]


def test_required_added_with_a_default_is_additive():
    assert kinds(diff([NAME], [{**NAME, "required": True, "default": "x"}]), "required_added") == [
        ADDITIVE
    ]


def test_unique_added_is_restrictive_and_removed_is_additive():
    """Nothing checked the existing values for duplicates until now (§7.8)."""
    unique = {**NAME, "unique": True}
    added = diff([NAME], [unique])
    assert kinds(added, "unique_added") == [RESTRICTIVE]
    # ``unique`` normalises to ``indexed``, so it is an index change too.
    assert kinds(added, "indexed_on") == [INDEXING]
    assert kinds(diff([unique], [NAME]), "unique_removed") == [ADDITIVE]


def test_indexed_toggled_either_way_is_index_affecting():
    on = field("name", "text", indexed=True)
    off = field("name", "text", indexed=False)
    assert kinds(diff([off], [on]), "indexed_on") == [INDEXING]
    assert kinds(diff([on], [off]), "indexed_off") == [INDEXING]


def constrained(**constraints) -> dict:
    return {**field("name", "text"), "constraints": constraints}


def test_a_raised_minimum_length_is_tightened_and_a_lowered_one_relaxed():
    assert kinds(
        diff([constrained(min_length=2)], [constrained(min_length=5)]), "constraint_tightened"
    ) == [RESTRICTIVE]
    assert kinds(
        diff([constrained(min_length=5)], [constrained(min_length=2)]), "constraint_relaxed"
    ) == [ADDITIVE]


def test_an_added_maximum_length_is_tightened_and_a_dropped_one_relaxed():
    """``None`` is the unbounded end: adding a ceiling narrows, dropping it
    widens, whatever the numbers on either side are."""
    assert kinds(diff([constrained()], [constrained(max_length=10)]), "constraint_tightened") == [
        RESTRICTIVE
    ]
    assert kinds(diff([constrained(max_length=10)], [constrained()]), "constraint_relaxed") == [
        ADDITIVE
    ]


def test_numeric_bounds_follow_the_same_rule():
    def numeric(**constraints):
        return {**field("price", "number"), "constraints": constraints}

    assert kinds(diff([numeric(min=0)], [numeric(min=5)]), "constraint_tightened") == [RESTRICTIVE]
    assert kinds(diff([numeric(max=100)], [numeric(max=10)]), "constraint_tightened") == [
        RESTRICTIVE
    ]
    assert kinds(diff([numeric(max=10)], [numeric(max=100)]), "constraint_relaxed") == [ADDITIVE]


def test_a_pattern_added_or_changed_is_tightened_and_removing_it_relaxes():
    """A changed pattern is classified tightened rather than merely changed:
    it can refuse values the old one accepted, and only the dry run can say."""
    none, first, second = constrained(), constrained(pattern="^a"), constrained(pattern="^b")
    assert kinds(diff([none], [first]), "constraint_tightened") == [RESTRICTIVE]
    assert kinds(diff([first], [second]), "constraint_tightened") == [RESTRICTIVE]
    assert kinds(diff([first], [none]), "constraint_relaxed") == [ADDITIVE]


def select_field(*choices: tuple[str, str]) -> dict:
    return {
        **field("kind", "select"),
        "options": {"choices": [{"value": v, "label": la} for v, la in choices]},
    }


def test_a_removed_choice_is_restrictive_and_an_added_one_additive():
    both = select_field(("a", "A"), ("b", "B"))
    one = select_field(("a", "A"))
    removed = diff([both], [one])
    assert kinds(removed, "choice_removed") == [RESTRICTIVE]
    assert removed.changes[0].before == ["b"]
    assert kinds(diff([one], [both]), "choice_added") == [ADDITIVE]


def test_a_relabelled_choice_is_additive():
    """The payload stores the *value*, so renaming its label touches nothing
    that is stored."""
    result = diff([select_field(("a", "A"))], [select_field(("a", "Apple"))])
    assert kinds(result, "options_changed") == [ADDITIVE]


def test_a_multiselect_uses_the_same_choice_rules():
    before = {**field("tags", "multiselect"), "options": dict(CHOICES)}
    after = {
        **field("tags", "multiselect"),
        "options": {"choices": [CHOICES["choices"][0]]},
    }
    assert kinds(diff([before], [after]), "choice_removed") == [RESTRICTIVE]


def relation(target: str = "author", **options) -> dict:
    return {**field("by", "relation"), "options": {"target_type": target, **options}}


def test_a_retargeted_relation_is_restrictive():
    result = diff([relation("author")], [relation("editor")])
    assert kinds(result, "options_changed") == [RESTRICTIVE]
    assert result.changes[0].after == {"target_type": "editor"}


def test_changing_many_is_restrictive_because_the_stored_shape_changes():
    assert kinds(diff([relation()], [relation(many=True)]), "options_changed") == [RESTRICTIVE]


def test_changing_on_delete_is_additive():
    """It only decides what a future delete does; nothing stored changes."""
    assert kinds(diff([relation()], [relation(on_delete="set_null")]), "options_changed") == [
        ADDITIVE
    ]


def test_label_help_and_default_changes_are_additive():
    before = {**NAME, "label": "Name", "help": None, "default": None}
    after = {**NAME, "label": "Full name", "help": "As printed", "default": "anon"}
    result = diff([before], [after])
    assert kinds(result, "label_changed") == [ADDITIVE]
    assert result.changes[0].after["label"] == "Full name"


def test_the_diff_takes_the_most_severe_class_and_lists_its_keys():
    """``SchemaDiff.kind`` is what the API reports as "what kind of change is
    this", and one destructive change in a batch of cosmetic ones decides it."""
    before = [NAME, PRICE, field("sku", "text")]
    after = [{**NAME, "label": "Renamed"}, PRICE]
    result = diff(before, after)
    assert result.kind is DESTRUCTIVE
    assert result.keys(DESTRUCTIVE) == ("sku",)
    assert set(result.keys(ADDITIVE, DESTRUCTIVE)) == {"name", "sku"}
