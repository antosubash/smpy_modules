import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';

import type { RecordRead } from '../utils/types';

/**
 * A 409 on save, as a real screen state — not a toast.
 *
 * Shows what the server now has (`current`) next to the JSON the person was
 * about to overwrite it with (`yourData`, read-only — editing continues in
 * the main form once they choose). "Reload" replaces local state with
 * `current`; there is no "overwrite anyway" button here because that is just
 * saving again with the new `expected_version`, which the caller does once
 * `RecordEditor` re-reads `current.version` — this panel only needs to get
 * out of the way for that.
 */
export function ConflictPanel({
  current,
  yourData,
  onReload,
}: {
  current: RecordRead;
  /** The data the person had typed, pretty-printed, shown read-only. */
  yourData: string;
  onReload: (current: RecordRead) => void;
}) {
  const { t } = useT();
  return (
    <Card className="border-destructive/50" data-testid="records-conflict-panel">
      <CardHeader>
        <CardTitle className="text-destructive">
          {t('records.editor.conflict_title', {
            defaultValue: 'This record changed while you were editing',
          })}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {t('records.editor.conflict_help', {
            defaultValue:
              'Someone else saved a change to this record since you opened it. Reload to see the latest version, or overwrite it with what you have.',
          })}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              {t('records.editor.server_version', { defaultValue: 'Current on the server' })}
            </p>
            <p className="mt-1 font-medium">{current.display_title}</p>
            <p className="text-sm text-muted-foreground">
              {t('records.records.updated_at', { defaultValue: 'Updated' })}:{' '}
              {current.updated_at ?? current.created_at}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              {t('records.editor.your_version', { defaultValue: 'Your unsaved version' })}
            </p>
            <pre className="mt-1 max-h-40 overflow-auto rounded-md border bg-muted p-2 text-xs">
              {yourData}
            </pre>
          </div>
        </div>
        <Button type="button" variant="outline" onClick={() => onReload(current)}>
          {t('records.editor.reload', { defaultValue: 'Reload' })}
        </Button>
      </CardContent>
    </Card>
  );
}
