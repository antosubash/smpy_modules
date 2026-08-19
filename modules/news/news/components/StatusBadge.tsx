import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { ArticleStatus } from '../utils/api';

// News' own badge rather than pagebuilder's, for the same reason it has its
// own `ArticleStatus`: rendering three labels is not worth a build-time
// dependency on another module's component path. The labels match
// pagebuilder's deliberately — the two lists sit side by side in the admin and
// the e2e suite asserts on this text verbatim (getByText('published',
// { exact: true })), so they stay lowercase and unabbreviated.
const LABELS: Record<ArticleStatus, string> = {
  published: 'published',
  submitted_for_review: 'pending review',
  draft: 'draft',
};

const VARIANTS: Record<ArticleStatus, 'default' | 'secondary' | 'outline'> = {
  published: 'default',
  submitted_for_review: 'secondary',
  draft: 'outline',
};

export function StatusBadge({ status }: { status: ArticleStatus }) {
  return <Badge variant={VARIANTS[status]}>{LABELS[status]}</Badge>;
}
