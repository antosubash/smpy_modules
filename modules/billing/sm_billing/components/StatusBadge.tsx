import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { statusLabel, statusTone } from '../utils/format';
import type { SubscriptionStatus } from '../utils/types';

export function StatusBadge({ status }: { status: SubscriptionStatus | null }) {
  return <Badge variant={statusTone(status)}>{statusLabel(status)}</Badge>;
}
