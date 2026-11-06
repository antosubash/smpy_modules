"""The errors CSV: every attacker-derived cell neutralised against formula injection (R16).

A file name and a header-derived field key are attacker text. Free-text cells (file name,
field) are prefixed with ``'`` whenever they are non-empty and not purely numeric, so no
trigger spelling (leading whitespace, full-width forms, a smuggled newline) can slip past.
Fixed columns (file index, line, code) go through :func:`neutralise`, which prefixes a cell
whose left-stripped form starts with a formula trigger. Every cell is quoted
(``QUOTE_ALL``) and ``;`` is replaced in file names, so a semicolon-locale parser cannot
split a cell into a formula. No cell value is ever echoed (R16).
"""

from __future__ import annotations

import csv
import io

from sm_newsletter.models import ImportJob

__all__ = ["HEADER", "errors_csv", "neutralise", "neutralise_text"]

HEADER = ("file", "file_name", "line", "code", "field")
_TRIGGERS = ("=", "+", "-", "@", "\t", "\r", "\n", "\uff1d", "\uff0b", "\uff0d", "\uff20")


def neutralise(cell: str) -> str:
    """``cell``, prefixed with ``'`` when a spreadsheet could read it as a formula."""
    return f"'{cell}" if cell.lstrip().startswith(_TRIGGERS) or cell[:1] in _TRIGGERS else cell


def neutralise_text(cell: str) -> str:
    """Free text: prefixed with ``'`` unless empty or purely ASCII digits."""
    if not cell or (cell.isascii() and cell.isdigit()):
        return cell
    return f"'{cell}"


def errors_csv(job: ImportJob) -> str:
    """Every kept row error of ``job``: ``file,file_name,line,code,field``."""
    names = [str(f.get("name", "")).replace(";", "_") for f in job.files or []]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerow(HEADER)
    for err in job.errors or []:
        index = err.get("file")
        name = names[index] if isinstance(index, int) and 0 <= index < len(names) else ""
        field = err.get("field")
        writer.writerow(
            (
                neutralise("" if index is None else str(index)),
                neutralise_text(name),
                neutralise("" if err.get("line") is None else str(err["line"])),
                neutralise("" if err.get("code") is None else str(err["code"])),
                neutralise_text("" if field is None else str(field)),
            )
        )
    return out.getvalue()
