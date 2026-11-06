"""The errors CSV: every cell neutralised against spreadsheet formula injection (R16).

A file name and a header-derived field key are attacker text, so every cell goes through
:func:`neutralise`, not only the ones that look risky.
"""

from __future__ import annotations

import csv
import io

from sm_newsletter.models import ImportJob

__all__ = ["HEADER", "errors_csv", "neutralise"]

HEADER = ("file", "file_name", "line", "code", "field")
_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def neutralise(cell: str) -> str:
    """``cell``, prefixed with ``'`` when a spreadsheet would read it as a formula."""
    return f"'{cell}" if cell.startswith(_TRIGGERS) else cell


def errors_csv(job: ImportJob) -> str:
    """Every kept row error of ``job``: ``file,file_name,line,code,field``."""
    names = [str(f.get("name", "")) for f in job.files or []]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADER)
    for err in job.errors or []:
        index = err.get("file")
        name = names[index] if isinstance(index, int) and 0 <= index < len(names) else ""
        cells = (index, name, err.get("line"), err.get("code"), err.get("field"))
        writer.writerow(neutralise("" if c is None else str(c)) for c in cells)
    return out.getvalue()
