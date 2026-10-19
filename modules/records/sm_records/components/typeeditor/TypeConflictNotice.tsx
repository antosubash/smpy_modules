import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { keys, useT } from '../../utils/i18n';

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
    <Card className="border-destructive/50" data-testid="records-type-conflict">
      <CardHeader>
        <CardTitle className="text-destructive">
          {t(keys.records.type_editor.conflict_title)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{t(keys.records.type_editor.conflict_help)}</p>
        <p className="text-sm">
          {t(keys.records.type_editor.conflict_server_label)}
          {': '}
          <span className="font-medium">{current.label}</span>
        </p>
        <Button type="button" variant="outline" onClick={() => onReload(current)}>
          {t(keys.records.editor.reload)}
        </Button>
      </CardContent>
    </Card>
  );
}
