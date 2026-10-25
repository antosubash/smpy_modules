import { Link } from '@inertiajs/react';

import type { PageStatus } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { StatusBadge } from '../StatusBadge';

/** What the admin's preview route sends; absent on every public URL. */
export interface PreviewInfo {
  editor_href: string;
  status: PageStatus;
}

/** Height the bar occupies, which the sticky site header sits below. */
export const PREVIEW_BAR_HEIGHT = '2.5rem';

/**
 * The draft preview's banner (#89).
 *
 * A preview that looks exactly like the live page gets screenshotted and
 * shared as if it were live, and left the editor with no way back. Its colours
 * are fixed rather than the design pack's, so it can never be mistaken for
 * part of the author's page. Sticky rather than fixed: it stays in the flow, so
 * it never covers the top of the content, and the site header's own sticky
 * offset moves down by its height (see `PublicShell`).
 */
export function PreviewBar({ preview }: { preview: PreviewInfo }) {
  const { t } = useT();
  return (
    <div
      role="status"
      data-testid="preview-bar"
      className="pb-preview-bar sticky top-0 z-[60] flex items-center gap-3 border-b border-amber-300 bg-amber-50 px-4 text-sm text-amber-950"
      style={{ height: PREVIEW_BAR_HEIGHT }}
    >
      <span className="min-w-0 truncate font-medium">
        {t(keys.pagebuilder.public.preview.label)}
      </span>
      <span className="shrink-0">
        <StatusBadge status={preview.status} />
      </span>
      <Link
        href={preview.editor_href}
        className="ml-auto shrink-0 font-medium underline underline-offset-2 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-900"
      >
        {t(keys.pagebuilder.public.preview.back_to_editor)}
      </Link>
    </div>
  );
}
