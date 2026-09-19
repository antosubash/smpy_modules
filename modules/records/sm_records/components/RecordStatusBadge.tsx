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

/** A record's `data` was last written against an older or newer version of
 *  its type's schema than the type currently has (`schema_version !=
 *  records_type.schema_version`) — it still reads leniently and restamps on
 *  its next write, but the list flags it so an editor knows to open and
 *  re-save it rather than assume it's fully in step with the current
 *  fields. */
export function SchemaStaleBadge() {
  const { t } = useT();
  return (
    <Badge variant="outline" className="text-amber-700 dark:text-amber-400">
      {t('records.records.schema_stale', { defaultValue: 'Outdated schema' })}
    </Badge>
  );
}
