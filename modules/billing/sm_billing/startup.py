"""Lifespan-start work: build the provider, seed the default plan, install entitlements."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


async def run(app: FastAPI) -> None:
    """Called from ``BillingModule.on_startup`` after settings hydration."""
