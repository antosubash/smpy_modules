import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';

import type { TypeRead } from '../../utils/types';

/**
 * A 409 on `PUT /types/{key}` whose body carried `current` — someone else
 * saved this type first. `ConflictPanel` is `RecordRead`-shaped and this
 * screen edits a `TypeRead`, so this is a variant rather than an import
 * (the module's per-page components deliberately do not share frontend code
 * with each other's shapes).
 */
export function TypeConflictNotice({
  current,
  onReload,
}: {
  current: TypeRead;
  onReload: (current: TypeRead) => void;
}) {
  const { t } = useT();
  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="text-destructive">
          {t('records.type_editor.conflict_title', {
            defaultValue: 'This type changed while you were editing',
          })}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {t('records.type_editor.conflict_help', {
            defaultValue:
              'Someone else saved a change to this type since you opened it. Reload to see the latest version, then reapply your changes.',
          })}
        </p>
        <p className="text-sm">
          {t('records.type_editor.conflict_server_label', {
            defaultValue: 'Current label on the server',
          })}
          {': '}
          <span className="font-medium">{current.label}</span>
        </p>
        <Button type="button" variant="outline" onClick={() => onReload(current)}>
          {t('records.editor.reload', { defaultValue: 'Reload' })}
        </Button>
      </CardContent>
    </Card>
  );
}
