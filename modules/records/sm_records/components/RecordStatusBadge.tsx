import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';

import { localeLabel } from '../utils/locale';
import type { RecordRead, RecordStatus, TypeRead } from '../utils/types';

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

/** The record's language, as a small badge — the record list's locale
 *  column and the editor header both use it, so it lives here next to the
 *  other one-line record badges rather than in either caller. `title` is
 *  the editor's own reminder that the language is fixed for a record's
 *  lifetime; the list omits it (a table cell has no room for a tooltip that
 *  matters on every row). */
export function RecordLocaleBadge({ locale, title }: { locale: string; title?: string }) {
  return (
    <Badge variant="outline" data-testid="records-locale-badge" title={title}>
      {localeLabel(locale)}
    </Badge>
  );
}

/** The editor header's badge row: outdated-schema, deleted and locale, in
 *  that order — pulled out of `RecordEditor` itself to keep that page under
 *  the 300-line cap. `current` is `null` on the new-record screen, where
 *  none of the three apply yet. */
export function RecordEditorHeaderBadges({
  current,
  translatable,
}: {
  current: RecordRead | null;
  translatable: TypeRead['translatable'];
}) {
  const { t } = useT();
  if (!current) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {current.schema_stale && (
        <Badge variant="outline" className="border-amber-500 text-amber-600">
          {t('records.editor.schema_stale', {
            defaultValue: 'Fields changed since this was saved',
          })}
        </Badge>
      )}
      {current.is_deleted && (
        <Badge variant="destructive">
          {t('records.editor.deleted_badge', { defaultValue: 'Deleted' })}
        </Badge>
      )}
      {translatable && (
        <RecordLocaleBadge
          locale={current.locale}
          title={t('records.editor.locale_badge_help', {
            defaultValue: "This record's language is fixed for its lifetime.",
          })}
        />
      )}
    </div>
  );
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
