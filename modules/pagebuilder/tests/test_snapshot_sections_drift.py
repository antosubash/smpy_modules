"""A stored bundle is held to the sections registered *now* (#80, Codex P2).

Upload validates against the registry of that moment; a restore can run under
another one. A module disabled since must not turn a required section into a
pagebuilder-only restore, and a module enabled since must not plan or apply
files its ``validate`` never saw. Plus the context path helpers, which must
never leave the section's own directory.
"""

from __future__ import annotations

import pytest
from bundle_fake import NotesSection, notes, notes_client, rezip, seed_note
from page_helpers import create_draft
from pagebuilder.contracts.bundle import (
    CaptureContext,
    RestoreContext,
    SectionCapture,
    ValidateContext,
    register_section,
)
from pagebuilder.snapshots import restore as restore_module
from pagebuilder.snapshots.files import UnsafeBundlePathError
from pagebuilder.snapshots.validate import BundleError

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_PENDING = "/api/pagebuilder/imports/pending"


def _registry(client):
    return client._transport.app.state.pagebuilder.bundle_sections


def _disable(client, name: str) -> None:
    """The host restarted without the module: its section is gone."""
    _registry(client)._sections.pop(name)


async def _take(client) -> dict:
    response = await client.post(_SNAPSHOTS, json={})
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_required_section_whose_module_left_is_refused_at_staging(tmp_path):
    section = NotesSection()
    section.required = True
    async for client in notes_client(tmp_path, section):
        await create_draft(client, slug="home", title="Home")
        snapshot = await _take(client)
        _disable(client, "notes")

        refused = await client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
        assert refused.status_code == 422
        assert "requires the 'notes' section" in refused.json()["detail"]
        assert (await client.get(_PENDING)).json() is None


async def test_a_required_section_whose_module_left_is_refused_at_approval(tmp_path):
    section = NotesSection()
    section.required = True
    async for client in notes_client(tmp_path, section):
        page = await create_draft(client, slug="home", title="Before")
        snapshot = await _take(client)
        await client.put(f"/api/pagebuilder/pages/{page['id']}", json={"title": "After"})
        staged = await client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
        assert staged.status_code == 201, staged.text
        _disable(client, "notes")

        refused = await client.post(f"/api/pagebuilder/imports/{staged.json()['id']}/approve")
        assert refused.status_code == 422
        assert "requires the 'notes' section" in refused.json()["detail"]
        # No pagebuilder-only restore: the page is as it was, the import pending.
        current = await client.get(f"/api/pagebuilder/pages/{page['id']}")
        assert current.json()["title"] == "After"
        assert (await client.get(_PENDING)).json()["id"] == staged.json()["id"]


async def _unvalidated_upload(tmp_path, client) -> int:
    """A bundle whose notes section is malformed, uploaded while notes was absent."""
    async for source in notes_client(tmp_path / "source", NotesSection()):
        await seed_note(source, "welcome", {"text": "hi"})
        taken = await _take(source)
        data = (await source.get(f"{_SNAPSHOTS}/{taken['id']}/download")).content
    bad = rezip(data, {"notes/notes.json": {"not": "a list"}})
    uploaded = await client.post(f"{_SNAPSHOTS}/upload", files={"file": ("b.zip", bad)})
    assert uploaded.status_code == 201, uploaded.text  # unknown optional: kept unread
    return uploaded.json()["id"]


async def test_a_section_enabled_after_upload_is_validated_before_staging(tmp_path):
    async for client in notes_client(tmp_path / "host", None):
        snapshot_id = await _unvalidated_upload(tmp_path, client)
        section = NotesSection()
        assert register_section(client._transport.app, section)  # the module is enabled

        refused = await client.post(f"{_SNAPSHOTS}/{snapshot_id}/restore")
        assert refused.status_code == 422
        assert "named notes" in refused.json()["detail"]
        assert [c[0] for c in section.calls] == ["validate"]


async def test_a_section_enabled_after_staging_is_validated_before_apply(tmp_path):
    async for client in notes_client(tmp_path / "host", None):
        snapshot_id = await _unvalidated_upload(tmp_path, client)
        staged = await client.post(f"{_SNAPSHOTS}/{snapshot_id}/restore")
        assert staged.status_code == 201, staged.text
        assert staged.json()["plan"]["skipped"] == [{"section": "notes", "version": 1}]
        section = NotesSection()
        assert register_section(client._transport.app, section)

        refused = await client.post(f"/api/pagebuilder/imports/{staged.json()['id']}/approve")
        assert refused.status_code == 422
        assert [c[0] for c in section.calls] == ["validate"]  # never planned or applied
        assert await notes(client) == {}
        assert (await client.get(_PENDING)).json()["id"] == staged.json()["id"]


