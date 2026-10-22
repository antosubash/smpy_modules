import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { useState } from 'react';
import { toast } from 'sonner';
import { ApiError } from '../utils/api';
import { getRecordRevision, listRevisions, restoreRecordRevision } from '../utils/api-history';
import { keys, type Translate, useT } from '../utils/i18n';
import type {
  RecordRead,
  RecordRevision,
  RecordRevisionDetail,
  ValidationError,
} from '../utils/types';
import { formatDateTime } from '../utils/values';
import { ConfirmDialog } from './ConfirmDialog';

/**
 * A collapsible panel over `GET .../revisions` (design §15's per-record
 * history): every prior version of this record, newest first. Clicking one
 * loads its full payload read-only before committing to anything; "Restore
 * this version" re-sends that payload as a normal versioned write, so it can
 * hit the same `409` (someone else saved meanwhile) or `422` (the schema has
 * moved on since — §8.3's "invalid under current schema" case) any other
 * save can.
 */
/** `RevisionEvent` (`models/_record.py`) as a word rather than the wire
 *  value `create`/`update`/`delete`/`restore` (R11). An event this build
 *  does not know still prints, as itself. Exported for its own test, the
 *  way `RecordDeleteDialog` exports its two halves. */
export function revisionEvent(t: Translate, event: string): string {
  const labels: Record<string, string> = {
    create: keys.records.editor.revisions.event.create,
    update: keys.records.editor.revisions.event.update,
    delete: keys.records.editor.revisions.event.delete,
    restore: keys.records.editor.revisions.event.restore,
  };
  const key = labels[event];
  return key ? t(key) : event;
}

export function RecordRevisions({
  typeKey,
  uuid,
  currentVersion,
  onRestored,
}: {
  typeKey: string;
  uuid: string;
  currentVersion: number;
  onRestored: (restored: RecordRead) => void;
}) {
  const { t, locale } = useT();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<RecordRevision[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<RecordRevisionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const load = async () => {
    setLoadError(null);
    try {
      const { items: list } = await listRevisions(typeKey, uuid);
      setItems(list);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && items === null) void load();
  };

  const showDetail = async (revision: RecordRevision) => {
    setDetailError(null);
    setRestoreError(null);
    setSelected(null);
    try {
      setSelected(await getRecordRevision(typeKey, uuid, revision.id));
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err));
    }
  };

  // A successful restore creates a new revision snapshot on the server (of
  // the data *before* the restore), so the list this panel is already
  // showing is stale the moment `onRestored` fires — reload it here (mirrors
  // `typeeditor/TypeRevisions.tsx`'s own restore handler, M4) so the new
  // revision shows up without the admin having to collapse and reopen the
  // panel.
  const restore = async (revision: RecordRevisionDetail) => {
    setRestoreError(null);
    try {
      const restored = await restoreRecordRevision(typeKey, uuid, revision.id, currentVersion);
      onRestored(restored);
      setSelected(null);
      toast.success(t(keys.records.editor.revisions.restored));
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
        setRestoreError(
          formatSchemaMismatch(t, err.body.errors) ??
            t(keys.records.editor.revisions.restore_schema_mismatch),
        );
      } else if (err instanceof ApiError && err.status === 409) {
        setRestoreError(t(keys.records.editor.conflict_title));
      } else {
        setRestoreError(err instanceof Error ? err.message : String(err));
      }
      throw err;
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        {/* See `RecordReferrers` for why the role is spelled out (R15). */}
        <CardTitle role="heading" aria-level={2}>
          {t(keys.records.editor.revisions.title)}
        </CardTitle>
        {/* This panel's own keys, not the type editor's: the two screens are
            free to word their toggles differently, and sharing a key made
            "one vocabulary per screen" (R14) a cross-screen argument. */}
        <Button type="button" variant="ghost" size="sm" onClick={toggle}>
          {open ? t(keys.records.editor.revisions.hide) : t(keys.records.editor.revisions.show)}
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
              {t(keys.records.type_editor.revisions.loading)}
            </p>
          )}
          {items?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {t(keys.records.editor.revisions.empty)}
            </p>
          )}
          {items && items.length > 0 && (
            <ul className="space-y-2">
              {items.map((rev) => (
                <li
                  key={rev.id}
                  className="rounded-md border p-3 text-sm"
                  data-testid="records-revision-item"
                >
                  <button
                    type="button"
                    className="w-full text-left"
                    onClick={() => void showDetail(rev)}
                  >
                    <p className="font-medium">
                      {t(keys.records.type_editor.revisions.version_label, {
                        version: rev.version,
                      })}
                      {' · '}
                      {revisionEvent(t, rev.event)}
                      {' · '}
                      {rev.display_title}
                    </p>
                    <p className="text-muted-foreground">
                      {formatDateTime(rev.created_at, locale)}
                      {rev.created_by ? ` · ${rev.created_by}` : ''}
                    </p>
                  </button>

                  {selected?.id === rev.id && (
                    <div className="mt-3 space-y-2 border-t pt-3">
                      <pre className="max-h-60 overflow-auto rounded-md border bg-muted p-2 text-xs">
                        {JSON.stringify(selected.data, null, 2)}
                      </pre>
                      {restoreError && (
                        <p className="text-sm text-destructive" role="alert">
                          {restoreError}
                        </p>
                      )}
                      <ConfirmDialog
                        trigger={
                          <Button type="button" variant="outline" size="sm">
                            {t(keys.records.editor.revisions.restore)}
                          </Button>
                        }
                        title={t(keys.records.editor.revisions.restore)}
                        description={t(keys.records.editor.revisions.restore_confirm, {
                          version: rev.version,
                        })}
                        confirmLabel={t(keys.records.editor.revisions.restore)}
                        onConfirm={() => restore(selected)}
                      />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          {detailError && (
            <p className="text-sm text-destructive" role="alert">
              {detailError}
            </p>
          )}
        </CardContent>
      )}
    </Card>
  );
}

/** The old data no longer fits the current schema — summarise the 422 list
 *  rather than showing nothing, since "restore failed" alone doesn't say
 *  why. `null` when the list is empty, so the caller's own fallback text
 *  shows instead. */
function formatSchemaMismatch(t: Translate, errors: ValidationError[]): string | null {
  if (errors.length === 0) return null;
  const detail = errors.map((e) => `${e.field}: ${e.message}`).join('; ');
  return t(keys.records.editor.revisions.restore_schema_mismatch_detail, {
    detail,
  });
}
