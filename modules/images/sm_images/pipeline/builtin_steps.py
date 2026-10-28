"""The core built-in steps: ``exif`` and ``renditions`` (spec §3).

Both wrap the pure processors in :mod:`sm_images.processing`, run the CPU work
in a thread, and hand their typed writes to the executor through the context's
private staging - never to the database themselves. The executor applies them
only if the run's lease still holds when it completes:

* ``exif`` - camera fields, ``captured_at`` (zone-aware only, and only when
  unset) and the location, which never overrides a manual or imported one;
* ``renditions`` - one JPEG per ``thumbnail_sizes`` entry, cut from the
  display copy (the original until a display mutator publishes one), all or
  nothing. A display change re-runs it automatically.

Registered through ``extensions._BUILTIN_LOADERS`` before any plugin.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict

from sm_images.pipeline import registry
from sm_images.pipeline.step import StepContext, StepOutcome
from sm_images.processing.exif import ExifData, read_exif
from sm_images.processing.renditions import make_renditions

__all__ = ["ExifStep", "RenditionsStep", "exif_output", "register_builtins"]


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _staging(ctx: StepContext) -> Any:
    staging = getattr(ctx, "_staging", None)
    if staging is None:
        raise RuntimeError(f"step {ctx.step.id!r} runs only under the pipeline executor")
    return staging


def exif_output(data: ExifData) -> dict[str, Any]:
    """What the run records. A time with no zone is kept as its wall-clock text
    and flagged, never stored as if it were UTC."""
    taken = data.captured_at
    return {
        "lat": data.lat,
        "lng": data.lng,
        "altitude": data.altitude,
        "heading": data.heading,
        "captured_at": taken.isoformat() if taken else None,
        "captured_at_zone_known": bool(taken and taken.utcoffset() is not None),
        "make": data.make,
        "model": data.model,
        "orientation": data.orientation,
    }


class ExifStep:
    id = "exif"
    version = 1
    requires: tuple[str, ...] = ()
    mutates_display = False
    queue = "images"

    def params_schema(self) -> type[BaseModel]:
        return NoParams

    def applies(self, image: Any, params: BaseModel) -> bool:
        return True

    async def run(self, ctx: StepContext) -> StepOutcome:
        data = await asyncio.to_thread(read_exif, await ctx.read_original())
        _staging(ctx).exif = data
        return StepOutcome.completed(exif_output(data))


class RenditionsStep:
    id = "renditions"
    version = 1
    requires: tuple[str, ...] = ()
    """The executor adds the enabled display mutator as an effective dependency."""
    mutates_display = False
    queue = "images"

    def params_schema(self) -> type[BaseModel]:
        return NoParams

    def applies(self, image: Any, params: BaseModel) -> bool:
        return True

    async def run(self, ctx: StepContext) -> StepOutcome:
        staging = _staging(ctx)
        sizes = dict(staging.settings.thumbnail_sizes)
        made = await asyncio.to_thread(make_renditions, await ctx.read_display(), sizes)
        staging.renditions = made
        return StepOutcome.completed({"sizes": {n: [w, h] for n, (_, w, h) in made.items()}})


def register_builtins() -> None:
    registry.register_builtin(ExifStep())
    registry.register_builtin(RenditionsStep())
