import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { PageStatus } from '../utils/api';
import { keys, useT } from '../utils/i18n';

// The e2e suite asserts on this text verbatim — getByText('published',
// { exact: true }) — so these labels stay lowercase and unabbreviated.
const LABELS: Record<PageStatus, string> = {
  published: keys.pagebuilder.badge.status_published,
  submitted_for_review: keys.pagebuilder.badge.status_review,
  draft: keys.pagebuilder.badge.status_draft,
};

const VARIANTS: Record<PageStatus, 'default' | 'secondary' | 'outline'> = {
  published: 'default',
  submitted_for_review: 'secondary',
  draft: 'outline',
};

export function StatusBadge({ status }: { status: PageStatus }) {
  const { t } = useT();
  return <Badge variant={VARIANTS[status]}>{t(LABELS[status])}</Badge>;
}
