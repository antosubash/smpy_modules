"""The reminder bounds: one place, consistent with each other."""

from __future__ import annotations

from datetime import timedelta

from sm_events.core.constants import reminders_limits as limits


def test_catchup_covers_every_lead():
    assert set(limits.REMINDER_CATCHUP) == set(limits.REMINDER_LEADS)
    for lead, catchup in limits.REMINDER_CATCHUP.items():
        assert catchup < timedelta(minutes=lead), lead


def test_leads_are_a_sorted_closed_set():
    assert limits.REMINDER_LEADS == (15, 60, 1440, 10080)
    assert max(limits.REMINDER_LEADS) == limits.MAX_LEAD_MINUTES
    assert list(limits.REMINDER_LEADS) == sorted(set(limits.REMINDER_LEADS))


def test_budgets_consistent():
    assert limits.REMINDER_TENANT_BUDGET <= limits.REMINDER_SEND_BUDGET
    assert limits.REMINDER_SEND_TIMEOUT < limits.REMINDER_UNFINISHED_AFTER
    assert limits.REMINDER_CLAIM_LEASE < limits.REMINDER_UNFINISHED_AFTER


def test_window_is_at_most_six_hours_and_a_minute():
    widest = max(limits.REMINDER_CATCHUP.values()) + limits.REMINDER_EARLY
    assert widest <= timedelta(hours=6, minutes=1)


def test_follow_bounds():
    assert limits.FOLLOWS_PER_USER == 200
    assert limits.FOLLOW_RATE == "30/minute"


def test_constants_name_the_states_and_codes():
    from sm_events.core import constants

    assert constants.REMINDER_STATES == ("claimed", "sending", "sent", "failed")
    assert constants.REMINDER_SEND_FAILED == "send_failed"
    assert constants.REMINDER_CODE_SEND_TIMEOUT == "send_timeout"
    assert constants.AVAILABILITY_REASONS == (
        "disabled",
        "no_public_base_url",
        "no_mail_transport",
        "console_mail",
    )
    assert constants.REMINDERS_URL == "/admin/events/reminders"
    assert constants._PAGE_REMINDERS == "Events/Reminders"
    assert constants.MENU_ICON_REMINDERS == "bell"
