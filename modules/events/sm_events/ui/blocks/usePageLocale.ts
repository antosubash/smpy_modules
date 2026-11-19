/** The language of the page a block sits on, which is not a field of the block: a block set to
 *  German on an English page is a mistake nothing would catch. The public viewer sends `locale`;
 *  the page editor's preview sends the page being edited. `undefined` anywhere else, and the
 *  server then answers in its default language. (News' `useContentLocale`, rewritten here so the
 *  two modules share nothing.) */

import { usePage } from '@inertiajs/react';

type LocaleCarrying = { locale?: string | null; page?: { locale?: string | null } | null };

export function usePageLocale(): string | undefined {
  const props = usePage().props as unknown as LocaleCarrying;
  return props?.locale ?? props?.page?.locale ?? undefined;
}
