"""A configurable Step stub for the registry tests."""

from __future__ import annotations

from pydantic import BaseModel


class _P(BaseModel):
    pass


class FakeStep:
    def __init__(self, id: str, requires=(), mutates_display: bool = False, queue: str = "images"):
        self.id = id
        self.version = 1
        self.requires = tuple(requires)
        self.mutates_display = mutates_display
        self.queue = queue

    def params_schema(self):
        return _P

    def applies(self, image, params) -> bool:
        return True

    async def run(self, ctx):
        raise NotImplementedError
