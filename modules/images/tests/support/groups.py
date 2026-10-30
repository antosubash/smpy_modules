"""Helpers for the group-run tests: a collection with one group of members."""

from __future__ import annotations

import uuid
from typing import Any

import pytest_asyncio
from sm_images.models import Group, PromptResult
from sm_images.models.enums import PromptScope
from sm_images.pipeline import registry
from sm_images.pipeline.ai.group_request import request_groups
from sqlalchemy import select

from tests.support.ai import add_prompt, use_ai_steps
from tests.support.pipeline import jpeg, make_pipe

ROLES = ["centre", "left", "right"]
SUMMARY = {"type": "object", "properties": {"verdict": {"type": "string"}}, "required": ["verdict"]}
PHOTO = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


async def group_with(pipe: Any, coll: Any, roles: list[str], **image_kw: Any) -> tuple[Any, list]:
    """A group of ``coll`` and one stored member per role (given in reverse, so
    the role order has to come from the collection)."""
    async with pipe.db_state.session_factory() as s:
        group = Group(collection_id=coll.id, key=f"g-{uuid.uuid4().hex[:6]}")
        s.add(group)
        await s.commit()
    members = {}
    for role in reversed(roles):
        members[role] = await pipe.image(
            coll, jpeg(), group_id=group.id, group_role=role, **image_kw
        )
    return group, [members[r] for r in roles]


async def group_prompt(pipe: Any, coll: Any, *, inputs: str, member: Any = None, **kw: Any):
    return await add_prompt(
        pipe,
        coll,
        scope=PromptScope.GROUP,
        inputs=inputs,
        member_prompt_id=getattr(member, "id", None),
        output_schema=kw.pop("output_schema", SUMMARY),
        instruction=kw.pop("instruction", "Summarise the site."),
        **kw,
    )


async def group_result(pipe: Any, prompt_id: uuid.UUID, group_id: uuid.UUID) -> PromptResult:
    async with pipe.db_state.session_factory() as s:
        stmt = select(PromptResult).where(
            PromptResult.prompt_id == prompt_id, PromptResult.group_id == group_id
        )
        return (await s.execute(stmt)).scalar_one()


@pytest_asyncio.fixture
async def file_pipe(tmp_path):
    """The pipeline harness on a file database: member runs use up to four
    sessions at once, which the in-memory database's one shared connection
    cannot. The AI steps are registered."""
    from tests.pg_support import make_db_state

    use_ai_steps()
    state = await make_db_state(file=tmp_path / "group.db")
    p = await make_pipe(tmp_path, state)
    yield p
    await p.db_state.engine.dispose()
    registry.reset_registry()


def answers(prompt_text: str) -> dict:
    """Members answer the photo schema, the consolidation the summary one."""
    return {"verdict": "ok"} if "Summarise" in prompt_text else {"n": 2}


async def run_groups(pipe: Any, prompt: Any, group: Any, scope: str = "missing") -> int:
    return await request_groups(pipe.runtime, "default", prompt.id, scope, [group.id])
