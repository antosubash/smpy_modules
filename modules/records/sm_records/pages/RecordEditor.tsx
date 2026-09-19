import { Head, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';
import { useState } from 'react';
import { toast } from 'sonner';

import { ConflictPanel } from '../components/ConflictPanel';
import { JsonField } from '../components/JsonField';
import { RecordActions } from '../components/RecordActions';
import { RecordForm } from '../components/RecordForm';
import { useRecordForm } from '../hooks/useRecordForm';
import { ApiError, createRecord, updateRecord } from '../utils/api';
import type { RecordRead, RecordStatus, TypeRead, ValidationError } from '../utils/types';

type Props = { type: TypeRead; record: RecordRead | null };

const SLUG_ID = 'record-slug';
const POSITION_ID = 'record-position';
const STATUS_ID = 'record-status';
const DATA_ID = 'record-data';
/** The 422 `field` values that belong to an input outside the schema form. */
const ENVELOPE_KEYS = ['status', 'slug', 'position'];

function fieldMessage(errors: ValidationError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}

/** `Records/RecordEditor` — `/admin/records/{key}/new` and `/…/{uuid}`.
 *
 * The schema-driven form of design §12: `type.fields` in declaration order,
 * each rendered by `components/fields/`'s registry. The raw-JSON textarea it
 * replaced is still here behind an "advanced" toggle, because a payload the
 * generic form cannot express (a `json` field holding something exotic, a
 * key left behind by a deleted field) still has to be editable — and because
 * it round-trips, switching back re-populates the fields from what was typed.
 */
function RecordEditor({ type, record }: Props) {
  const { t } = useT();
  const isNew = record === null;
  const [current, setCurrent] = useState<RecordRead | null>(record);
  const [status, setStatus] = useState<RecordStatus>(record?.status ?? 'draft');
  const [slug, setSlug] = useState(record?.slug ?? '');
  const [position, setPosition] = useState(String(record?.position ?? 0));
  const [conflict, setConflict] = useState<RecordRead | null>(null);
  const [pending, setPending] = useState(false);
  const form = useRecordForm(type, record);

  const save = async () => {
    setConflict(null);
    const data = form.validateAndBuild();
    if (data === null) return;

    const payload = { data, status, slug: slug || null, position: Number(position) || 0 };
    setPending(true);
    try {
      const saved = isNew
        ? await createRecord(type.key, payload)
        : await updateRecord(type.key, current?.uuid ?? '', current?.version ?? 0, payload);
      if (isNew) {
        router.visit(`/admin/records/${type.key}/${saved.uuid}`);
        return;
      }
      setCurrent(saved);
      // The server can derive its own `slug` (and, in principle, adjust
      // `status`/`position`), so the envelope inputs have to re-sync from
      // what it actually stored — otherwise a server-derived slug doesn't
      // show until the next full reload.
      setStatus(saved.status);
      setSlug(saved.slug ?? '');
      setPosition(String(saved.position));
      form.reset(saved);
      toast.success(t('records.editor.saved', { defaultValue: 'Saved' }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.body?.current) {
        setConflict(err.body.current as RecordRead);
      } else if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
        form.setServerErrors(err.body.errors);
      } else {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  };

  const reloadFromConflict = (server: RecordRead) => {
    setCurrent(server);
    setStatus(server.status);
    setSlug(server.slug ?? '');
    setPosition(String(server.position));
    form.reset(server);
    setConflict(null);
  };

  const backHref = `/admin/records/${type.key}`;
  const envelope = form.envelopeErrors;
  // Raw mode hides the per-field form, so the field-level 422s it would have
  // carried are listed here instead — otherwise a save in raw mode is refused
  // with nothing on screen saying why.
  const unplaceable = (form.raw ? form.serverErrors : envelope).filter(
    (entry) => !ENVELOPE_KEYS.includes(entry.field),
  );

  return (
    <>
      <Head
        title={
          isNew
            ? t('records.editor.title_new', { defaultValue: 'New record' })
            : t('records.editor.title_edit', { defaultValue: 'Edit record' })
        }
      />
      <PageShell
        title={
          isNew
            ? t('records.editor.title_new', { defaultValue: 'New record' })
            : (current?.display_title ?? type.label)
        }
        description={type.label}
        actions={
          <Button variant="outline" onClick={() => router.visit(backHref)}>
            {t('records.editor.cancel', { defaultValue: 'Cancel' })}
          </Button>
        }
      >
        <div className="space-y-6">
          {current?.schema_stale && (
            <Badge variant="outline" className="border-amber-500 text-amber-600">
              {t('records.editor.schema_stale', {
                defaultValue: 'Fields changed since this was saved',
              })}
            </Badge>
          )}
          {current?.is_deleted && (
            <Badge variant="destructive">
              {t('records.editor.deleted_badge', { defaultValue: 'Deleted' })}
            </Badge>
          )}

          {conflict && (
            <ConflictPanel
              current={conflict}
              yourData={form.currentPayloadText()}
              onReload={reloadFromConflict}
            />
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor={STATUS_ID}>
                {t('records.records.status', { defaultValue: 'Status' })}
              </Label>
              <NativeSelect
                id={STATUS_ID}
                className="w-full"
                value={status}
                onChange={(e) => setStatus(e.target.value as RecordStatus)}
              >
                <NativeSelectOption value="draft">
                  {t('records.records.draft', { defaultValue: 'Draft' })}
                </NativeSelectOption>
                <NativeSelectOption value="published">
                  {t('records.records.published', { defaultValue: 'Published' })}
                </NativeSelectOption>
              </NativeSelect>
              {fieldMessage(envelope, 'status') && (
                <p className="text-sm text-destructive">{fieldMessage(envelope, 'status')}</p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={SLUG_ID}>
                {t('records.editor.slug_label', { defaultValue: 'Slug' })}
              </Label>
              <Input id={SLUG_ID} value={slug} onChange={(e) => setSlug(e.target.value)} />
              {fieldMessage(envelope, 'slug') && (
                <p className="text-sm text-destructive">{fieldMessage(envelope, 'slug')}</p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={POSITION_ID}>
                {t('records.editor.position_label', { defaultValue: 'Position' })}
              </Label>
              <Input
                id={POSITION_ID}
                type="number"
                value={position}
                onChange={(e) => setPosition(e.target.value)}
              />
              {fieldMessage(envelope, 'position') && (
                <p className="text-sm text-destructive">{fieldMessage(envelope, 'position')}</p>
              )}
            </div>
          </div>

          {unplaceable.length > 0 && (
            <ul className="space-y-1 text-sm text-destructive" role="alert">
              {unplaceable.map((entry) => (
                <li key={`${entry.field}:${entry.message}`}>
                  {entry.field}: {entry.message}
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-medium uppercase text-muted-foreground">
              {t('records.editor.fields_heading', { defaultValue: 'Fields' })}
            </h2>
            <Button type="button" variant="ghost" size="sm" onClick={form.toggleRaw}>
              {form.raw
                ? t('records.editor.use_form', { defaultValue: 'Back to the form' })
                : t('records.editor.use_raw_json', { defaultValue: 'Advanced: edit raw JSON' })}
            </Button>
          </div>

          {form.raw ? (
            <JsonField
              id={DATA_ID}
              label={t('records.editor.data_label', { defaultValue: 'Data' })}
              helpText={t('records.editor.data_help', {
                defaultValue:
                  "Raw JSON for this record's fields. Switching back re-fills the form from it.",
              })}
              value={form.rawText}
              onChange={form.setRawText}
              error={form.rawError}
            />
          ) : (
            <RecordForm
              fields={type.fields}
              values={form.values}
              errors={form.fieldErrors}
              disabled={pending}
              onChange={form.setValue}
            />
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" disabled={pending} onClick={() => void save()}>
              {pending
                ? t('records.editor.saving', { defaultValue: 'Saving…' })
                : t('records.editor.save', { defaultValue: 'Save' })}
            </Button>

            {current && (
              <RecordActions
                typeKey={type.key}
                record={current}
                onRestored={(restored) => {
                  setCurrent(restored);
                  form.reset(restored);
                }}
                onGone={() => router.visit(backHref)}
              />
            )}
          </div>
        </div>
      </PageShell>
    </>
  );
}

RecordEditor.layout = (page: React.ReactNode) => <AdminLayout>{page}</AdminLayout>;
export default RecordEditor;
