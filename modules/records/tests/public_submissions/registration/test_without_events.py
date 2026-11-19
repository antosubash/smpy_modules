"""Records without events: the kind is refused, everything else carries on."""

from __future__ import annotations

import subprocess
import sys

from sm_records.public_submissions.registration import seats

from tests.support.public_submissions_support import create
from tests.support.registration_http import registration_type
from tests.support.submissions_http import contact_type, send


def _without_events(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "sm_events", None)
    for name in [n for n in sys.modules if n.startswith("sm_events.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.delitem(sys.modules, "sm_records.integrations.events.registration", raising=False)


def test_available_with_events():
    assert seats.available() is True


def test_unavailable_without_events(monkeypatch):
    _without_events(monkeypatch)
    assert seats.available() is False


async def test_the_kind_is_refused_without_events(site, monkeypatch):
    _without_events(monkeypatch)
    resp = await registration_type(site)
    assert resp.status_code == 422 and "events_unavailable" in resp.text


async def test_forms_still_work_without_events(site, monkeypatch):
    _without_events(monkeypatch)
    assert (await create(site, "plain")).status_code == 201
    await contact_type(site)
    assert (await send(site)).status_code == 202


def test_the_extension_file_and_the_seam_import_no_events():
    code = (
        "import sys, sm_records.events_extensions, "
        "sm_records.public_submissions.registration.seats;"
        "assert 'sm_events' not in sys.modules"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
