/** Which language the surrounding page is in.
 *
 * A feed block runs inside whatever page an author dropped it on, so it has no
 * props of its own to carry a language. It reads the one the server already
 * resolved for that page instead: the public viewer sends `locale`, and the
 * editor — where the same block renders in the preview canvas — sends the page
 * being edited. Reading it here rather than threading it through Puck's props
 * matters because it must not be an author-editable field: a block set to
 * "German" sitting on an English page is a mistake nothing would catch.
 *
 * `undefined` when neither is present, which is every screen that is not a
 * page. The listing then filters by nothing, i.e. behaves exactly as it did
 * before there were languages.
 */

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
