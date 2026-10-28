"""Registers ``testplugin.count_pixels`` and the ``testplugin`` preset."""

from __future__ import annotations

import io

from PIL import Image
from pydantic import BaseModel
from sm_images.contracts import Preset, StepOutcome

STEP_ID = "testplugin.count_pixels"


class CountParams(BaseModel):
    pass


class CountPixels:
    """Counts the display copy's pixels; the count is the stored result."""

    id = STEP_ID
    version = 1
    requires: tuple[str, ...] = ()
    mutates_display = False
    queue = "images"

    def __init__(self) -> None:
        self.calls = 0

    def params_schema(self):
        return CountParams

    def applies(self, image, params) -> bool:
        return True

    async def run(self, ctx):
        self.calls += 1
        with Image.open(io.BytesIO(await ctx.read_display())) as img:
            width, height = img.size
        return StepOutcome.completed({"pixels": width * height})


def register(registry) -> None:
    registry.register_step(CountPixels())
    registry.register_preset(
        Preset(id="testplugin", label_key="testplugin.label", pipeline={STEP_ID: {}})
    )
