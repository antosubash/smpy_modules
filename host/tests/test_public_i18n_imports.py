"""Bounded import guard for the known anonymous frontend entries of admin catalogues.

AI, analytics and billing have no anonymous React surface. Newsletter's unsubscribe
page is server-rendered Python; its confirmation page belongs to records. Events'
shared console/public components must resolve through PageLocale, never bypass it.
This follows local static and literal lazy imports, not third-party packages or globs.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "modules"
PACKAGES = {"ai": "sm_ai", "analytics": "sm_analytics", "billing": "sm_billing",
            "events": "sm_events", "newsletter": "sm_newsletter"}
PUBLIC_ENTRIES = {
    "events": (
        "pages/PublicIndex.tsx", "pages/PublicEvent.tsx", "pages/PublicNotFound.tsx",
        "ui/blocks/UpcomingEventsRender.tsx", "ui/blocks/EventsCalendarRender.tsx",
    ),
}
IMPORT = re.compile(r'''(?:from\s*|import\s*\(\s*|import\s*)['"](\.[^'"]+)['"]''')


def reachable(entry):
    pending, seen = [entry], set()
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        source = path.read_text()
        yield path, source
        for specifier in IMPORT.findall(source):
            base = path.parent / specifier
            candidates = [base, Path(f"{base}.ts"), Path(f"{base}.tsx"),
                          base / "index.ts", base / "index.tsx"]
            match = next((p for p in candidates if p.is_file()), None)
            assert match is not None, f"unresolved local import {specifier} in {path}"
            if match.suffix in {".ts", ".tsx"}:
                pending.append(match)


@pytest.mark.parametrize("name", PACKAGES)
def test_new_public_pages_require_an_audience_audit(name):
    package = ROOT / name / PACKAGES[name]
    known = {p for p in PUBLIC_ENTRIES.get(name, ()) if p.startswith("pages/")}
    found = {str(p.relative_to(package)) for p in (package / "pages").glob("Public*.tsx")}
    assert found == known


@pytest.mark.parametrize("entry", PUBLIC_ENTRIES["events"])
def test_public_events_cannot_bypass_their_own_catalogue(entry):
    package = ROOT / "events" / PACKAGES["events"]
    source = (package / entry).read_text()
    assert "<PageLocale locale=" in source, f"{entry} needs its own catalogue provider"
    adapter = package / "ui/utils/i18n.ts"
    for path, source in reachable(package / entry):
        if path == adapter:
            # The dual-use hook chooses PageCatalogueContext on public pages.
            # PublicLocale.test.tsx verifies this with an empty shared catalogue.
            continue
        assert "@simple-module-py/i18n" not in source, path
        # Non-hook translation bypasses React's PageLocale context.
        assert not re.search(r"\btranslate\s*(?:\(|[,}])", source), path
