from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.models import Layout, LayoutRevision


def _has_content(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    content = data.get("content")
    return isinstance(content, list) and len(content) > 0


class LayoutService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self) -> Layout:
        result = await self.db.execute(
            select(Layout).order_by(Layout.id.asc()).limit(1)
        )
        layout = result.scalars().first()
        if layout is None:
            layout = Layout(header_data={}, footer_data={})
            self.db.add(layout)
            await self.db.flush()
            await self.db.refresh(layout)
        return layout

    async def update(
        self,
        *,
        header_data: dict | None = None,
        footer_data: dict | None = None,
        note: str | None = None,
    ) -> Layout:
        layout = await self.get()
        header_changed = header_data is not None and header_data != layout.header_data
        footer_changed = footer_data is not None and footer_data != layout.footer_data
        # No-op save: skip the revision row so save-button-spam doesn't
        # pollute history. The layout row itself is also untouched.
        if not header_changed and not footer_changed:
            return layout

        if header_changed:
            layout.header_data = header_data  # type: ignore[assignment]
        if footer_changed:
            layout.footer_data = footer_data  # type: ignore[assignment]
        self.db.add(layout)

        assert layout.id is not None
        revision = LayoutRevision(
            layout_id=layout.id,
            header_data=layout.header_data,
            footer_data=layout.footer_data,
            note=note,
        )
        self.db.add(revision)

        await self.db.flush()
        await self.db.refresh(layout)
        return layout

    async def list_revisions(self) -> list[LayoutRevision]:
        layout = await self.get()
        result = await self.db.execute(
            select(LayoutRevision)
            .where(LayoutRevision.layout_id == layout.id)
            .order_by(LayoutRevision.id.desc())
        )
        return list(result.scalars().all())

    async def get_revision(self, revision_id: int) -> LayoutRevision:
        revision = await self.db.get(LayoutRevision, revision_id)
        if revision is None:
            raise HTTPException(status_code=404, detail="Revision not found")
        return revision

    async def restore(self, revision_id: int) -> Layout:
        revision = await self.get_revision(revision_id)
        return await self.update(
            header_data=revision.header_data,
            footer_data=revision.footer_data,
            note=f"Restored from revision #{revision.id}",
        )


def public_layout_props(layout: Layout) -> dict[str, dict | None]:
    # Empty slots surface as None so PublicPage can drop the wrapper —
    # an empty <header> is worse than no header.
    return {
        "layout_header": layout.header_data
        if _has_content(layout.header_data)
        else None,
        "layout_footer": layout.footer_data
        if _has_content(layout.footer_data)
        else None,
    }
