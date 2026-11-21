"""The registration form and its confirmation mail speak the visitor's language: labels, and the
expiry time in the mail's language and the event's zone (never ISO)."""

from __future__ import annotations

import re

import pytest

from tests.support.registration_http import load_registration, register

pytestmark = pytest.mark.usefixtures("reg_site")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


async def test_the_form_labels_are_translated(reg_site):
    for locale, name, email in (("en", "Name", "Email"), ("de", "Name", "E-Mail")):
        got = (await load_registration(reg_site, reg_site.event, locale=locale)).json()
        labels = {f["key"]: f["label"] for f in got["definition"]["fields"]}
        assert labels["sm_name"] == name and labels["sm_email"] == email, (locale, labels)


async def test_the_expiry_is_worded_in_the_mails_language_and_the_events_zone(reg_site):
    await load_registration(reg_site, reg_site.event)
    assert (await register(reg_site, "ada@example.org", locale="de")).status_code == 202
    text = next(m for m in reg_site.outbox.sent if m.to == "ada@example.org").text
    line = next(part for part in text.splitlines() if "Dieser Link gilt bis" in part)
    assert not ISO.search(line), line  # not an ISO date
    assert re.search(r"\b(CET|CEST)\b", line), line  # the event's zone, labelled
    assert "von selbst wieder frei" not in text  # a pending registration holds no seat
