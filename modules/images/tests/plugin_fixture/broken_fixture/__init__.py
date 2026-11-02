"""A plugin whose own package import fails on a missing dependency."""

import no_such_dependency_xyz  # noqa: F401
