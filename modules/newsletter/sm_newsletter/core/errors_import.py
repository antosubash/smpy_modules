"""Failures of the Mailchimp import. ``detail`` names a file index, line, column
index or field key; none repeats a cell value."""

from __future__ import annotations

from sm_newsletter.core.errors import NewsletterError


class ImportNotCsv(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_not_csv"
    detail = "The file is not a CSV file"


class ImportNotUtf8(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_not_utf8"
    detail = "The file is not UTF-8 text"


class ImportMalformedCsv(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_malformed_csv"
    detail = "The file is not valid CSV"


class ImportEmptyFile(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_empty_file"
    detail = "The file has no rows"


class ImportNoEmailColumn(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_no_email_column"
    detail = "The file has no email address column"


class ImportZipUnsafe(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_zip_unsafe"
    detail = "The archive cannot be read safely"


class ImportTooLarge(NewsletterError):  # noqa: N818 - the state it refuses
    status = 413
    code = "import_too_large"
    detail = "The upload is too large"


class ImportTooManyFiles(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_too_many_files"
    detail = "The upload has too many files"


class ImportTooManyRows(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_too_many_rows"
    detail = "The upload has too many rows"


class ImportTooManyColumns(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_too_many_columns"
    detail = "The file has too many columns"


class ImportDuplicateColumn(NewsletterError):  # noqa: N818 - the state it refuses
    """Two columns with one header; the detail names the header (never a cell)."""

    status = 422
    code = "import_duplicate_column"
    detail = "The file has the same column twice"


class ImportTooManyTags(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_too_many_tags"
    detail = "The upload would add too many new tags"


class ImportBadMapping(NewsletterError):  # noqa: N818 - names the payload
    status = 422
    code = "import_bad_mapping"
    detail = "The column mapping is not valid"


class ImportNotStaged(NewsletterError):  # noqa: N818 - the state it refuses
    status = 409
    code = "import_not_staged"
    detail = "This import is no longer waiting for a mapping"


class ImportChanged(NewsletterError):  # noqa: N818 - the state it refuses
    """The import moved on since the caller looked (another tab applied or discarded it)."""

    status = 409
    code = "import_changed"
    detail = "This import changed in the meantime"


class ImportNoRows(NewsletterError):  # noqa: N818 - the state it refuses
    status = 422
    code = "import_no_rows"
    detail = "The import has no rows to apply"


class ImportRunning(NewsletterError):  # noqa: N818 - the state it refuses
    status = 409
    code = "import_running"
    detail = "An import is already running"


class ListExists(NewsletterError):  # noqa: N818 - the state it refuses
    status = 409
    code = "list_exists"
    detail = "A list with that key already exists"


class InvalidListKey(NewsletterError):  # noqa: N818 - names the field
    status = 422
    code = "invalid_list_key"
    detail = "The list key is not valid"


class ImportFailed(NewsletterError):  # noqa: N818 - the state it reports
    """A fixed message: the worker raises it ``from None``, so no original exception (which
    can carry an address) is chained into a task result or a traceback (D6)."""

    status = 500
    code = "import_failed"
    detail = "The import failed"
