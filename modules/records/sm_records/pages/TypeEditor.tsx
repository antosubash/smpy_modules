import { Head, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { RecordsToaster } from '../components/RecordsToaster';
import { groupErrors } from '../components/typeeditor/errors';
import { FieldsCard } from '../components/typeeditor/FieldsCard';
import {
  buildChanges,
  extraCreateFields,
  metadataFrom,
  schemaIsDirty,
  stripUids,
  typeIsDirty,
  withUids,
} from '../components/typeeditor/formHelpers';
import { PointerFields } from '../components/typeeditor/PointerFields';
import { ReindexStatus } from '../components/typeeditor/ReindexStatus';
import { SaveBar } from '../components/typeeditor/SaveBar';
import { TypeConflictNotice } from '../components/typeeditor/TypeConflictNotice';
import { TypeEditorFooter } from '../components/typeeditor/TypeEditorFooter';
import { TypeMetadataForm } from '../components/typeeditor/TypeMetadataForm';
import type { EditableField, TypeEditorProps } from '../components/typeeditor/types';
import type { SchemaApplyBody } from '../hooks/useSchemaApply';
import { useSchemaApply } from '../hooks/useSchemaApply';
import { useUnsavedGuard } from '../hooks/useUnsavedGuard';
import { ApiError, createType, updateType } from '../utils/api';
import type { DryRunReport, TypeRead, ValidationError } from '../utils/types';

const TYPES_LIST_HREF = '/admin/records/';

/** `Records/TypeEditor` — `/admin/records/types/new` and `/…/types/{key}`.
 *
 * The schema editor from design §6.1/§7.2/§16: type metadata, the field
 * list (with `indexed` — "the single most consequential choice on the
 * screen", §7.2 — named once in the Fields card header), the two field
 * pointers *below* it (UX review R19: on a new type they have nothing to
 * point at until a field exists), and, on an existing type, the danger zone.
 * Phase 3 lifts the Phase 1 lock: a populated type's `fields`,
 * `display_field` and `slug_field` are editable here too, checked by
 * "Preview changes" before saving and by the save itself, which the server
 * enforces with a dry-run (§8.2) rather than trusting the client to have run
 * one. */
function TypeEditor({
  type,
  target_types,
  roles,
  public_route_prefix,
  content_locales,
  collections,
}: TypeEditorProps) {
  const { t } = useT();
  const isNew = type === null;
  const [current, setCurrent] = useState<TypeRead | null>(type);
  const [values, setValues] = useState(metadataFrom(type));
  const [fields, setFields] = useState<EditableField[]>(() => withUids(type?.fields ?? []));
  const [originalKeys] = useState<Set<string>>(new Set((type?.fields ?? []).map((f) => f.key)));
  const [createErrors, setCreateErrors] = useState<ValidationError[]>([]);
  const [pending, setPending] = useState(false);
  // The dry-run report of the change that was last forced through (R7a) —
  // `useSchemaApply` clears its own on success, and that report is the only
  // inventory of the records the force just marked invalid.
  const [lastApplied, setLastApplied] = useState<DryRunReport | null>(null);
  // A 409 from turning "Translatable" off while foreign-locale records exist
  // (design §4.1) — not one of `useSchemaApply`'s four known 409/422 shapes,
  // so it is rethrown to here rather than handled there.
  const [translatableError, setTranslatableError] = useState<string | null>(null);

  // `current` is seeded once from `type` (the initial `useState` argument is
  // only read on mount), so a background `router.reload({ only: ['type'] })'
  // — the reindex poll (F4) — updated the incoming `type` *prop* without
  // ever reaching `current`, and `ReindexStatus` (which reads `current`, not
  // `type`) never saw the cleared `reindex_pending`. Re-sync whenever Inertia
  // hands this page a new `type` object; `values`/`fields` are deliberately
  // left alone so an in-progress edit survives a poll.
  useEffect(() => {
    setCurrent(type);
  }, [type]);

  const applySaved = (saved: TypeRead) => {
    setCurrent(saved);
    setValues(metadataFrom(saved));
    setFields(withUids(saved.fields));
  };

  const schemaApply = useSchemaApply((result) => {
    applySaved(result);
    toast.success(t('records.editor.saved', { defaultValue: 'Saved' }));
  });

  const attemptUpdate = useCallback(
    (body: SchemaApplyBody) => {
      if (!current) return Promise.reject(new Error('No type loaded to update'));
      const { expected_version, ...rest } = body;
      return updateType(current.key, expected_version, rest);
    },
    [current],
  );

  const activeErrors = isNew ? createErrors : schemaApply.errors;
  // Three-way, not two: an error naming neither an input nor a row (a
  // `__root__` one) used to be handed to the field list and dropped there,
  // which is how a refused save came to change nothing at all (R6). `SaveBar`
  // renders what nothing else owns.
  const fieldKeys = fields.map((field) => field.key);
  const errorGroups = groupErrors(activeErrors, fieldKeys);
  const schemaDirty = !isNew && schemaIsDirty(current, values, fields);
  const dirty = typeIsDirty(current, values, fields);
  const guard = useUnsavedGuard(dirty);

  /** Force a refused change through, keeping its report on screen
   *  afterwards — `retryWith` answers `null` when the retry was itself
   *  refused, and there is nothing applied to report in that case. */
  const forceApply = async () => {
    const report = schemaApply.report;
    const result = await schemaApply.retryWith({ force: true });
    if (result) setLastApplied(report);
    return result;
  };

  const save = async () => {
    setPending(true);
    setTranslatableError(null);
    let changedTranslatable = false;
    try {
      if (isNew) {
        setCreateErrors([]);
        const created = await createType({
          key: values.key,
          label: values.label,
          label_plural: values.labelPlural,
          fields: stripUids(fields),
          ...extraCreateFields(values),
        });
        // The draft has just been written; the guard must not then ask about
        // it on the way to the editor for the type it became.
        guard.allow();
        router.visit(`/admin/records/types/${created.key}`);
        return;
      }
      if (!current) return;
      const changes = buildChanges(current, values, fields);
      changedTranslatable = 'translatable' in changes;
      if (Object.keys(changes).length === 0) {
        // Unreachable while Save is disabled on a clean draft (R22b), kept
        // as the honest answer rather than a green "Saved" for a write that
        // never happened.
        toast(t('records.type_editor.no_changes', { defaultValue: 'No changes to save' }));
        return;
      }
      schemaApply.reset();
      await schemaApply.run(attemptUpdate, { expected_version: current.version, ...changes });
    } catch (err) {
      // Turning "Translatable" off while records in another locale exist —
      // a 409 that carries none of `useSchemaApply`'s four known shapes
      // (`current`/`report`/`conflicts`), so it lands here instead of there.
      if (err instanceof ApiError && err.status === 409 && changedTranslatable) {
        setTranslatableError(err.body?.detail ?? err.message);
        // The switch itself moved on click; the server refused, so it
        // reverts to what is actually saved rather than sit disagreeing with
        // the error text underneath it (UX-7).
        if (current) setValues((prev) => ({ ...prev, translatable: current.translatable }));
      } else if (err instanceof ApiError && err.status === 422 && err.body?.errors) {
        setCreateErrors(err.body.errors);
      } else {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  };

  const reloadFromConflict = (server: TypeRead) => {
    applySaved(server);
    schemaApply.reset();
  };

  const title = isNew
    ? t('records.type_editor.title_new', { defaultValue: 'New type' })
    : (current?.label ?? '');

  return (
    <>
      <Head
        title={
          isNew
            ? title
            : t('records.type_editor.title_edit', {
                defaultValue: 'Edit {label}',
                label: current?.label ?? '',
              })
        }
      />
      <PageShell
        title={title}
        actions={
          <Button variant="outline" onClick={() => router.visit(TYPES_LIST_HREF)}>
            {t('records.editor.cancel', { defaultValue: 'Cancel' })}
          </Button>
        }
      >
        <div className="space-y-6">
          {schemaApply.versionConflict && (
            <TypeConflictNotice
              current={schemaApply.versionConflict}
              onReload={reloadFromConflict}
            />
          )}

          {!isNew && current && <ReindexStatus type={current} />}

          <Card>
            <CardHeader>
              <CardTitle>
                {t('records.type_editor.section_details', { defaultValue: 'Details' })}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <TypeMetadataForm
                isNew={isNew}
                roles={roles}
                values={values}
                onChange={(patch) => setValues((prev) => ({ ...prev, ...patch }))}
                errors={errorGroups.topLevel}
                publicRoutePrefix={public_route_prefix}
                contentLocales={content_locales}
                collections={collections}
                translatableError={translatableError}
              />
            </CardContent>
          </Card>

          <FieldsCard
            current={current}
            isNew={isNew}
            fields={fields}
            originalKeys={originalKeys}
            targetTypes={target_types}
            displayField={values.displayField}
            slugField={values.slugField}
            disabled={pending}
            dirty={schemaDirty}
            errors={errorGroups.rows}
            lastApplied={lastApplied}
            onChange={setFields}
          />

          <PointerFields
            fields={fields}
            values={values}
            errors={errorGroups.topLevel}
            onChange={(patch) => setValues((prev) => ({ ...prev, ...patch }))}
          />

          <SaveBar
            errors={activeErrors}
            fieldKeys={fieldKeys}
            pending={pending}
            dirty={dirty}
            onSave={() => void save()}
          />

          <TypeEditorFooter
            current={isNew ? null : current}
            report={schemaApply.report}
            conflicts={schemaApply.conflicts}
            pending={schemaApply.pending || pending}
            onForce={forceApply}
            onOrphaned={(choice) => schemaApply.retryWith({ orphaned: choice })}
            onRestored={applySaved}
            onDeleted={() => {
              guard.allow();
              router.visit(TYPES_LIST_HREF);
            }}
          />
        </div>
      </PageShell>
    </>
  );
}

TypeEditor.layout = (page: React.ReactNode) => (
  <AdminLayout>
    {page}
    <RecordsToaster />
  </AdminLayout>
);
export default TypeEditor;
