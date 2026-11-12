#!/usr/bin/env python
"""Re-encrypt every stored module secret under the current ``SM_SECRET_KEY`` (#351).

    uv run python scripts/reencrypt_secrets.py --dry-run
    uv run python scripts/reencrypt_secrets.py
    uv run python scripts/reencrypt_secrets.py --no-seal-plaintext

The second step of a key rotation (``docs/secret-key-rotation.md``): with the
new key in ``SM_SECRET_KEY`` and the old one in ``SM_SECRET_KEY_PREVIOUS``,
this rewrites ai's provider keys, billing's Stripe secrets, newsletter's SMTP
password and records' CAPTCHA secret so they open under the new key alone. It
also upgrades the 0.0.15 ``enc:v1:`` format to ``enc:v2:``, and encrypts a
secret stored in the clear unless ``--no-seal-plaintext`` is given.

It is all or nothing. Every row is decided first; if any cannot be decrypted
with the keys given, or belongs to a module that is not installed, the rows are
listed and nothing is written (exit 1). Otherwise every rewrite runs in one
transaction, each a compare-and-set on the value it read, so a secret saved
while this runs is never overwritten: that rolls the whole run back and asks
for another. A second run finds nothing to do. Values are never printed.

The app is built (not started) with ``headless_settings`` like
``set_setting.py``, so this never provisions a secret key of its own. Restart
the web process and every worker afterwards: they cache what they decrypted.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import reencrypt_support as rs
from headless_settings import headless_settings
from simple_module_db.stored_settings import settings_table_clause
from simple_module_hosting.app_builder import create_app
from sqlalchemy import and_, or_, select


async def _rows(session) -> tuple[list[rs.Row], list[rs.Row]]:
    """The target rows, and every other row that looks encrypted."""
    table = settings_table_clause()
    keys = set(rs.target_keys())
    found = await session.execute(
        select(
            table.c.scope, table.c.scope_id, table.c.key, table.c.value, table.c.value_type
        ).where(
            or_(
                table.c.key.in_(sorted(keys)),
                table.c.value.like("enc:%"),
                table.c.value.like('"enc:%'),
            )
        )
    )
    rows = [rs.Row(*row) for row in found.all()]
    targets = [row for row in rows if row.key in keys]
    others = [row for row in rows if row.key not in keys and rs.looks_encrypted(row.value)]
    return targets, others


async def _apply(session, plans: list[rs.Plan]) -> bool:
    """Every rewrite, compare-and-set; ``False`` (rolled back) if any lost a race."""
    table = settings_table_clause()
    for plan in plans:
        row = plan.row
        result = await session.execute(
            table.update()
            .where(
                and_(
                    table.c.scope == row.scope,
                    table.c.scope_id == row.scope_id,
                    table.c.key == row.key,
                    table.c.value == row.value,
                )
            )
            .values(value=plan.new_value)
        )
        if result.rowcount != 1:
            await session.rollback()
            return False
    await session.commit()
    return True


async def run(*, dry_run: bool, seal_plaintext: bool) -> int:
    app = create_app(headless_settings())
    try:
        # headless_settings() already refused when no key is provisioned.
        rs.install_secret(app.state.sm.settings.secret_key)
        async with app.state.sm.db.session_factory() as session:
            targets, others = await _rows(session)
            try:
                # Once, before planning: one "cannot run" line, not a per-row raise.
                rs.check_secret()
                rs.check_previous()
                plans = [rs.plan_row(row, seal_plaintext=seal_plaintext) for row in targets]
            except RuntimeError as exc:
                print(f"cannot run: {exc}", file=sys.stderr)
                return 1
            for plan in plans:
                print(f"{plan.outcome:>20}  {plan.row.where()}")
            for row in others:
                print(f"{'not a target':>20}  {row.where()} (left untouched)")
            errors = [plan for plan in plans if plan.outcome in rs.ERRORS]
            if errors:
                print(
                    f"\n{len(errors)} secret(s) cannot be re-encrypted; nothing was written. "
                    "Add the key they were saved under to SM_SECRET_KEY_PREVIOUS, or re-enter "
                    "them, then run this again.",
                    file=sys.stderr,
                )
                return 1
            todo = [plan for plan in plans if plan.outcome in rs.REWRITES]
            if not todo:
                print("\nNothing to re-encrypt.")
                return 0
            if dry_run:
                print(f"\n{len(todo)} secret(s) would be re-encrypted (dry run; nothing written).")
                return 0
            if not await _apply(session, todo):
                print(
                    "\nA secret changed while this ran; nothing was written. Run it again.",
                    file=sys.stderr,
                )
                return 1
        print(
            f"\nRe-encrypted {len(todo)} secret(s). "
            "Restart the web process, every worker and beat so they read the new values."
        )
        return 0
    finally:
        await app.state.sm.db.engine.dispose()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="decide and report; write nothing")
    parser.add_argument(
        "--no-seal-plaintext",
        action="store_true",
        help="leave a secret stored in the clear as it is",
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(dry_run=args.dry_run, seal_plaintext=not args.no_seal_plaintext))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
