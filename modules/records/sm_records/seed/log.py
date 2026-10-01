"""The seeder's one progress channel.

stderr rather than a logger: the seeder is a CLI command whose stdout is its
summary, and a module that wanted its progress lines would have to configure
logging before anything printed. One prefix, in one place, so
:mod:`sm_records.seed.runner` and :mod:`sm_records.seed._i18n` cannot drift
into two.
"""

from __future__ import annotations

import sys

__all__ = ["log"]


def log(message: str) -> None:
    print(f"records seed: {message}", file=sys.stderr)
