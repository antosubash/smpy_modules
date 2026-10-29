"""Fakes for the AI step tests: no network, no billing tables.

``ai`` patches the two seams the steps call through ``sm_ai.contracts``:
``resolve_model`` (a Pydantic AI ``FunctionModel`` that records what it was
sent and answers what the test set) and ``consume_requests`` (records each
charge, answers ``admit``).
"""

from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from PIL import Image as PILImage
from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sm_images.models import Prompt, PromptResult
from sm_images.models.enums import PromptScope
from sm_images.pipeline import registry
from sm_images.pipeline.builtin_steps import register_builtins
from sm_images.steps.classify import ClassifyStep
from sqlalchemy import select


@dataclass
class FakeAi:
    answer: Any = field(default_factory=lambda: {"labels": [{"label": "tree", "confidence": 0.9}]})
    """A dict is the structured output; a str is free text."""
    admit: bool = True
    fail: BaseException | None = None
    charges: list[dict[str, Any]] = field(default_factory=list)
    pictures: list[PILImage.Image] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)
    """The keyword arguments of each ``resolve_model`` call."""

    @property
    def calls(self) -> int:
        return len(self.prompts)

    def model(self) -> FunctionModel:
        def reply(messages: list[Any], info: AgentInfo) -> ModelResponse:
            if self.fail is not None:
                raise self.fail
            for part in messages[0].parts:
                content = getattr(part, "content", None)
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, BinaryContent):
                            self.pictures.append(PILImage.open(io.BytesIO(item.data)))
                        elif isinstance(item, str):
                            self.prompts.append(item)
            if isinstance(self.answer, str):
                return ModelResponse(parts=[TextPart(self.answer)])
            tool = info.output_tools[0].name
            return ModelResponse(parts=[ToolCallPart(tool, json.dumps(self.answer))])

        return FunctionModel(reply, model_name="fake-vision")

    async def consume(self, tenant_id, qty=1, *, idempotency_key, source, session_factory=None):
        self.charges.append(
            {"tenant": tenant_id, "key": idempotency_key, "source": source, "sf": session_factory}
        )
        return self.admit


@pytest.fixture
def ai(monkeypatch) -> FakeAi:
    from sm_ai import contracts

    fake = FakeAi()

    def resolve(model_name=None, **kw):
        fake.resolved.append(kw)
        return fake.model()

    monkeypatch.setattr(contracts, "resolve_model", resolve)
    monkeypatch.setattr(contracts, "consume_requests", fake.consume)
    return fake


def use_ai_steps(*steps: Any) -> None:
    """Built-ins plus ``classify`` (what a host with the ``[ai]`` extra has)."""
    registry.reset_registry()
    register_builtins()
    registry.register_builtin(ClassifyStep())
    for step in steps:
        registry.register_step(step)
    registry.freeze()


async def add_prompt(pipe: Any, coll: Any, **kw: Any) -> Prompt:
    async with pipe.db_state.session_factory() as s:
        row = Prompt(
            collection_id=coll.id,
            name=kw.pop("name", f"p-{uuid.uuid4().hex[:6]}"),
            scope=kw.pop("scope", PromptScope.IMAGE),
            instruction=kw.pop("instruction", "Describe the photo."),
            **kw,
        )
        s.add(row)
        await s.commit()
        return row


async def results(pipe: Any, prompt_id: uuid.UUID) -> list[PromptResult]:
    async with pipe.db_state.session_factory() as s:
        stmt = select(PromptResult).where(PromptResult.prompt_id == prompt_id)
        return list((await s.execute(stmt)).scalars())
