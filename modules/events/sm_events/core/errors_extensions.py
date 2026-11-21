"""The refusals of the extension registry (PR 6).

Kept beside :mod:`sm_events.core.errors` (which is near the file-size cap); they are
:class:`EventsError` subclasses, so the one installed handler renders them.
"""

from __future__ import annotations

from sm_events.core import constants
from sm_events.core.errors import Invalid, ServiceUnavailable

__all__ = [
    "BuiltinSource",
    "DuplicateSource",
    "ExtraTooLarge",
    "SourceUnavailable",
    "TooManySources",
    "TypeNotInstalled",
    "UnknownSource",
]


class UnknownSource(Invalid):
    code = constants.UNKNOWN_SOURCE_CODE
    detail = constants.UNKNOWN_SOURCE_DETAIL


class BuiltinSource(Invalid):
    code = constants.BUILTIN_SOURCE_CODE
    detail = constants.BUILTIN_SOURCE_DETAIL


class DuplicateSource(Invalid):
    code = constants.DUPLICATE_SOURCE_CODE
    detail = constants.DUPLICATE_SOURCE_DETAIL


class TooManySources(Invalid):
    code = constants.TOO_MANY_SOURCES_CODE
    detail = constants.TOO_MANY_SOURCES_DETAIL


class ExtraTooLarge(Invalid):
    code = constants.EXTRA_TOO_LARGE_CODE
    detail = constants.EXTRA_TOO_LARGE_DETAIL


class TypeNotInstalled(Invalid):
    """A change to the ``extra`` of an event whose type no installed plugin provides."""

    code = constants.TYPE_NOT_INSTALLED_CODE
    detail = constants.TYPE_NOT_INSTALLED_DETAIL


class SourceUnavailable(ServiceUnavailable):
    code = constants.SOURCE_UNAVAILABLE_CODE
    detail = constants.SOURCE_UNAVAILABLE_DETAIL
