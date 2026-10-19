import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { keys, useT } from '../utils/i18n';

import type { RecordRead } from '../utils/types';
import { formatDateTime } from '../utils/values';

/**
 * A 409 on save, as a real screen state — not a toast.
 *
 * Shows what the server now has (`current`) next to the JSON the person was
 * about to overwrite it with (`yourData`, read-only — editing continues in
 * the main form once they choose). Two ways out: "Reload" replaces local
 * state with `current`, discarding the person's edits; "Overwrite anyway"
 * keeps the edits and re-saves with `current.version` as the caller's next
 * `expected_version` (H1) — so it can 409 again if someone saved a third
 * time in between, which just reopens this panel with the newer `current`.
 */
export function ConflictPanel({
  current,
  yourData,
  onReload,
  onOverwrite,
}: {
  current: RecordRead;
  /** The data the person had typed, pretty-printed, shown read-only. */
  yourData: string;
  onReload: (current: RecordRead) => void;
  /** Re-saves the form's own (unread) values against `current.version`. */
  onOverwrite: () => void;
}) {
  const { t } = useT();
  return (
    <Card className="border-destructive/50" data-testid="records-conflict-panel">
      <CardHeader>
        {/* A heading, so a screen reader navigating by heading finds the
            one panel on this page that must not be missed (R15). */}
        <CardTitle className="text-destructive" role="heading" aria-level={2}>
          {t(keys.records.editor.conflict_title)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{t(keys.records.editor.conflict_help)}</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              {t(keys.records.editor.server_version)}
            </p>
            <p className="mt-1 font-medium">{current.display_title}</p>
            <p className="text-sm text-muted-foreground">
              {t(keys.records.records.updated_at)}:{' '}
              {formatDateTime(current.updated_at ?? current.created_at)}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              {t(keys.records.editor.your_version)}
            </p>
            <pre className="mt-1 max-h-40 overflow-auto rounded-md border bg-muted p-2 text-xs">
              {yourData}
            </pre>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => onReload(current)}>
            {t(keys.records.editor.reload)}
          </Button>
          <Button
            type="button"
            variant="outline"
            data-testid="records-conflict-overwrite"
            onClick={onOverwrite}
          >
            {t(keys.records.editor.overwrite)}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
