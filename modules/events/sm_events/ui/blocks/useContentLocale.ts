/** The language of the page a block sits on, which is not a field of the block: a block set to
 *  German on an English page is a mistake nothing would catch. The public viewer sends `locale`;
 *  the page editor's preview sends the page being edited. `undefined` anywhere else, and the
 *  server then answers in its default language.
 *
 *  A parity copy of news' `useContentLocale` (`scripts/tests/parity_families.py`): events cannot
 *  import news' hook. Pagebuilder exporting one is #423; until then the two stay identical. */

import { usePage } from '@inertiajs/react';

interface LocaleCarryingProps {
  /** Sent by the public page viewer. */
  locale?: string | null;
  /** Sent by the page editor, whose preview renders the same blocks. */
  page?: { locale?: string | null } | null;
}

export function useContentLocale(): string | undefined {
  const props = usePage().props as unknown as LocaleCarryingProps;
  return props?.locale ?? props?.page?.locale ?? undefined;
}
