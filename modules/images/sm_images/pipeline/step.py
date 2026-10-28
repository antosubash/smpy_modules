"""The Step protocol and what a step is handed (spec §3, §8.3).

A step never touches storage or a session. :class:`StepContext` reaches bytes
through callables the executor injects (Task 10), which keeps the
never-overwrite-the-original rule in one place and lets a step be tested with
three lambdas.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from sm_images.contracts.schemas import ImageRead  # runtime import would cycle via contracts

__all__ = ["DisplayNotAllowed", "DisplayWriterMissing", "Step", "StepContext", "StepOutcome"]


class DisplayNotAllowed(PermissionError):  # noqa: N818 - name fixed by the plan
    """A step that does not declare ``mutates_display`` tried to write one."""


class DisplayWriterMissing(RuntimeError):  # noqa: N818 - pairs with DisplayNotAllowed
    """A display mutator ran with no writer: the executor's bug, not the step's."""


@runtime_checkable
class Step(Protocol):
    id: str
    version: int
    requires: tuple[str, ...]
    mutates_display: bool
    queue: str

    def params_schema(self) -> type[BaseModel]: ...

    def applies(self, image: ImageRead, params: BaseModel) -> bool: ...

    async def run(self, ctx: StepContext) -> StepOutcome: ...


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """``completed(output)`` | ``skipped(reason)`` | ``failed(code, message)``."""

    status: Literal["completed", "skipped", "failed"]
    output: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    code: str | None = None
    message: str | None = None

    @classmethod
    def completed(cls, output: dict[str, Any] | None = None) -> StepOutcome:
        return cls("completed", output=dict(output or {}))

    @classmethod
    def skipped(cls, reason: str) -> StepOutcome:
        return cls("skipped", reason=reason)

    @classmethod
    def failed(cls, code: str, message: str) -> StepOutcome:
        return cls("failed", code=code, message=message)


class StepContext:
    """Passed to ``Step.run``. I/O is injected: the executor supplies the
    readers, the fenced display writer and the lease-renewal callback.

    Every method is a coroutine and **must be awaited** - ``progress`` too: an
    un-awaited ``ctx.progress(50)`` renews nothing, and the lease then expires
    under a step that is still working.
    """

    def __init__(
        self,
        *,
        step: Step,
        image: ImageRead,
        params: BaseModel,
        tenant_id: str,
        read_display: Callable[[], Awaitable[bytes]],
        read_original: Callable[[], Awaitable[bytes]],
        write_display: Callable[[bytes, str], Awaitable[None]] | None = None,
        on_progress: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self.step = step
        self.image = image
        self.params = params
        self.tenant_id = tenant_id
        self._read_display = read_display
        self._read_original = read_original
        self._write_display = write_display
        self._on_progress = on_progress
        self._staging: Any = None
        """Executor-only: where the built-in steps leave their typed writes."""

    async def read_display(self) -> bytes:
        return await self._read_display()

    async def read_original(self) -> bytes:
        return await self._read_original()

    async def write_display(self, data: bytes, content_type: str) -> None:
        """Stage a new display copy. Published only if the step's lease still
        holds when it completes; the original is never touched."""
        if not self.step.mutates_display:
            raise DisplayNotAllowed(f"step {self.step.id!r} does not declare mutates_display")
        if self._write_display is None:
            raise DisplayWriterMissing(f"no display writer was supplied for step {self.step.id!r}")
        await self._write_display(data, content_type)

    async def progress(self, pct: int) -> None:
        """Renew the lease (executor callback) and tell the task sweep we live.

        Must be awaited. Raises the executor's lost-lease error when another
        worker has reclaimed the run: stop working, the result would be discarded.
        """
        pct = max(0, min(100, int(pct)))
        if self._on_progress is not None:
            await self._on_progress(pct)
        import background_tasks  # lazy: heartbeat is a no-op outside a task

        background_tasks.heartbeat(progress=(pct, 100))
