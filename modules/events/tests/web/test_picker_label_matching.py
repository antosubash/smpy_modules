"""Email text embedded in a display name must not become a search oracle."""

import pytest
from sm_events.web.services.masking import matches_query


@pytest.mark.parametrize("query", ["nina@exa", "ina@exam", "example.com"])
def test_email_tokens_in_display_name_are_not_searchable(query):
    assert not matches_query("Nina <nina@example.com>", "nina@example.com", query)
