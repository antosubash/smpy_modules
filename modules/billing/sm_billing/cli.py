"""``smpy billing reconcile [--tenant ID]`` — mounted through the framework CLI seam.

Run from the repo root like every other entry point, so the host's settings
(database URL, secret key) are the ones the app boots with.
"""

from __future__ import annotations

import asyncio

import typer

app = typer.Typer(help="Billing module administration.", no_args_is_help=True)


@app.callback()
def _main() -> None:
    """Billing module administration."""


@app.command("reconcile")
def reconcile_command(
    tenant: str | None = typer.Option(None, "--tenant", help="Only this tenant id."),
) -> None:
    """Re-fetch provider subscriptions and push drifted seat quantities."""
    from simple_module_hosting.app_builder import create_app
    from simple_module_hosting.settings import Settings

    from sm_billing.reconcile import reconcile

    fastapi_app = create_app(Settings())

    async def run() -> int:
        async with fastapi_app.router.lifespan_context(fastapi_app):
            report = await reconcile(fastapi_app, tenant_id=tenant)
        if report.skipped:
            typer.echo(f"Nothing to reconcile: {report.skipped}.")
            return 0
        typer.echo(f"Synced {report.synced}, pushed {report.pushed} quantity change(s).")
        for tenant_id, error in report.errors:
            typer.echo(f"  {tenant_id}: {error}", err=True)
        return 1 if report.errors else 0

    raise typer.Exit(code=asyncio.run(run()))
