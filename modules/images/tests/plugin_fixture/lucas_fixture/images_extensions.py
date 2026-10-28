from __future__ import annotations

from pydantic import BaseModel
from sm_images.contracts import Preset, StepOutcome


class _Params(BaseModel):
    pass


class CountStep:
    id = "lucas_fixture.count"
    version = 1
    requires: tuple[str, ...] = ()
    mutates_display = False
    queue = "images"

    def params_schema(self):
        return _Params

    def applies(self, image, params) -> bool:
        return True

    async def run(self, ctx):
        return StepOutcome.completed({})


def register(registry) -> None:
    registry.register_step(CountStep())
    registry.register_preset(Preset(id="lucas_fixture", label_key="lucas.label"))
