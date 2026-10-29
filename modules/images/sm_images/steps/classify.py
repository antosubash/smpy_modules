"""The ``classify`` step: labels for a picture from a vision model (``[ai]``).

A structured call through ``sm_ai.contracts.resolve_model()``
(:func:`sm_images.ai.runner.ai_call`): the display copy at ``max_side``, the
step's ``instruction`` and, when ``vocabulary`` is set, labels restricted to
it. The output is ``{"labels": [{"label", "confidence"}], "model"}`` in the
run's ``output``; an empty list is a completed run, distinct from a failure.

The defaults are neutral (no domain vocabulary): a deployment that wants a
taxonomy sets it per collection, or a preset ships it. Registered only when
the ``ai`` module and Pydantic AI are installed; without them a collection
that enables ``classify`` keeps it and the runs settle as ``not_installed``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    create_model,
    field_validator,
)

from sm_images.pipeline import registry
from sm_images.pipeline.step import StepContext, StepOutcome

__all__ = ["DEFAULT_INSTRUCTION", "ClassifyParams", "ClassifyStep", "register_classify"]

DEFAULT_INSTRUCTION = (
    "List what this photo shows as short labels: the kind of scene, the setting "
    "and the notable objects. Give each label a confidence between 0 and 1. "
    "Only name what is visible."
)
VOCABULARY_MAX = 200
LABEL_MAX = 100


class ClassifyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vocabulary: list[str] = Field(default_factory=list, max_length=VOCABULARY_MAX)
    instruction: str = Field(DEFAULT_INSTRUCTION, min_length=1, max_length=4000)
    max_side: int = Field(1024, ge=256, le=2048)

    @field_validator("vocabulary")
    @classmethod
    def _labels(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip() for v in value]
        if any(not v or len(v) > LABEL_MAX for v in cleaned):
            raise ValueError(f"each label must be 1 to {LABEL_MAX} characters")
        return list(dict.fromkeys(cleaned))


@lru_cache(maxsize=64)
def _output_type(vocabulary: tuple[str, ...]) -> type[BaseModel]:
    free = Annotated[str, StringConstraints(min_length=1, max_length=LABEL_MAX)]
    label: Any = Literal[vocabulary] if vocabulary else free
    item = create_model("Label", label=(label, ...), confidence=(float, Field(..., ge=0, le=1)))
    return create_model("Labels", labels=(list[item], Field(default_factory=list)))


def _instruction(params: ClassifyParams) -> str:
    if not params.vocabulary:
        return params.instruction
    return f"{params.instruction}\nUse only these labels: {', '.join(params.vocabulary)}."


class ClassifyStep:
    id = "classify"
    version = 1
    requires: tuple[str, ...] = ()
    """The planner adds the enabled display mutator: the picture sent is redacted."""
    mutates_display = False
    sends_display_out = True
    queue = "images_heavy"

    def params_schema(self) -> type[BaseModel]:
        return ClassifyParams

    def applies(self, image: Any, params: BaseModel) -> bool:
        return True

    async def run(self, ctx: StepContext) -> StepOutcome:
        from sm_images.ai.runner import ai_call

        params = ctx.params
        assert isinstance(params, ClassifyParams)
        result = await ai_call(
            ctx,
            _instruction(params),
            _output_type(tuple(params.vocabulary)),
            version=self.version,
            max_side=params.max_side,
            source="images:classify",
        )
        if isinstance(result, StepOutcome):
            return result
        data, model_name = result
        return StepOutcome.completed({"labels": data.get("labels", []), "model": model_name})


def register_classify() -> None:
    from sm_images import ai

    if ai.ai_available():
        registry.register_builtin(ClassifyStep())
