import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';
import { ApiError, deleteType } from '../../utils/api';
import type { TypeRead } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';

/**
 * The danger zone: delete this type and everything stored against it.
 *
 * `DELETE /types/{key}` requires `confirm_record_count` to equal the exact
 * `record_count + trashed_record_count` the operator was shown (design
 * §8.9) — content that arrived between opening this dialog and clicking
 * confirm makes the confirmation stale, and refusing is the only honest
 * answer. So the confirmation is "type the number", not a plain yes/no:
 * typing the count is what proves the operator saw the number this call is
 * about to compare against.
 */
export function DeleteTypeSection({ type, onDeleted }: { type: TypeRead; onDeleted: () => void }) {
  const { t } = useT();
  const [typed, setTyped] = useState('');
  const [referrers, setReferrers] = useState<string[] | null>(null);
  const total = type.record_count + type.trashed_record_count;

  const confirm = async () => {
    if (Number(typed) !== total || typed.trim() === '') {
      throw new Error(
        t('records.type_editor.delete_count_mismatch', {
          defaultValue: "That doesn't match. Type the exact number to confirm.",
        }),
      );
    }
    try {
      await deleteType(type.key, total);
      onDeleted();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.body?.referrers) {
        setReferrers(err.body.referrers);
      }
      throw err;
    }
  };

  const inputId = 'type-editor-delete-confirm';

  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle role="heading" aria-level={2} className="text-destructive">
          {t('records.type_editor.danger_zone', { defaultValue: 'Danger zone' })}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {t('records.type_editor.delete_help', {
            defaultValue:
              'Deletes this type and every record stored against it, including the trash. This cannot be undone.',
          })}
        </p>

        {referrers && referrers.length > 0 && (
          <div className="rounded-md border border-destructive/50 p-3 text-sm">
            <p className="font-medium text-destructive">
              {t('records.type_editor.referrers_notice', {
                defaultValue: 'Other types still have a relation field pointing at this one:',
              })}
            </p>
            <ul className="mt-1 list-inside list-disc">
              {referrers.map((key) => (
                <li key={key}>{key}</li>
              ))}
            </ul>
          </div>
        )}

        <ConfirmDialog
          trigger={
            <Button type="button" variant="destructive">
              {t('records.type_editor.delete_type', { defaultValue: 'Delete this type' })}
            </Button>
          }
          title={t('records.type_editor.delete_type', { defaultValue: 'Delete this type' })}
          description={t('records.type_editor.delete_confirm_description', {
            count: total,
            defaultValue:
              'This permanently deletes "{label}" and its {count} record(s) (live and trashed). Type {count} to confirm.',
            label: type.label,
          })}
          body={
            <div className="grid gap-2">
              <Label htmlFor={inputId}>
                {t('records.type_editor.delete_confirm_label', { defaultValue: 'Record count' })}
              </Label>
              <Input
                id={inputId}
                inputMode="numeric"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
              />
            </div>
          }
          // Reopening the dialog used to show the previous attempt's
          // digits, which read as though the count had already been
          // confirmed (polish note).
          onOpenChange={(open) => {
            if (!open) setTyped('');
          }}
          confirmLabel={t('records.records.delete', { defaultValue: 'Delete' })}
          cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
          pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
          destructive
          onConfirm={confirm}
        />
      </CardContent>
    </Card>
  );
}