async def test_a_contributor_crashing_in_validate_is_a_422(tmp_path):
    section = NotesSection()
    async for client in notes_client(tmp_path, section):
        taken = await _take(client)
        data = (await client.get(f"{_SNAPSHOTS}/{taken['id']}/download")).content

        def crash(ctx):
            raise KeyError("name")

        section.validate = crash
        refused = await client.post(f"{_SNAPSHOTS}/upload", files={"file": ("b.zip", data)})
        assert refused.status_code == 422
        assert "'notes' section is malformed" in refused.json()["detail"]


async def test_non_integer_counts_fail_the_capture(tmp_path):
    section = NotesSection()
    original = section.capture

    async def bad_counts(ctx):
        await original(ctx)
        return SectionCapture(counts={"notes": "1"})

    section.capture = bad_counts
    async for client in notes_client(tmp_path, section):
        with pytest.raises(ValueError, match="non-integer counts"):
            await client.post(_SNAPSHOTS, json={})
        root = client._transport.app.state.pagebuilder.settings.snapshot_root / "snapshots"
        assert not root.exists() or list(root.iterdir()) == []


async def test_a_bundle_error_during_apply_is_a_422_and_stays_pending(tmp_path, monkeypatch):
    async for client in notes_client(tmp_path, NotesSection()):
        page = await create_draft(client, slug="home", title="Before")
        snapshot = await _take(client)
        await client.put(f"/api/pagebuilder/pages/{page['id']}", json={"title": "After"})
        staged = await client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")

        async def unreadable(*args, **kwargs):
            raise BundleError("unsupported version 1 of the 'notes' section")

        monkeypatch.setattr(restore_module, "apply_sections", unreadable)
        refused = await client.post(f"/api/pagebuilder/imports/{staged.json()['id']}/approve")
        assert refused.status_code == 422
        current = await client.get(f"/api/pagebuilder/pages/{page['id']}")
        assert current.json()["title"] == "After"
        assert (await client.get(_PENDING)).json()["id"] == staged.json()["id"]


# --- the context path helpers stay inside the section's directory ------------

_UNSAFE = ["../escape.json", "/etc/passwd", "a/../../x.json", "", "a//b.json", "a\\..\\x", "./x"]


@pytest.mark.parametrize("name", _UNSAFE)
def test_write_json_refuses_an_escaping_name(tmp_path, name):
    section_dir = tmp_path / "bundle" / "notes"
    section_dir.mkdir(parents=True)
    ctx = CaptureContext(db=None, tenant_id="default", dir=section_dir, to_portable=lambda n: n)
    with pytest.raises(UnsafeBundlePathError):
        ctx.write_json(name, {})
    assert not (tmp_path / "bundle" / "escape.json").exists()


@pytest.mark.parametrize("name", _UNSAFE)
def test_read_json_refuses_an_escaping_name(tmp_path, name):
    section_dir = tmp_path / "bundle" / "notes"
    section_dir.mkdir(parents=True)
    (tmp_path / "bundle" / "escape.json").write_text("{}")
    validate = ValidateContext(dir=section_dir, version=1, media_names=frozenset())
    with pytest.raises(BundleError, match="unsafe section path"):
        validate.read_json(name)
    restore = RestoreContext(
        db=None, tenant_id="default", dir=section_dir, version=1, from_portable=lambda n: n
    )
    with pytest.raises(UnsafeBundlePathError):
        restore.read_json(name)


def test_a_symlink_out_of_the_section_is_refused(tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text('{"secret": true}')
    section_dir = tmp_path / "bundle" / "notes"
    section_dir.mkdir(parents=True)
    (section_dir / "link.json").symlink_to(secret)
    (section_dir / "sub").symlink_to(tmp_path, target_is_directory=True)
    validate = ValidateContext(dir=section_dir, version=1, media_names=frozenset())
    for name in ("link.json", "sub/secret.json"):
        with pytest.raises(BundleError, match="symlink"):
            validate.read_json(name)
    ctx = CaptureContext(db=None, tenant_id="default", dir=section_dir, to_portable=lambda n: n)
    with pytest.raises(UnsafeBundlePathError):
        ctx.write_json("sub/planted.json", {})
    assert not (tmp_path / "planted.json").exists()


def test_a_safe_nested_name_works(tmp_path):
    section_dir = tmp_path / "notes"
    section_dir.mkdir()
    ctx = CaptureContext(db=None, tenant_id="default", dir=section_dir, to_portable=lambda n: n)
    ctx.write_json("articles/en__home.json", {"a": 1})
    restore = RestoreContext(
        db=None, tenant_id="default", dir=section_dir, version=1, from_portable=lambda n: n
    )
    assert restore.read_json("articles/en__home.json") == {"a": 1}
    assert restore.read_json("missing.json", []) == []
