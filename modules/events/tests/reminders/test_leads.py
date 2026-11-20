"""Lead times: a closed set, validated one way everywhere, effective defaults."""

from __future__ import annotations

import pytest
from sm_events.core.constants import reminders_limits as limits
from sm_events.core.errors_reminders import InvalidLead
from sm_events.core.settings import EventsSettings
from sm_events.models import Calendar
from sm_events.reminders import leads


def test_validate():
    assert leads.validate_leads([60, 15, 60]) == (15, 60)
    assert leads.validate_leads([]) == ()
    assert leads.validate_leads(iter(limits.REMINDER_LEADS)) == limits.REMINDER_LEADS
    with pytest.raises(InvalidLead):
        leads.validate_leads([30])


@pytest.mark.parametrize(
    "bad", [[0], [-15], [limits.MAX_LEAD_MINUTES + 1], [True], ["60"], [60.0], [None]]
)
def test_validate_refuses_everything_outside_the_set(bad):
    with pytest.raises(InvalidLead):
        leads.validate_leads(bad)


def test_validate_bounds_the_input_before_looking_at_it():
    """A body of a million integers is refused by length, not walked."""
    with pytest.raises(InvalidLead):
        leads.validate_leads([60] * (leads.LEADS_INPUT_MAX + 1))
    assert leads.validate_leads([60] * leads.LEADS_INPUT_MAX) == (60,)


def test_each_lead_at_the_edge_and_one_past():
    for lead in limits.REMINDER_LEADS:
        assert leads.validate_leads([lead]) == (lead,)
        with pytest.raises(InvalidLead):
            leads.validate_leads([lead + 1])
    with pytest.raises(InvalidLead):
        leads.validate_leads([min(limits.REMINDER_LEADS) - 1])


def test_duplicates_are_forgiven_everywhere():
    assert leads.validate_leads([60, 15, 60]) == (15, 60)
    assert not hasattr(leads, "validate_distinct")  # one validator, not two with two opinions


def _calendar(minutes):
    return Calendar(slug="c", name="C", owner_id="o", default_reminder_minutes=minutes)


def test_effective_prefers_calendar():
    settings = EventsSettings(default_reminder_minutes=(60,))
    assert leads.effective_defaults(settings, _calendar([15, 1440])) == (15, 1440)
    assert leads.effective_defaults(settings, _calendar(None)) == (60,)


def test_an_explicit_empty_calendar_list_is_no_preselection():
    settings = EventsSettings(default_reminder_minutes=(60,))
    assert leads.effective_defaults(settings, _calendar([])) == ()


def test_stored_garbage_dropped():
    settings = EventsSettings(default_reminder_minutes=(60, 7))
    assert leads.effective_defaults(settings, _calendar(None)) == (60,)
    assert leads.effective_defaults(settings, _calendar([7, 1440, 1440, "x", True])) == (1440,)  # type: ignore[list-item]


def test_settings_fields():
    settings = EventsSettings()
    assert settings.reminders_enabled is True
    assert settings.default_reminder_minutes == (60,)
    for name in ("reminders_enabled", "default_reminder_minutes"):
        field = EventsSettings.model_fields[name]
        assert field.description
        assert "requires_restart" not in (field.json_schema_extra or {})
