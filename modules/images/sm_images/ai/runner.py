"""One vision call: prepare the picture, meter it, ask the model (spec §3).

:func:`run_structured` is the model call: ``sm_ai.contracts.resolve_model()``
and a Pydantic AI ``Agent`` whose ``output_type`` is a pydantic model (built
from the prompt's JSON Schema after ``schema_safety.check``) or ``str``.

:func:`ai_call` is what both AI steps run inside the executor, in this order:

1. the **privacy gate** - the display copy must be safe to send
   (``display_not_ready`` otherwise; the executor decided it in the load
   phase): the original never leaves, and an unredacted display neither;
2. the **model** - an unconfigured ``ai`` fails ``ai_not_configured``
   before anything is charged;
3. **metering** - one ``ai.requests`` per call through
   ``sm_ai.contracts.consume_requests``, keyed
   ``images:{tenant}:{image}:{step}:{version}:{lease token}`` so a retry of
   the same claim is never charged twice; a refusal fails ``quota_exceeded``
   (final until someone retries it: nothing re-queues a failed run);
4. the **picture** - the display copy, EXIF-orientation applied, scaled to
   ``max_side`` and re-encoded as a metadata-free JPEG, off the event loop;
5. the call - a reply that never fits the output type is ``invalid_ai_output``,
   a provider error ``ai_error``. Anything else propagates to the executor.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

from pydantic import BaseModel

from sm_images.pipeline.step import StepContext, StepOutcome

__all__ = ["ai_call", "metering_key", "prepare_image", "run_structured"]

JPEG_QUALITY = 85
MESSAGE_MAX = 2000


def prepare_image(data: bytes, max_side: int) -> bytes:
    """A JPEG no larger than ``max_side`` on either side, with no metadata."""
    from PIL import Image, ImageOps

    from sm_images._heif import register_heif
    from sm_images.ingest.guards import guard_pixels

    register_heif()
    guard_pixels(data)  # the decompression-bomb guard, before any decode
    with Image.open(io.BytesIO(data)) as src:
        src.load()
        img = ImageOps.exif_transpose(src).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY)  # no exif= : nothing carried over
    return out.getvalue()


async def run_structured(
    instruction: str,
    output_type: type[BaseModel] | type[str],
    images: list[bytes],
    *,
    model: Any = None,
) -> tuple[Any, str]:
    """``(data, model_name)``: a dict (by alias) for a model output type, else text."""
    from pydantic_ai import Agent, BinaryContent
    from sm_ai import contracts

    model = model if model is not None else contracts.resolve_model()
    agent = Agent(model, output_type=output_type)
    parts: list[Any] = [instruction]
    parts += [BinaryContent(data=img, media_type="image/jpeg") for img in images]
    result = await agent.run(parts)
    out = result.output
    if isinstance(out, BaseModel):
        out = out.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return out, str(getattr(model, "model_name", "") or "")


def metering_key(ctx: StepContext, version: int, token: Any) -> str:
    return f"images:{ctx.tenant_id}:{ctx.image.id}:{ctx.step.id}:{version}:{token}"


def _fail(code: str, exc: BaseException | str) -> StepOutcome:
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    return StepOutcome.failed(code, text[:MESSAGE_MAX])


async def ai_call(
    ctx: StepContext,
    instruction: str,
    output_type: type[BaseModel] | type[str],
    *,
    version: int,
    max_side: int,
    source: str,
) -> tuple[Any, str] | StepOutcome:
    """Gate, meter and run one call for ``ctx``'s image; a failed outcome or
    ``(data, model_name)``."""
    from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
    from sm_ai import contracts

    staging = getattr(ctx, "_staging", None)
    if staging is None:
        raise RuntimeError(f"step {ctx.step.id!r} runs only under the pipeline executor")
    if not staging.display_safe:
        return _fail("display_not_ready", "the display copy is not redacted yet")
    try:
        model = contracts.resolve_model()
    except contracts.AiError as exc:
        return _fail("ai_not_configured", exc)
    admitted = await contracts.consume_requests(
        ctx.tenant_id,
        idempotency_key=metering_key(ctx, version, staging.token),
        source=source,
        session_factory=staging.session_factory,
    )
    if not admitted:
        return _fail("quota_exceeded", "the plan's AI request limit is used up")
    picture = await asyncio.to_thread(prepare_image, await ctx.read_display(), max_side)
    try:
        return await run_structured(instruction, output_type, [picture], model=model)
    except UnexpectedModelBehavior as exc:
        return _fail("invalid_ai_output", exc)
    except ModelAPIError as exc:
        return _fail("ai_error", exc)
