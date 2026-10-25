"""A fake contributed bundle section (#80), and an app that has it.

Stands in for news, which pagebuilder must never import: a ``notes`` section
backed by one tenant-scoped table of its own, written through the contract in
:mod:`pagebuilder.contracts.bundle` exactly as a real contributor would — only
through ``ctx.db``, flushing and never committing. Knobs on the instance
inject the failures the tests need. A plain module (``tests`` is on
``pythonpath``), like ``page_helpers``.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from conftest import _build_app, _client_for
from httpx import AsyncClient
from pagebuilder.contracts.bundle import (
    CaptureContext,
    PlanItem,
    PlanLine,
    RestoreContext,
    SectionApplied,
    SectionCapture,
    SectionPlan,
    ValidateContext,
    register_section,
)
from simple_module_db.base import create_module_base
from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import JSON, Column, delete
from sqlmodel import Field, select

FakeBase = create_module_base("bundlefake")


class FakeNote(FakeBase, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "bundlefake_notes"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    body: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )


NOTES = "notes.json"


class NotesSection:
    name = "notes"
    version = 1
    readable_versions = frozenset({1})
    required = False
    label_key = "notes.bundle.title"
    count_label_keys: ClassVar[dict[str, str]] = {"notes": "notes.bundle.counts.notes"}

    def __init__(self) -> None:
        self.fail_apply = False
        self.conflict_on: str | None = None
        self.calls: list[tuple[str, Any]] = []

    async def _live(self, ctx: CaptureContext | RestoreContext) -> dict[str, FakeNote]:
        rows = (await ctx.db.execute(select(FakeNote).order_by(FakeNote.name))).scalars()
        return {row.name: row for row in rows}

    async def capture(self, ctx: CaptureContext) -> SectionCapture:
        ctx.check_tenant()
        self.calls.append(("capture", ctx.tenant_id))
        live = await self._live(ctx)
        docs = [{"name": n, "body": ctx.to_portable(row.body)} for n, row in live.items()]
        ctx.write_json(NOTES, docs)
        return SectionCapture(counts={"notes": len(docs)})

    def validate(self, ctx: ValidateContext) -> None:
        self.calls.append(("validate", ctx.version))
        if not (ctx.dir / NOTES).is_file():
            return
        docs = ctx.read_json(NOTES)
        if not isinstance(docs, list) or not all(
            isinstance(d, dict) and isinstance(d.get("name"), str) for d in docs
        ):
            raise ctx.invalid(f"notes/{NOTES} is not a list of named notes")
        for doc in docs:
            ctx.check_media(doc.get("body"), f"note {doc['name']!r}")

    async def plan(self, ctx: RestoreContext) -> SectionPlan:
        ctx.check_tenant()
        self.calls.append(("plan", ctx.tenant_id))
        docs = ctx.read_json(NOTES, [])
        if self.conflict_on and any(d["name"] == self.conflict_on for d in docs):
            raise ctx.conflict(f"note {self.conflict_on!r} cannot be restored here")
        live = await self._live(ctx)
        new = [d for d in docs if d["name"] not in live]
        changed = [
            d
            for d in docs
            if d["name"] in live and ctx.from_portable(d["body"]) != live[d["name"]].body
        ]

        def items(found: list[dict[str, Any]]) -> list[PlanItem]:
            return [PlanItem(title=d["name"], slug=d["name"]) for d in found]

        return SectionPlan(
            lines=[
                PlanLine("notes.plan.new", len(new), items(new)),
                PlanLine("notes.plan.overwritten", len(changed), items(changed), "warning"),
            ],
            overwrites=len(changed),
        )

    async def apply(self, ctx: RestoreContext) -> SectionApplied:
        ctx.check_tenant()
        self.calls.append(("apply", ctx.tenant_id))
        live = await self._live(ctx)
        docs = ctx.read_json(NOTES, [])
        for doc in docs:
            row = live.get(doc["name"]) or FakeNote(name=doc["name"])
            row.body = ctx.from_portable(doc["body"])
            ctx.db.add(row)
        await ctx.db.flush()
        if self.fail_apply:
            raise RuntimeError("injected failure in the notes section")
        return SectionApplied(
            counts={"notes": len(docs)}, applied={"written": [{"name": d["name"]} for d in docs]}
        )


async def prepare(app: Any) -> None:
    """Create the fake table on the app's database, empty."""
    engine = app.state.sm.db.engine
    async with engine.begin() as conn:
        await conn.run_sync(FakeBase.metadata.create_all)
        await conn.execute(delete(FakeNote.__table__))


async def notes_client(
    tmp_path, section: NotesSection | None, **kwargs: Any
) -> AsyncIterator[AsyncClient]:
    """An admin client whose app has *section* registered (``None``: no contributor)."""
    app, cleanup = await _build_app(
        tmp_path, requires_auth=True, csrf_protect=False, inject_user=True, **kwargs
    )
    if section is not None:
        assert register_section(app, section) is True
    await prepare(app)
    try:
        async with _client_for(app) as client:
            yield client
    finally:
        await cleanup()


def session(client: AsyncClient) -> Any:
    return client._transport.app.state.sm.db.session_factory()  # type: ignore[attr-defined]


async def seed_note(client: AsyncClient, name: str, body: dict[str, Any]) -> None:
    async with session(client) as db:
        db.add(FakeNote(name=name, body=body))
        await db.commit()


async def notes(client: AsyncClient) -> dict[str, dict[str, Any]]:
    async with session(client) as db:
        rows = (await db.execute(select(FakeNote))).scalars()
        return {row.name: row.body for row in rows}


def rezip(data: bytes, replace: dict[str, Any]) -> bytes:
    """*data* (a bundle zip) with members replaced; a dict/list value is JSON."""
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for info in source.infolist():
            if info.filename not in replace:
                out.writestr(info, source.read(info.filename))
        for name, value in replace.items():
            if value is None:
                continue
            out.writestr(name, value if isinstance(value, bytes) else json.dumps(value))
    return buffer.getvalue()
