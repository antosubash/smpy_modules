from __future__ import annotations

from datetime import UTC, datetime

from pagebuilder.models import Page, PageStatus
from pagebuilder.snapshots.pages import PAGE_FIELDS, apply_payload, page_to_payload


def _page() -> Page:
    return Page(
        slug="about",
        title="About",
        status=PageStatus.PUBLISHED,
        draft_data={"content": [1]},
        published_data={"content": [2]},
        meta_title="About us",
        index_in_search=False,
        show_in_header_nav=True,
        publish_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_payload_carries_every_authored_field_and_the_parent_slug():
    payload = page_to_payload(_page(), parent_slug="home")
    assert payload["slug"] == "about"
    assert payload["status"] == "published"
    assert payload["draft_data"] == {"content": [1]}
    assert payload["published_data"] == {"content": [2]}
    assert payload["parent_slug"] == "home"
    assert payload["meta_title"] == "About us"
    assert payload["index_in_search"] is False
    assert payload["show_in_header_nav"] is True
    assert payload["publish_at"] == "2026-01-01T00:00:00+00:00"
    assert payload["unpublish_at"] is None


def test_payload_omits_host_local_and_workflow_columns():
    payload = page_to_payload(_page(), parent_slug=None)
    for absent in ("id", "parent_id", "deleted_at", "rejection_note", "created_at"):
        assert absent not in payload


def test_apply_payload_round_trips_without_touching_parent_id():
    payload = page_to_payload(_page(), parent_slug="home")
    target = Page(slug="about", title="stale")
    target.parent_id = 42
    apply_payload(target, payload)
    assert target.title == "About"
    assert target.status is PageStatus.PUBLISHED
    assert target.published_data == {"content": [2]}
    assert target.publish_at == datetime(2026, 1, 1, tzinfo=UTC)
    # The second pass owns parenting; pass one must not clear it.
    assert target.parent_id == 42


def test_apply_payload_clears_a_schedule_the_bundle_does_not_have():
    target = Page(slug="about", title="About", publish_at=datetime(2026, 1, 1, tzinfo=UTC))
    apply_payload(target, page_to_payload(Page(slug="about", title="About"), None))
    assert target.publish_at is None


def test_page_fields_are_real_columns():
    # A typo here would silently drop content from every bundle.
    for field in PAGE_FIELDS:
        assert hasattr(Page, field), field
