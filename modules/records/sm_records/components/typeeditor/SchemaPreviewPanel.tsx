import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

import { previewSchema } from '../../utils/api';
import type { FieldDef, SchemaPreview } from '../../utils/types';
import { DryRunReportView } from './DryRunReportView';
import { SchemaChangeList } from './SchemaChangeList';

/**
 * "Preview changes": `POST .../schema/preview` writes nothing (design
 * §8.9) — it classifies the proposed `fields` and dry-runs it, so this
 * button is safe to press as often as the draft changes.
 *
 * The result is treated as stale the moment `fields` moves to a new
 * reference — tracked by holding on to the exact `fields` a preview was
 * fetched for and comparing rather than clearing it from an effect — so a
 * fresh keystroke after "Preview changes" can't leave a report on screen
 * that no longer matches the draft.
 */
export function SchemaPreviewPanel({
  typeKey,
  fields,
  displayField,
  slugField,
  dirty,
}: {
  typeKey: string;
  fields: FieldDef[];
  /** The editor's current `display_field`/`slug_field` form values (empty
   *  string = cleared) — sent alongside `fields` on every preview so a
   *  pointer-only edit (no field added/removed/changed) doesn't preview as
   *  "No changes" (F5). */
  displayField: string;
  slugField: string;
  dirty: boolean;
}) {
  const { t } = useT();
  const [preview, setPreview] = useState<SchemaPreview | null>(null);
  const [previewedFields, setPreviewedFields] = useState<FieldDef[] | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stale = preview !== null && previewedFields !== fields;

  const runPreview = async () => {
    setPending(true);
    setError(null);
    try {
      const result = await previewSchema(typeKey, {
        fields,
        display_field: displayField || null,
        slug_field: slugField || null,
      });
      setPreview(result);
      setPreviewedFields(fields);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="space-y-4">
      <Button
        type="button"
        variant="outline"
        disabled={!dirty || pending}
        onClick={() => void runPreview()}
      >
        {pending
          ? t('records.type_editor.preview.checking', { defaultValue: 'Checking…' })
          : t('records.type_editor.preview.button', { defaultValue: 'Preview changes' })}
      </Button>
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      {preview && !stale && (
        <div className="space-y-3 rounded-md border p-4" data-testid="records-schema-preview">
          <SchemaChangeList preview={preview} />
          <DryRunReportView report={preview.report} />
        </div>
      )}
    </div>
  );
}
