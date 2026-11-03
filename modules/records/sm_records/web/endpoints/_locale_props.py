"""Content language view props."""

from sm_records.core import locales
from sm_records.core.settings import RecordsSettings


def _locale_props(settings: RecordsSettings) -> dict[str, object]:
    """What the editor's Languages panel needs besides the record.

    Configuration, not data: ``content_locales`` and ``default_content_locale``
    are DB-backed settings (§4.2), so the browser has no other way to know
    which languages the panel should offer a row for. The type's own
    ``translatable`` arrives inside ``type`` and decides whether the panel is
    rendered at all.
    """
    return {
        "content_locales": list(locales.supported(settings)),
        "default_locale": locales.default(settings),
    }
