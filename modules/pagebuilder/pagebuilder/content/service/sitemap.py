"""Sitemap row projection."""

from datetime import datetime
from typing import NamedTuple


class SitemapEntry(NamedTuple):
    """The four fields a sitemap URL needs — deliberately not a ``Page``.

    ``locale`` is one of them because the URL is locale-prefixed: without it
    the sitemap would advertise every translation at the default language's
    address, which is both wrong and a duplicate-content report.
    ``translation_group`` is what lets each entry list its counterparts as
    ``xhtml:link`` alternates, so a crawler learns the German page exists
    without having to fetch the English one first.
    """

    slug: str
    updated_at: datetime | None
    locale: str
    translation_group: str
