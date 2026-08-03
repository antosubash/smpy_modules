import type { PageStatus } from '../utils/api';

const TONES: Record<PageStatus, string> = {
  published: 'bg-green-100 text-green-800',
  submitted_for_review: 'bg-amber-100 text-amber-800',
  draft: 'bg-gray-100 text-gray-700',
};

const LABELS: Record<PageStatus, string> = {
  published: 'published',
  submitted_for_review: 'pending review',
  draft: 'draft',
};

export function StatusBadge({ status }: { status: PageStatus }) {
  return (
    <span className={`inline-block text-xs font-medium px-2 py-1 rounded ${TONES[status]}`}>
      {LABELS[status]}
    </span>
  );
}
