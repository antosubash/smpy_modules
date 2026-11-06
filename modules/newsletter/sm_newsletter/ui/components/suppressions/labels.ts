import { keys } from '../../utils/i18n';
import type { SuppressionReason } from '../../utils/types';

const copy = keys.newsletter.suppressions;

export const REASON_LABELS: Record<SuppressionReason, string> = {
  hard_bounce: copy.reasons.hard_bounce,
  complaint: copy.reasons.complaint,
  imported_cleaned: copy.reasons.imported_cleaned,
  unsubscribed: copy.reasons.unsubscribed,
};

export const SOURCE_LABELS: Record<string, string> = {
  records_event: copy.sources.records_event,
  reconcile: copy.sources.reconcile,
  unsubscribe_page: copy.sources.unsubscribe_page,
  send: copy.sources.send,
  import: copy.sources.import,
  admin: copy.sources.admin,
};
