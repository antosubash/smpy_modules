import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import { useSchemaApply } from '../../hooks/useSchemaApply';
import { listTypeRevisions, restoreTypeRevision } from '../../utils/api';
import type { TypeRead, TypeRevision } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { SchemaConflictPanel } from './SchemaConflictPanel';
import { TypeConflictNotice } from './TypeConflictNotice';

/**
 * A collapsible panel over `GET /types/{key}/revisions` (design §8.6): every
 * snapshot `records_type_revision` took of this type's schema, newest first,
 * each restorable. Restoring re-enters the same classify-and-dry-run
 * pipeline as any other schema write — reverting a field delete is itself a
 * `field_added`-shaped change against the *current* schema, so it can be
 * just as restrictive or conflict-laden as an edit typed by hand.
 */
export function TypeRevisions({
  type,
  onRestored,
}: {
  type: TypeRead;
  onRestored: (result: TypeRead) => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<TypeRevision[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const { items: list } = await listTypeRevisions(type.key);
      setItems(list);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, [type.key]);

  // A successful restore creates a new revision snapshot on the server (of
  // the schema *before* the restore), so the list this panel is already
  // showing is stale the moment `onRestored` fires — reload it here (covers
  // both a plain restore and a force/orphaned retry through
  // `SchemaConflictPanel`, since both funnel success through this callback)
  // so that new revision shows up without the admin having to collapse and
  // reopen the panel.
  const apply = useSchemaApply((result) => {
    onRestored(result);
    toast.success(t('records.type_editor.revisions.restored', { defaultValue: 'Schema restored' }));
    void load();
  });

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && items === null) void load();
  };

  const restore = async (version: number) => {
    apply.reset();
    try {
      await apply.run((body) => restoreTypeRevision(type.key, version, body), {
        expected_version: type.version,
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>
          {t('records.type_editor.revisions.title', { defaultValue: 'Schema history' })}
        </CardTitle>
        <Button type="button" variant="ghost" size="sm" onClick={toggle}>
          {open
            ? t('records.type_editor.revisions.hide', { defaultValue: 'Hide' })
            : t('records.type_editor.revisions.show', { defaultValue: 'Show' })}
        </Button>
      </CardHeader>
      {open && (
        <CardContent className="space-y-3">
          {loadError && (
            <p className="text-sm text-destructive" role="alert">
              {loadError}
            </p>
          )}
          {items === null && !loadError && (
            <p className="text-sm text-muted-foreground">
              {t('records.type_editor.revisions.loading', { defaultValue: 'Loading…' })}
            </p>
          )}
          {items?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {t('records.type_editor.revisions.empty', {
                defaultValue: 'No earlier versions yet.',
              })}
            </p>
          )}
          {items && items.length > 0 && (
            <ul className="space-y-2">
              {items.map((rev) => (
                <li
                  key={rev.id}
                  data-testid="records-type-revision-item"
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm"
                >
                  <div>
                    <p className="font-medium">
                      {t('records.type_editor.revisions.version_label', {
                        version: rev.version,
                        defaultValue: 'v{{version}}',
                      })}
                      {' · '}
                      {t('records.type_editor.revisions.field_count', {
                        count: rev.fields.length,
                        defaultValue: '{{count}} field',
                        defaultValue_other: '{{count}} fields',
                      })}
                      {' · '}
                      {t('records.type_editor.revisions.schema_version_label', {
                        version: rev.schema_version,
                        defaultValue: 'schema v{{version}}',
                      })}
                    </p>
                    <p className="text-muted-foreground">
                      {rev.created_at}
                      {rev.created_by ? ` · ${rev.created_by}` : ''}
                    </p>
                  </div>
                  <ConfirmDialog
                    trigger={
                      <Button type="button" variant="outline" size="sm">
                        {t('records.type_editor.revisions.restore', {
                          defaultValue: 'Restore this schema',
                        })}
                      </Button>
                    }
                    title={t('records.type_editor.revisions.restore', {
                      defaultValue: 'Restore this schema',
                    })}
                    description={t('records.type_editor.revisions.restore_confirm', {
                      version: rev.version,
                      defaultValue:
                        'Restore the schema from v{{version}}? This is checked the same way any other schema change is.',
                    })}
                    confirmLabel={t('records.type_editor.revisions.restore', {
                      defaultValue: 'Restore this schema',
                    })}
                    cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
                    pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
                    onConfirm={() => restore(rev.version)}
                  />
                </li>
              ))}
            </ul>
          )}

          <SchemaConflictPanel
            report={apply.report}
            conflicts={apply.conflicts}
            pending={apply.pending}
            onForce={() => apply.retryWith({ force: true })}
            onOrphaned={(choice) => apply.retryWith({ orphaned: choice })}
          />

          {apply.versionConflict && (
            <TypeConflictNotice
              current={apply.versionConflict}
              onReload={(server) => {
                onRestored(server);
                apply.reset();
              }}
            />
          )}
        </CardContent>
      )}
    </Card>
  );
}
