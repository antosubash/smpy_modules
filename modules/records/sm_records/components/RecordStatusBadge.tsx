import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { RecordStatus } from '../utils/types';

/** See `utils/api.ts`'s header comment / the module report for why `t()`
 *  takes a string literal here rather than `keys.records.…` — the installed
 *  `@simple-module-py/i18n` build does not yet know this module's
 *  namespace, so the typed key tree has no `records` branch to reach. */
export function RecordStatusBadge({ status }: { status: RecordStatus }) {
  const { t } = useT();
  if (status === 'published') {
    return (
      <Badge variant="default">
        {t('records.records.published', { defaultValue: 'Published' })}
      </Badge>
    );
  }
  return <Badge variant="secondary">{t('records.records.draft', { defaultValue: 'Draft' })}</Badge>;
}
