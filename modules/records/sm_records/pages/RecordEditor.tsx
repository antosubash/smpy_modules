import { Head, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';
import { useState } from 'react';
import { toast } from 'sonner';

import { ConflictPanel } from '../components/ConflictPanel';
import { InvalidNotice } from '../components/InvalidNotice';
import { JsonField } from '../components/JsonField';
import { RecordActions } from '../components/RecordActions';
import { RecordEnvelopeFields } from '../components/RecordEnvelopeFields';
import { RecordForm } from '../components/RecordForm';
import { RecordReferrers } from '../components/RecordReferrers';
import { RecordRevisions } from '../components/RecordRevisions';
import { RecordEditorHeaderBadges } from '../components/RecordStatusBadge';
import { RecordsToaster } from '../components/RecordsToaster';
import { RecordTranslations } from '../components/RecordTranslations';
import { useRecordForm } from '../hooks/useRecordForm';
import { ApiError, createRecord, updateRecord } from '../utils/api';
import type { RecordRead, RecordStatus, TranslationRead, TypeRead } from '../utils/types';

type Props = {
  type: TypeRead;
  record: RecordRead | null;
  /** "Referenced by" badge count — absent on the new-record screen. */
  referrer_count?: number;
  /** The record's translation group, current record included — `[]` on the
   *  new-record screen, which has no group yet (`views.py::record_new`). */
  translations?: TranslationRead[];
  /** Every content locale the module is configured for (design §4.4); absent
   *  degrades to "no language UI", as `news`' list screen treats it. */
  content_locales?: string[];
  default_locale?: string;
};

const DATA_ID = 'record-data';
/** The 422 `field` values that belong to an input outside the schema form. */
const ENVELOPE_KEYS = ['status', 'slug', 'position'];

/** `Records/RecordEditor` — `/admin/records/{key}/new` and `/…/{uuid}`.
 *
 * The schema-driven form of design §12: `type.fields` in declaration order,
 * each rendered by `components/fields/`'s registry, with a raw-JSON "advanced"
 * toggle for a payload the form can't express — it round-trips, so switching
 * back re-populates the fields from what was typed. A trashed record loads
 * here too (for `records.edit`): the `Deleted` badge above and the
 * restore/purge buttons in `RecordActions` are how it's reached from the UI. */
function RecordEditor({
  type,
  record,
  referrer_count,
  translations,
  content_locales,
  default_locale,
}: Props) {
  const { t } = useT();
  const isNew = record === null;
  const contentLocales = content_locales ?? [];
  const defaultLocale = default_locale ?? contentLocales[0] ?? 'en';
  // Only a new record on a translatable type with several locales gets to
  // pick one — an existing record's language is fixed for its lifetime.
  const showLocalePicker = isNew && type.translatable && contentLocales.length > 1;
  const [current, setCurrent] = useState<RecordRead | null>(record);
  const [status, setStatus] = useState<RecordStatus>(record?.status ?? 'draft');
  const [slug, setSlug] = useState(record?.slug ?? '');
  const [position, setPosition] = useState(String(record?.position ?? 0));
  const [locale, setLocale] = useState(defaultLocale);
  const [conflict, setConflict] = useState<RecordRead | null>(null);
  const [pending, setPending] = useState(false);
  const form = useRecordForm(type, record);

  const save = async () => {
    setConflict(null);
    const data = form.validateAndBuild();
    if (data === null) return;

    const payload = {
      data,
      status,
      slug: slug || null,
      position: Number(position) || 0,
      ...(showLocalePicker ? { locale } : {}),
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

  /** A trash-restore (`RecordActions`) and a revision restore (`RecordRevisions`)
   *  both hand back a fresh `RecordRead`, so the envelope inputs and form re-sync. */
  const applyRestored = (restored: RecordRead) => {
    setCurrent(restored);
    setStatus(restored.status);
    setSlug(restored.slug ?? '');
    setPosition(String(restored.position));
    form.reset(restored);
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
          <RecordEditorHeaderBadges current={current} translatable={type.translatable} />

          {conflict && (
            <ConflictPanel
              current={conflict}
              yourData={form.currentPayloadText()}
              onReload={reloadFromConflict}
            />
          )}

          <RecordEnvelopeFields
            status={status}
            slug={slug}
            position={position}
            envelope={envelope}
            onStatusChange={setStatus}
            onSlugChange={setSlug}
            onPositionChange={setPosition}
            {...(showLocalePicker
              ? { locale, locales: contentLocales, onLocaleChange: setLocale }
              : {})}
          />

          {current && type.translatable && contentLocales.length > 1 && (
            <RecordTranslations
              typeKey={type.key}
              record={current}
              locales={contentLocales}
              translations={translations ?? []}
            />
          )}

          {unplaceable.length > 0 && (
            <ul
              className="space-y-1 text-sm text-destructive"
              role="alert"
              data-testid="records-unplaceable-errors"
            >
              {unplaceable.map((entry) => (
                <li key={`${entry.field}:${entry.message}`}>
                  {entry.field}: {entry.message}
                </li>
              ))}
            </ul>
          )}

          <InvalidNotice errors={current?.invalid ?? []} />

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
              expanded={current?.expanded ?? undefined}
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
                onRestored={applyRestored}
                onGone={() => router.visit(backHref)}
              />
            )}
          </div>

          {current && (
            <RecordReferrers
              typeKey={type.key}
              uuid={current.uuid}
              referrerCount={referrer_count ?? 0}
            />
          )}

          {current && (
            <RecordRevisions
              typeKey={type.key}
              uuid={current.uuid}
              currentVersion={current.version}
              onRestored={applyRestored}
            />
          )}
        </div>
      </PageShell>
    </>
  );
}

RecordEditor.layout = (page: React.ReactNode) => (
  <AdminLayout>
    {page}
    <RecordsToaster />
  </AdminLayout>
);
export default RecordEditor;
