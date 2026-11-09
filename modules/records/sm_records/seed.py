"""Public in-process demo seeding API."""

from sm_records.records.seed import SeedSummary, seed_database

__all__ = ["SeedSummary", "seed_database"]

# This path was a package before 0.0.14: its old submodules resolve through
# core/moved_paths until 0.0.17 (#319), and a submodule import needs a __path__.
__path__: list[str] = []
