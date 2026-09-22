import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { Spinner } from '@simple-module-py/ui/components/ui/spinner';

import type { ParseFailure, TypeDefinition } from '../../utils/type-io';

// See `FilterBar.tsx` for why `t` is typed this loosely here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

function failureMessage(t: Translate, reason: ParseFailure): string {
  const defaults: Record<ParseFailure, string> = {
    not_json: "That file isn't valid JSON — open it in a text editor and check it's complete.",
    not_object: "That file isn't a type definition: the top level has to be a JSON object.",
    missing_key: 'That definition has no "key", so there is no type to create or update.',
    missing_label: 'That definition has no "label".',
    missing_fields: 'That definition has no "fields" list.',
  };
  return t(`records.type_io.error_${reason}`, { defaultValue: defaults[reason] });
}

/**
 * What a picked definition would do, before it does it (M3).
 *
 * The same shape the record import takes: nothing is written until the
 * summary on screen has been read and Apply pressed. The check itself is
 * necessarily lighter than the record import's, because `POST /types/import`
 * has no `dry_run` — what it has instead is the §8 pipeline: `mode=update`
 * routes through `update_type`, so a definition that would break records is
 * classified and refused with the same report (and the same "Apply anyway")
 * as the equivalent edit made by hand in the editor below. This dialog says
 * which of the two modes the file lands in and what it carries; the server
 * says whether it is safe.
 */
export function TypeImportDialog({
  fileName,
  definition,
  failure,
  currentKey,
  pending,
  onApply,
  onClose,
}: {
  fileName: string | null;
  definition: TypeDefinition | null;
  failure: ParseFailure | null;
  /** The type being edited — a definition naming a different key creates a
   *  new type instead of updating this one, and the summary says so. */
  currentKey: string | null;
  pending: boolean;
  onApply: () => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const open = definition !== null || failure !== null;
  const creates = definition !== null && definition.key !== currentKey;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="records-type-import-dialog">
        <DialogHeader>
          <DialogTitle>
            {t('records.type_io.import_title', { defaultValue: 'Import a type definition' })}
          </DialogTitle>
        </DialogHeader>

        {fileName && (
          <p className="text-sm text-muted-foreground" data-testid="records-type-import-file">
            {fileName}
          </p>
        )}

        {failure && (
          <p className="text-sm text-destructive" role="alert">
            {failureMessage(t, failure)}
          </p>
        )}

        {definition && (
          <div className="space-y-1 text-sm" data-testid="records-type-import-summary">
            <p>
              {creates
                ? t('records.type_io.will_create', {
                    key: definition.key,
                    label: definition.label,
                    defaultValue: 'Creates a new type "{label}" ({key}).',
                  })
                : t('records.type_io.will_update', {
                    key: definition.key,
                    defaultValue: 'Updates this type ({key}) from the definition.',
                  })}
            </p>
            <p className="text-muted-foreground">
              {t('records.type_io.field_count', {
                count: definition.fields.length,
                defaultValue: '{count} field',
                defaultValue_other: '{count} fields',
              })}
            </p>
            <p className="text-muted-foreground">
              {creates
                ? t('records.type_io.create_help', {
                    defaultValue:
                      'Nothing about the type you are editing changes; you will land on the new type.',
                  })
                : t('records.type_io.update_help', {
                    defaultValue:
                      'Checked against this type’s records first, exactly as the same change made here would be — anything it would break is reported instead of applied.',
                  })}
            </p>
          </div>
        )}

        <div className="flex justify-end gap-2">
          {/* U15: the dialog's own X control (framework-owned) has the fixed
              accessible name "Close" — naming this button the same thing
              gave the dialog two controls with one name. */}
          <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
            {t('records.io.close', { defaultValue: 'Done' })}
          </Button>
          {definition && (
            <Button
              type="button"
              disabled={pending}
              data-testid="records-type-import-apply"
              onClick={onApply}
            >
              {pending ? (
                <span className="inline-flex items-center gap-1.5">
                  <Spinner className="size-3.5" />
                  {t('records.editor.saving', { defaultValue: 'Saving…' })}
                </span>
              ) : (
                t('records.type_io.apply', { defaultValue: 'Import definition' })
              )}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
