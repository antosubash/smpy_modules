import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { Spinner } from '@simple-module-py/ui/components/ui/spinner';
import { keys, type Translate, useT } from '../../utils/i18n';
import type { ParseFailure, TypeDefinition } from '../../utils/type-io';

function failureMessage(t: Translate, reason: ParseFailure): string {
  const labels: Record<ParseFailure, string> = {
    not_json: keys.records.type_io.error_not_json,
    not_object: keys.records.type_io.error_not_object,
    missing_key: keys.records.type_io.error_missing_key,
    missing_label: keys.records.type_io.error_missing_label,
    missing_fields: keys.records.type_io.error_missing_fields,
  };
  return t(labels[reason]);
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
          <DialogTitle>{t(keys.records.type_io.import_title)}</DialogTitle>
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
                ? t(keys.records.type_io.will_create, {
                    key: definition.key,
                    label: definition.label,
                  })
                : t(keys.records.type_io.will_update, {
                    key: definition.key,
                  })}
            </p>
            <p className="text-muted-foreground">
              {t(keys.records.type_io.field_count, {
                count: definition.fields.length,
              })}
            </p>
            <p className="text-muted-foreground">
              {creates ? t(keys.records.type_io.create_help) : t(keys.records.type_io.update_help)}
            </p>
          </div>
        )}

        <div className="flex justify-end gap-2">
          {/* U15: this used to say "Done" — chosen only to avoid colliding
              with the dialog's own X control (framework-owned, fixed
              accessible name "Close") — even on the parse-failure branch,
              where nothing was done. `apply()` (`TypeIoMenu`) closes this
              dialog itself the moment an import actually succeeds, so this
              button is never on screen *after* one did; "Cancel" is what
              it always means, without claiming a completion that has not
              happened. */}
          <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
            {t(keys.records.type_io.cancel)}
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
                  {t(keys.records.editor.saving)}
                </span>
              ) : (
                t(keys.records.type_io.apply)
              )}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
