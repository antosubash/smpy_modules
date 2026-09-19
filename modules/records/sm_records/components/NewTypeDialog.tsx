import { router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';

import { ApiError, createType } from '../utils/api';
import type { FieldDef } from '../utils/types';
import { JsonField } from './JsonField';

/** What a brand-new type starts with: one text field, so the JSON textarea
 *  below is never empty and always shows valid shape to copy from. */
const EXAMPLE_FIELDS: FieldDef[] = [
  {
    key: 'title',
    type: 'text',
    label: 'Title',
    required: true,
    unique: false,
    indexed: true,
    default: null,
    help: null,
    constraints: {},
    options: {},
  },
];

const KEY_ID = 'new-type-key';
const LABEL_ID = 'new-type-label';
const LABEL_PLURAL_ID = 'new-type-label-plural';
const FIELDS_ID = 'new-type-fields';

type FieldErrors = Record<string, string>;

function fieldErrorsFrom(err: unknown): FieldErrors {
  if (!(err instanceof ApiError) || !err.body?.errors) return {};
  const out: FieldErrors = {};
  for (const e of err.body.errors) out[e.field] = e.message;
  return out;
}

/** "New type" — key, label, label_plural, and the field list as raw JSON.
 *
 * The schema editor from the design doc's `TypeEditor.tsx` is Phase 2; this
 * dialog is the whole of Phase 1's type-authoring surface, which is why the
 * field list is a textarea rather than a form. */
export function NewTypeDialog() {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState('');
  const [label, setLabel] = useState('');
  const [labelPlural, setLabelPlural] = useState('');
  const [fieldsText, setFieldsText] = useState(JSON.stringify(EXAMPLE_FIELDS, null, 2));
  const [fieldsError, setFieldsError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [conflict, setConflict] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const reset = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    if (!next) {
      setKey('');
      setLabel('');
      setLabelPlural('');
      setFieldsText(JSON.stringify(EXAMPLE_FIELDS, null, 2));
      setFieldsError(null);
      setFieldErrors({});
      setConflict(null);
    }
  };

  const submit = async () => {
    setFieldsError(null);
    setFieldErrors({});
    setConflict(null);

    let fields: FieldDef[];
    try {
      fields = JSON.parse(fieldsText) as FieldDef[];
    } catch {
      setFieldsError(t('records.editor.invalid_json', { defaultValue: 'Invalid JSON' }));
      return;
    }

    setPending(true);
    try {
      const created = await createType({ key, label, label_plural: labelPlural, fields });
      router.visit(`/admin/records/${created.key}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflict(err.body?.detail ?? err.message);
      } else if (err instanceof ApiError && err.status === 422) {
        setFieldErrors(fieldErrorsFrom(err));
      } else {
        setConflict(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <Button type="button">{t('records.types.new', { defaultValue: 'New type' })}</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('records.types.new', { defaultValue: 'New type' })}</DialogTitle>
          <DialogDescription>
            {t('records.types.new_dialog_help', {
              defaultValue: 'Define a key, its labels, and the fields it starts with.',
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor={KEY_ID}>{t('records.types.key', { defaultValue: 'Key' })}</Label>
            <Input id={KEY_ID} value={key} onChange={(e) => setKey(e.target.value)} />
            {fieldErrors.key && <p className="text-sm text-destructive">{fieldErrors.key}</p>}
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={LABEL_ID}>{t('records.types.label', { defaultValue: 'Label' })}</Label>
            <Input id={LABEL_ID} value={label} onChange={(e) => setLabel(e.target.value)} />
            {fieldErrors.label && <p className="text-sm text-destructive">{fieldErrors.label}</p>}
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={LABEL_PLURAL_ID}>
              {t('records.types.label_plural', { defaultValue: 'Plural label' })}
            </Label>
            <Input
              id={LABEL_PLURAL_ID}
              value={labelPlural}
              onChange={(e) => setLabelPlural(e.target.value)}
            />
            {fieldErrors.label_plural && (
              <p className="text-sm text-destructive">{fieldErrors.label_plural}</p>
            )}
          </div>
          <JsonField
            id={FIELDS_ID}
            label={t('records.types.fields_label', { defaultValue: 'Fields' })}
            helpText={t('records.types.fields_help', {
              defaultValue: 'A JSON array of field definitions.',
            })}
            value={fieldsText}
            onChange={setFieldsText}
            error={fieldsError ?? fieldErrors.fields}
            rows={10}
          />
          {conflict && (
            <p className="text-sm text-destructive" role="alert">
              {conflict}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => reset(false)} disabled={pending}>
            {t('records.editor.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            type="button"
            disabled={pending || !key || !label || !labelPlural}
            onClick={() => void submit()}
          >
            {pending
              ? t('records.editor.saving', { defaultValue: 'Saving…' })
              : t('records.types.create', { defaultValue: 'Create' })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
