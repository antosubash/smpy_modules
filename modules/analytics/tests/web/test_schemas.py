"""Property validation is useful without a database or a running host."""

import pytest
from pydantic import ValidationError
from sm_analytics.web.schemas import PropertyIn


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("p/:slug", "Route patterns must start with /"),
        ("/" + "a" * 500, "Route patterns must be at most 500 characters"),
        ("//example.com", "Use literal path segments or :name placeholders"),
        ("/p/../secret", "Use literal path segments or :name placeholders"),
    ],
)
def test_route_errors_name_the_specific_problem(pattern, message):
    with pytest.raises(ValidationError) as caught:
        PropertyIn(name="Site", origins=["https://example.com"], route_patterns=[pattern])
    error = caught.value.errors()[0]
    assert error["loc"] == ("route_patterns",)
    assert error["msg"].removeprefix("Value error, ") == message


def test_route_validation_accepts_the_length_boundary_and_deduplicates():
    pattern = "/" + "a" * 499
    prop = PropertyIn(
        name="Site", origins=["https://example.com"], route_patterns=[pattern, pattern, "/p/:slug"]
    )
    assert prop.route_patterns == [pattern, "/p/:slug"]
