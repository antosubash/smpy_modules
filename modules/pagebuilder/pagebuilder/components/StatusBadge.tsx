import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { PageStatus } from '../utils/api';

// The e2e suite asserts on this text verbatim — getByText('published',
// { exact: true }) — so these labels stay lowercase and unabbreviated.
const LABELS: Record<PageStatus, string> = {
  published: 'published',
  submitted_for_review: 'pending review',
  draft: 'draft',
};

const VARIANTS: Record<PageStatus, 'default' | 'secondary' | 'outline'> = {
  published: 'default',
  submitted_for_review: 'secondary',
  draft: 'outline',
};

export function StatusBadge({ status }: { status: PageStatus }) {
  return <Badge variant={VARIANTS[status]}>{LABELS[status]}</Badge>;
}
