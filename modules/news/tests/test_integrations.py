"""Unit tests for the seam news borrows pagebuilder through.

``news.integrations.pagebuilder`` is the only module here that imports that
package, so it is also the only place where a change on pagebuilder's side
(or its absence) can break news silently. This is asserted rather than left
to review because it is the kind of thing a single convenient import quietly
undoes, and nothing else would fail.
"""

from __future__ import annotations

import pathlib
import re

import news


class TestNoOtherModuleImportsPagebuilder:
    def test_the_seam_is_the_only_importer(self) -> None:
        root = pathlib.Path(news.__file__).parent
        offenders = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if path.name != "pagebuilder.py"
            and re.search(r"^\s*(from|import) pagebuilder", path.read_text(), re.M)
        )

        assert offenders == []
