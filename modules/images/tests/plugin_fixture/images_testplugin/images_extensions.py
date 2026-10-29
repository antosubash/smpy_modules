"""Registers ``testplugin.count_pixels`` and the ``testplugin`` preset: its
step, two prompts (one per image, auto-run; one per group over their results),
group roles and a cross-check that compares the summary with the members."""

from __future__ import annotations

import io

from PIL import Image
from pydantic import BaseModel
from sm_images.contracts import Preset, PromptSpec, StepOutcome

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


PHOTO = {"type": "object", "properties": {"trees": {"type": "integer"}}, "required": ["trees"]}
SUMMARY = {"type": "object", "properties": {"trees": {"type": "integer"}}, "required": ["trees"]}


def agreement(group, results) -> dict:
    """Does the summary's tree count equal the members' total?"""
    *members, summary = results
    total = sum((r.result_data or {}).get("trees", 0) for r in members)
    found = (summary.result_data or {}).get("trees")
    return {"members": len(members), "total": total, "agrees": found == total}


def register(registry) -> None:
    registry.register_step(CountPixels())
    registry.register_preset(
        Preset(
            id="testplugin",
            label_key="testplugin.label",
            pipeline={STEP_ID: {}},
            group_roles=["centre", "left", "right"],
            filename_patterns=[r"^(?P<group>.+?)_(?P<role>centre|left|right)"],
            prompts=[
                PromptSpec(
                    id="testplugin.photo",
                    name="Trees per photo",
                    instruction="Count the trees.",
                    output_schema=PHOTO,
                    auto_run=True,
                ),
                PromptSpec(
                    id="testplugin.summary",
                    name="Trees per site",
                    scope="group",
                    inputs="results",
                    instruction="Summarise the site.",
                    output_schema=SUMMARY,
                ),
            ],
            cross_check=agreement,
        )
    )
