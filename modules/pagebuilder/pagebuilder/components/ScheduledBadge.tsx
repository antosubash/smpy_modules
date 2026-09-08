import type { PageStatus } from '../utils/api';
import { keys, useT } from '../utils/i18n';

interface Props {
  status: PageStatus;
  publishAt: string | null;
  unpublishAt: string | null;
}

/**
 * Inline pill rendered next to ``StatusBadge`` when a page has a
 * pending scheduler-driven flip. Drafts surface the upcoming publish
 * time; published pages surface the upcoming unpublish time. Pages
 * with no schedule for their current state render nothing — so callers
 * can drop this in unconditionally.
 */
export function ScheduledBadge({ status, publishAt, unpublishAt }: Props) {
  const { t } = useT();
  const target =
    status === 'draft' && publishAt
      ? { kind: 'publish' as const, at: publishAt }
      : status === 'published' && unpublishAt
        ? { kind: 'unpublish' as const, at: unpublishAt }
        : null;
  if (!target) return null;
  const label =
    target.kind === 'publish'
      ? t(keys.pagebuilder.badge.scheduled_publish)
      : t(keys.pagebuilder.badge.scheduled_unpublish);
  return (
    <span
      className="ml-2 inline-block text-xs font-medium px-2 py-1 rounded bg-blue-100 text-blue-800"
      title={new Date(target.at).toLocaleString()}
      data-testid="scheduled-badge"
    >
      {label} {new Date(target.at).toLocaleString()}
    </span>
  );
}
