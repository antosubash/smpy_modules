"""Router wiring, kept out of ``module.py`` so the hook stays one line."""

from __future__ import annotations

from fastapi import APIRouter


def include(api_router: APIRouter, view_router: APIRouter) -> None:
    """Mount the tenant API, admin API, webhook and tenant views."""


def include_admin(admin_router: APIRouter) -> None:
    """Mount the platform-admin Inertia views under ``/admin/billing``."""
