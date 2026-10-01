"""The languages a record can be authored in.

Content locales are deliberately **not** the host's UI locales
(``SM_I18N_SUPPORTED_LOCALES``, which decides what language the admin chrome
speaks), and deliberately not ``pagebuilder``'s either. The two questions are
different — a site can run an English-only console while publishing in four
languages, or publish an English-only catalogue beside a four-language
marketing site — and ``records`` is published on its own, so reaching into
another plugin for its configuration would make one installable module depend
on another. See :attr:`sm_records.settings.RecordsSettings.content_locales`.

**Every function here takes the settings object**, rather than reading a
process-global the module published at startup the way ``pagebuilder.locales``
does. That is the shape the rest of this module already has: ``create_record``,
``list_records`` and every other service take ``settings=`` explicitly, because
the hydrated instance lives on ``app.state.sm_records`` (``deps.get_settings``)
and is re-read per request — which is what makes a Settings-screen edit take
effect without a restart. A module-level cache here would be a second, staler
copy of the one value this module's URLs are keyed on.

Resolution is case-insensitive: the tag arrives from a query string at least as
often as from a select, and ``?locale=DE`` naming a real language and being
refused would be a puzzle rather than a policy. What comes back is always the
*configured* spelling, so nothing downstream has to normalise again.
"""

from __future__ import annotations

from sm_records.models import RecordType
from sm_records.services.errors import ValidationFailed
from sm_records.settings import RecordsSettings

__all__ = ["default", "require", "resolve", "resolve_locale", "supported"]


def supported(settings: RecordsSettings) -> tuple[str, ...]:
    """Every locale a record may be authored in, the default one included."""
    return tuple(settings.content_locales)


def default(settings: RecordsSettings) -> str:
    """The locale a record is in when nobody says, and the only one a type that
    is not ``translatable`` accepts."""
    return settings.default_content_locale


def resolve(settings: RecordsSettings, value: str | None) -> str | None:
    """``value`` as a configured content locale, or ``None``.

    ``None`` for an empty or unknown value alike: the caller decides whether
    that is "use the default" (the create path, an import row with no locale
    column) or "refuse and name it" (:func:`require`, the public ``?locale=``).
    """
    if not value:
        return None
    lowered = value.strip().lower()
    for locale in supported(settings):
        if locale.lower() == lowered:
            return locale
    return None


def require(settings: RecordsSettings, value: str | None, *, field: str = "locale") -> str:
    """:func:`resolve`, or a 422 naming the locale and listing the real ones.

    ``None`` means "the caller did not choose" and gets the default — the rule
    :class:`~sm_records.contracts.schemas.RecordCreate` documents. An explicit
    value that is not configured is refused rather than silently defaulted,
    because defaulting it is how a record meant for the German site is written
    into the English one.
    """
    if value is None:
        return default(settings)
    resolved = resolve(settings, value)
    if resolved is None:
        raise ValidationFailed(
            f"{value!r} is not a content locale; configured: {', '.join(supported(settings))}",
            [{"field": field, "message": f"{value!r} is not a content locale"}],
        )
    return resolved


def resolve_locale(rtype: RecordType, settings: RecordsSettings, locale: str | None) -> str:
    """The language a new record is written in — the whole of §4.3's create rule.

    Three answers and no fourth: nothing asked for gets the configured default;
    something asked for that is not a content locale is a 422 naming it
    (:func:`require`); and a type that is not ``translatable`` accepts only the
    default, because every screen and every public read for such a type assumes
    one language and a record written into another would be reachable by uuid
    and by nothing else.

    A separate function because the translation endpoint needs the same three
    answers with one of them reversed — there, a request for the default locale
    on a non-translatable type is the refusal. It lives here rather than beside
    ``create_record`` because it is locale policy and nothing else — the write
    path calls it and re-exports it, as it does every other rule it borrows.
    """
    resolved = require(settings, locale)
    if not rtype.translatable and resolved != default(settings):
        raise ValidationFailed(
            f"type {rtype.key!r} is not translatable, so its records are all in "
            f"{default(settings)!r}; enable 'translatable' on the type first",
            [{"field": "locale", "message": f"{rtype.key!r} is not translatable"}],
        )
    return resolved
