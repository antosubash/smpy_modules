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
import { ApiError, createRecord, updateRecord } from '../utils/api';
import type { RecordRead, RecordStatus, TypeRead, ValidationError } from '../utils/types';

type Props = { type: TypeRead; record: RecordRead | null };

const SLUG_ID = 'record-slug';
const POSITION_ID = 'record-position';
const STATUS_ID = 'record-status';
const DATA_ID = 'record-data';

function fieldMessage(errors: ValidationError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}

/** `Records/RecordEditor` — `/admin/records/{key}/new` and `/…/{uuid}`.
 *
 * Phase 1's form: status, slug, position, and the record's `data` as raw
 * JSON. The schema-driven per-field form is Phase 2. */
function RecordEditor({ type, record }: Props) {
  const { t } = useT();
  const isNew = record === null;
  const [current, setCurrent] = useState<RecordRead | null>(record);
  const [status, setStatus] = useState<RecordStatus>(record?.status ?? 'draft');
  const [slug, setSlug] = useState(record?.slug ?? '');
  const [position, setPosition] = useState(String(record?.position ?? 0));
  const [dataText, setDataText] = useState(JSON.stringify(record?.data ?? {}, null, 2));
  const [dataError, setDataError] = useState<string | null>(null);
  const [errors, setErrors] = useState<ValidationError[]>([]);
  const [conflict, setConflict] = useState<RecordRead | null>(null);
  const [pending, setPending] = useState(false);

  const save = async () => {
    setDataError(null);
    setErrors([]);
    setConflict(null);

    let data: Record<string, unknown>;
    try {
      const parsed = JSON.parse(dataText);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('not an object');
      }
      data = parsed as Record<string, unknown>;
    } catch {
      setDataError(t('records.editor.invalid_json', { defaultValue: 'Invalid JSON' }));
      return;
    }

    const payload = {
      data,
      status,
      slug: slug || null,
      position: Number(position) || 0,
    };

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
      toast.success(t('records.editor.saved', { defaultValue: 'Saved' }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.body?.current) {
        setConflict(err.body.current as RecordRead);
      } else if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
        setErrors(err.body.errors);
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
    setDataText(JSON.stringify(server.data, null, 2));
    setConflict(null);
  };

  const dataFieldErrors = errors.filter((e) => e.field === 'data' || e.field.startsWith('data.'));
  const dataErrorText =
    dataError ??
    (dataFieldErrors.length
      ? dataFieldErrors.map((e) => `${e.field}: ${e.message}`).join('; ')
      : undefined);

  const backHref = `/admin/records/${type.key}`;

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
            <ConflictPanel current={conflict} yourData={dataText} onReload={reloadFromConflict} />
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor={STATUS_ID}>
                {t('records.records.status', { defaultValue: 'Status' })}
              </Label>
              <NativeSelect
                id={STATUS_ID}
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
              {fieldMessage(errors, 'status') && (
                <p className="text-sm text-destructive">{fieldMessage(errors, 'status')}</p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={SLUG_ID}>
                {t('records.editor.slug_label', { defaultValue: 'Slug' })}
              </Label>
              <Input id={SLUG_ID} value={slug} onChange={(e) => setSlug(e.target.value)} />
              {fieldMessage(errors, 'slug') && (
                <p className="text-sm text-destructive">{fieldMessage(errors, 'slug')}</p>
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
              {fieldMessage(errors, 'position') && (
                <p className="text-sm text-destructive">{fieldMessage(errors, 'position')}</p>
              )}
            </div>
          </div>

          <JsonField
            id={DATA_ID}
            label={t('records.editor.data_label', { defaultValue: 'Data' })}
            helpText={t('records.editor.data_help', {
              defaultValue: "Raw JSON for this record's fields.",
            })}
            value={dataText}
            onChange={setDataText}
            error={dataErrorText}
          />

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
                onRestored={setCurrent}
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
