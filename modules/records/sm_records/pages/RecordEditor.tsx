import { Head, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';

import { ConflictPanel } from '../components/ConflictPanel';
import { InvalidNotice } from '../components/InvalidNotice';
import { JsonField } from '../components/JsonField';
import { MediaApiProvider } from '../components/media/MediaApiContext';
import { RecordEditorActionsRow } from '../components/RecordEditorActionsRow';
import { RecordEditorTypeLink } from '../components/RecordEditorTypeLink';
import { RecordAdvancedFields, RecordHeaderFields } from '../components/RecordEnvelopeFields';
import { RecordForm } from '../components/RecordForm';
import { RecordReferrers } from '../components/RecordReferrers';
import { RecordRevisions } from '../components/RecordRevisions';
import { RecordEditorHeaderBadges } from '../components/RecordStatusBadge';
import { RecordsToaster } from '../components/RecordsToaster';
import { RecordTranslations } from '../components/RecordTranslations';
import { useRecordEditor } from '../hooks/useRecordEditor';
import { displayFieldKey } from '../utils/errors-display';
import type { MediaApi } from '../utils/media-api';
import { withCurrentPatched } from '../utils/record-types';
import type { RecordRead, TranslationRead, TypeRead } from '../utils/types';

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
  /** Where the `media` picker lists and uploads (`sm_records.media`); `null`
   *  or absent leaves a `media` field the plain text box. */
  media_api?: MediaApi | null;
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
 * restore/purge buttons in `RecordActions` are how it's reached from the UI.
 * Layout follows UX review R16: the record's own fields first, Status (and,
 * on a new translatable record, Language) in the header row beside Cancel,
 * and Slug/Position behind an "Advanced" disclosure under the form. */
function RecordEditor({
  type,
  record,
  referrer_count,
  translations,
  content_locales,
  default_locale,
  media_api,
}: Props) {
  const { t } = useT();
  const contentLocales = content_locales ?? [];
  const defaultLocale = default_locale ?? contentLocales[0] ?? 'en';
  // Only a new record on a translatable type with several locales gets to
  // pick one — an existing record's language is fixed for its lifetime.
  const showLocalePicker = record === null && type.translatable && contentLocales.length > 1;
  const {
    isNew,
    current,
    allowNavigation,
    status,
    slug,
    position,
    locale,
    conflict,
    pending,
    form,
    setStatus,
    setSlug,
    setPosition,
    setLocale,
    save,
    reloadFromConflict,
    applyRestored,
    duplicate,
  } = useRecordEditor(type, record, { showLocalePicker, defaultLocale });

  const backHref = `/admin/records/${type.key}`;
  const envelope = form.envelopeErrors;
  // Raw mode hides the per-field form, so the field-level 422s it would
  // have carried are listed here instead — otherwise a raw-mode save is
  // refused with nothing on screen saying why.
  const unplaceable = (form.raw ? form.serverErrors : envelope).filter(
    (entry) => !ENVELOPE_KEYS.includes(entry.field),
  );
  const slugSource = type.slug_field
    ? type.fields.find((field) => field.key === type.slug_field)?.label
    : undefined;

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
        // U14: was plain text (`type.label`) — no way back to the list but
        // Cancel/Back. `description` is a plain `string` (framework), so the
        // link below takes its place instead.
        actions={
          <>
            <RecordHeaderFields
              status={status}
              envelope={envelope}
              onStatusChange={setStatus}
              {...(showLocalePicker
                ? { locale, locales: contentLocales, onLocaleChange: setLocale }
                : {})}
            />
            {/* The guard in `useRecordEditor` is what asks about unsaved work
                here: this is an ordinary Inertia visit, and `router.on(
                'before')` sees it (R12c). */}
            <Button variant="outline" onClick={() => router.visit(backHref)}>
              {t('records.editor.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </>
        }
      >
        <RecordEditorTypeLink label={type.label} backHref={backHref} />
        {/* A real `<form>` (R13): Save was a `type="button"` inside plain
            `<div>`s, so the busiest data-entry screen in the module had no
            keyboard path to it — the argument `FilterBar` already makes for
            a screen people type into far less. `RelationPicker` swallows
            Enter while its listbox is open (the one collision); ⌘S/Ctrl+S
            lives in `useRecordEditor`. `noValidate`: `useRecordForm`'s
            validator is what refuses a save, and the browser's own bubble
            would pre-empt it with a message this module did not write. */}
        <form
          className="space-y-6"
          data-testid="records-editor-form"
          noValidate
          onSubmit={(event: React.FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            if (!pending) void save();
          }}
        >
          <RecordEditorHeaderBadges current={current} translatable={type.translatable} />

          {conflict && (
            <ConflictPanel
              current={conflict}
              yourData={form.currentPayloadText()}
              onReload={reloadFromConflict}
              onOverwrite={() => void save(conflict.version)}
            />
          )}

          {current && type.translatable && contentLocales.length > 1 && (
            <RecordTranslations
              typeKey={type.key}
              record={current}
              locales={contentLocales}
              translations={withCurrentPatched(translations ?? [], current)}
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
                  {displayFieldKey(entry.field)}: {entry.message}
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
            <MediaApiProvider value={media_api}>
              <RecordForm
                fields={type.fields}
                values={form.values}
                errors={form.fieldErrors}
                disabled={pending}
                onChange={form.setValue}
                expanded={current?.expanded ?? undefined}
              />
            </MediaApiProvider>
          )}

          <RecordAdvancedFields
            slug={slug}
            position={position}
            envelope={envelope}
            onSlugChange={setSlug}
            onPositionChange={setPosition}
            slugSourceLabel={slugSource}
          />

          <RecordEditorActionsRow
            typeKey={type.key}
            current={current}
            pending={pending}
            errorCount={form.errorCount}
            allowNavigation={allowNavigation}
            onRestored={applyRestored}
            onGone={() => router.visit(backHref)}
            onDuplicate={duplicate}
          />

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
        </form>
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
